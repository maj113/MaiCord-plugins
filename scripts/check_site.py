#!/usr/bin/env python3
"""Checks a built site directory the way a client reads it: the index parses under the client's schema (and, with
--public-key, verifies under the catalog key), every details, preview, loop and package file the index names exists
with the listed size and SHA-256, and nothing else is published.

    python -B scripts/check_site.py --tools <MaiCord>/tools/release [--public-key <hex>] site
    python -B scripts/check_site.py --tools <MaiCord>/tools/release --source build/index-source.json site

With --source the unsigned index source stands in for site/index.json (the build job checks the files before the
sign job stamps and signs the index).
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
    parser.add_argument("--source", type=Path, help="index source JSON to check instead of site/index.json")
    parser.add_argument("site", type=Path)
    arguments = parser.parse_args()
    sys.path.insert(0, str(arguments.tools.resolve()))
    import plugin_index

    site = arguments.site
    now = int(time.time())
    try:
        if arguments.source:
            document = plugin_index.render_index(json.loads(arguments.source.read_text(encoding="utf-8")))
            index = plugin_index.parse_index(document, None)
        elif arguments.public_key:
            document = (site / "index.json").read_bytes()
            point = plugin_index.cng_p256.parse_public_point(arguments.public_key)
            index = plugin_index.verify_index(document, (site / "index.json.sig").read_bytes(), point, now)
        else:
            document = (site / "index.json").read_bytes()
            index = plugin_index.parse_index(document, now)
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
    published -= {"index.json", "index.json.sig"}
    failures += [f"{name} is published but no item names it" for name in sorted(published - set(expected))]
    for failure in failures:
        print(f"error: {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"site ok: {len(index['items'])} items, {len(expected)} files, index sequence {index['sequence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
