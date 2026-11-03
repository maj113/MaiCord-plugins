# Contributing to the MaiCord catalog

Thanks for adding to it. This page has the steps for each kind of item, the
metadata CI checks, and the rules a maintainer reviews against. The
[README](README.md) explains what the catalog is and what it refuses.

Before you start:

- Plugins and effects are written with `maicord-plugin`, in MaiCord's
  repository under `tools/maicord-plugin`. You need Windows 10 or 11 x64 and
  Python 3.9 or newer. Put that folder on `PATH`. The tool downloads MaiCord's
  pinned clang-cl once and needs no Visual Studio. The guides are the
  [plugin SDK](https://github.com/maj113/MaiCord/blob/master/include/maicord/sdk/README.md)
  and [background effects](https://github.com/maj113/MaiCord/blob/master/samples/effects/README.md).
- Read [what the catalog refuses](README.md#discords-terms-of-service) first.
  It lists what is refused and why.
- One item per pull request, so it can be reviewed and reverted on its own.
- Open an issue first if you're unsure an idea fits.

## A plugin

1. **Create it.**

   ```powershell
   maicord-plugin new "My Plugin"     # my-plugin\plugin.cpp, README.md, .gitignore, .clangd
   cd my-plugin
   ```

   `new` picks a random 64-bit **owner id** (`.owner` in `MC_PLUGIN`). Keep
   it, see [the owner id](#the-owner-id).
2. **Write it** in `plugin.cpp`, the only source file. In `MC_PLUGIN` set
   `.name`, `.version` (`"1.0.0"`), `.summary`, `.author`, and `.permissions`
   and `.network` to **the least the plugin needs**. The host adds the
   permissions your hooks and buttons imply; declare only what API calls need.
3. **Build it.** `maicord-plugin build` compiles with the flags CI uses, so the
   DLL is what CI will build, then checks the PE headers and the descriptor.
4. **Test it in MaiCord.** Turn on **Developer Mode** (Settings > Advanced) and
   run `maicord-plugin dev --watch`; the plugin appears under Settings >
   Plugins > Developer and reloads on every save. Press its buttons, and make
   it fail: an empty string, a 4,000-byte message, someone else's message,
   and the network down.
5. **Write the page.** Put a `DETAILS.md` next to `plugin.cpp`: what it does,
   its settings, and, if it uses `.network`, a **Network** section saying what
   leaves the PC, to which hosts, and when. Use the [Markdown subset](README.md#layout).
6. **Pack it.**

   ```powershell
   maicord-plugin pack --author "Your Name" --github you --license MPL-2.0 --category chat --category utility
   ```

   `pack` re-checks the DLL and writes `dist\my-plugin\` with `plugin.cpp`,
   `catalog.json` and `details.md`. It refuses `automated_actions` and
   `persistent_log`, and so does the CI build (it fails with a message naming
   the permission): the catalog doesn't accept them. Categories are up to
   three of `chat`, `appearance`, `notifications`, `privacy`, `utility`,
   `voice`, `accessibility`, `moderation`, `developer`, `fun`.
7. **Open the pull request.** Fork this repository, copy `dist\my-plugin\` to
   `plugins/my-plugin/`, and open a pull request titled like the existing
   commits (`Add My Plugin: what it does`). The folder is the whole change:

   ```
   plugins/my-plugin/
       plugin.cpp
       catalog.json
       details.md
   ```

   Tick the checklist the template shows. Read the CI report (see
   [what CI reports](#what-ci-reports)) before a maintainer does.
8. **Update it later.** Change `plugin.cpp`, bump `.version` in `MC_PLUGIN`,
   optionally set `changelog` in `catalog.json` (512 bytes at most), and open
   another pull request. See [versions](#versions-and-immutability).

## A theme

A theme is a data file: it runs no code.

1. Copy the closest folder under `themes/` to `themes/my-theme/` and start
   from MaiCord's `assets/themes/example.maicord-theme.json`, which lists every
   token. Edit `theme.json` (`"version": "2.0"` is the document format; 64 KiB
   at most). Its `name` must equal `name` in `catalog.json`.
2. **Try it:** in MaiCord choose Settings > Appearance > Import theme..., which
   checks the document and previews it before anything is applied. Check the
   contrast: text colours must meet WCAG AA, 4.5:1 for text and 3:1 for muted
   text and accents.
3. **Take the preview.** Apply it and capture the main chat view at 1440x900 as
   `preview.png` (256 KiB at most; use PNG optimisation). Show the theme, not
   private conversations.
4. **Write `catalog.json`, `details.md` and `README.md`** as the other themes do
   (the README holds the colours and the contrast figures).
5. **Build it locally** (see [checking your work](#checking-your-work)):
   `python -B scripts/build_catalog.py --maicord ..\MaiCord --out site --only theme/my-theme`.
6. Open the pull request with the folder:

   ```
   themes/my-theme/
       theme.json
       preview.png
       catalog.json
       details.md
       README.md
   ```

A theme may name a background effect in `catalog.json` (`effect`, an effect
slug) and a `base` (`dark`, `light` or `amoled`); otherwise the base is the
theme's own. The swatches the site shows come from `theme.json`'s colours.

## An effect

An effect is one HLSL pixel shader plus a sidecar; it runs on the GPU only.

1. **Create it.**

   ```powershell
   maicord-plugin effect new "Soft Rain"    # soft-rain\soft-rain.hlsl, soft-rain.effect, README.md
   cd soft-rain
   ```
2. **Write it** against `maicord/sdk/background.hlsli`. The `// @effect`,
   `// @knob`, `// @uses` and `// @blend` comments at the top of the `.hlsl` are
   the one source of truth for the name, knobs, inputs and blend. Credit the
   original in `derived_from` when you port something. `@uses clock` and
   `@uses appearance` give the shader the local time of day, the date and the
   light or dark appearance (`mc_ambient`, eased by MaiCord); such an effect is
   packed as interface 2 and needs a MaiCord that has them (older ones refuse
   it), so use them only when the effect is about them. An effect that needs
   more than one full-screen function can be a **pass graph** (`// @target`
   and `// @pass` lines, up to six passes of pixel and vertex shaders over
   host-made geometry, small float targets, persistent state); see
   MaiCord's `samples/effects/README.md` (Pass graphs). It is packed as
   interface 3, and CI measures and previews the whole graph.
3. **Build it:** `maicord-plugin effect build` compiles, lints (constant buffer
   `b0`, textures `t0-t4` or `t0-t10` for a graph, samplers `s0-s2`, no UAVs,
   at most 4,096 instructions and 64 texture reads per shader) and writes
   `build\soft-rain.mcfx`. It also rewrites the sidecar (a graph's `targets`
   and `passes` lines too, which CI checks against the comments); keep its
   `resolution` and `fps` requests if you set them.
4. **Try it:** turn on Developer Mode and run
   `maicord-plugin effect preview --watch`; pick the effect under Appearance >
   Background effect. `--time 18:30`, `--date 12-24`, `--day-seconds 60` and
   `--appearance dark|light` stand in for the clock and the appearance;
   `--real-inputs` goes back to the real ones.
5. **Make the item folder** `effects/soft-rain/` with the `.hlsl`, the
   `.effect`, a `catalog.json` and a `details.md`. `effect` has no `pack`
   command, so write the last two by hand. The `@effect` name and license, the
   sidecar's name, and `catalog.json` must agree.
6. **Build it locally** (see [checking your work](#checking-your-work)) and
   look at the preview CI would render.
7. Open the pull request:

   ```
   effects/soft-rain/
       soft-rain.hlsl
       soft-rain.effect
       catalog.json
       details.md
   ```

You don't commit previews or measurements for an effect: CI makes them.

## Required metadata

`catalog.json` holds what the catalog shows. Unknown members fail the build.
Byte limits count UTF-8 bytes.

| Member | Applies to | Rule |
|---|---|---|
| `name` | all | 1 to 95 bytes; plugins also at most 64 and equal to `.name` in `MC_PLUGIN`; effects at most 48 and equal to `@effect name`; themes equal to `theme.json`'s `name` |
| `summary` | all | 1 to 255 bytes, one line |
| `authors` | all | 1 to 4 of `{"name": up to 64 bytes, "github": optional, up to 39}` |
| `license` | all | An SPDX id, at most 32 characters of letters, digits, `.`, `+`, `-` (see [licenses](#licenses)) |
| `categories` | all | Up to 3 lower-case slugs of at most 24 characters. Plugins use the ten listed above; themes and effects use short descriptive words (`warm`, `ambient`) |
| `homepage` | optional | An `https://` URL on a real host, at most 256 bytes |
| `derived_from` | optional | `{"url", "author" (1 to 64), "license"}`: what this was ported or adapted from |
| `changelog` | optional | At most 512 bytes |
| `owner_id` | plugins | `0x` and 16 hex digits, the descriptor's `.owner` (see [the owner id](#the-owner-id)) |
| `version` | themes, effects | `MAJOR.MINOR.PATCH`, each 0 to 999 with no leading zeros |
| `preview_alt` | themes, effects | 1 to 255 bytes: what the preview shows, for people who can't see it |
| `base` | themes, optional | `dark`, `light` or `amoled` (default: the theme's own) |
| `effect` | themes, optional | An effect slug |

The folder name is the slug: lower-case letters, digits and `-`, starting
with a letter or digit, at most 40 characters. A slug is the item's identity
for its whole life, per kind; never rename it. `develop` is reserved for any
kind, because maicord.com/plugins/develop/ and /effects/develop/ are the
developer guides, and the build refuses a folder with that name.

Everything else is taken from the item itself, so the index can't disagree
with the binary:

- **Plugins:** version, API level, permissions and network hosts (up to 8) come
  from the built DLL's descriptor. The DLL is at most 8 MiB, and the
  version is `MAJOR.MINOR.PATCH`.
- **Effects:** knobs (at most 16 numbers and toggles, 4 colours, 8 choices),
  blend and inputs come from the `@knob`, `@blend` and `@uses` lines. The
  package is at most 1.5 MiB (the bytecode and the source each at most
  64 KiB).
- **Themes:** the swatches come from `theme.json`; the file is at most 64 KiB.

`details.md` is the item's page: 1 to 16,384 bytes, LF line ends, and only the
[Markdown subset](README.md#layout). CI rejects anything else with the line
number. Say what the item does, its settings, and what it sends over the
network.

## Licenses

Any license that allows **redistribution and modification**, with credit, is
accepted: for example MIT, MPL-2.0, Apache-2.0, BSD-3-Clause or CC0-1.0, and
for themes and effects also Creative Commons licenses such as CC BY-NC-SA. An
item with no license isn't accepted. Credit is part of the listing: put the
people who wrote it in `authors`, and what you ported or adapted in
`derived_from` with its license. Submit only work you wrote or have the right
to submit under the license you state. A Shadertoy shader with no stated
license is CC BY-NC-SA 3.0 by default: ask its author, or rewrite the idea.

## The owner id

A plugin's 64-bit **owner id** is its identity: its settings and its stored
data live under it, and MaiCord refuses to sideload a plugin whose owner id is
already in the catalog.

- `maicord-plugin new` picks a random one. Don't choose a readable or
  sequential value, and never copy another plugin's.
- It is `.owner` in `MC_PLUGIN` and `owner_id` in `catalog.json`
  (`0x6D63636C75726C73` style, 16 hex digits). CI fails the build when the two
  differ, or when another listed plugin has the same id.
- Keep it for the life of the plugin. Changing it makes the plugin a different
  one to every user, with its settings gone; a pull request that changes the
  owner id of a listed plugin is rejected.

## Versions and immutability

Every version that is published stays as it was built; a fix is a new
version.

- **Plugins:** bump `.version` in `MC_PLUGIN` whenever `plugin.cpp` changes.
  CI fails if the source changed and the version did not, or if the version
  isn't higher than the published one. The newest four versions are kept for
  rollback. A version that adds a permission or a host asks the user to
  approve it again.
- **Themes and effects:** bump `version` in `catalog.json` when you change the
  item, or clients won't notice. It may not go down. CI warns when the content
  changed but the version did not. A new version carries the user's knob
  values over by knob id.
- Pure page edits (`details.md`, a typo in `summary`) don't need a bump.

To withdraw a version that is bad, don't edit it: open an issue (see
[takedowns](#takedowns-and-security-reports)).

## Checking your work

The tool tests need only Python:

```powershell
python -m pip install -r requirements.txt
python -B scripts/test_catalog_tools.py
```

A full local build is the one CI runs. In a Visual Studio developer shell
(MaiCord's `tools/enter_build_environment.ps1`), with MaiCord checked out next
to this repository:

```powershell
python -B scripts/build_catalog.py --maicord ..\MaiCord --out site --only plugin/my-plugin
```

`--only` takes `kind/slug` items (`theme/my-theme`, `effect/soft-rain`) and
writes a partial site: the files, the details, the previews and
`build/index-source.json`. Look at `site\previews\` for an effect's preview.
The build log shows each effect's WARP time and cost class.

## How previews are made

You don't make an effect's previews; CI does, from your shader, so every
effect is shown the same way:

- It compiles the `.hlsl` with the pinned `fxc` and renders it with the knobs at
  their defaults, over MaiCord's default dark theme, on **WARP**, the in-box
  software rasterizer (CI has no GPU).
- The **still** is the frame at 2 seconds, 960x540, shrunk (800x450, 640x360,
  480x270) until it fits 256 KiB. It is stored as the smallest lossless PNG
  CI finds (the best of a few filters, and a palette when the picture has at
  most 256 colours), so most effects sit well under the limit.
- The **loop** is an animated PNG that starts at 2 seconds: 480x270 at
  15 fps for 3 seconds, stepping down (to 160x90 at 8 fps for 2 seconds) until it fits 2 MiB.
- The **cost class** is the time to render 300 frames at 960x540 (best of
  three), as a multiple of a fixed calibration shader on the same machine:
  `light` up to 0.5, `medium` up to 1.5, `heavy` up to 4. Slower effects are
  refused. MaiCord also measures the cost on the user's own GPU.

For a **theme**, CI doesn't run MaiCord's UI, so the 1440x900 `preview.png`
you commit is the preview. CI checks that it is a PNG within the limits and
puts it in the index with the swatches it computes from `theme.json` and the
alt text you give in `preview_alt`.

The effect's still and loop are published beside the package as
`previews/<sha256>.png`.

## What CI reports

Every pull request runs the build job without any secret, so it works for
pull requests from forks. It builds every item, then writes a **review
report** to the run's summary (the pull request's **Checks** tab, then the
`Publish the catalog` run, then **Summary**). For each item the pull request
changes it lists, against the published version:

- **plugins:** the version, the DLL size and how it changed, the API level, the
  permissions and the network hosts, with what was **added** or removed;
- **themes:** the version, the base, the effect, the swatches and the preview;
- **effects:** the cost class (and whether it got slower), the blend, the
  inputs, the knob counts, the file size, the preview and the loop.

The previews themselves are in the `review-previews` artifact of the run. The
report is an aid for you and the maintainer; the checks that gate a merge are
the build and the review. If it shows a permission or a host you didn't mean
to ask for, fix the source.

## Takedowns and security reports

- **A bug in a listed item:** open a *Bug in a catalog item* issue.
- **A takedown request** (you wrote it, it is yours and it is listed without
  your permission, its license doesn't allow it, or it breaks Discord's Terms)
  or **a security report**: open the *Takedown or security report* issue. For
  a vulnerability, or anything you don't want public yet, use
  [private vulnerability reporting](https://github.com/maj113/MaiCord-plugins/security/advisories/new)
  instead.
- **What maintainers do:** remove the item's folder in a pull request to stop
  new installs, and, to turn off the copies people already run, add the SHA-256 of
  its file to [`index/revocations.json`](index/revocations.json):

  ```json
  {"revoked": [{"sha256": "<64 hex digits>", "severity": "malicious", "reason": "Up to 128 bytes", "since": 1767225600}],
   "blocklist": []}
  ```

  `severity` is `malicious`, `broken` or `withdrawn`; `since` is a Unix time.
  The next signed index carries it to every client, which turns the file off.

## Review

A maintainer reviews every pull request against [the policy](README.md#review-policy),
and may ask for changes: fewer permissions, a host removed, a clearer details
page. Please don't take it personally; the code runs on other people's PCs. If
CI fails, the log says which item and why.

When it merges, CI on `main` builds, signs and publishes; MaiCord clients see
the item on their next catalog check.
