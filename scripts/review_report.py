#!/usr/bin/env python3
"""Writes the reviewer's report of a pull request: what each changed catalog item declares, set against what is published.

    python -B scripts/review_report.py --tools <MaiCord>/tools/release --source build/index-source.json --site site \
        --previous https://maj113.github.io/MaiCord-plugins --base <the pull request's base commit> \
        --report build/review-report.md --previews review-previews

The build job runs it after the build, on pull requests only, and appends the report to the job summary. It reads only
public data (this checkout, the build output and the published index, which it does not need a key to read), so it works
for pull requests from forks, which get no secrets and no write token.

For every item whose folder the pull request touches it lists:
  plugins   the version against the published one, the DLL size, the API level, the permissions and the network hosts,
            with what was added and removed;
  themes    the version, the base, the effect it names, the swatches, the file size and the preview;
  effects   the version, the cost class against the published one, the blend, the inputs, the knobs, the file size, the
            preview and the loop.
Every preview of a changed item is copied to --previews under a readable name (the workflow uploads that folder as an
artifact: GitHub cannot show images that live in an artifact inside a summary).

The report is an aid: it never fails the build, and every figure in it comes from the built index source, so it cannot
disagree with what CI publishes. Text an author controls (names, summaries, alt text) is escaped before it is printed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

DIRECTORIES = {"plugins": "plugin", "themes": "theme", "effects": "effect"}
KIND_TITLES = {"plugin": "Plugin", "theme": "Theme", "effect": "Effect"}
COST_ORDER = {"light": 0, "medium": 1, "heavy": 2}


# ---- text -------------------------------------------------------------------------------------------------------
def esc(text: object, limit: int = 160) -> str:
    """Author-controlled text made safe for Markdown: one line, no markup, no links or images."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    if len(text) > limit:
        text = text[:limit - 1] + "..."
    return re.sub(r"([\\`*_\[\]<>|&~#!])", r"\\\1", text)


def code(values: list) -> str:
    return ", ".join(f"`{v}`" for v in values) if values else "none"


def size(count: int) -> str:
    return f"{count:,} bytes"


def delta(new: int, old: int | None) -> str:
    if old is None or new == old:
        return ""
    return f" ({'+' if new > old else '-'}{abs(new - old):,} bytes against the published {old:,})"


def compare(new: list, old: list | None) -> str:
    """The list, then what a published version did not have and what it no longer has."""
    line = code(new)
    if old is None:
        return line
    added, removed = [v for v in new if v not in old], [v for v in old if v not in new]
    if added:
        line += f"; **added:** {code(added)}"
    if removed:
        line += f"; removed: {code(removed)}"
    if not added and not removed:
        line += " (unchanged)"
    return line


# ---- what changed -----------------------------------------------------------------------------------------------
def touched_items(paths: list) -> set:
    """The {(kind, slug)} whose folder holds one of the repository-relative paths."""
    found = set()
    for path in paths:
        parts = path.replace("\\", "/").split("/")
        if len(parts) >= 3 and parts[0] in DIRECTORIES:
            found.add((DIRECTORIES[parts[0]], parts[1]))
    return found


