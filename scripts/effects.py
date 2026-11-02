"""Background effects: read an effect's HLSL annotations, compile it with fxc, lint what the client will run,
and pack the `.mcfx` package (design section 16). Everything an effect declares lives in its HLSL header, the
`.effect` sidecar (the client's dev-folder defaults) and `catalog.json` (what the catalog shows); this module
checks that the three agree, so the package, the preview and the index never describe different shaders.

`.mcfx` container (little-endian), shared with the client's mcfx_parse:
  header   16 bytes: "MCFX", u16 format = 1, u16 section count (<= 6), u32 file bytes, u32 0
  table    count x 16 bytes: u32 type, u32 offset, u32 bytes, u32 0
  types    1 MANIFEST, 2 DXBC, 3 TEXTURE0, 4 TEXTURE1, 5 SOURCE, 6 PREVIEW; strictly ascending
  sections packed back to back after the table, no padding; the last one ends at the file's end
"""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

INTERFACE = 1
MANIFEST_MAX = 16 * 1024
DXBC_MAX = 64 * 1024
SOURCE_MAX = 64 * 1024
PACKAGE_MAX = 1536 * 1024
INSTRUCTIONS_MAX = 4096
SAMPLES_MAX = 64
KNOB_ROWS = 8
NAME_MAX = 48
USES = ("noise", "glyphs", "blue_noise", "pointer", "texture0", "texture1")
BLENDS = ("normal", "screen", "add")
RESOLUTIONS = (25, 35, 50, 75, 100)
FRAME_RATES = (10, 15, 24, 30, 60)
SECTION = {"MANIFEST": 1, "DXBC": 2, "TEXTURE0": 3, "TEXTURE1": 4, "SOURCE": 5, "PREVIEW": 6}
# Cost classes from the WARP measurement, as multiples of the calibration shader's time on the same machine.
COST_LIMITS = (("light", 0.5), ("medium", 1.5), ("heavy", 4.0))  # slower than the last is refused ("extreme")
SAMPLE_OPS = ("sample", "sample_l", "sample_b", "sample_d", "sample_c", "sample_c_lz", "ld", "gather4", "lod")


class EffectError(Exception):
    pass


# ---- the HLSL header -----------------------------------------------------------------
_PAIR = re.compile(r'(\w+)="([^"]*)"')
_NUMBER = r"-?\d+(?:\.\d+)?"
_KNOB = re.compile(r'//\s*@knob\s+([a-z][a-z0-9_]*)\s+(float|int|toggle|color|choice)\s*(.*)$')


def _number(text: str):
    value = float(text)
    return int(value) if value == int(value) and "." not in text else value


def parse_header(source: str) -> dict:
    """The `@effect`, `@knob`, `@uses` and `@blend` comment lines of one effect."""
    header = {"effect": {}, "knobs": [], "uses": [], "blend": None}
    for number, line in enumerate(source.splitlines(), 1):
        line = line.strip()
        where = f"line {number}"
        if line.startswith("// @effect"):
            header["effect"] = dict(_PAIR.findall(line))
        elif line.startswith("// @uses"):
            header["uses"] = line[len("// @uses"):].split()
        elif line.startswith("// @blend"):
            header["blend"] = line[len("// @blend"):].strip()
        elif line.startswith("// @knob"):
            match = _KNOB.match(line)
            if not match:
                raise EffectError(f"{where}: cannot read the @knob line")
            header["knobs"].append(_parse_knob(match, where))
    for key, allowed in (("uses", USES),):
        for use in header[key]:
            if use not in allowed:
                raise EffectError(f"@uses names {use!r}, which the interface does not have")
    if header["blend"] not in BLENDS:
        raise EffectError(f"@blend must be one of {', '.join(BLENDS)}")
    if not header["effect"].get("name") or not header["effect"].get("license"):
        raise EffectError("@effect needs name and license")
    return header


