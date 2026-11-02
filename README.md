# MaiCord plugins

The official catalog of [MaiCord](https://github.com/maj113/MaiCord), the
native Windows Discord client: **plugins**, **themes** and **background
effects**. This repository holds their **source**, CI builds every listed file
from it, and a signed index tells MaiCord what is available.

- **Browse and install:** MaiCord's **Plugins**, **Themes** and **Effects**
  pages, or [maicord.com/plugins](https://maicord.com/plugins),
  [maicord.com/themes](https://maicord.com/themes) and
  [maicord.com/effects](https://maicord.com/effects).
- **Add yours:** read [CONTRIBUTING.md](CONTRIBUTING.md) and open a pull
  request.
- **Report a problem** with a listed item, ask for a plugin, or ask for
  something to be taken down: [open an issue](https://github.com/maj113/MaiCord-plugins/issues/new/choose).

## Install from the catalog

- **In MaiCord:** open the Plugins, Themes or Effects page and use its
  **Browse** tab. Each item shows what it is, who wrote it, its license and
  where its source lives. A plugin also lists the permissions and the network
  hosts it asks for, and you approve them before it runs. A plugin that later
  asks for more waits for your review; one that asks for nothing new updates on
  its own. Themes and effects are data, not code, and update on their own.
- **From maicord.com:** each item's page has an **Install** link that opens
  MaiCord on that item (`maicord://install/<kind>/<slug>`). The first time,
  MaiCord asks whether it may open `maicord://` links; until you agree, copy
  the link or find the item on the Browse tab.
- **By hand:** themes and effects can also be installed from a link or a file
  (Install from link...). Those get a "not reviewed" card and never update
  themselves. A plugin that isn't in this catalog needs Developer Mode, see
  [Sideloading](#sideloading).

What MaiCord reads is public, on GitHub Pages:

- <https://maj113.github.io/MaiCord-plugins/index.json> and
  <https://maj113.github.io/MaiCord-plugins/index.json.sig>
- `details/<sha256>.md`, `previews/<sha256>.png` and
  `files/<sha256>.dll|.json|.mcfx`, the files the index names

## Layout

Every item has its own folder, named by its slug (lower-case letters, digits
and `-`, at most 40 characters), with a `catalog.json` (what the catalog shows)
and a `details.md` (the item's page).

| Folder | Holds |
|---|---|
| `plugins/<slug>/` | `plugin.cpp` (source only, never a prebuilt DLL), `catalog.json`, `details.md` |
| `themes/<slug>/` | `theme.json` (a MaiCord theme document, 64 KiB at most), `preview.png` (1440x900, 256 KiB at most), `catalog.json`, `details.md`, `README.md` |
| `effects/<slug>/` | `<slug>.hlsl` (written against `maicord/sdk/background.hlsli`), `<slug>.effect` (the sidecar the client's dev folder reads), `catalog.json`, `details.md` |

Beside the items:

| Path | Holds |
|---|---|
| `index/revocations.json` | The files the signed index tells clients to turn off |
| `scripts/` | The build: `build_catalog.py`, `publish_index.py`, `check_site.py`, `review_report.py`, the effect tools and their tests |
| `.github/workflows/catalog.yml` | CI: build, review report, sign, deploy |
| `.github/` | The pull request and issue templates |

[CONTRIBUTING.md](CONTRIBUTING.md) lists every `catalog.json` member and its
limits. `details.md` uses the Markdown subset the site and the client render:
headings, paragraphs, `-` lists, code, `**bold**`, `` `code` `` and https links.
No tables, images, HTML or numbered lists.

## Proposing an item

1. Write it with MaiCord's tools (`maicord-plugin` for plugins and effects; see
   the [SDK guide](https://github.com/maj113/MaiCord/blob/master/include/maicord/sdk/README.md)
   and the [effect guide](https://github.com/maj113/MaiCord/blob/master/samples/effects/README.md)),
   and try it in Developer Mode.
2. Add its folder to a fork and open a pull request, one item per pull
   request. [CONTRIBUTING.md](CONTRIBUTING.md) has the steps for each kind and
   the checklist the pull request template asks you to tick.
3. CI builds it from the pull request: plugins compile with MaiCord's pinned
   clang-cl against the SDK headers of MaiCord's repository; effects compile
   with `fxc`, are linted (constant buffer `b0`, textures `t0-t4`, samplers
   `s0-s2`, no UAVs, at most 4,096 instructions and 64 texture reads),
   measured and rendered on WARP (the in-box software rasterizer) into a still
   and a short loop; themes are checked and swatched. The run's summary lists,
   for every changed item, the permissions and network hosts it declares
   against the published version, the DLL size, the effect's cost class and its
   previews. It needs no secret, so it works on pull requests from forks.
4. A maintainer reviews, asks for changes or merges.
5. CI on `main` builds again, signs the index and deploys it. Clients see the
   item on their next catalog check.

Don't want to write code? [Request a plugin](https://github.com/maj113/MaiCord-plugins/issues/new/choose).

## Review policy

A maintainer reads every line that gets listed. Plugins are native code with
the same access to the PC as MaiCord, so the review asks:

- Does the source do what `details.md` says, and nothing else? No hidden
  network use, no telemetry, no obfuscated code.
- Are the permissions the least the plugin needs, and is every network host
  used and disclosed on the details page? The CI report shows both, and what a
  new version added.
- Is it safe for the user's Discord account (see below)?
- Is the license one that allows redistribution and modification, and are the
  authors and any original author credited?
- Is it one source file that builds with the pinned toolchain, with a version
  bump for every change?
- Themes: do the text colours meet WCAG AA (4.5:1 for text, 3:1 for muted text
  and accents)? Effects: is the cost class one the picker can offer? An effect
  slower than the `heavy` class is refused.

Every version is reviewed before it is listed. The index lists only files CI
builds from the merged commit, never anything an author uploads.

### Discord's Terms of Service

Plugins that may break Discord's Terms of Service are not accepted:

- **Self-bots:** acting for the user's account without the user doing it,
  that is sending, editing, deleting or reacting on a timer or an event (the
  `automated_actions` permission).
- **Paid-feature bypass:** unlocking what Discord sells, such as Nitro-only
  emoji, stickers or themes.
- **Persistent message logs:** saving other people's deleted or edited messages
  to disk (the `persistent_log` permission). Keeping them visible until MaiCord
  closes (`message_history`) is allowed.

The build enforces the two permissions: a plugin that declares
`automated_actions` or `persistent_log` fails CI. The rest is judged in
review: no telemetry, no hidden network use, no obfuscated code, and anything
else that could put the user's account at risk. Anything this policy refuses
can still be sideloaded in Developer Mode, at the user's own risk.

### Licenses and credit

Every item states its license in `catalog.json`. It may be anything that allows
redistribution and modification (CC BY-NC-SA counts); no license means no
listing. Credit is shown to users: `authors` for the people who wrote it and
`derived_from` (URL, author, license) for what it was ported or adapted from.

### Takedowns

A listed item can be revoked: add its file's SHA-256 to
[`index/revocations.json`](index/revocations.json) and the signed index tells
clients to turn it off. See [CONTRIBUTING.md](CONTRIBUTING.md#takedowns-and-security-reports).

## Sideloading

MaiCord installs themes and effects from a link or a file behind a "not
reviewed" card. It loads a plugin that isn't in this catalog only when
**Developer Mode** is on, and marks it everywhere. Sideloads are the user's
choice and responsibility: they get no review and no automatic updates. That
is the home of plugins the catalog's policy refuses.

## How signing and publishing work

1. Pull requests run the **build** job: it needs no secret and signs nothing,
   so a pull request from a fork can never reach the key.
2. A merge to `main` (and a weekly run, and a manual run) builds everything
   again, then the **sign** job stamps the index with its issue time, an expiry
   30 days later (the client accepts at most 35) and a sequence that grows with
   every run, renders it under MaiCord's strict schema, and signs it with the
   catalog key. The key is a secret of the protected `catalog` environment.
3. The job verifies the signature against the public key compiled into MaiCord,
   and the **deploy** job publishes the site to GitHub Pages.
4. MaiCord checks the signature, the expiry and the sequence on every fetch,
   and checks each downloaded file against the SHA-256 the signed index lists.
   A listed binary is always one CI built from reviewed source in this
   repository, and published plugin versions are immutable: the last four stay
   available for rollback.

The workflow is
[`.github/workflows/catalog.yml`](.github/workflows/catalog.yml). Key setup and
rotation are described in MaiCord's
[`tools/release/README.md`](https://github.com/maj113/MaiCord/blob/master/tools/release/README.md#plugin-catalog).

### What the build does

Set the `MAICORD_SDK_REF` repository variable to pin the MaiCord branch, tag or
commit the SDK headers come from (default: `master`).

- **Build** (every push, pull request, schedule and manual run; no secrets):
  checks out MaiCord's `master` (sparse: the SDK headers, the toolchain pin and
  `tools/release`), runs the tool tests, builds every item, checks that every
  file the index will name exists with the right size and hash, and on pull
  requests writes the review report.
- **Sign** (not on pull requests): see above.
- **Deploy** the site to GitHub Pages.

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
publish; `--only plugin/clear-urls ...` builds a subset. A throwaway key comes
from MaiCord's `tools/release/generate_update_key.py`; use it only for this
local run and keep it out of the repository (`*.jwk` is ignored).