def git_changed(base: str) -> list:
    result = subprocess.run(["git", "-C", str(ROOT), "diff", "--name-only", "--no-renames", base, "HEAD"],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"git diff against {base} failed: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]


# ---- one item ---------------------------------------------------------------------------------------------------
def file_of(item: dict) -> dict:
    return item["versions"][0]["file"] if item["kind"] == "plugin" else item["file"]


def version_of(item: dict) -> str:
    return item["versions"][0]["version"] if item["kind"] == "plugin" else item["version"]


def status_of(item: dict, old: dict | None) -> str:
    if old is None:
        return "new"
    new_version, old_version = version_of(item), version_of(old)
    if new_version != old_version:
        return f"updated from {old_version}"
    if file_of(item)["sha256"] != file_of(old)["sha256"]:
        return "same version, different file"
    return "same file"


def image_line(label: str, entry: dict) -> str:
    extra = f", {entry['fps']} fps for {entry['seconds']} s" if "fps" in entry else ""
    alt = f", alt: \"{esc(entry['alt'])}\"" if "alt" in entry else ""
    return f"{label}: {entry['width']}x{entry['height']}, {size(entry['bytes'])}{extra}{alt}"


def item_lines(item: dict, old: dict | None, compared: bool) -> list:
    kind = item["kind"]
    state = status_of(item, old) if compared else "not compared with a published version"
    lines = [f"- Status: {state}"]
    if state == "same version, different file":
        lines[0] += (" (**the version was not bumped**; "
                     + ("the build refuses this for plugins" if kind == "plugin" else "clients only notice a new version") + ")")
    file = file_of(item)
    old_file = file_of(old)["bytes"] if old else None
    if kind == "plugin":
        new, previous = item["versions"][0], old["versions"][0] if old else None
        lines.append(f"- DLL: {size(file['bytes'])}{delta(file['bytes'], old_file)}")
        lines.append(f"- API level: {new['api_level']}" + (f" (published: {previous['api_level']})"
                     if previous and previous["api_level"] != new["api_level"] else ""))
        lines.append("- Permissions: " + compare(new["permissions"], previous["permissions"] if previous else None))
        lines.append("- Network hosts: " + compare(new["network"], previous.get("network", []) if previous else None))
        if new["network"]:
            lines.append("- Check that each host is used for what `details.md` says, and that nothing is sent before the user acts.")
        if "changelog" in new:
            lines.append(f"- Changelog: {esc(new['changelog'], 512)}")
    else:
        lines.append(f"- File: {size(file['bytes'])}{delta(file['bytes'], old_file)}")
        if kind == "theme":
            lines.append(f"- Base: {item['base']}" + (f" (published: {old['base']})" if old and old.get("base") != item["base"] else ""))
            lines.append("- Effect: " + (f"`{item['effect']}`" if item.get("effect") else "none"))
            swatches = item["swatches"]
            lines.append("- Swatches: " + ", ".join(f"{name} `{swatches[name]}`" for name in ("background", "surface", "text", "accent")))
        else:
            cost = item["cost"]
            moved = ""
            if old and old.get("cost") != cost:
                moved = f" (published: {old['cost']}" + ("; **slower**" if COST_ORDER[cost] > COST_ORDER[old["cost"]] else "") + ")"
            lines.append(f"- Cost class: **{cost}**{moved}, measured on WARP at 960x540 against the calibration shader")
            lines.append(f"- Blend: {item['blend']}; inputs: {code(item['uses'])}")
            if item.get("interface", 1) > 1:
                lines.append(f"- Interface {item['interface']}: listed for MaiCord 0.6.3 and later only (index.json, "
                             "which 0.6.0 to 0.6.2 read, leaves it out)")
            counts = {t: sum(1 for k in item["knobs"] if k["type"] == t) for t in ("float", "int", "toggle", "color", "choice")}
            lines.append(f"- Knobs: {len(item['knobs'])} ({', '.join(f'{n} {t}' for t, n in counts.items() if n) or 'none'})")
        if "changelog" in item:
            lines.append(f"- Changelog: {esc(item['changelog'], 512)}")
        for number, preview in enumerate(item["previews"], 1):
            lines.append("- " + image_line("Preview" if len(item["previews"]) == 1 else f"Preview {number}", preview))
        if item.get("loop"):
            lines.append("- " + image_line("Loop", item["loop"]))
    credit = ", ".join(esc(a["name"]) + (f" (@{esc(a['github'])})" if a.get("github") else "") for a in item["authors"])
    license_note = f"{esc(item['license'])}" + (f" (published: {esc(old['license'])})" if old and old["license"] != item["license"] else "")
    lines.append(f"- License: {license_note}; authors: {credit}")
    if item.get("derived_from"):
        derived = item["derived_from"]
        lines.append(f"- Derived from: {esc(derived['author'])}, {esc(derived['license'])}, {esc(derived['url'], 256)}")
    lines.append(f"- Categories: {code(item['categories'])}")
    return lines


# ---- the report -------------------------------------------------------------------------------------------------
def render(items: dict, previous: dict | None, touched: set) -> str:
    """The Markdown report. `items` and `previous` map (kind, slug) to an index item; `previous` is None when the
    published index could not be read."""
    out = ["## Catalog review report", ""]
    if previous is None:
        out += ["The published index could not be read, so nothing below is compared with a published version.", ""]
    elif not previous:
        out += ["Nothing is published yet: every item counts as new.", ""]
    changed = sorted((k, s) for k, s in touched if (k, s) in items)
    removed = sorted((k, s) for k, s in touched if (k, s) not in items)
    if not touched:
        out += ["This pull request changes no plugin, theme or effect folder. Changes to the scripts or the workflow "
                "rebuild every item, so a green build is the evidence.", ""]
        return "\n".join(out)
    out += ["| Item | Kind | Status | Version |", "|---|---|---|---|"]
    compared = previous is not None
    for kind, slug in changed:
        item = items[(kind, slug)]
        state = status_of(item, previous.get((kind, slug))) if compared else "unknown"
        out.append(f"| {esc(item['name'], 80)} (`{slug}`) | {kind} | {state} | {version_of(item)} |")
    for kind, slug in removed:
        out.append(f"| `{slug}` | {kind} | removed from the catalog | |")
    out.append("")
    for kind, slug in changed:
        item = items[(kind, slug)]
        out += [f"### {KIND_TITLES[kind]}: {esc(item['name'], 80)} (`{slug}`) {version_of(item)}", ""]
        out += item_lines(item, previous.get((kind, slug)) if compared else None, compared)
        out += ["", f"> {esc(item['summary'], 255)}", ""]
    for kind, slug in removed:
        out += [f"### {KIND_TITLES[kind]}: `{slug}` removed", "",
                "- The folder is gone, so the next index no longer lists it. To stop installed copies, add the SHA-256 of its "
                "file to `index/revocations.json`.", ""]
    return "\n".join(out)


def copy_previews(items: dict, touched: set, site: Path, out: Path) -> list:
    """Copies every preview and loop of a touched item to out/<kind>-<slug>-<what>.png; the names written."""
    names = []
    for kind, slug in sorted(touched):
        item = items.get((kind, slug))
        if not item:
            continue
        entries = [(f"preview{'' if len(item['previews']) == 1 else f'-{n}'}", p) for n, p in enumerate(item["previews"], 1)]
        if item.get("loop"):
            entries.append(("loop", item["loop"]))
        for label, entry in entries:
            source = site / "previews" / f"{entry['sha256']}.png"
            if source.is_file():
                out.mkdir(parents=True, exist_ok=True)
                name = f"{kind}-{slug}-{label}.png"
                shutil.copyfile(source, out / name)
                names.append(name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tools", type=Path, required=True, help="MaiCord's tools/release directory")
    parser.add_argument("--source", type=Path, required=True, help="the built index source (build/index-source.json)")
    parser.add_argument("--site", type=Path, required=True, help="the built site directory (for the previews)")
    parser.add_argument("--base", required=True, help="the commit the pull request merges into")
    parser.add_argument("--previous", help="the published site: a URL or a directory")
    parser.add_argument("--public-key", help="130 hex digits (comma separated for several): verifies the published index")
    parser.add_argument("--report", type=Path, required=True, help="where to write the Markdown report")
    parser.add_argument("--previews", type=Path, help="a folder for the previews of the changed items")
    arguments = parser.parse_args()

    try:
        sys.path.insert(0, str(arguments.tools.resolve()))
        import build_catalog
        import plugin_index

        source = json.loads(arguments.source.read_text(encoding="utf-8"))
        items = {(i["kind"], i["slug"]): i for i in source["items"]}
        touched = touched_items(git_changed(arguments.base))
        try:
            previous = build_catalog.previous_items(build_catalog.Previous(arguments.previous), plugin_index, arguments.public_key)
        except build_catalog.BuildError as error:
            print(f"warning: {error}", file=sys.stderr)
            previous = None
        report = render(items, previous, touched)
        if arguments.previews:
            names = copy_previews(items, touched, arguments.site, arguments.previews)
            if names:
                report += "\n### Previews\n\n" + "\n".join(f"- `{name}`" for name in names) + "\n"
    except Exception as error:  # an aid: say what went wrong in the report, never fail the pull request's check
        print(f"warning: review report failed: {error}", file=sys.stderr)
        report = f"## Catalog review report\n\nThe report could not be written: {esc(error, 300)}\n"
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(report if report.endswith("\n") else report + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {arguments.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
