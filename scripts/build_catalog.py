#!/usr/bin/env python3
"""Builds everything the catalog publishes, from this repository's sources, into a site directory.

    python -B scripts/build_catalog.py --maicord <MaiCord checkout> --out site [--previous <url or directory>]

Reads plugins/<slug>/, themes/<slug>/ and effects/<slug>/ (each holds a catalog.json with what the catalog shows,
a details.md page and the item's source) and writes:

    files/<sha256>.dll|.json|.mcfx    the packages (plugins built from source, themes verbatim, effects packed)
    details/<sha256>.md               the item pages
    previews/<sha256>.png             theme and effect previews; effect loops (APNG) too
    <work>/index-source.json          the format-2 index members; publish_index.py stamps, renders and signs it

Nothing here needs a signing key. MaiCord's checkout (sparse is enough: include/maicord/sdk, include/maicord/sys,
src/render/effects/blue_noise_64.bin, tools/) supplies the SDK headers, the pinned LLVM toolchain, the index schema
(tools/release/plugin_index.py) and the blue noise table. Run it in a Visual Studio developer shell
(tools/enter_build_environment.ps1 in MaiCord's checkout): clang-cl, fxc and the Windows SDK libraries come from it.

Plugins are built with the client's own flags, a fixed output name and /Brepro, so a rebuild of the same source is
the same file. Published versions are immutable: a plugin version that is already in the previous index keeps its
published file, and a source change without a version bump fails the build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import effects  # noqa: E402
import images  # noqa: E402
import pe_descriptor  # noqa: E402

KINDS = ("plugin", "theme", "effect")
DIRECTORIES = {"plugin": "plugins", "theme": "themes", "effect": "effects"}
SHARED_KEYS = {"name", "summary", "authors", "license", "categories", "homepage", "derived_from"}
EXTRA_KEYS = {"plugin": {"owner_id", "changelog"},
              "theme": {"version", "changelog", "preview_alt", "base", "effect"},
              "effect": {"version", "changelog", "preview_alt"}}
PLUGIN_COMPILE = ["/nologo", "/c", "/std:c++latest", "/clang:-nostdinc", "/O2", "/W4", "/WX", "/utf-8", "/Zl", "/GS-",
                  "/GR-", "/permissive-", "/clang:-fno-asynchronous-unwind-tables", "/clang:-fno-unwind-tables",
                  "/DMC_RUNTIME"]
PLUGIN_LINK = ["/nologo", "/DLL", "/NOENTRY", "/NODEFAULTLIB", "/SUBSYSTEM:WINDOWS,6.02", "/DYNAMICBASE",
               "/HIGHENTROPYVA", "/NXCOMPAT", "/CETCOMPAT", "/OPT:REF", "/OPT:ICF=8", "/INCREMENTAL:NO", "/ALLOWBIND:NO",
               "/MERGE:.pdata=.rdata", "/DEBUG:NONE", "/Brepro", "/mllvm:-enable-machine-outliner"]
THEME_VERSION = "2.0"


class BuildError(Exception):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(f"warning: {message}", flush=True)


def run(arguments: list, **options) -> subprocess.CompletedProcess:
    result = subprocess.run([str(a) for a in arguments], capture_output=True, text=True, **options)
    if result.returncode:
        raise BuildError(f"{Path(str(arguments[0])).name} failed:\n{result.stdout}{result.stderr}".rstrip())
    return result


def git(*arguments: str) -> str | None:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


# ---- the previous publish --------------------------------------------------------------
class Previous:
    """The last published site (a URL or a directory), read by file name; None when it has no such file."""

    def __init__(self, location: str | None):
        self.location = location

    def read(self, name: str) -> bytes | None:
        if not self.location:
            return None
        if re.match(r"https?://", self.location):
            request = urllib.request.Request(self.location.rstrip("/") + "/" + name, headers={"User-Agent": "maicord-catalog-build"})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                raise BuildError(f"previous {name}: HTTP {error.code}") from error
            except urllib.error.URLError as error:
                raise BuildError(f"previous {name}: {error.reason}") from error
        path = Path(self.location) / name
        return path.read_bytes() if path.is_file() else None


def previous_items(previous: Previous, plugin_index, public_key: str | None) -> dict:
    """{(kind, slug): item} of the previously published index, verified when a key is given."""
    document = previous.read("index.json")
    if document is None:
        log("previous: none published")
        return {}
    now = int(time.time())
    if public_key:
        signature = previous.read("index.json.sig") or b""
        index = None
        for key in public_key.split(","):
            try:
                point = plugin_index.cng_p256.parse_public_point(key.strip())
                index = plugin_index.verify_index(document, signature, point, now, accept_expired=True)
                break
            except plugin_index.PluginIndexError as error:
                failure = error
        if index is None:
            raise BuildError(f"the previous index does not verify: {failure}")
    else:
        warn("the previous index is not verified (no --public-key)")
        index = plugin_index.parse_index(document, now, accept_expired=True)
    log(f"previous: sequence {index['sequence']}, {len(index['items'])} items")
    return {(i["kind"], i["slug"]): i for i in index["items"]}


# ---- shared item parts -----------------------------------------------------------------
class Site:
    def __init__(self, out: Path):
        self.out = out

    def put(self, folder: str, extension: str, data: bytes) -> dict:
        digest = hashlib.sha256(data).hexdigest()
        (self.out / folder).mkdir(parents=True, exist_ok=True)
        (self.out / folder / f"{digest}.{extension}").write_bytes(data)
        return {"sha256": digest, "bytes": len(data)}


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BuildError(f"{path}: {error}") from error


def item_metadata(kind: str, slug: str, directory: Path) -> dict:
    meta = load_json(directory / "catalog.json")
    unknown = set(meta) - SHARED_KEYS - EXTRA_KEYS[kind]
    if unknown:
        raise BuildError(f"{directory / 'catalog.json'}: unknown members {sorted(unknown)}")
    return meta


def check_details(text: str, where: str) -> bytes:
    """The Markdown subset the site and the client render: headings, paragraphs, `-` lists, code, **bold**, `code`
    and https links. Tables, images, HTML, numbered lists and other link schemes would show as literal text."""
    data = text.encode("utf-8")
    if not data or len(data) > 16 * 1024 or b"\r" in data:
        raise BuildError(f"{where}: details.md must be 1 to 16384 bytes with LF line ends")
    if any(ord(c) < 32 and c != "\n" or 127 <= ord(c) <= 159 for c in text):
        raise BuildError(f"{where}: details.md has control characters")
    fenced = False
    for number, line in enumerate(text.split("\n"), 1):
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        stripped = line.lstrip()
        if (stripped.startswith(("|", "![", "> ", "<")) or re.match(r"\d+[.)] ", stripped) or re.match(r"[*+] ", stripped)
                or re.search(r"<[A-Za-z/!]", line) or re.search(r"\]\((?!https://)", line)):
            raise BuildError(f"{where}: details.md line {number} uses markup outside the supported subset")
    if fenced:
        raise BuildError(f"{where}: details.md has an unclosed code fence")
    return data


def common_item(kind: str, slug: str, meta: dict, source_url: str, details: dict) -> dict:
    item = {"kind": kind, "slug": slug, "name": meta["name"], "summary": meta["summary"], "authors": meta["authors"],
            "license": meta["license"], "source": source_url}
    for key in ("homepage",):
        if key in meta:
            item[key] = meta[key]
    item["categories"] = meta["categories"]
    if "derived_from" in meta:
        item["derived_from"] = meta["derived_from"]
    item["details"] = details
    return item


def dated(directory: Path, now: int) -> int:
    """The time of the directory's newest commit; the build time without history."""
    stamp = git("log", "-1", "--format=%ct", "--", str(directory))
    return int(stamp) if stamp and stamp.isdigit() else now