def _parse_knob(match, where: str) -> dict:
    knob_id, kind, rest = match.group(1), match.group(2), match.group(3)
    knob = {"id": knob_id, "type": kind}
    label = re.search(r'"([^"]*)"\s*$', rest)
    if not label:
        raise EffectError(f"{where}: the knob has no label")
    knob["label"] = label.group(1)
    rest = rest[:label.start()].strip()
    if kind in ("float", "int"):
        parsed = re.fullmatch(rf"({_NUMBER})\.\.({_NUMBER})\s*=\s*({_NUMBER})", rest)
        if not parsed:
            raise EffectError(f"{where}: expected <min>..<max> = <default>")
        low, high, default = (_number(parsed.group(i)) for i in (1, 2, 3))
        if kind == "int" and not all(isinstance(v, int) for v in (low, high, default)):
            raise EffectError(f"{where}: an int knob needs integers")
        if not low < high or not low <= default <= high:
            raise EffectError(f"{where}: expected min < max and min <= default <= max")
        knob.update({"min": low, "max": high, "default": default})
    elif kind == "toggle":
        if rest not in ("= on", "= off", "=on", "=off"):
            raise EffectError(f"{where}: expected = on or = off")
        knob["default"] = rest.endswith("on")
    elif kind == "color":
        parsed = re.fullmatch(r"=\s*(#[0-9A-Fa-f]{6})", rest)
        if not parsed:
            raise EffectError(f"{where}: expected = #RRGGBB")
        knob["default"] = parsed.group(1)
    else:
        parsed = re.fullmatch(r'"([^"]+)"\s*=\s*(\d+)', rest)
        if not parsed:
            raise EffectError(f"{where}: expected \"A|B\" = <index>")
        knob["choices"] = parsed.group(1).split("|")
        knob["default"] = int(parsed.group(2))
        if not 2 <= len(knob["choices"]) <= 16 or knob["default"] >= len(knob["choices"]):
            raise EffectError(f"{where}: a choice knob needs 2 to 16 choices and a default among them")
    return knob


def parse_sidecar(text: str) -> dict:
    values = {}
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


# ---- knob slots ------------------------------------------------------------------------
def assign_slots(knobs: list) -> list:
    """(row, lane) per knob, in declaration order: scalars, toggles and choices take one lane and wrap at four;
    a colour skips to a fresh row and takes its .rgb. lane is None for a colour."""
    row, lane, slots = 0, 0, []
    for knob in knobs:
        if knob["type"] == "color":
            if lane:
                row, lane = row + 1, 0
            slots.append((row, None))
            row += 1
        else:
            slots.append((row, lane))
            lane += 1
            if lane == 4:
                row, lane = row + 1, 0
    if row + (1 if lane else 0) > KNOB_ROWS:
        raise EffectError(f"the knobs need more than {KNOB_ROWS} rows of mc_knobs")
    return slots


def knob_values(knobs: list) -> list:
    """The 32 floats of mc_knobs at the knobs' defaults."""
    values = [0.0] * (KNOB_ROWS * 4)
    for knob, (row, lane) in zip(knobs, assign_slots(knobs)):
        default = knob["default"]
        if knob["type"] == "color":
            for channel in range(3):
                values[row * 4 + channel] = int(default[1 + 2 * channel:3 + 2 * channel], 16) / 255
        else:
            values[row * 4 + lane] = float(default)
    return values


_LANES = {"x": 0, "y": 1, "z": 2, "w": 3}


def check_defines(source: str, knobs: list) -> None:
    """Every knob has a `#define knob_<id>` that reads the slot the container assigns."""
    for knob, (row, lane) in zip(knobs, assign_slots(knobs)):
        match = re.search(rf"#define\s+knob_{knob['id']}\b.*?mc_knobs\[(\d+)\]\.([xyzwrgb]+)", source)
        if not match:
            raise EffectError(f"knob {knob['id']}: no #define knob_{knob['id']} reading mc_knobs")
        want = "rgb" if lane is None else "xyzw"[lane]
        if int(match.group(1)) != row or match.group(2).translate(str.maketrans("rgba", "xyzw")) != want.translate(
                str.maketrans("rgba", "xyzw")):
            raise EffectError(f"knob {knob['id']} reads mc_knobs[{match.group(1)}].{match.group(2)}, "
                              f"its slot is mc_knobs[{row}].{want}")


