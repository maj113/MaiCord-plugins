# MaiCord plugins

The official catalog of [MaiCord](https://github.com/maj113/MaiCord), the
native Windows Discord client: **plugins**, **themes** and **background
effects**. MaiCord's Plugins, Themes and Effects pages (and the catalog pages
on maicord.com) read the signed index this repository publishes on GitHub
Pages:

- <https://maj113.github.io/MaiCord-plugins/index.json>
- <https://maj113.github.io/MaiCord-plugins/index.json.sig>
- `details/<sha256>.md`, `previews/<sha256>.png` and
  `files/<sha256>.dll|.json|.mcfx`, the files the index names

## Layout

Every item has its own folder, named by its slug, with a `catalog.json` (what
the catalog shows) and a `details.md` (the item's page).

| Folder | Holds |
|---|---|
| `plugins/<slug>/` | `plugin.cpp` (source only, never a prebuilt DLL), `catalog.json`, `details.md` |
| `themes/<slug>/` | `theme.json` (a MaiCord theme document, 64 KiB at most), `preview.png` (1440x900, 256 KiB at most), `catalog.json`, `details.md`, `README.md` |
| `effects/<slug>/` | `<slug>.hlsl` (written against `maicord/sdk/background.hlsli`), `<slug>.effect` (the sidecar the client's dev folder reads), `catalog.json`, `details.md` |

`catalog.json` members: `name`, `summary`, `authors` (1-4 of `{name, github?}`),
`license` (SPDX id), `categories` (at most 3), `homepage?` and `derived_from?`
(`{url, author, license}`), plus per kind:

- plugins: `owner_id` (the descriptor's `.owner` as `0x` and 16 hex digits; CI
  refuses a mismatch and duplicates) and `changelog?`. The version, API level,
  permissions and network hosts are read from the built DLL's descriptor, so
  the index never disagrees with the binary.
- themes: `version`, `changelog?`, `preview_alt`, `base?` (`dark`, `light`,
  `amoled`; default: the theme's own) and `effect?` (an effect slug).
  The swatches come from the theme's colours.
- effects: `version`, `changelog?`, `preview_alt`. Knobs, blend and inputs come
  from the `@knob`, `@blend` and `@uses` lines in the HLSL; CI checks that they
  agree with the `.effect` sidecar and the `#define knob_*` lines. Cost, preview
  and loop are measured and rendered in CI.

`details.md` uses the Markdown subset the site and the client render: headings,
paragraphs, `-` lists, code, `**bold**`, `` `code` `` and https links. No tables,
images, HTML or numbered lists.

## How an item gets listed

1. Open a pull request that adds the item's **source**. CI builds it from the
   PR: plugins compile with MaiCord's pinned clang-cl against the SDK headers
   of MaiCord's repository; effects compile with `fxc`, are linted (constant
   buffer `b0`, textures `t0-t4`, samplers `s0-s2`, no UAVs, at most 4,096
   instructions and 64 texture reads), measured and rendered on WARP (the
   in-box software rasterizer) into a still and a short loop; themes are
   checked and swatched.
2. A maintainer reviews the code and, for plugins, the permissions and hosts
   the build reports, then merges.
3. CI on `main` builds again, renders the index, signs it with the catalog key
   (a secret of the `catalog` environment) and deploys it. Clients see the item
   on their next catalog check.

Published plugin versions are immutable: bump `.version` in `MC_PLUGIN` when you
change a plugin (CI fails if the source changed and the version did not), and
bump `version` in `catalog.json` when you change a theme or an effect so clients
notice. Every listed binary is built by CI from reviewed source in this
repository. A cost class (`light`, `medium`, `heavy`) is the effect's WARP time
relative to a fixed calibration shader; slower effects are refused.

## Policy

- Plugins that could break Discord's Terms of Service are not accepted. That
  includes automating a user account (self-bot behavior: sending, editing or
  reacting without the user's action), unlocking paid features, and logging
  deleted messages.
- Plugins must say what they do: no hidden network use, no telemetry, no
  obfuscated code.
- Themes and effects need a license that allows redistribution and
  modification, and credit (`authors`, `derived_from`) is shown to users.
- A listed item can be revoked: add its file's SHA-256 to
  [`index/revocations.json`](index/revocations.json) and the signed index tells
  clients to turn it off.

## Sideloading

MaiCord installs themes and effects from a link or a file behind a "not
reviewed" card. It loads a plugin that isn't in this catalog only when
**Developer Mode** is on. Sideloads are the user's choice and responsibility:
they get no review and no automatic updates.

## Building locally

From a Visual Studio developer shell (MaiCord's
`tools/enter_build_environment.ps1`) with MaiCord checked out next to this
repository:

```powershell
python -m pip install -r requirements.txt
python -B scripts/test_catalog_tools.py
python -B scripts/build_catalog.py --maicord ..\MaiCord --out site
$env:MAICORD_PLUGIN_CATALOG_SIGNING_KEY = Get-Content throwaway.jwk -Raw   # never the real key
python -B scripts/publish_index.py --tools ..\MaiCord\tools\release build/index-source.json site/index.json
python -B scripts/check_site.py --tools ..\MaiCord\tools\release --public-key <130 hex digits> site
```

`build_catalog.py` needs `clang-cl`, `fxc` and the Windows SDK libraries (the
developer shell provides them), writes the packages, details and previews into
`site/` and the unsigned index into `build/index-source.json`. `--previous <url
or directory>` carries earlier plugin versions (for rollback) from the last
publish; `--only plugin/clear-urls ...` builds a subset.

## How publishing works

[`.github/workflows/catalog.yml`](.github/workflows/catalog.yml):

1. **Build** (every push, pull request, schedule and manual run; no secrets):
   checks out MaiCord's `master` (sparse: the SDK headers, the toolchain pin and
   `tools/release`; set the `MAICORD_SDK_REF` variable to pin a branch, tag or
   commit), runs the tool tests, builds every item, and checks that every file
   the index will name exists with the right size and hash.
2. **Sign** (not on pull requests): stamps `index/` with the issue time, an
   expiry 30 days later (the client accepts at most 35) and a sequence equal to
   the issue time, so every run outranks the last one; renders the compact index
   with MaiCord's strict schema, signs it with the catalog key held in the
   `catalog` environment, and verifies it against the public key MaiCord
   compiles in.
3. **Deploy** the site to GitHub Pages.

Key setup and rotation are described in MaiCord's
[`tools/release/README.md`](https://github.com/maj113/MaiCord/blob/master/tools/release/README.md#plugin-catalog).