def png_size(data: bytes, where: str) -> tuple:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise BuildError(f"{where}: not a PNG")
    return struct.unpack(">II", data[16:24])


# ---- plugins -------------------------------------------------------------------------------
class Toolchain:
    def __init__(self, llvm_bin: Path, maicord: Path):
        self.clang, self.linker = llvm_bin / "clang-cl.exe", llvm_bin / "lld-link.exe"
        self.includes = [maicord / "include", maicord / "include" / "maicord" / "sys" / "libc"]
        for tool in (self.clang, self.linker):
            if not tool.is_file():
                raise BuildError(f"{tool} not found")


def resolve_llvm(explicit: str | None, maicord: Path) -> Path:
    chosen = explicit or os.environ.get("MAICORD_LLVM_BIN")
    if chosen:
        return Path(chosen)
    resolver = maicord / "tools" / "resolve_llvm_toolchain.ps1"
    result = run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", resolver])
    return Path(result.stdout.strip().splitlines()[-1])


def build_plugin(tools: Toolchain, slug: str, directory: Path, work: Path) -> Path:
    """plugin.cpp -> <slug>.dll with the flags of MaiCord's maicord_plugin() helper."""
    work.mkdir(parents=True, exist_ok=True)
    obj, dll = work / "plugin.obj", work / f"{slug}.dll"
    run([tools.clang, *PLUGIN_COMPILE, *[f"/I{p}" for p in tools.includes], directory / "plugin.cpp", f"/Fo{obj}"])
    # The export directory names the file, so the output name is fixed per slug for a reproducible hash.
    run([tools.linker, *PLUGIN_LINK, obj, f"/OUT:{dll}"])
    return dll


