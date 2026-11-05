#!/usr/bin/env python3
"""Self-contained checks for the catalog build tools (no toolchain, GPU or key needed).

    python -B scripts/test_catalog_tools.py

Covers what can be checked without compiling: the effect annotations and knob slots against every effect in the
repository, the `.mcfx` container layout, the details Markdown subset, the theme colour reader, that every item
folder has the files the build reads, and the pull request review report.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import struct
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_catalog  # noqa: E402
import build_linux_plugins  # noqa: E402
import effects  # noqa: E402
import images  # noqa: E402
import published  # noqa: E402
import review_report  # noqa: E402


def effect_folders():
    return sorted(p for p in (ROOT / "effects").iterdir() if p.is_dir())


class EffectTests(unittest.TestCase):
    def test_every_effect_agrees_with_its_sidecar_and_defines(self):
        self.assertEqual(len(effect_folders()), 8)
        for folder in effect_folders():
            slug = folder.name
            source = (folder / f"{slug}.hlsl").read_text(encoding="utf-8")
            sidecar = effects.parse_sidecar((folder / f"{slug}.effect").read_text(encoding="utf-8"))
            meta = json.loads((folder / "catalog.json").read_text(encoding="utf-8"))
            header = effects.parse_header(source)
            self.assertEqual(header["effect"]["name"], meta["name"], slug)
            self.assertEqual(header["blend"], sidecar["blend"], slug)
            self.assertEqual(sorted(header["uses"]), sorted(sidecar.get("uses", "").split()), slug)
            effects.check_defines(source, header["knobs"])
            values = effects.knob_values(header["knobs"])
            given = [int(v) / 1000 for v in sidecar["knobs"].split()]
            for lane, expected in enumerate(values):
                self.assertAlmostEqual(given[lane] if lane < len(given) else 0.0, expected, delta=0.0015, msg=f"{slug} mc_knobs value {lane}")

    def test_knob_slots(self):
        knobs = [{"type": "float"}, {"type": "int"}, {"type": "toggle"}, {"type": "choice"}, {"type": "float"},
                 {"type": "color"}, {"type": "float"}, {"type": "color"}]
        self.assertEqual(effects.assign_slots(knobs), [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (2, None), (3, 0), (4, None)])
        with self.assertRaises(effects.EffectError):
            effects.assign_slots([{"type": "color"}] * 9)

    def test_knob_annotations(self):
        source = ('// @effect name="X" license="MIT"\n// @blend add\n'
                  '// @knob a float 0..2 = 0.5 "A"\n// @knob b int 1..4 = 3 "B"\n// @knob c toggle = off "C"\n'
                  '// @knob d color = #AABBCC "D"\n// @knob e choice "One|Two|Three" = 2 "E"\n// @uses noise glyphs\n')
        header = effects.parse_header(source)
        self.assertEqual([k["type"] for k in header["knobs"]], ["float", "int", "toggle", "color", "choice"])
        self.assertEqual(header["knobs"][4], {"id": "e", "type": "choice", "label": "E", "choices": ["One", "Two", "Three"], "default": 2})
        for bad in ('// @knob a float 2..0 = 1 "A"', '// @knob a int 0..1.5 = 1 "A"', '// @knob a float 0..1 = 1', '// @blend multiply'):
            with self.assertRaises(effects.EffectError, msg=bad):
                effects.parse_header(source + bad + "\n")

    def test_container_layout(self):
        package = effects.pack_mcfx({"SOURCE": b"s" * 5, "DXBC": b"DXBC" + b"d" * 8, "MANIFEST": b"{}"})
        magic, version, count, total, reserved = struct.unpack_from("<4sHHII", package)
        self.assertEqual((magic, version, count, total, reserved), (b"MCFX", 1, 3, len(package), 0))
        table = [struct.unpack_from("<IIII", package, 16 + 16 * i) for i in range(count)]
        self.assertEqual([t[0] for t in table], [1, 2, 5])
        offset = 16 + 16 * count
        for kind, start, size, zero in table:
            self.assertEqual((start, zero), (offset, 0))
            offset += size
        self.assertEqual(offset, len(package))
        self.assertEqual(package[table[2][1]:], b"sssss")
        with self.assertRaises(effects.EffectError):
            effects.pack_mcfx({"MANIFEST": b"{}"})

    def test_universal_package_is_the_same_package_with_glsl_and_interface_4(self):
        manifest = b'{"interface":3,"slug":"x","passes":[]}'
        plain = effects.pack_mcfx({"MANIFEST": manifest, "DXBC": b"DXBC" + b"d" * 8, "SOURCE": b"s", "SHADERS": b"DXBC"})
        glsl = struct.pack("<HH", 1, 0) + b"entry"
        universal = effects.universal_package(plain, glsl)
        old, new = effects.read_sections(plain), effects.read_sections(universal)
        self.assertEqual(list(new), ["MANIFEST", "DXBC", "SOURCE", "SHADERS", "GLSL"], "written in section order")
        self.assertEqual(new["MANIFEST"], b'{"interface":4,"slug":"x","passes":[]}')
        self.assertEqual(new["GLSL"], glsl)
        for name in ("DXBC", "SOURCE", "SHADERS"):
            self.assertEqual(new[name], old[name], f"{name} is the DXBC package's")
        self.assertEqual(effects.read_sections(effects.universal_package(plain.replace(b'"interface":3', b'"interface":1'), glsl))["MANIFEST"][:15],
                         b'{"interface":4,')
        with self.assertRaises(effects.EffectError):
            effects.universal_package(universal, glsl)  # already has the section
        with self.assertRaises(effects.EffectError):
            effects.universal_package(effects.pack_mcfx({"MANIFEST": b'{"slug":"x"}', "DXBC": b"D"}), glsl)
        for broken in (plain[:-1], plain + b"\0", b"MCFX" + plain[4:12] + b"\1" + plain[13:], b"nope"):
            with self.assertRaises(effects.EffectError):
                effects.read_sections(broken)

    def test_ambient_inputs_are_interface_2_and_stay_out_of_the_index(self):
        source = '// @effect name="X" license="MIT"\n// @blend normal\n// @uses blue_noise clock appearance\n'
        header = effects.parse_header(source)
        meta = {"name": "X", "authors": [{"name": "A"}], "license": "MIT"}
        document = effects.manifest("x", header, {}, meta, "1.0.0")
        self.assertEqual((document["interface"], document["uses"]), (2, ["blue_noise", "clock", "appearance"]))
        plain = effects.manifest("x", effects.parse_header(source.replace(" clock appearance", "")), {}, meta, "1.0.0")
        self.assertEqual(plain["interface"], 1, "an effect without them still runs on every client")
        # The index reader of a format-2 client refuses unknown names: the index lists the old six only.
        self.assertEqual(effects.INDEX_USES, ("noise", "glyphs", "blue_noise", "pointer", "texture0", "texture1"))
        self.assertNotIn("clock", effects.INDEX_USES)

    def test_cost_classes(self):
        self.assertEqual([effects.cost_class(r) for r in (0.1, 0.5, 0.51, 1.5, 4.0)], ["light", "light", "medium", "medium", "heavy"])
        with self.assertRaises(effects.EffectError):
            effects.cost_class(4.01)

    def test_lint_refuses_what_the_client_does_not_bind(self):
        ok = "ps_5_0\ndcl_constantbuffer CB0[12], immediateIndexed\ndcl_sampler s1, mode_default\ndcl_resource_texture2d (float,float,float,float) t2\nmov r0.x, l(1)\nret\n"
        self.assertEqual(effects.lint(ok), {"instructions": 1, "samples": 0})
        for bad in ("dcl_constantbuffer CB1[2], immediateIndexed\n", "dcl_uav_typed_texture2d (float) u0\n",
                    "dcl_resource_texture2d (float,float,float,float) t7\n", "dcl_sampler s4, mode_default\n",
                    "mov r0.x, l(1)\n" * 4097):
            with self.assertRaises(effects.EffectError, msg=bad[:40]):
                effects.lint(bad)
        with self.assertRaises(effects.EffectError):
            effects.lint("sample_l r0.xyzw, r1.xy, t0.xyzw, s0, l(0)\n" * 65)
        graph = "vs_5_0\ndcl_resource_texture2d (float,float,float,float) t10\nld r0.xyzw, v0.xyzw, t10.xyzw\nret\n"
        self.assertEqual(effects.lint(graph, 10), {"instructions": 1, "samples": 1}, "interface 3 binds t0-t10")
        with self.assertRaises(effects.EffectError):
            effects.lint(graph)

    GRAPH = ('// @effect name="X" license="MIT"\n// @blend normal\n'
             '// @target parts rgba32f 32x32 persistent\n// @target glow rgba16f 50%\n'
             '// @pass simulate to=parts in=parts\n// @pass ribbon vs=ribbon_vs grid=96x24 to=glow blend=add clear\n'
             '// @pass compose in=glow\n// @pass spark vs=spark_vs quads=1024 in=parts blend=add\n')

    def test_a_pass_graph_is_interface_3_with_the_clients_graph(self):
        header = effects.parse_header(self.GRAPH)
        meta = {"name": "X", "authors": [{"name": "A"}], "license": "MIT"}
        document = effects.manifest("x", header, {}, meta, "1.0.0")
        self.assertEqual(document["interface"], 3)
        self.assertEqual(document["targets"], [{"format": "rgba32f", "size": [32, 32], "persistent": True},
                                               {"format": "rgba16f", "scale": 50}])
        self.assertEqual(document["passes"], [{"ps": 0, "target": 0, "inputs": [0]},
                                              {"ps": 2, "vs": 1, "grid": [96, 24], "target": 1, "blend": "add", "clear": True},
                                              {"ps": 3, "inputs": [1]},
                                              {"ps": 5, "vs": 4, "quads": 1024, "inputs": [0], "blend": "add"}])
        targets, passes, shaders = effects.graph_of(header)
        self.assertEqual(shaders, [("simulate", "ps_5_0"), ("ribbon_vs", "vs_5_0"), ("ribbon", "ps_5_0"),
                                   ("compose", "ps_5_0"), ("spark_vs", "vs_5_0"), ("spark", "ps_5_0")])
        text = effects.graph_text(targets, passes, shaders, Path("w"), "x").splitlines()
        self.assertEqual(text[1], f"shader vs {Path('w') / 'x.ribbon_vs.cso'}")
        self.assertEqual(text[6:], ["target 2 32 32 0 1", "target 1 0 0 50 0", "pass -1 0 0 1 0 0 0 0 0",
                                    "pass 1 2 1 0 2 96 24 0 1", "pass -1 3 -1 2 0 0 0 0 0", "pass 4 5 -1 1 2 0 0 1024 0"])
        self.assertEqual(effects.interface_of(effects.parse_header('// @effect name="X" license="MIT"\n// @blend normal\n'
                                                                   '// @uses texture2\n')), 3)
        package = effects.pack_mcfx({"SHADERS": b"s", "DXBC": b"d", "MANIFEST": b"{}"})
        self.assertEqual([struct.unpack_from("<I", package, 16 + 16 * i)[0] for i in range(3)], [1, 2, 9])

    def test_graph_limits_are_the_clients(self):
        good = '// @effect name="X" license="MIT"\n// @blend normal\n// @target a rgba16f 50%\n'
        for text in ("// @pass p to=a\n", "// @pass p to=a in=a\n// @pass q\n", "// @pass p vs=v\n",
                     "// @pass p vs=v grid=1x4\n", "// @pass p vs=v quads=16385\n", "// @pass p in=b\n", "// @pass p\n" * 7,
                     "// @target b rgba32f 512x512 persistent\n// @target c rgba8 1x1\n// @pass p\n",
                     "// @target b rgba32f 100% persistent\n// @pass p\n", "// @pass p vs=p quads=1\n"):
            with self.assertRaises(effects.EffectError, msg=text):
                effects.graph_of(effects.parse_header(good + text))


class DetailsAndThemeTests(unittest.TestCase):
    def test_details_subset(self):
        good = "Text with **bold**, `code` and [a link](https://example.com/x).\n\n### Heading\n\n- one\n- two\n\n```\n| not a table |\n```\n"
        self.assertEqual(build_catalog.check_details(good, "t"), good.encode())
        for bad in ("| a | b |\n", "![img](https://example.com/a.png)\n", "<b>x</b>\n", "1. one\n", "* item\n", "[x](http://example.com)\n",
                    "> quote\n", "a\r\nb\n", "", "x" * 16385, "```\nunclosed\n", "tab\there\n"):
            with self.assertRaises(build_catalog.BuildError, msg=bad[:20]):
                build_catalog.check_details(bad, "t")

    def test_every_item_has_its_files(self):
        for kind, folder in build_catalog.DIRECTORIES.items():
            directories = sorted(p for p in (ROOT / folder).iterdir() if p.is_dir())
            self.assertGreaterEqual(len(directories), 5)
            for directory in directories:
                meta = build_catalog.item_metadata(kind, directory.name, directory)
                build_catalog.check_details((directory / "details.md").read_bytes().decode("utf-8"), directory.name)
                self.assertLessEqual(len(meta["summary"]), 255)
                if kind == "plugin":
                    self.assertTrue((directory / "plugin.cpp").is_file())
                    self.assertRegex(meta["owner_id"], r"0x[0-9A-F]{16}")
                if kind == "theme":
                    self.assertTrue((directory / "theme.json").is_file() and (directory / "preview.png").is_file())

    def test_theme_colours(self):
        document = {"palette": {"p": [1, 0.5, 0, 1]}, "colors": {"a": "{palette.p}", "b": "#AABBCCDD"}}
        self.assertEqual(build_catalog.theme_color(document, document["colors"]["a"]), "#ff8000")
        self.assertEqual(build_catalog.theme_color(document, document["colors"]["b"]), "#aabbcc")
        with self.assertRaises(build_catalog.BuildError):
            build_catalog.theme_color(document, "red")

    def test_silk_waves_theme_is_readable_in_every_phase_and_month(self):
        document = json.loads((ROOT / "themes" / "silk-waves" / "theme.json").read_text(encoding="utf-8"))
        looks = build_catalog.variant_looks(document, "silk-waves")
        # 4 phases in 12 months, each in 8 steps of turning toward the next month, and 7 mixing steps for each of the
        # two same-base pairs (night to dawn, day to dusk).
        self.assertEqual(len(looks), 4 * 12 * 8 + 2 * 12 * 8 * 7)
        build_catalog.check_variant_contrast(document, "silk-waves")
        for where, colours in looks:
            for surface in build_catalog.SURFACES:
                for text in ("text_primary", "text_secondary"):
                    self.assertGreaterEqual(build_catalog.contrast(colours[text], colours[surface]), 4.5, f"{text} on {surface}, {where}")
        bases = {phase: document["variants"][phase]["base"] for phase in build_catalog.PHASES}
        self.assertEqual(bases, {"night": "dark", "dawn": "dark", "day": "light", "dusk": "light"})
        self.assertEqual(document["background"]["effect"], "silk-waves")

    def test_variant_contrast_refuses_unreadable_or_incomplete_themes(self):
        document = json.loads((ROOT / "themes" / "silk-waves" / "theme.json").read_text(encoding="utf-8"))
        document["variants"]["day"]["months"][5]["text_secondary"] = "#c0c0c0"
        with self.assertRaisesRegex(build_catalog.BuildError, r"text_secondary on .* at day, month [56]"):
            build_catalog.check_variant_contrast(document, "t")
        del document["variants"]["dusk"]
        with self.assertRaisesRegex(build_catalog.BuildError, "night, dawn, day and dusk"):
            build_catalog.variant_looks(document, "t")
        self.assertEqual(build_catalog.mix_colour("#000000", "#ff8040", .5), "#804020")

    def test_follow_names_choice_knobs_of_the_themes_effect(self):
        document = json.loads((ROOT / "themes" / "silk-waves" / "theme.json").read_text(encoding="utf-8"))
        background = document["background"]
        self.assertEqual(background["follow"], {"month": "month", "phase": "sky", "phases": ["auto", "auto", "day", "night"]})
        build_catalog.check_follow(background, "silk-waves")
        for follow in ({"month": "speed"}, {"month": "sky"}, {"phase": "sky", "phases": ["auto", "day"]},
                       {"phase": "sky", "phases": ["auto", "auto", "noon", "night"]}, {"phase": "sky"},
                       {"phases": ["day"]}, {"month": "month", "hour": "x"}):
            with self.assertRaisesRegex(build_catalog.BuildError, "follow", msg=str(follow)):
                build_catalog.check_follow(dict(background, follow=follow), "t")
        with self.assertRaisesRegex(build_catalog.BuildError, "follow"):
            build_catalog.check_follow({"effect": "starfield", "follow": {"month": "month"}}, "t")


class PolicyTests(unittest.TestCase):
    def test_refused_permissions_fail_the_build(self):
        build_catalog.refuse_policy_permissions("ok", ["read_messages", "network", "message_history"])
        for permission in ("automated_actions", "persistent_log"):
            with self.assertRaisesRegex(build_catalog.BuildError, permission):
                build_catalog.refuse_policy_permissions("bad", ["clipboard", permission])

    def test_slugs_the_website_reserves_are_refused(self):
        for kind in build_catalog.DIRECTORIES:
            with self.assertRaisesRegex(build_catalog.BuildError, "reserved for the website"):
                build_catalog.item_metadata(kind, "develop", ROOT / "plugins" / "develop")
            build_catalog.check_slug(kind, "developer")
        for kind, folder in build_catalog.DIRECTORIES.items():
            self.assertFalse(any(p.name in build_catalog.RESERVED_SLUGS for p in (ROOT / folder).iterdir()))


def release_tools():
    """MaiCord's tools/release (plugin_index.py): MAICORD_TOOLS_RELEASE, else next to this repository (CI's `maicord`,
    a sibling checkout's `MaiCord`); None when it isn't there."""
    for candidate in (os.environ.get("MAICORD_TOOLS_RELEASE"), ROOT.parent / "maicord" / "tools" / "release",
                      ROOT.parent / "MaiCord" / "tools" / "release"):
        if candidate and (Path(candidate) / "plugin_index.py").is_file():
            return Path(candidate)
    return None


class FakeSite(published.Previous):
    """A published site held in memory."""

    def __init__(self, files: dict):
        super().__init__("memory")
        self.files = files

    def read(self, name: str):
        return self.files.get(name)


class LinuxPayloadTests(unittest.TestCase):
    @staticmethod
    def source(sha: str, linux: str | None = None) -> dict:
        version = {"version": "1.0.0", "released": 1700000000, "api_level": 3, "permissions": ["message_send"], "network": [],
                   "file": {"sha256": sha, "bytes": 4096}}
        if linux:
            version["linux"] = {"sha256": linux, "bytes": 2048}
        item = {"kind": "plugin", "slug": "demo", "name": "Demo", "summary": "Does a thing.", "authors": [{"name": "A"}],
                "license": "MPL-2.0", "source": "https://github.com/maj113/MaiCord-plugins/tree/main/plugins/demo",
                "categories": ["utility"], "details": {"sha256": "d" * 64, "bytes": 10}, "previews": [], "versions": [version]}
        return {"format": 2, "sequence": 1, "issued": 1, "expires": 2, "items": [item], "revoked": [], "blocklist": []}

    def site(self, plugin_index, source: dict, listed_in_4: bool) -> FakeSite:
        """The documents a publish of `source` leaves; with listed_in_4 False, index-4.json is the one from before
        shared objects existed (it lists the DLL)."""
        files = {}
        for name, reader, _ in plugin_index.INDEXES:
            shown = plugin_index.reader_source(source, reader)
            if reader == 4 and not listed_in_4:
                shown = plugin_index.reader_source(source, 3)
            files[name] = plugin_index.render_index(shown, reader)
        return FakeSite(files)

    def test_a_published_shared_object_is_carried_and_a_dll_listing_is_not(self):
        tools = release_tools()
        if tools is None:
            self.skipTest("MaiCord's tools/release is not next to this repository")
        sys.path.insert(0, str(tools))
        import plugin_index

        dll, so = "a" * 64, "b" * 64
        for listed, expected in ((True, {("demo", "1.0.0"): {"sha256": so, "bytes": 2048}}), (False, {})):
            previous = self.site(plugin_index, self.source(dll, so), listed)
            with contextlib.redirect_stdout(io.StringIO()):
                items = build_catalog.previous_items(previous, plugin_index, None)
                found = build_catalog.previous_shared_objects(previous, plugin_index, None, items)
            self.assertEqual(found, expected, f"index-4 listed {'the shared object' if listed else 'the DLL'}")
            self.assertEqual(items[("plugin", "demo")]["versions"][0]["file"]["sha256"], dll, "index-3 keeps the DLL")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_catalog.previous_shared_objects(FakeSite({}), plugin_index, None, {}), {}, "nothing published")

    def test_the_shared_object_must_describe_the_same_plugin(self):
        record = {"version": "1.0.0", "api_level": 3, "permissions": ["message_send"], "network": ["a.example"]}
        meta = {"name": "Demo", "owner_id": "0x00000000000000AB"}
        info = {"name": "Demo", "owner_id": 0xAB, "api_level": 3, "permissions": ["message_send"], "network": ["a.example"],
                "version": "1.0.0", "summary": "s", "author": "a", "homepage": ""}
        build_linux_plugins.check_descriptor("demo", meta, record, info, None)
        for key, value in (("name", "Other"), ("owner_id", 0xAC), ("api_level", 2), ("permissions", ["message_send", "network"]),
                           ("network", [])):
            with self.assertRaisesRegex(build_catalog.BuildError, "one source must give one descriptor", msg=key):
                build_linux_plugins.check_descriptor("demo", meta, record, dict(info, **{key: value}), None)


class PngEncoderTests(unittest.TestCase):
    def _check(self, image):
        data = images.png_bytes(image)
        decoded = Image.open(io.BytesIO(data))
        decoded.load()
        self.assertEqual(decoded.convert("RGB").tobytes(), image.tobytes())
        plain = io.BytesIO()
        image.save(plain, "PNG", optimize=True)
        self.assertLessEqual(len(data), len(plain.getvalue()))
        return data

    def test_gradient_noise_and_flat_pictures_round_trip_and_never_grow(self):
        width, height = 96, 64
        gradient = Image.new("RGB", (width, height))
        gradient.putdata([((x * 2 + y) % 256, (x + y * 3) % 256, (x * y) % 256) for y in range(height) for x in range(width)])
        seed, grain = 12345, []
        for _ in range(width * height):
            seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
            grain.append((seed >> 16) % 4 * 60)
        noise = Image.new("RGB", (width, height))
        noise.putdata([(v, v // 2, 255 - v) for v in grain])
        for image in (gradient, noise, Image.new("RGB", (width, height), (9, 8, 7)), Image.new("RGB", (1, 1), (1, 2, 3))):
            self._check(image)

    def test_few_colours_use_a_palette(self):
        image = Image.new("RGB", (64, 48))
        image.putdata([((x // 8 + y // 8) % 5 * 50, 20, 30) for y in range(48) for x in range(64)])
        self.assertEqual(Image.open(io.BytesIO(self._check(image))).mode, "P")


def plugin_record(version, permissions, network, size=1000, sha="a" * 64):
    return {"kind": "plugin", "slug": "demo", "name": "Demo | **x**", "summary": "[evil](https://example.com)", "authors": [{"name": "Ada", "github": "ada"}],
            "license": "MIT", "categories": ["utility"],
            "versions": [{"version": version, "released": 1, "api_level": 2, "permissions": permissions, "network": network,
                          "file": {"sha256": sha, "bytes": size}}]}


class ReviewReportTests(unittest.TestCase):
    def test_touched_items(self):
        paths = ["plugins/clear-urls/plugin.cpp", "plugins/clear-urls/details.md", "effects/aurora/aurora.hlsl", "themes/fjord/theme.json",
                 "README.md", "scripts/build_catalog.py", "plugins/stray.txt"]
        self.assertEqual(review_report.touched_items(paths), {("plugin", "clear-urls"), ("effect", "aurora"), ("theme", "fjord")})

    def test_permission_and_host_diff(self):
        old = plugin_record("1.0.0", ["read_messages", "network"], ["a.example.com"], 1000, "b" * 64)
        new = plugin_record("1.1.0", ["read_messages", "network", "clipboard", "persistent_log"], ["a.example.com", "b.example.com"], 1300)
        report = review_report.render({("plugin", "demo"): new}, {("plugin", "demo"): old}, {("plugin", "demo")})
        self.assertIn("updated from 1.0.0", report)
        self.assertIn("**added:** `clipboard`, `persistent_log`", report)
        self.assertIn("**added:** `b.example.com`", report)
        self.assertIn("+300 bytes against the published 1,000", report)

    def test_new_item_and_unreadable_index(self):
        item = plugin_record("1.0.0", [], [])
        fresh = review_report.render({("plugin", "demo"): item}, {}, {("plugin", "demo")})
        self.assertIn("Nothing is published yet", fresh)
        self.assertIn("| new |", fresh)
        blind = review_report.render({("plugin", "demo"): item}, None, {("plugin", "demo")})
        self.assertIn("could not be read", blind)
        self.assertIn("| unknown |", blind)

    def test_author_text_is_escaped(self):
        report = review_report.render({("plugin", "demo"): plugin_record("1.0.0", [], [])}, {}, {("plugin", "demo")})
        self.assertNotIn("[evil]", report)
        self.assertIn("Demo \\| \\*\\*x\\*\\*", report)
        self.assertEqual(review_report.esc("a\n`b`<img src=x>"), "a \\`b\\`\\<img src=x\\>")

    def test_effect_cost_and_removed_item(self):
        effect = {"kind": "effect", "slug": "fx", "name": "Fx", "summary": "s", "authors": [{"name": "Ada"}], "license": "MIT",
                  "categories": [], "version": "1.0.1", "file": {"sha256": "c" * 64, "bytes": 2000}, "cost": "heavy", "blend": "add",
                  "uses": ["noise"], "knobs": [{"type": "float"}, {"type": "toggle"}], "previews": [
                      {"sha256": "d" * 64, "bytes": 5, "width": 960, "height": 540, "alt": "x"}],
                  "loop": {"sha256": "e" * 64, "bytes": 9, "width": 480, "height": 270, "fps": 15, "seconds": 3}}
        old = dict(effect, version="1.0.0", cost="light", file={"sha256": "f" * 64, "bytes": 1500})
        report = review_report.render({("effect", "fx"): effect}, {("effect", "fx"): old}, {("effect", "fx"), ("theme", "gone")})
        self.assertIn("**heavy** (published: light; **slower**)", report)
        self.assertIn("Knobs: 2 (1 float, 1 toggle)", report)
        self.assertIn("Loop: 480x270, 9 bytes, 15 fps for 3 s", report)
        self.assertIn("| `gone` | theme | removed from the catalog |", report)
        self.assertNotIn("Interface", report, "an interface-1 effect runs on every client")
        report = review_report.render({("effect", "fx"): dict(effect, interface=3)}, {}, {("effect", "fx")})
        self.assertIn("Interface 3: listed for MaiCord 0.6.3 and later only", report)
        self.assertIn("changes no plugin, theme or effect folder", review_report.render({}, {}, set()))


if __name__ == "__main__":
    unittest.main(verbosity=1)
