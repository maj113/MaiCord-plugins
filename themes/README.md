# Themes

Colour themes for MaiCord. The catalog lists them: they appear on MaiCord's Themes page and at maicord.com/themes, and you can also import one by hand.

| Theme | Base | Description | License |
|---|---|---|---|
| [Deep Ocean](deep-ocean/README.md) | Dark | A deep navy dark theme with a cool teal accent. | CC0-1.0 |
| [Warm Paper](warm-paper/README.md) | Light | A warm, cream-coloured light theme with a terracotta accent, easy on the eyes. | CC0-1.0 |
| [High Contrast](high-contrast/README.md) | Dark | Pure black and white with a yellow accent, strong borders and heavier icons. Passes WCAG AAA for text. | CC0-1.0 |
| [Fjord](fjord/README.md) | Dark | A muted, frosty blue-grey dark theme in the spirit of the Nord palette. | MIT |
| [Rose Dusk](rose-dusk/README.md) | Dark | Deep plum surfaces with a soft rose accent, like the sky just after sunset. | CC0-1.0 |
| [Obsidian](obsidian/README.md) | Dark | True black chat and surfaces for OLED panels, with neutral greys and an emerald accent. | CC0-1.0 |
| [Neon Grid](neon-grid/README.md) | Dark | Deep violet-black surfaces, a hot-pink accent and a faint drift of stars (asks for the Starfield effect). | CC0-1.0 |
| [Silk Waves](silk-waves/README.md) | Dark at night, light by day | Follows the Silk Waves sky through the day and the year, turning light and dark on its own (asks for the Silk Waves effect; MaiCord 0.6.4 and later). | MIT |

## Layout

Each theme has its own folder named by its slug:

- `catalog.json` and `details.md`: what the catalog shows (see the [repository README](../README.md#layout)).
- `theme.json`: a MaiCord theme document (`"version": "2.0"`, 64 KiB at most). It's the same format as `assets/themes/example.maicord-theme.json` in the client repository, which lists every token. A theme that changes with the time of day can also follow knobs of its effect (`background.follow`, see the [contributing guide](../CONTRIBUTING.md#a-theme-that-changes-with-the-time-of-day)): Silk Waves holds the month or the day or night you pick on the effect's knob page.
- `preview.png`: the main chat view at 1x (1440×900), rendered by MaiCord's own renderer.
- `README.md`: name, author, license, description and the contrast figures.

## Trying one now

Download a theme's `theme.json`, then in MaiCord choose **Settings > Appearance > Import theme…**. MaiCord checks the document and shows a preview before anything is applied.

## Contributing a theme

Open a pull request with a new folder holding these files. Themes here are licensed CC0-1.0 or MIT, say so in the README, and the text colours must meet WCAG AA (4.5:1 for text, 3:1 for muted text and accents).
