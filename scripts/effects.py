"""Background effects: read an effect's HLSL annotations, compile it with fxc, lint what the client will run,
and pack the `.mcfx` package (design section 16). Everything an effect declares lives in its HLSL header, the
`.effect` sidecar (the client's dev-folder defaults) and `catalog.json` (what the catalog shows); this module
checks that the three agree, so the package, the preview and the index never describe different shaders.

`.mcfx` container (little-endian), shared with the client's mcfx_parse:
  header   16 bytes: "MCFX", u16 format = 1, u16 section count (<= 10), u32 file bytes, u32 0
  table    count x 16 bytes: u32 type, u32 offset, u32 bytes, u32 0
  types    1 MANIFEST, 2 DXBC, 3 TEXTURE0, 4 TEXTURE1, 5 SOURCE, 6 PREVIEW, 7 TEXTURE2, 8 TEXTURE3, 9 SHADERS,
           10 GLSL; strictly ascending
  sections packed back to back after the table, no padding; the last one ends at the file's end

The manifest's "interface" is 1; 2 when the effect uses clock or appearance (mc_ambient); 3 for a pass graph
(`@target` / `@pass` lines: up to six passes of ps_5_0 and vs_5_0 shaders, the first pass's pixel shader in DXBC
and the others, in order of first use, in SHADERS) or texture2/texture3. A client before an interface refuses its
packages, so the catalog lists an interface above 1 in index-3.json (MaiCord 0.6.4 and later on Windows) and
index-full.json (0.6.3) and leaves such an effect out of index.json (0.6.0 to 0.6.2). The index lists only
INDEX_USES, the names every format-2 client reads (the readers before 0.6.4 refuse an unknown name, so a new one
there would break the whole catalog for them).

The Linux client runs GLSL instead of DXBC: interface 4 is the same package plus the GLSL section (type 10, made from
the HLSL by MaiCord's `maicord-plugin effect build --glsl yes --dxbc-from`) and the manifest's "interface" set to 4.
build_package makes the DXBC package on Windows; universal_package turns it into the interface 4 one
(scripts/build_universal.py, on Linux), which the item lists as "universal": index-4.json carries it as the file,
and every other index keeps the DXBC package.
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
AMBIENT_USES = ("clock", "appearance")  # interface 2
GRAPH_USES = ("texture2", "texture3")  # interface 3
MANIFEST_MAX = 16 * 1024
DXBC_MAX = 64 * 1024
SHADERS_MAX = 512 * 1024
SOURCE_MAX = 64 * 1024
PACKAGE_MAX = 1536 * 1024
INSTRUCTIONS_MAX = 4096
SAMPLES_MAX = 64
KNOB_ROWS = 8
NAME_MAX = 48
INDEX_USES = ("noise", "glyphs", "blue_noise", "pointer", "texture0", "texture1")
USES = INDEX_USES + AMBIENT_USES + GRAPH_USES
BLENDS = ("normal", "screen", "add")
RESOLUTIONS = (25, 35, 50, 75, 100)
FRAME_RATES = (10, 15, 24, 30, 60)
SECTION = {"MANIFEST": 1, "DXBC": 2, "TEXTURE0": 3, "TEXTURE1": 4, "SOURCE": 5, "PREVIEW": 6, "TEXTURE2": 7,
           "TEXTURE3": 8, "SHADERS": 9, "GLSL": 10}
UNIVERSAL_INTERFACE = 4
# The pass graph's limits (the client's include/maicord/render/effects/background_effect.hpp).
GRAPH_PASSES, GRAPH_TARGETS, GRAPH_SHADERS = 6, 4, 12
TARGET_EXTENT, FIXED_BYTES, SCALED_BYTES = 512, 8 << 20, 16
GRID_EXTENT, QUADS_MAX = 256, 16384
TEXEL_BYTES = {"rgba8": 4, "rgba16f": 8, "rgba32f": 16}
PASS_BLENDS = ("opaque", "alpha", "add", "premultiplied")
VERSION_TOKENS = {"ps_5_0": 0x50, "vs_5_0": 0x10050}
# Cost classes from the WARP measurement, as multiples of the calibration shader's time on the same machine.
COST_LIMITS = (("light", 0.5), ("medium", 1.5), ("heavy", 4.0))  # slower than the last is refused ("extreme")
SAMPLE_OPS = ("sample", "sample_l", "sample_b", "sample_d", "sample_c", "sample_c_lz", "ld", "gather4", "lod")


class EffectError(Exception):
    pass


# ---- the HLSL header -----------------------------------------------------------------
_PAIR = re.compile(r'(\w+)="([^"]*)"')
_NUMBER = r"-?\d+(?:\.\d+)?"
_KNOB = re.compile(r'//\s*@knob\s+([a-z][a-z0-9_]*)\s+(float|int|toggle|color|choice)\s*(.*)$')
_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_TARGET = re.compile(r"//\s*@target\s+([a-z][a-z0-9_]*)\s+(rgba8|rgba16f|rgba32f)\s+(?:(\d+)x(\d+)|(\d+)%)(\s+persistent)?$")


def _number(text: str):
    value = float(text)
    return int(value) if value == int(value) and "." not in text else value


def parse_header(source: str) -> dict:
    """The `@effect`, `@knob`, `@uses`, `@blend`, `@target` and `@pass` comment lines of one effect."""
    header = {"effect": {}, "knobs": [], "uses": [], "blend": None, "targets": [], "passes": []}
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
        elif line.startswith("// @target"):
            match = _TARGET.match(line)
            if not match:
                raise EffectError(f"{where}: expected @target <id> rgba8|rgba16f|rgba32f <W>x<H>|<P>% [persistent]")
            target = {"id": match.group(1), "format": match.group(2), "persistent": bool(match.group(6))}
            if match.group(5):
                target["scale"] = int(match.group(5))
            else:
                target["size"] = [int(match.group(3)), int(match.group(4))]
            header["targets"].append(target)
        elif line.startswith("// @pass"):
            header["passes"].append(_parse_pass(line[len("// @pass"):].split(), where))
    for key, allowed in (("uses", USES),):
        for use in header[key]:
            if use not in allowed:
                raise EffectError(f"@uses names {use!r}, which the interface does not have")
    if header["blend"] not in BLENDS:
        raise EffectError(f"@blend must be one of {', '.join(BLENDS)}")
    if not header["effect"].get("name") or not header["effect"].get("license"):
        raise EffectError("@effect needs name and license")
    if header["targets"] and not header["passes"]:
        raise EffectError("@target needs @pass lines that draw into it")
    return header


def _parse_pass(words: list, where: str) -> dict:
    """`@pass <ps> [vs=<entry>] [grid=WxH | quads=N] [to=<target>] [in=<target>,...] [blend=...] [clear]`."""
    if not words or not re.fullmatch(_IDENTIFIER, words[0]):
        raise EffectError(f"{where}: @pass starts with the pixel shader's entry point")
    result = {"ps": words[0], "to": "out", "in": [], "blend": "opaque", "clear": False}
    for word in words[1:]:
        key, _, value = word.partition("=")
        if word == "clear":
            result["clear"] = True
        elif key == "vs" and re.fullmatch(_IDENTIFIER, value):
            result["vs"] = value
        elif key == "grid" and re.fullmatch(r"\d+x\d+", value):
            result["grid"] = [int(v) for v in value.split("x")]
        elif key == "quads" and value.isdigit():
            result["quads"] = int(value)
        elif key == "to" and value:
            result["to"] = value
        elif key == "in" and value:
            result["in"] = value.split(",")
        elif key == "blend" and value in PASS_BLENDS:
            result["blend"] = value
        else:
            raise EffectError(f"{where}: cannot read {word!r}")
    return result


def graph_of(header: dict) -> tuple[list, list, list] | None:
    """(manifest "targets", manifest "passes", the shaders as (entry, profile) in index order) checked against the
    client's limits, as maicord-plugin builds them; None without @pass lines. Shader 0 is the first pass's pixel
    shader; the others follow in order of first use."""
    targets, passes = header["targets"], header["passes"]
    if not passes:
        return None
    if len(passes) > GRAPH_PASSES or len(targets) > GRAPH_TARGETS:
        raise EffectError(f"a graph has at most {GRAPH_PASSES} passes and {GRAPH_TARGETS} targets")
    ids = [t["id"] for t in targets]
    if len(set(ids)) != len(ids) or "out" in ids:
        raise EffectError("target ids must differ, and 'out' is the output")
    fixed = scaled = 0
    documents = []
    for target in targets:
        planes = 2 if target["persistent"] else 1
        if "size" in target:
            width, height = target["size"]
            if not (1 <= width <= TARGET_EXTENT and 1 <= height <= TARGET_EXTENT):
                raise EffectError(f"target {target['id']}: a fixed size is 1x1 to {TARGET_EXTENT}x{TARGET_EXTENT}")
            fixed += TEXEL_BYTES[target["format"]] * planes * width * height
            document = {"format": target["format"], "size": [width, height]}
        else:
            if not 1 <= target["scale"] <= 100:
                raise EffectError(f"target {target['id']}: a scale is 1% to 100% of the output")
            scaled += TEXEL_BYTES[target["format"]] * planes * target["scale"] ** 2
            document = {"format": target["format"], "scale": target["scale"]}
        if target["persistent"]:
            document["persistent"] = True
        documents.append(document)
    if fixed > FIXED_BYTES or scaled > SCALED_BYTES * 10000:
        raise EffectError("the targets need more memory than the client allows")
    shaders = [(passes[0]["ps"], "ps_5_0")]
    for item in passes:
        for entry, profile in ((item.get("vs"), "vs_5_0"), (item["ps"], "ps_5_0")):
            if entry and (entry, profile) not in shaders:
                if (entry, "ps_5_0" if profile == "vs_5_0" else "vs_5_0") in shaders:
                    raise EffectError(f"{entry} is used as both a vertex and a pixel shader")
                shaders.append((entry, profile))
    if len(shaders) > GRAPH_SHADERS:
        raise EffectError(f"a graph has at most {GRAPH_SHADERS} shaders")
    pass_documents = []
    for item in passes:
        where = f"@pass {item['ps']}"
        document = {"ps": shaders.index((item["ps"], "ps_5_0"))}
        if ("grid" in item or "quads" in item) != ("vs" in item) or ("grid" in item and "quads" in item):
            raise EffectError(f"{where}: a vertex shader draws grid=WxH or quads=N, and only one")
        if "vs" in item:
            document["vs"] = shaders.index((item["vs"], "vs_5_0"))
        if "grid" in item:
            if not all(2 <= v <= GRID_EXTENT for v in item["grid"]):
                raise EffectError(f"{where}: a grid is 2x2 to {GRID_EXTENT}x{GRID_EXTENT} points")
            document["grid"] = item["grid"]
        if "quads" in item:
            if not 1 <= item["quads"] <= QUADS_MAX:
                raise EffectError(f"{where}: quads is 1 to {QUADS_MAX}")
            document["quads"] = item["quads"]
        for name in item["in"] + ([] if item["to"] == "out" else [item["to"]]):
            if name not in ids:
                raise EffectError(f"{where}: no target {name!r}")
        inputs = [ids.index(name) for name in item["in"]]
        if len(set(inputs)) != len(inputs):
            raise EffectError(f"{where}: an input is named twice")
        if item["to"] != "out":
            target = ids.index(item["to"])
            if target in inputs and not targets[target]["persistent"]:
                raise EffectError(f"{where}: a pass reads the target it draws only when that target is persistent")
            document["target"] = target
        if inputs:
            document["inputs"] = inputs
        if item["blend"] != "opaque":
            document["blend"] = item["blend"]
        if item["clear"]:
            document["clear"] = True
        pass_documents.append(document)
    if all(item["to"] != "out" for item in passes):
        raise EffectError("no @pass draws the output")
    return documents, pass_documents, shaders


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


def compile_effect(fxc: str, hlsl: Path, include: Path, work: Path, entry: str = "main",
                   profile: str = "ps_5_0") -> tuple[bytes, str]:
    """(stripped bytecode, disassembly) of one entry point, compiled as the client's tests compile the samples. The
    .cso stays in `work` (<stem>.cso, or <stem>.<entry>.cso for a graph's shader) for effect_render."""
    work.mkdir(parents=True, exist_ok=True)
    stem = hlsl.stem if entry == "main" else f"{hlsl.stem}.{entry}"
    cso, asm = work / (stem + ".cso"), work / (stem + ".asm")
    result = subprocess.run([fxc, "/nologo", "/T", profile, "/E", entry, "/O3", "/Ges", "/WX", "/I", str(include),
                             "/Qstrip_debug", "/Qstrip_reflect", "/Fo", str(cso), "/Fc", str(asm), str(hlsl)],
                            capture_output=True, text=True)
    if result.returncode:
        raise EffectError(f"fxc failed for {hlsl.name} ({entry}):\n{result.stdout}{result.stderr}")
    return cso.read_bytes(), asm.read_text(encoding="utf-8", errors="replace")


def check_bytecode(code: bytes, profile: str = "ps_5_0") -> None:
    if len(code) > DXBC_MAX:
        raise EffectError(f"the bytecode is {len(code)} bytes, over {DXBC_MAX}")
    if code[:4] != b"DXBC":
        raise EffectError("not DXBC")
    count = struct.unpack_from("<I", code, 28)[0]
    for index in range(count):
        offset = struct.unpack_from("<I", code, 32 + 4 * index)[0]
        tag, size = struct.unpack_from("<4sI", code, offset)
        if tag in (b"SHEX", b"SHDR"):
            if struct.unpack_from("<I", code, offset + 8)[0] != VERSION_TOKENS[profile]:
                raise EffectError(f"the shader is not {profile}")
            return
    raise EffectError("no shader chunk")


def lint(assembly: str, textures: int = 4) -> dict:
    """Reflection lint from the disassembly: only b0, t0-t4 (t0-t10 at interface 3) and s0-s2; no UAVs; instruction
    and sample caps. Pixel and vertex shaders alike."""
    instructions = samples = 0
    for raw in assembly.splitlines():
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("ps_") or line.startswith("vs_"):
            continue
        opcode = line.split()[0]
        if opcode.startswith("dcl_"):
            if "uav" in opcode or opcode in ("dcl_resource_texture3d", "dcl_resource_structured", "dcl_resource_raw"):
                raise EffectError(f"the shader declares {opcode}")
            for match in re.finditer(r"\b(CB|cb)(\d+)\b", line):
                if opcode == "dcl_constantbuffer" and int(match.group(2)) != 0:
                    raise EffectError("only constant buffer b0 is allowed")
            if opcode.startswith("dcl_resource") and not any(int(t) <= textures for t in re.findall(r"\bt(\d+)\b", line)):
                raise EffectError(f"only textures t0-t{textures} are allowed")
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
def interface_of(header: dict) -> int:
    """3 for a pass graph or texture2/texture3; 2 when the effect reads mc_ambient (clock, appearance); else 1, so it
    still runs on every client."""
    if header.get("passes") or any(u in GRAPH_USES for u in header["uses"]):
        return 3
    return 2 if any(u in AMBIENT_USES for u in header["uses"]) else INTERFACE


def manifest(slug: str, header: dict, sidecar: dict, meta: dict, version: str) -> dict:
    """The MANIFEST section, members in the order the client documents."""
    result = {"interface": interface_of(header), "slug": slug, "name": meta["name"], "version": version,
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
    graph = graph_of(header)
    if graph:
        result["targets"], result["passes"] = graph[0], graph[1]
    return result


def graph_text(targets: list, passes: list, shaders: list, folder: Path, stem: str) -> str:
    """The graph as effect_render reads it (--cso <file>.graph): one line per shader, target and pass."""
    lines = [f"shader {profile[:2]} {folder / f'{stem}.{entry}.cso'}" for entry, profile in shaders]
    for target in targets:
        width, height = target.get("size", [0, 0])
        lines.append(f"target {list(TEXEL_BYTES).index(target['format'])} {width} {height} {target.get('scale', 0)} "
                     f"{int(target.get('persistent', False))}")
    for item in passes:
        grid = item.get("grid", [0, 0])
        mask = sum(1 << i for i in item.get("inputs", []))
        lines.append(f"pass {item.get('vs', -1)} {item['ps']} {item.get('target', -1)} {mask} "
                     f"{PASS_BLENDS.index(item.get('blend', 'opaque'))} {grid[0]} {grid[1]} {item.get('quads', 0)} "
                     f"{int(item.get('clear', False))}")
    return "\n".join(lines) + "\n"


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


def read_sections(package: bytes) -> dict:
    """name -> bytes of every section of a .mcfx, after checking its container as mcfx_parse does."""
    names = {number: name for name, number in SECTION.items()}
    if len(package) < 16 or package[:4] != b"MCFX":
        raise EffectError("not a .mcfx package")
    version, count, total, reserved = struct.unpack_from("<HHII", package, 4)
    if version != 1 or not 1 <= count <= len(SECTION) or total != len(package) or reserved or len(package) < 16 + 16 * count:
        raise EffectError("the package header is wrong")
    sections, at, last = {}, 16 + 16 * count, 0
    for index in range(count):
        kind, offset, size, zero = struct.unpack_from("<IIII", package, 16 + 16 * index)
        if kind not in names or kind <= last or zero or offset != at or size > len(package) - at:
            raise EffectError("the package's section table is wrong")
        sections[names[kind]] = package[offset:offset + size]
        last, at = kind, at + size
    if at != len(package):
        raise EffectError("the package's last section does not end the file")
    return sections


_INTERFACE_MEMBER = re.compile(rb'\{"interface":[123],')


def universal_package(plain: bytes, glsl: bytes) -> bytes:
    """The interface 4 package of the DXBC package `plain` (interface 1 to 3): the same sections, the manifest naming
    interface 4 and `glsl` as the GLSL section."""
    sections = read_sections(plain)
    if "GLSL" in sections:
        raise EffectError("the package already has a GLSL section")
    head = _INTERFACE_MEMBER.match(sections["MANIFEST"])
    if not head:
        raise EffectError("the manifest does not start with an interface 1 to 3")
    sections["MANIFEST"] = b'{"interface":%d,' % UNIVERSAL_INTERFACE + sections["MANIFEST"][head.end():]
    sections["GLSL"] = glsl
    return pack_mcfx(sections)


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
    graph = graph_of(header)
    if graph and (json.loads(sidecar.get("targets", "[]")) != graph[0] or json.loads(sidecar.get("passes", "[]")) != graph[1]):
        raise EffectError("the sidecar's targets or passes differ from the @target and @pass lines")
    # Every shader is compiled and linted on its own; a graph's counts are summed for the log.
    codes, counts = [], {"instructions": 0, "samples": 0}
    for entry, profile in graph[2] if graph else [("main", "ps_5_0")]:
        code, assembly = compile_effect(fxc, hlsl, include, work, entry, profile)
        check_bytecode(code, profile)
        for key, value in lint(assembly, 10 if interface_of(header) == 3 else 4).items():
            counts[key] += value
        codes.append(code)
    if sum(map(len, codes[1:])) > SHADERS_MAX:
        raise EffectError("the graph's shaders are too large")
    document = manifest(slug, header, sidecar, meta, version)
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(text) > MANIFEST_MAX:
        raise EffectError("the manifest is too large")
    source_bytes = source.encode("utf-8")
    if len(source_bytes) > SOURCE_MAX:
        raise EffectError("the source is too large")
    sections = {"MANIFEST": text, "DXBC": codes[0], "SOURCE": source_bytes}
    # What effect_render draws: the shader, or a graph file naming each pass's shaders.
    render = work / f"{slug}.cso"
    if graph:
        sections["SHADERS"] = b"".join(codes[1:])
        render = work / f"{slug}.graph"
        render.write_text(graph_text(graph[0], graph[1], graph[2], work, hlsl.stem), encoding="utf-8")
    package = pack_mcfx(sections)
    return {"package": package, "header": header, "sidecar": sidecar, "code": codes[0], "knob_values": values,
            "lint": counts, "manifest": document, "render": render}
