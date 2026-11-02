#!/usr/bin/env python3
"""Self-contained checks for the catalog build tools (no toolchain, GPU or key needed).

    python -B scripts/test_catalog_tools.py

Covers what can be checked without compiling: the effect annotations and knob slots against every effect in the
repository, the `.mcfx` container layout, the details Markdown subset, the theme colour reader, that every item
folder has the files the build reads, and the pull request review report.
"""

from __future__ import annotations

import io
import json
import struct
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_catalog  # noqa: E402
import effects  # noqa: E402
import images  # noqa: E402
import review_report  # noqa: E402


def effect_folders():
    return sorted(p for p in (ROOT / "effects").iterdir() if p.is_dir())


class EffectTests(unittest.TestCase):
    def test_every_effect_agrees_with_its_sidecar_and_defines(self):
        self.assertEqual(len(effect_folders()), 7)
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


class PolicyTests(unittest.TestCase):
    def test_refused_permissions_fail_the_build(self):
        build_catalog.refuse_policy_permissions("ok", ["read_messages", "network", "message_history"])
        for permission in ("automated_actions", "persistent_log"):
            with self.assertRaisesRegex(build_catalog.BuildError, permission):
                build_catalog.refuse_policy_permissions("bad", ["clipboard", permission])


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
        self.assertIn("changes no plugin, theme or effect folder", review_report.render({}, {}, set()))


if __name__ == "__main__":
    unittest.main(verbosity=1)
