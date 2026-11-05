"""What is already published, and what the repository says about it: the shared parts of the catalog's build scripts
(build_catalog.py, build_linux_plugins.py). Needs nothing but the standard library."""

from __future__ import annotations

import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class BuildError(Exception):
    pass


def git(*arguments: str) -> str | None:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def source_changed(commit: str | None, directory: Path) -> bool | None:
    """Whether the plugin source differs from the commit a published version was built from; None when unknown."""
    if not commit or git("cat-file", "-e", commit + "^{commit}") is None:
        return None
    return subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", commit, "HEAD", "--", str(directory / "plugin.cpp")],
                          stdout=subprocess.DEVNULL).returncode != 0


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


def read_index(previous: Previous, plugin_index, name: str, reader: int, public_key: str | None, warn) -> dict | None:
    """The previously published index `name` as `reader` parses it, None when the site has none. With a key (130 hex
    digits, comma separated for several) the signature must verify under one of them; without, `warn` says so."""
    document = previous.read(name)
    if document is None:
        return None
    now = int(time.time())
    if not public_key:
        warn("the previous index is not verified (no --public-key)")
        return plugin_index.parse_index(document, now, accept_expired=True, reader=reader)
    signature = previous.read(f"{name}.sig") or b""
    failure = None
    for key in public_key.split(","):
        try:
            point = plugin_index.cng_p256.parse_public_point(key.strip())
            return plugin_index.verify_index(document, signature, point, now, accept_expired=True, reader=reader)
        except plugin_index.PluginIndexError as error:
            failure = error
    raise BuildError(f"the previous index does not verify: {failure}")
