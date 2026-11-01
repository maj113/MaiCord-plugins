#!/usr/bin/env python3
"""Stamp, render and sign the official MaiCord plugin catalog index (format 1).

    python -B scripts/publish_index.py --tools <MaiCord>/tools/release index/source.json site/v1/index.json

The private JWK comes from the MAICORD_PLUGIN_CATALOG_SIGNING_KEY environment
variable and never touches the disk. The script stamps the source with:
  issued    the current time;
  expires   issued + --validity-days (the client refuses more than 35 days);
  sequence  max(the source's sequence, issued): the client refuses an index
            whose sequence is lower than the last one it accepted, or equal
            to it with different bytes, so every signing run needs a higher
            sequence. The issue time grows with every run, re-runs included.
It then renders the document with plugin_index.render_index (the client's
strict schema) and writes <output> and <output>.sig.
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
    parser.add_argument("output", type=Path)
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
        document = plugin_index.render_index(source)
    except plugin_index.PluginIndexError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    try:
        key = cng_p256.PrivateKey.from_jwk(jwk)
        signature = plugin_index.sign_index(document, key)
    except (cng_p256.CngError, KeyError, ValueError) as error:
        # The type only: the message could quote the key.
        print(f"error: the signing key is unusable ({type(error).__name__})", file=sys.stderr)
        return 1
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(document)
    Path(str(arguments.output) + ".sig").write_bytes(signature)
    print(f"{arguments.output}: {len(document)} bytes, sequence {source['sequence']}, expires {source['expires']}; "
          f"signed by {key.public_point.hex()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