def source_changed(commit: str | None, directory: Path) -> bool | None:
    """Whether the directory differs from the commit a published version was built from; None when unknown."""
    if not commit or git("cat-file", "-e", commit + "^{commit}") is None:
        return None
    return subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", commit, "HEAD", "--", str(directory)]).returncode != 0


def plugin_item(site: Site, tools: Toolchain, slug: str, directory: Path, meta: dict, ctx: dict, previous: dict | None,
                owners: dict) -> dict:
    if not (directory / "plugin.cpp").is_file():
        raise BuildError(f"{directory}: plugin.cpp is missing")
    dll = build_plugin(tools, slug, directory, ctx["work"] / "plugins" / slug)
    try:
        descriptor = pe_descriptor.read_descriptor(dll)
    except pe_descriptor.DescriptorError as error:
        raise BuildError(f"plugin {slug}: {error}") from error
    if descriptor.name != meta["name"]:
        raise BuildError(f"plugin {slug}: catalog.json names it {meta['name']!r}, the descriptor {descriptor.name!r}")
    if f"0x{descriptor.owner_id:016X}" != meta.get("owner_id", "").upper().replace("0X", "0x"):
        raise BuildError(f"plugin {slug}: catalog.json owner_id {meta.get('owner_id')} is not the descriptor's "
                         f"0x{descriptor.owner_id:016X}")
    if descriptor.owner_id in owners:
        raise BuildError(f"plugin {slug}: owner id also used by {owners[descriptor.owner_id]}")
    owners[descriptor.owner_id] = slug
    data = dll.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    record = {"version": descriptor.version, "released": ctx["released"](directory)}
    if "changelog" in meta:
        record["changelog"] = meta["changelog"]
    record.update({"commit": ctx["commit"]} if ctx["commit"] else {})
    record.update({"api_level": descriptor.api_level, "permissions": descriptor.permissions, "network": descriptor.network,
                   "file": {"sha256": digest, "bytes": len(data)}})
    versions, files = [record], {digest: data}
    if previous:
        published = previous["versions"]
        same = next((v for v in published if v["version"] == descriptor.version), None)
        if same and same["file"]["sha256"] != digest:
            changed = source_changed(same.get("commit"), directory)
            if changed:
                raise BuildError(f"plugin {slug}: the source changed since {same['version']} was published; bump the version "
                                 "in MC_PLUGIN (published versions are immutable)")
            warn(f"plugin {slug} {same['version']} rebuilt to a different file; keeping the published one "
                 f"(toolchain drift or an unnoticed change: bump the version to publish a new build)")
            versions, files = [dict(same, **({"changelog": meta["changelog"]} if "changelog" in meta else {}))], {}
            ctx["carry"].append((same["file"], "dll"))
            published = [v for v in published if v is not same]
        elif same:
            versions = [dict(same, **({"changelog": meta["changelog"]} if "changelog" in meta else {}))]
            files = {digest: data}
            published = [v for v in published if v is not same]
        else:
            newest = published[0]
            if version_key(descriptor.version) <= version_key(newest["version"]):
                raise BuildError(f"plugin {slug}: version {descriptor.version} is not newer than the published {newest['version']}")
            record["released"] = max(record["released"], newest["released"])
        for old in published:
            if len(versions) >= 4:
                break
            versions.append(old)
            ctx["carry"].append((old["file"], "dll"))
    for entry in versions:
        entry.setdefault("network", [])
    for sha, content in files.items():
        (site.out / "files").mkdir(parents=True, exist_ok=True)
        (site.out / "files" / f"{sha}.dll").write_bytes(content)
    return {"versions": versions, "descriptor": descriptor}


