#!/usr/bin/env python3
"""Checks a built site directory the way a client reads it: both indexes (index-full.json for MaiCord 0.6.3 and later,
index.json for 0.6.0 to 0.6.2) parse under the client's schema (and, with --public-key, verify under the catalog key),
index.json is the legacy form of index-full.json one sequence lower, every details, preview, loop and package file the
full index names exists with the listed size and SHA-256, and nothing else is published.

    python -B scripts/check_site.py --tools <MaiCord>/tools/release [--public-key <hex>] site
    python -B scripts/check_site.py --tools <MaiCord>/tools/release --source build/index-source.json site

With --source the unsigned index source stands in for both indexes (the build job checks the files before the sign
job stamps and signs them).
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tools", type=Path, required=True, help="MaiCord's tools/release directory")
    parser.add_argument("--public-key", help="130 hex digits; the index signature must verify under it")
    parser.add_argument("--source", type=Path, help="index source JSON to check instead of the site's indexes")
    parser.add_argument("site", type=Path)
    arguments = parser.parse_args()
    sys.path.insert(0, str(arguments.tools.resolve()))
    import plugin_index

    site = arguments.site
    now = int(time.time())
    names = (plugin_index.FULL_INDEX, plugin_index.LEGACY_INDEX)
    try:
        if arguments.source:
            source = json.loads(arguments.source.read_text(encoding="utf-8"))
            index = plugin_index.parse_index(plugin_index.render_index(source), None)
            plugin_index.render_index(plugin_index.legacy_source(source))
        else:
            point = plugin_index.cng_p256.parse_public_point(arguments.public_key) if arguments.public_key else None
            documents = {name: (site / name).read_bytes() for name in names}
            indexes = {name: plugin_index.verify_index(documents[name], (site / f"{name}.sig").read_bytes(), point, now)
                       if point else plugin_index.parse_index(documents[name], now) for name in names}
            index = indexes[plugin_index.FULL_INDEX]
            full = json.loads(documents[plugin_index.FULL_INDEX])
            legacy = plugin_index.render_index(dict(plugin_index.legacy_source(full), sequence=full["sequence"] - 1))
            if documents[plugin_index.LEGACY_INDEX] != legacy:
                print(f"error: {plugin_index.LEGACY_INDEX} is not the legacy form of {plugin_index.FULL_INDEX}, one "
                      "sequence lower", file=sys.stderr)
                return 1
    except plugin_index.PluginIndexError as error:
        print(f"error: index: {error}", file=sys.stderr)
        return 1
    expected: dict = {}
    for item in index["items"]:
        where = f"{item['kind']} {item['slug']}"
        entries = [("details", "md", item["details"])]
        entries += [("previews", "png", p) for p in item["previews"]]
        if item.get("loop"):
            entries.append(("previews", "png", item["loop"]))
        extension = plugin_index.FILE_EXTENSIONS[item["kind"]]
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
    published = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    published -= {name + suffix for name in names for suffix in ("", ".sig")}
    failures += [f"{name} is published but no item names it" for name in sorted(published - set(expected))]
    for failure in failures:
        print(f"error: {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"site ok: {len(index['items'])} items, {len(expected)} files, index sequence {index['sequence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
