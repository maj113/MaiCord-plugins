#!/usr/bin/env python3
"""Checks a built site directory the way a client reads it: the four indexes (plugin_index.INDEXES: index-4.json for the
Linux client, index-3.json for MaiCord 0.6.4 and later on Windows, index-full.json for 0.6.3, index.json for 0.6.0 to
0.6.2) parse under each client's schema (and, with --public-key, verify under the catalog key), the other three are
index-4.json's items as reader_source gives them one to three sequences lower (an effect's interface 4 package is the
file of index-4.json and the "universal" member of the source, a plugin version's Linux shared object is its file there
and its "linux" member of the source; the others keep the DXBC package and the DLL), every details, preview, loop,
package and plugin file any index names exists with the listed size and SHA-256 (a .so is an ELF, a .dll a PE), every
interface 4 package is the DXBC package of its effect plus the GLSL section (plugin_index.check_universal), and
nothing else is published.

    python -B scripts/check_site.py --tools <MaiCord>/tools/release [--public-key <hex>] [--require-universal] site
    python -B scripts/check_site.py --tools <MaiCord>/tools/release --source build/index-source.json site

With --source the unsigned index source stands in for the indexes (the build jobs check the files before the sign job
stamps and signs them). --require-universal fails an effect without an interface 4 package and a plugin whose newest
version has no Linux shared object: the build job has none yet, the Linux job and the sign job's check demand them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent


def source_of_site(plugin_index, documents: dict) -> dict:
    """The index source the published documents come from: index-3.json (every item with its DXBC package and every
    plugin version with its DLL) with the package index-4.json lists for an effect as its "universal" member and the
    shared object it lists for a plugin version as that version's "linux" member."""
    source = json.loads(documents[plugin_index.INDEX_3])
    listed = {(i["kind"], i["slug"]): i for i in json.loads(documents[plugin_index.INDEX_4])["items"]}
    for item in source["items"]:
        newest = listed.get((item["kind"], item["slug"]))
        if item["kind"] == "effect" and newest and newest["file"] != item["file"]:
            item["universal"] = newest["file"]
        elif item["kind"] == "plugin" and newest:
            shared = {v["version"]: v["file"] for v in newest["versions"]}
            for version in item["versions"]:
                if version["version"] in shared:
                    version["linux"] = shared[version["version"]]
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tools", type=Path, required=True, help="MaiCord's tools/release directory")
    parser.add_argument("--public-key", help="130 hex digits; the index signature must verify under it")
    parser.add_argument("--source", type=Path, help="index source JSON to check instead of the site's indexes")
    parser.add_argument("--require-universal", action="store_true",
                        help="every effect needs an interface 4 package and every plugin a Linux shared object")
    parser.add_argument("site", type=Path)
    arguments = parser.parse_args()
    sys.path.insert(0, str(arguments.tools.resolve()))
    import plugin_index

    site = arguments.site
    now = int(time.time())
    names = [name for name, _, _ in plugin_index.INDEXES]
    parsed: dict = {}
    try:
        if arguments.source:
            source = json.loads(arguments.source.read_text(encoding="utf-8"))
            plugin_index.check_source(source)
            for _, reader, _ in plugin_index.INDEXES:
                document = plugin_index.render_index(plugin_index.reader_source(source, reader), reader)
                parsed[reader] = plugin_index.parse_index(document, None, reader=reader)
        else:
            point = plugin_index.cng_p256.parse_public_point(arguments.public_key) if arguments.public_key else None
            documents = {name: (site / name).read_bytes() for name in names}
            for name, reader, _ in plugin_index.INDEXES:
                if point:
                    plugin_index.verify_index(documents[name], (site / f"{name}.sig").read_bytes(), point, now, reader=reader)
                parsed[reader] = plugin_index.parse_index(documents[name], now, reader=reader)
            source = source_of_site(plugin_index, documents)
            top = plugin_index.INDEXES[0][2]
            base = json.loads(documents[plugin_index.INDEX_4])["sequence"] - top
            for name, reader, offset in plugin_index.INDEXES:
                expected = plugin_index.render_index(dict(plugin_index.reader_source(source, reader), sequence=base + offset), reader)
                if documents[name] != expected:
                    print(f"error: {name} is not what its reader gets of the index source the other indexes give "
                          f"({plugin_index.INDEX_4} first, signed {top - offset} below it for each older reader)", file=sys.stderr)
                    return 1
    except plugin_index.PluginIndexError as error:
        print(f"error: index: {error}", file=sys.stderr)
        return 1
    expected: dict = {}
    for reader, index in parsed.items():
        platform = "linux" if reader == plugin_index.INDEXES[0][1] else "windows"
        for item in index["items"]:
            where = f"{item['kind']} {item['slug']}"
            entries = [("details", "md", item["details"])]
            entries += [("previews", "png", p) for p in item["previews"]]
            if item.get("loop"):
                entries.append(("previews", "png", item["loop"]))
            extension = plugin_index.PAYLOAD_EXTENSIONS[platform] if item["kind"] == "plugin" else plugin_index.FILE_EXTENSIONS[item["kind"]]
            entries += [("files", extension, v["file"]) for v in (item["versions"] if item["kind"] == "plugin" else [item])]
            for folder, ext, entry in entries:
                expected[f"{folder}/{entry['sha256']}.{ext}"] = (entry, where)
    failures = []
    for name, (entry, where) in sorted(expected.items()):
        path = site / name
        if not path.is_file():
            failures.append(f"{where}: {name} is missing")
            continue
        data = path.read_bytes()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            failures.append(f"{where}: {name} does not match the size and SHA-256 the index lists")
        elif name.endswith(".so") and data[:4] != b"\x7fELF" or name.endswith(".dll") and data[:2] != b"MZ":
            failures.append(f"{where}: {name} is not {'an ELF shared object' if name.endswith('.so') else 'a PE DLL'}")
    universal = shared = 0
    for item in source["items"]:
        where = f"{item['kind']} {item['slug']}"
        if item["kind"] == "plugin":
            linux = [v["linux"] for v in item["versions"] if "linux" in v]
            shared += len(linux)
            if arguments.require_universal and "linux" not in item["versions"][0]:
                failures.append(f"{where}: its newest version has no Linux shared object (\"linux\"), which the Linux client needs")
            continue
        if item["kind"] != "effect":
            continue
        if "universal" not in item:
            if arguments.require_universal:
                failures.append(f"{where}: has no interface 4 package (\"universal\"), which the Linux client needs")
            continue
        paths = [site / "files" / f"{member['sha256']}.mcfx" for member in (item["file"], item["universal"])]
        if all(path.is_file() for path in paths):
            try:
                plugin_index.check_universal(paths[0].read_bytes(), paths[1].read_bytes())
                universal += 1
            except plugin_index.PluginIndexError as error:
                failures.append(f"{where}: {error}")
    published = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    published -= {name + suffix for name in names for suffix in ("", ".sig")}
    failures += [f"{name} is published but no item names it" for name in sorted(published - set(expected))]
    for failure in failures:
        print(f"error: {failure}", file=sys.stderr)
    if failures:
        return 1
    newest = parsed[plugin_index.INDEXES[0][1]]
    print(f"site ok: {len(newest['items'])} items, {len(expected)} files, {universal} interface 4 effect packages, "
          f"{shared} plugin versions with a Linux shared object, index sequence {newest['sequence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