def version_key(text: str) -> tuple:
    return tuple(int(part) for part in text.split("."))


# ---- themes -------------------------------------------------------------------------------------
COLOR = re.compile(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?")


def theme_color(document: dict, value, depth: int = 0) -> str:
    """A theme colour as #rrggbb: a hex string, an [r, g, b, a] array in 0..1, or a {path} reference."""
    if isinstance(value, str) and value.startswith("{") and value.endswith("}") and depth < 4:
        node = document
        for part in value[1:-1].split("."):
            node = node[part]
        return theme_color(document, node, depth + 1)
    if isinstance(value, str) and COLOR.fullmatch(value):
        return value[:7].lower()
    if isinstance(value, list) and len(value) in (3, 4) and all(isinstance(v, (int, float)) for v in value):
        return "#" + "".join(f"{round(min(max(v, 0), 1) * 255):02x}" for v in value[:3])
    raise BuildError(f"cannot read the theme colour {value!r}")


def theme_item(site: Site, slug: str, directory: Path, meta: dict, ctx: dict) -> dict:
    path = directory / "theme.json"
    data = path.read_bytes().replace(b"\r\n", b"\n")  # the repository stores LF; a CRLF checkout must hash the same
    if len(data) > 64 * 1024:
        raise BuildError(f"theme {slug}: theme.json is over 64 KiB")
    document = load_json(path)
    if document.get("version") != THEME_VERSION or document.get("name") != meta["name"]:
        raise BuildError(f"theme {slug}: theme.json must be version {THEME_VERSION} named {meta['name']!r}")
    base = meta.get("base", document.get("base"))
    colors = document.get("colors", {})
    try:
        swatches = {"background": theme_color(document, colors["base_low"]), "surface": theme_color(document, colors["surface"]),
                    "text": theme_color(document, colors["text_primary"]), "accent": theme_color(document, colors["accent"])}
    except (KeyError, TypeError) as error:
        raise BuildError(f"theme {slug}: colors lack {error}") from error
    background = document.get("background")
    if background is not None and meta.get("effect") not in (None, background.get("effect")):
        raise BuildError(f"theme {slug}: catalog.json effect and theme.json background.effect differ")
    preview = (directory / "preview.png").read_bytes()
    width, height = png_size(preview, f"theme {slug} preview.png")
    return {"data": data, "base": base, "swatches": swatches, "previews": [dict(site.put("previews", "png", preview),
            width=width, height=height, alt=meta["preview_alt"])], "effect": meta.get("effect")}


# ---- effects ---------------------------------------------------------------------------------------
def effect_item(site: Site, slug: str, directory: Path, meta: dict, renderer, calibration_ms: float, ctx: dict) -> dict:
    package = effects.build_package(slug, directory, {"name": meta["name"], "authors": meta["authors"],
                                    "license": meta["license"], "derived_from": meta.get("derived_from")},
                                    meta["version"], ctx["include"], ctx["fxc"], ctx["work"] / "effects" / slug)
    header, cso = package["header"], ctx["work"] / "effects" / slug / f"{slug}.cso"
    uses, blend, knobs = header["uses"], header["blend"], package["knob_values"]
    milliseconds = renderer.milliseconds(cso, blend, uses, knobs)
    cost = effects.cost_class(milliseconds / calibration_ms)
    log(f"effect {slug}: {milliseconds:.2f} ms on WARP at 960x540 ({milliseconds / calibration_ms:.2f} of the calibration) -> {cost}; "
        f"{package['lint']['instructions']} instructions, {package['lint']['samples']} texture reads")
    still, size = images.still(renderer, cso, blend, uses, knobs)
    loop, shape = images.loop(renderer, cso, blend, uses, knobs)
    return {"data": package["package"], "cost": cost, "blend": blend, "uses": [u for u in effects.USES if u in uses],
            "knobs": header["knobs"],
            "previews": [dict(site.put("previews", "png", still), width=size[0], height=size[1], alt=meta["preview_alt"])],
            "loop": dict(site.put("previews", "png", loop), **shape)}


# ---- the catalog ---------------------------------------------------------------------------------------
def check_item(plugin_index, item: dict) -> None:
    try:
        plugin_index.render_index({"format": 2, "sequence": 1, "issued": 1, "expires": 2, "items": [item]})
    except plugin_index.PluginIndexError as error:
        raise BuildError(f"{item['kind']} {item['slug']}: {error}") from error


def fetch_carried(site: Site, previous: Previous, carried: list) -> None:
    for file, extension in carried:
        name = f"files/{file['sha256']}.{extension}"
        data = previous.read(name)
        if data is None or len(data) != file["bytes"] or hashlib.sha256(data).hexdigest() != file["sha256"]:
            raise BuildError(f"previous {name} is missing or does not match the previous index")
        (site.out / "files").mkdir(parents=True, exist_ok=True)
        (site.out / "files" / f"{file['sha256']}.{extension}").write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--maicord", type=Path, required=True, help="MaiCord checkout (SDK headers, tools/release, toolchain pin)")
    parser.add_argument("--out", type=Path, required=True, help="site directory to write (emptied first)")
    parser.add_argument("--work", type=Path, default=ROOT / "build", help="scratch directory")
    parser.add_argument("--previous", help="the last published site: a URL or a directory (carries old plugin versions)")
    parser.add_argument("--public-key", help="130 hex digits (comma separated for several keys): verifies the previous index")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "maj113/MaiCord-plugins"))
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA") or git("rev-parse", "HEAD"))
    parser.add_argument("--llvm-bin", help="directory with clang-cl.exe and lld-link.exe (default: MAICORD_LLVM_BIN, else the pin)")
    parser.add_argument("--only", nargs="*", default=[], help="build just these kind/slug items (a partial index, for iterating)")
    arguments = parser.parse_args()

    maicord = arguments.maicord.resolve()
    sys.path.insert(0, str(maicord / "tools" / "release"))
    import plugin_index

    now = int(time.time())
    out, work = arguments.out.resolve(), arguments.work.resolve()
    for path in (out, work):
        if path == ROOT or path in ROOT.parents or ROOT in path.parents and path.relative_to(ROOT).parts[0] in (
                "plugins", "themes", "effects", "scripts", "index", ".git", ".github"):
            raise BuildError(f"refusing to clear {path}")
    shutil.rmtree(out, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    out.mkdir(parents=True)
    work.mkdir(parents=True)
    site = Site(out)
    previous = Previous(arguments.previous)
    published = previous_items(previous, plugin_index, arguments.public_key)
    commit = arguments.commit if arguments.commit and re.fullmatch(r"[0-9a-f]{40}", arguments.commit) else None
    ctx = {"work": work, "commit": commit, "carry": [], "include": maicord / "include",
           "released": lambda directory: dated(directory, now)}

    tools = Toolchain(resolve_llvm(arguments.llvm_bin, maicord), maicord)
    log(f"toolchain: {tools.clang.parent}")
    renderer = calibration_ms = None
    owners: dict = {}
    items = []
    selected = {tuple(x.split("/", 1)) for x in arguments.only}
    for kind in KINDS:
        for directory in sorted((ROOT / DIRECTORIES[kind]).glob("*/")):
            slug = directory.name
            if not directory.is_dir() or not (directory / "catalog.json").is_file():
                continue
            if selected and (kind, slug) not in selected:
                continue
            meta = item_metadata(kind, slug, directory)
            where = f"{kind} {slug}"
            details = site.put("details", "md", check_details((directory / "details.md").read_bytes().decode("utf-8"), where))
            source = f"https://github.com/{arguments.repository}/tree/{commit or 'main'}/{DIRECTORIES[kind]}/{slug}"
            item = common_item(kind, slug, meta, source, details)
            if kind == "plugin":
                built = plugin_item(site, tools, slug, directory, meta, ctx, published.get((kind, slug)), owners)
                item["previews"] = []
                item["versions"] = built["versions"]
                log(f"plugin {slug}: {built['descriptor'].version}, api {built['descriptor'].api_level}, "
                    f"permissions {built['descriptor'].permissions}, hosts {built['descriptor'].network}")
            else:
                version = meta["version"]
                version_key(version)  # x.y.z
                released = dated(directory, now)
                if kind == "theme":
                    built = theme_item(site, slug, directory, meta, ctx)
                    extension = "json"
                else:
                    if renderer is None:
                        renderer, calibration_ms = prepare_renderer(maicord, work, ctx, tools)
                    built = effect_item(site, slug, directory, meta, renderer, calibration_ms, ctx)
                    extension = "mcfx"
                old = published.get((kind, slug))
                if old and version_key(version) < version_key(old["version"]):
                    raise BuildError(f"{where}: version {version} is older than the published {old['version']}")
                file = site.put("files", extension, built["data"])
                if old and old["version"] == version and old["file"]["sha256"] != file["sha256"]:
                    warn(f"{where} {version} changed without a version bump; clients only notice a new version")
                item["previews"] = built["previews"]
                item["version"], item["released"] = version, released
                if "changelog" in meta:
                    item["changelog"] = meta["changelog"]
                item["file"] = file
                if kind == "theme":
                    item["base"] = built["base"]
                    if built["effect"]:
                        item["effect"] = built["effect"]
                    item["swatches"] = built["swatches"]
                else:
                    for key in ("cost", "blend", "uses", "knobs", "loop"):
                        item[key] = built[key]
            check_item(plugin_index, item)
            items.append(item)

    fetch_carried(site, previous, ctx["carry"])
    revocations = load_json(ROOT / "index" / "revocations.json")
    source = {"format": 2, "sequence": 1, "issued": 1, "expires": 2, "items": items,
              "revoked": revocations.get("revoked", []), "blocklist": revocations.get("blocklist", [])}
    plugin_index.render_index(source)  # the whole catalog, as the client will read it
    (work / "index-source.json").write_text(json.dumps(source, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"built {len(items)} items into {out}; index source {work / 'index-source.json'}")
    return 0


def prepare_renderer(maicord: Path, work: Path, ctx: dict, tools: Toolchain):
    """Compiles effect_render.exe, finds fxc and measures the calibration shader."""
    ctx["fxc"] = effects.find_fxc()
    executable = work / "effect_render.exe"
    try:
        run([tools.clang, "/nologo", "/O2", "/EHsc", "/D_CRT_SECURE_NO_WARNINGS", ROOT / "scripts" / "effect_render.cpp",
             f"/Fo{work / 'effect_render.obj'}", f"/Fe{executable}", "user32.lib", "gdi32.lib", "d3d11.lib", "d3dcompiler.lib"])
    except BuildError as error:
        raise BuildError(f"{error}\n(run this from a Visual Studio developer shell: MaiCord's tools/enter_build_environment.ps1)") from None
    renderer = images.Renderer(executable, maicord / "src" / "render" / "effects" / "blue_noise_64.bin", work / "render")
    calibration = work / "calibration"
    calibration.mkdir()
    (calibration / "calibration.hlsl").write_text(images.CALIBRATION_SOURCE % (16, 16), encoding="utf-8")
    effects.compile_effect(ctx["fxc"], calibration / "calibration.hlsl", ctx["include"], calibration)
    milliseconds = renderer.milliseconds(calibration / "calibration.cso", "normal", [], [0.0] * 32)
    log(f"calibration: {milliseconds:.2f} ms per frame on WARP at 960x540")
    return renderer, milliseconds


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BuildError, effects.EffectError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
