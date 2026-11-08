#!/usr/bin/env python3
"""Adds the interface 4 package (the one with the GLSL section the Linux client runs) of every effect to a built site.

    python -B scripts/build_universal.py --maicord <MaiCord checkout> --source build/index-source.json site

Runs after scripts/build_catalog.py, on a Linux runner. For each effect item of the index source it
  1. takes the DXBC package the Windows job built (files/<sha256>.mcfx, which stays what index-3.json, index-full.json
     and index.json list),
  2. has MaiCord's `maicord-plugin effect build --glsl yes --dxbc-from <package>` translate the effect's HLSL to GLSL
     ES 3.10 (DXC, SPIRV-Cross and mc_shadertool, pinned by tools/linux_shader_toolchain.json) in a scratch copy of the
     effect's folder,
  3. writes the same package with that GLSL section and the manifest naming interface 4 (effects.universal_package) to
     files/<sha256>.mcfx and names it in the item's "universal" member,
  4. checks it as MaiCord's plugin_index.check_universal does (every other section byte for byte the DXBC package's).
The source is rewritten in place; publish_index.py lists the package as the file of index-4.json (plugin_index.
reader_source, reader 4), which the Linux client reads.

The toolchain: MAICORD_GLSL_TOOLCHAIN names a directory with dxc and mc_shadertool; without it, on Linux, the pinned
one is fetched and built into ~/.cache/maicord-toolchain (MAICORD_TOOLCHAIN_CACHE) on first use, which needs git, cmake,
a C++ compiler and network access. MaiCord's checkout needs (sparse is enough) include/maicord/sdk, include/maicord/sys
and tools/ (maicord-plugin, glsl_translate.py and the optimal_deflate.py it imports, fetch_linux_shader_toolchain.py,
linux_shader_toolchain.json, shadertool, release). Nothing here needs a signing key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import effects  # noqa: E402

TEXTURE_SUFFIXES = (".png", ".mcft")


class UniversalError(Exception):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def glsl_section(maicord: Path, slug: str, directory: Path, plain: bytes, work: Path) -> bytes:
    """The GLSL section of effect `slug`, translated by MaiCord's effect tool in a scratch copy of its folder (the tool
    rewrites the sidecar and writes build/, which must not reach the repository)."""
    scratch = work / slug
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    hlsl = directory / f"{slug}.hlsl"
    shutil.copyfile(hlsl, scratch / hlsl.name)
    for texture in directory.iterdir():
        if texture.suffix in TEXTURE_SUFFIXES:
            shutil.copyfile(texture, scratch / texture.name)
    package = work / f"{slug}.plain.mcfx"
    package.write_bytes(plain)
    command = [sys.executable, "-B", str(maicord / "tools" / "maicord-plugin" / "maicord_plugin.py"), "effect", "build",
               "--dir", str(scratch), "--sdk", str(maicord), "--glsl", "yes", "--dxbc-from", str(package)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise UniversalError(f"effect {slug}: the GLSL translation failed:\n{result.stdout}{result.stderr}".rstrip())
    built = scratch / "build" / f"{slug}.mcfx"
    try:
        sections = effects.read_sections(built.read_bytes())
    except (OSError, effects.EffectError) as error:
        raise UniversalError(f"effect {slug}: the tool's package is unusable: {error}") from error
    if "GLSL" not in sections:
        raise UniversalError(f"effect {slug}: the tool wrote no GLSL section")
    return sections["GLSL"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--maicord", type=Path, required=True, help="MaiCord checkout (tools/maicord-plugin, the shader toolchain pin)")
    parser.add_argument("--source", type=Path, required=True, help="build/index-source.json of build_catalog.py; rewritten")
    parser.add_argument("--work", type=Path, default=ROOT / "build" / "universal", help="scratch directory")
    parser.add_argument("site", type=Path, help="the site directory build_catalog.py wrote; the packages are added to it")
    arguments = parser.parse_args()

    maicord, site = arguments.maicord.resolve(), arguments.site.resolve()
    sys.path.insert(0, str(maicord / "tools" / "release"))
    import plugin_index

    work = arguments.work.resolve()
    if work == ROOT or work in ROOT.parents or (ROOT in work.parents and work.relative_to(ROOT).parts[0] != "build"):
        raise UniversalError(f"refusing to clear {work}")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    source = json.loads(arguments.source.read_text(encoding="utf-8"))
    count = 0
    for item in source["items"]:
        if item["kind"] != "effect":
            continue
        slug, listed = item["slug"], item["file"]
        plain = (site / "files" / f"{listed['sha256']}.mcfx").read_bytes()
        if len(plain) != listed["bytes"] or hashlib.sha256(plain).hexdigest() != listed["sha256"]:
            raise UniversalError(f"effect {slug}: files/{listed['sha256']}.mcfx does not match the source's file record")
        glsl = glsl_section(maicord, slug, ROOT / "effects" / slug, plain, work)
        try:
            package = effects.universal_package(plain, glsl)
            plugin_index.check_universal(plain, package)
        except (effects.EffectError, plugin_index.PluginIndexError) as error:
            raise UniversalError(f"effect {slug}: {error}") from error
        digest = hashlib.sha256(package).hexdigest()
        (site / "files" / f"{digest}.mcfx").write_bytes(package)
        item["universal"] = {"sha256": digest, "bytes": len(package)}
        count += 1
        log(f"effect {slug}: interface 4 package {len(package):,} bytes ({len(package) - len(plain):,} more than the DXBC one)")
    try:
        plugin_index.check_source(source)
    except plugin_index.PluginIndexError as error:
        raise UniversalError(f"the index source: {error}") from error
    arguments.source.write_text(json.dumps(source, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"{count} effects have an interface 4 package; index source {arguments.source}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except UniversalError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
