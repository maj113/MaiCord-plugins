#!/usr/bin/env python3
"""Adds the Linux shared object of every plugin to a built site.

    python -B scripts/build_linux_plugins.py --maicord <MaiCord checkout> --source build/index-source.json site

Runs after scripts/build_catalog.py, on a Linux runner with clang and ld.lld (the Linux job installs MaiCord's pinned
LLVM release: tools/install_linux_toolchain.sh; MAICORD_LLVM_BIN or --llvm-bin names its bin directory). For each plugin
item of the index source it
  1. builds plugins/<slug>/plugin.cpp with MaiCord's own tool, as `maicord-plugin build --target linux` does (the flags
     are cmake/test_support.cmake's maicord_plugin() on Linux: freestanding, no libc, one export), twice from different
     folders to show that a rebuild is the same file,
  2. runs the tool's checks, the offline mirror of the client's ELF loader (src/app/plugins/loader.cpp); any finding fails
     the build, because the client would refuse the file on every machine,
  3. compares the descriptor with the DLL's (the index lists one set of permissions and hosts for both files): name,
     version, owner id, API level, permissions and hosts, and, with the DLL at hand, the summary, author and homepage,
  4. writes files/<sha256>.so and names it in the version's "linux" member of the source, which plugin_index.reader_source
     lists as the file of index-4.json, the index the Linux client reads. The other indexes never see it.
A version that already has a "linux" member (scripts/build_catalog.py carries what the signed previous index-4.json lists)
keeps that file: published versions are immutable. A source change since that version's commit fails the build (bump the
version); a different file from the same source is toolchain drift and only warns. A version older than the one the
repository builds and without a shared object stays Windows-only: there is no source of its own to build it from.

Nothing here needs a signing key. MaiCord's checkout needs (sparse is enough) include/maicord/sdk, include/maicord/sys,
tools/maicord-plugin and tools/release.
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
import pe_descriptor  # noqa: E402
from published import BuildError, source_changed  # noqa: E402


def log(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(f"warning: {message}", flush=True)


def build(plugin_tool, toolchain, include: Path, directory: Path, scratch: Path) -> tuple[Path, dict]:
    """plugin.cpp (and whatever sits next to it) built in a copy of the plugin's folder named by its slug; the file and
    the descriptor the tool read from it."""
    shutil.rmtree(scratch, ignore_errors=True)
    shutil.copytree(directory, scratch, ignore=shutil.ignore_patterns("build", "dist"))
    try:
        project = plugin_tool.open_project(str(scratch))
        binary = plugin_tool.build_project(project, toolchain, include, False, "linux")
    except plugin_tool.ToolError as error:
        raise BuildError(f"plugin {directory.name}: {error}") from error
    report = plugin_tool.inspect_dll(binary)
    if not report.ok:
        raise BuildError(f"plugin {directory.name}: the shared object fails the checks MaiCord's loader makes:\n  "
                         + "\n  ".join(report.errors))
    for line in report.warnings:
        warn(f"plugin {directory.name}: {line}")
    return binary, report.info


def check_descriptor(slug: str, meta: dict, record: dict, info: dict, dll: Path | None) -> None:
    """The shared object says what the DLL, and so the index, says."""
    same = {"name": (info["name"], meta["name"]),
            "owner id": (f"0x{info['owner_id']:016X}", str(meta.get("owner_id", "")).upper().replace("0X", "0x")),
            "API level": (info["api_level"], record["api_level"]),
            "permissions": (info["permissions"], record["permissions"]),
            "network hosts": (info["network"], record.get("network", []))}
    if dll is not None:
        try:
            other = pe_descriptor.read_descriptor(dll)
        except (OSError, pe_descriptor.DescriptorError) as error:
            raise BuildError(f"plugin {slug}: the DLL {dll.name} is unreadable: {error}") from error
        for key, value in (("summary", other.summary), ("author", other.author), ("homepage", other.homepage)):
            same[key] = (info[key], value)
        same["version"] = (info["version"], other.version)
    for key, (shared, windows) in same.items():
        if shared != windows:
            raise BuildError(f"plugin {slug}: the Linux build's {key} is {shared!r}, the Windows build's {windows!r}: "
                             "one source must give one descriptor (an #ifdef on the platform must not change it)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--maicord", type=Path, required=True, help="MaiCord checkout (include/, tools/maicord-plugin, tools/release)")
    parser.add_argument("--source", type=Path, required=True, help="build/index-source.json of build_catalog.py; rewritten")
    parser.add_argument("--work", type=Path, default=ROOT / "build" / "linux", help="scratch directory")
    parser.add_argument("--llvm-bin", help="directory with clang and ld.lld (default: MAICORD_LLVM_BIN, else PATH)")
    parser.add_argument("--summary", type=Path, help="write a Markdown table of what was built (for a job summary)")
    parser.add_argument("site", type=Path, help="the site directory build_catalog.py wrote; the shared objects are added to it")
    arguments = parser.parse_args()

    maicord, site = arguments.maicord.resolve(), arguments.site.resolve()
    sys.path.insert(0, str(maicord / "tools" / "release"))
    sys.path.insert(0, str(maicord / "tools" / "maicord-plugin"))
    import plugin_index
    import plugin_tool

    work = arguments.work.resolve()
    if work == ROOT or work in ROOT.parents or (ROOT in work.parents and work.relative_to(ROOT).parts[0] != "build"):
        raise BuildError(f"refusing to clear {work}")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        toolchain = plugin_tool.find_linux_toolchain(arguments.llvm_bin)
        include = plugin_tool.sdk_include(str(maicord))
    except plugin_tool.ToolError as error:
        raise BuildError(str(error)) from error
    version = subprocess.run([str(toolchain.clang), "--version"], capture_output=True, text=True).stdout.splitlines()
    log(f"toolchain: {toolchain.clang} ({version[0] if version else 'version unknown'}), SDK {include}")

    source = json.loads(arguments.source.read_text(encoding="utf-8"))
    rows = []
    count = 0
    for item in source["items"]:
        if item["kind"] != "plugin":
            continue
        slug = item["slug"]
        directory = ROOT / "plugins" / slug
        meta = json.loads((directory / "catalog.json").read_text(encoding="utf-8"))
        binary, info = build(plugin_tool, toolchain, include, directory, work / "first" / slug)
        again, _ = build(plugin_tool, toolchain, include, directory, work / "second" / slug)
        data = binary.read_bytes()
        if data != again.read_bytes():
            raise BuildError(f"plugin {slug}: two builds of the same source differ; a published file would not be reproducible")
        record = next((v for v in item["versions"] if v["version"] == info["version"]), None)
        if record is None:
            raise BuildError(f"plugin {slug}: the Linux build is version {info['version']}, the index source lists "
                             f"{', '.join(v['version'] for v in item['versions'])}")
        dll = site / "files" / f"{record['file']['sha256']}.dll"
        check_descriptor(slug, meta, record, info, dll if dll.is_file() else None)
        digest = hashlib.sha256(data).hexdigest()
        published = record.get("linux")
        if (not published or published["sha256"] != digest) and source_changed(record.get("commit"), directory):
            raise BuildError(f"plugin {slug}: the source changed since {record['version']} was published (commit "
                             f"{record['commit']}); bump the version in MC_PLUGIN (published versions are immutable)")
        if published and published["sha256"] != digest:
            warn(f"plugin {slug} {record['version']} rebuilt to a different shared object; keeping the published one "
                 "(toolchain drift: bump the version to publish a new build)")
            state, size = "published file kept (rebuilt differently)", published["bytes"]
        elif published:
            state, size = "published, unchanged", published["bytes"]
        else:
            (site / "files").mkdir(parents=True, exist_ok=True)
            (site / "files" / f"{digest}.so").write_bytes(data)
            record["linux"] = {"sha256": digest, "bytes": len(data)}
            state, size = "new", len(data)
        count += 1
        rows.append((item["name"], slug, record["version"], size, state))
        log(f"plugin {slug} {record['version']}: {size:,} bytes, {state}")
    try:
        plugin_index.check_source(source)
    except plugin_index.PluginIndexError as error:
        raise BuildError(f"the index source: {error}") from error
    arguments.source.write_text(json.dumps(source, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if arguments.summary:
        lines = ["### Linux shared objects", "", "| Plugin | Version | Size | State |", "|---|---|---|---|"]
        lines += [f"| {name} (`{slug}`) | {version} | {size:,} bytes | {state} |" for name, slug, version, size, state in rows]
        arguments.summary.parent.mkdir(parents=True, exist_ok=True)
        arguments.summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"{count} plugins have a Linux shared object; index source {arguments.source}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