# ---- fxc -------------------------------------------------------------------------------------
def find_fxc() -> str:
    candidates = []
    for variable in ("MAICORD_FXC_EXECUTABLE",):
        if os.environ.get(variable):
            candidates.append(os.environ[variable])
    if os.environ.get("WindowsSdkVerBinPath"):
        candidates.append(str(Path(os.environ["WindowsSdkVerBinPath"]) / "x64" / "fxc.exe"))
    found = shutil.which("fxc")
    if found:
        candidates.append(found)
    root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    if root.exists():
        candidates += [str(p / "x64" / "fxc.exe") for p in sorted(root.iterdir(), reverse=True)]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise EffectError("fxc.exe was not found (set MAICORD_FXC_EXECUTABLE or install the Windows SDK)")


def compile_effect(fxc: str, hlsl: Path, include: Path, work: Path) -> tuple[bytes, str]:
    """(stripped ps_5_0 bytecode, disassembly), compiled as the client's tests compile the samples."""
    work.mkdir(parents=True, exist_ok=True)
    cso, asm = work / (hlsl.stem + ".cso"), work / (hlsl.stem + ".asm")
    result = subprocess.run([fxc, "/nologo", "/T", "ps_5_0", "/E", "main", "/O3", "/Ges", "/WX", "/I", str(include),
                             "/Qstrip_debug", "/Qstrip_reflect", "/Fo", str(cso), "/Fc", str(asm), str(hlsl)],
                            capture_output=True, text=True)
    if result.returncode:
        raise EffectError(f"fxc failed for {hlsl.name}:\n{result.stdout}{result.stderr}")
    return cso.read_bytes(), asm.read_text(encoding="utf-8", errors="replace")


def check_bytecode(code: bytes) -> None:
    if len(code) > DXBC_MAX:
        raise EffectError(f"the bytecode is {len(code)} bytes, over {DXBC_MAX}")
    if code[:4] != b"DXBC":
        raise EffectError("not DXBC")
    count = struct.unpack_from("<I", code, 28)[0]
    for index in range(count):
        offset = struct.unpack_from("<I", code, 32 + 4 * index)[0]
        tag, size = struct.unpack_from("<4sI", code, offset)
        if tag in (b"SHEX", b"SHDR"):
            if struct.unpack_from("<I", code, offset + 8)[0] != 0x50:
                raise EffectError("the shader is not ps_5_0")
            return
    raise EffectError("no shader chunk")


def lint(assembly: str) -> dict:
    """Reflection lint from the disassembly: only b0, t0-t4 and s0-s2; no UAVs; instruction and sample caps."""
    instructions = samples = 0
    for raw in assembly.splitlines():
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("ps_"):
            continue
        opcode = line.split()[0]
        if opcode.startswith("dcl_"):
            if "uav" in opcode or opcode in ("dcl_resource_texture3d", "dcl_resource_structured", "dcl_resource_raw"):
                raise EffectError(f"the shader declares {opcode}")
            for match in re.finditer(r"\b(CB|cb)(\d+)\b", line):
                if opcode == "dcl_constantbuffer" and int(match.group(2)) != 0:
                    raise EffectError("only constant buffer b0 is allowed")
            if opcode.startswith("dcl_resource") and not re.search(r"\bt[0-4]\b", line):
                raise EffectError("only textures t0-t4 are allowed")
            if opcode == "dcl_sampler" and not re.search(r"\bs[0-2]\b", line):
                raise EffectError("only samplers s0-s2 are allowed")
            continue
        if opcode == "ret":
            continue
        instructions += 1
        if opcode.split("_")[0] in ("sample", "ld", "gather4", "lod") or opcode in SAMPLE_OPS:
            samples += 1
    if instructions > INSTRUCTIONS_MAX:
        raise EffectError(f"{instructions} instructions, over {INSTRUCTIONS_MAX}")
    if samples > SAMPLES_MAX:
        raise EffectError(f"{samples} texture reads, over {SAMPLES_MAX}")
    return {"instructions": instructions, "samples": samples}


def cost_class(ratio: float) -> str:
    for name, limit in COST_LIMITS:
        if ratio <= limit:
            return name
    raise EffectError(f"the shader takes {ratio:.1f}x the calibration time on WARP; the Extreme class is refused")


