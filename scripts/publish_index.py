#!/usr/bin/env python3
"""Stamp, render and sign the official MaiCord catalog's two indexes (format 2).

    python -B scripts/publish_index.py --tools <MaiCord>/tools/release build/index-source.json site

The private JWK comes from the MAICORD_PLUGIN_CATALOG_SIGNING_KEY environment
variable and never touches the disk. The script stamps the source with:
  issued    the current time;
  expires   issued + --validity-days (the client refuses more than 35 days);
  sequence  max(the source's sequence, issued): the client refuses an index
            whose sequence is lower than the last one it accepted, or equal
            to it with different bytes, so every signing run needs a higher
            sequence. The issue time grows with every run, re-runs included.
It then renders the documents with plugin_index.render_index (the client's
strict schema) and writes, each with its .sig:
  index-full.json  the whole source at sequence + 1, for MaiCord 0.6.3 and
                   later; a client updated from 0.6.2 accepts it over the
                   index.json it last read;
  index.json       plugin_index.legacy_source() of it at sequence, for 0.6.0 to
                   0.6.2: without the effects whose package they refuse.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True

KEY_ENV = "MAICORD_PLUGIN_CATALOG_SIGNING_KEY"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tools", type=Path, required=True, help="MaiCord's tools/release directory")
    parser.add_argument("--validity-days", type=int, default=30)
    parser.add_argument("source", type=Path)
    parser.add_argument("site", type=Path, help="the directory that receives the indexes")
    arguments = parser.parse_args()
    sys.path.insert(0, str(arguments.tools.resolve()))
    import cng_p256
    import plugin_index

    jwk = os.environ.get(KEY_ENV, "")
    if not jwk.strip():
        print(f"error: {KEY_ENV} is not set.", file=sys.stderr)
        return 1
    if not 1 <= arguments.validity_days * 86400 <= plugin_index.MAX_VALIDITY_SECONDS:
        print("error: --validity-days is outside the client's window.", file=sys.stderr)
        return 1
    source = json.loads(arguments.source.read_text(encoding="utf-8"))
    issued = int(time.time())
    source["issued"] = issued
    source["expires"] = issued + arguments.validity_days * 86400
    source["sequence"] = max(int(source.get("sequence", 0)), issued)
    try:
        legacy = plugin_index.render_index(plugin_index.legacy_source(source))
        full = plugin_index.render_index(dict(source, sequence=source["sequence"] + 1))
    except plugin_index.PluginIndexError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    try:
        key = cng_p256.PrivateKey.from_jwk(jwk)
        signatures = [plugin_index.sign_index(document, key) for document in (full, legacy)]
    except (cng_p256.CngError, KeyError, ValueError) as error:
        # The type only: the message could quote the key.
        print(f"error: the signing key is unusable ({type(error).__name__})", file=sys.stderr)
        return 1
    arguments.site.mkdir(parents=True, exist_ok=True)
    for name, document, signature in zip((plugin_index.FULL_INDEX, plugin_index.LEGACY_INDEX), (full, legacy), signatures):
        (arguments.site / name).write_bytes(document)
        (arguments.site / f"{name}.sig").write_bytes(signature)
        print(f"{arguments.site / name}: {len(document)} bytes, sequence {json.loads(document)['sequence']}, "
              f"expires {source['expires']}")
    print(f"signed by {key.public_point.hex()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
