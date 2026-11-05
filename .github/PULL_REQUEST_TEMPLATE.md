## What this adds or changes

<!-- One item per pull request. Name it, say what it does in a sentence, and for an update say what changed. -->

- Kind and slug: <!-- plugin, theme or effect; the folder name -->
- New or update: <!-- if an update, the version before and after -->

## Checklist

Read [CONTRIBUTING.md](https://github.com/maj113/MaiCord-plugins/blob/main/CONTRIBUTING.md) first. Tick what is true and explain anything that isn't.

**Everything**

- [ ] The change is one item and nothing else (no unrelated files).
- [ ] It builds: CI is green, and I built it locally (`maicord-plugin build` or `effect build`, or `build_catalog.py --only kind/slug`).
- [ ] I ran it in MaiCord with Developer Mode on and it works, including when it fails (empty input, no network).
- [ ] It does nothing that could break Discord's Terms of Service: no self-bot behavior (acting without the user), no unlocking paid features, no persistent message logs.
- [ ] It has no hidden network use, no telemetry and no obfuscated code.
- [ ] The license allows redistribution and modification, `catalog.json` states it, and I have the right to submit the work under it.
- [ ] Credits are right: `authors`, and `derived_from` (URL, author, license) for anything ported or adapted.
- [ ] `details.md` says what it does and uses only the supported Markdown subset.

**Plugins**

- [ ] The permissions are the least it needs, and I checked them against the review report.
- [ ] Every network host is used, listed in `.network` and explained in `details.md` (what leaves the PC, and when).
- [ ] `owner_id` in `catalog.json` is `.owner` in `MC_PLUGIN`, it came from `maicord-plugin new`, and it is not another plugin's. For an update it did not change.
- [ ] I bumped `.version` (this is an update), or this is a new plugin at `1.0.0`.
- [ ] `plugin.cpp` is the only source file.
- [ ] It builds for Linux too (`maicord-plugin build --target linux`), with no code that only runs on Windows.

**Themes**

- [ ] Text meets WCAG AA (4.5:1 for text, 3:1 for muted text and accents).
- [ ] `preview.png` is the main chat view at 1440x900, under 256 KiB, with no private conversations.
- [ ] `name` matches `theme.json`; I bumped `version` if this is an update.

**Effects**

- [ ] The `@effect` name and license, the sidecar and `catalog.json` agree.
- [ ] The cost class in the review report is acceptable for what the effect draws.
- [ ] I bumped `version` if this is an update.

## Notes for the reviewer

<!-- Anything the review report can't show: why a permission or a host is needed, what you tested, what you are unsure about. -->