# ---- manifest and container ------------------------------------------------------------------
def manifest(slug: str, header: dict, sidecar: dict, meta: dict, version: str) -> dict:
    """The MANIFEST section, members in the order the client documents."""
    result = {"interface": INTERFACE, "slug": slug, "name": meta["name"], "version": version,
              "authors": meta["authors"], "license": meta["license"]}
    if meta.get("derived_from"):
        result["derived_from"] = meta["derived_from"]
    result["blend"] = header["blend"]
    result["uses"] = [u for u in USES if u in header["uses"]]
    if "resolution" in sidecar:
        result["resolution"] = int(sidecar["resolution"])
    if "fps" in sidecar:
        result["fps"] = int(sidecar["fps"])
    result["knobs"] = header["knobs"]
    return result


def pack_mcfx(sections: dict) -> bytes:
    """sections: name -> bytes, in any order; written ascending by type."""
    names = sorted(sections, key=lambda n: SECTION[n])
    if "MANIFEST" not in sections or "DXBC" not in sections:
        raise EffectError("a package needs MANIFEST and DXBC")
    offset = 16 + 16 * len(names)
    table, body = b"", b""
    for name in names:
        data = sections[name]
        table += struct.pack("<IIII", SECTION[name], offset + len(body), len(data), 0)
        body += data
    total = offset + len(body)
    package = struct.pack("<4sHHII", b"MCFX", 1, len(names), total, 0) + table + body
    if total > PACKAGE_MAX:
        raise EffectError(f"the package is {total} bytes, over {PACKAGE_MAX}")
    return package


def build_package(slug: str, directory: Path, meta: dict, version: str, include: Path, fxc: str, work: Path) -> dict:
    """Checks and compiles one effect folder. Returns the package bytes, the index members and the lint numbers."""
    hlsl = directory / f"{slug}.hlsl"
    sidecar_path = directory / f"{slug}.effect"
    source = hlsl.read_text(encoding="utf-8")
    header = parse_header(source)
    sidecar = parse_sidecar(sidecar_path.read_text(encoding="utf-8"))
    name = header["effect"]["name"]
    if not name or len(name.encode("utf-8")) > NAME_MAX:
        raise EffectError(f"the effect name must be 1 to {NAME_MAX} bytes")
    if name != sidecar.get("name") or name != meta["name"]:
        raise EffectError(f"the name differs between @effect ({name!r}), the sidecar ({sidecar.get('name')!r}) "
                          f"and catalog.json ({meta['name']!r})")
    if header["effect"]["license"] != meta["license"]:
        raise EffectError("the license differs between @effect and catalog.json")
    if sorted(header["uses"]) != sorted(sidecar.get("uses", "").split()):
        raise EffectError("@uses and the sidecar's uses differ")
    if header["blend"] != sidecar.get("blend"):
        raise EffectError("@blend and the sidecar's blend differ")
    if int(sidecar.get("resolution", 50)) not in RESOLUTIONS or int(sidecar.get("fps", 24)) not in FRAME_RATES:
        raise EffectError("the sidecar's resolution or fps is not a step the client offers")
    for knob in header["knobs"]:
        if len(knob["label"].encode()) > 48 or any(len(c.encode()) > 24 for c in knob.get("choices", [])):
            raise EffectError(f"knob {knob['id']}: label over 48 or choice over 24 bytes")
    if len({k["id"] for k in header["knobs"]}) != len(header["knobs"]):
        raise EffectError("duplicate knob id")
    check_defines(source, header["knobs"])
    values = knob_values(header["knobs"])
    given = [int(v) / 1000 for v in sidecar.get("knobs", "").split()]
    for lane, expected in enumerate(values):
        have = given[lane] if lane < len(given) else 0.0
        if abs(have - expected) > 0.0015:
            raise EffectError(f"the sidecar's knobs differ from the @knob defaults at mc_knobs value {lane}: "
                              f"{have} against {expected:.4f}")
    code, assembly = compile_effect(fxc, hlsl, include, work)
    check_bytecode(code)
    counts = lint(assembly)
    document = manifest(slug, header, sidecar, meta, version)
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(text) > MANIFEST_MAX:
        raise EffectError("the manifest is too large")
    source_bytes = source.encode("utf-8")
    if len(source_bytes) > SOURCE_MAX:
        raise EffectError("the source is too large")
    package = pack_mcfx({"MANIFEST": text, "DXBC": code, "SOURCE": source_bytes})
    return {"package": package, "header": header, "sidecar": sidecar, "code": code, "knob_values": values,
            "lint": counts, "manifest": document}
