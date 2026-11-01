# MaiCord plugins

The official plugin catalog of [MaiCord](https://github.com/maj113/MaiCord), the
native Windows Discord client. MaiCord's plugin explorer reads the signed index
this repository publishes on GitHub Pages:

- <https://maj113.github.io/MaiCord-plugins/v1/index.json>
- <https://maj113.github.io/MaiCord-plugins/v1/index.json.sig>

The catalog is empty for now.

## How a plugin gets listed

1. Open a pull request that adds the plugin's **source**, never a prebuilt
   DLL. Each plugin lives in its own folder with its code, a `README.md` (its
   details page) and its catalog entry (slug, categories, authors, license).
2. A maintainer reviews the code and the permissions it asks for, then merges.
3. CI builds the plugin from the merged source, records its SHA-256, adds it to
   the index, signs the index and deploys it. Clients see the plugin on their
   next catalog check.

Every listed binary is built by CI from reviewed source in this repository.

## Policy

- Plugins that could break Discord's Terms of Service are not accepted. That
  includes automating a user account (self-bot behavior: sending, editing or
  reacting without the user's action), unlocking paid features, and logging
  deleted messages.
- Plugins must say what they do: no hidden network use, no telemetry, no
  obfuscated code.
- A listed plugin can be revoked: the signed index tells clients to disable it.

## Sideloading

MaiCord can load a plugin that isn't in this catalog when **Developer Mode** is
on. Sideloaded plugins are the user's choice and responsibility: they get no
review and no automatic updates.

## How publishing works

[`.github/workflows/catalog.yml`](.github/workflows/catalog.yml) runs on every
push to `main`, on manual dispatch, and weekly. It:

1. takes `tools/release` from MaiCord's `master` branch (`plugin_index.py`, the
   client's strict schema, and `cng_p256.py`, which signs with Windows CNG);
2. stamps [`index/source.json`](index/source.json) with the issue time, an
   expiry 30 days later (the client accepts at most 35) and a sequence equal to
   the issue time, so every run outranks the last one;
3. renders the compact index, signs it with the catalog key held in the
   `catalog` environment, and verifies it against the public key MaiCord
   compiles in;
4. deploys `v1/index.json` and `v1/index.json.sig` to GitHub Pages.

Key setup and rotation are described in MaiCord's
[`tools/release/README.md`](https://github.com/maj113/MaiCord/blob/master/tools/release/README.md#plugin-catalog).
