# Silk Waves

Follows the Silk Waves sky through the day and the year: near-black with the month's glow at night, soft month-tinted light by day, turning light and dark on its own.

| | |
|---|---|
| Author | MaiCord |
| License | MIT |
| Kind | Theme (changes with the time of day) |
| Base | Dark at night and dawn, light by day and at dusk |
| Effect | [Silk Waves](../../effects/silk-waves/details.md) |
| Needs | MaiCord 0.6.4 or later (theme interface 2) |
| File | [`theme.json`](theme.json) |

![Silk Waves in the main chat view](preview.png)

## How it changes

`theme.json` holds four phases in `variants`, each with a base and, for every month, its surfaces, controls, accent and text. MaiCord follows the Silk Waves schedule: each phase is held around its hours (night 23:00 to 01:00, dawn 05:00 to 07:00, day 11:00 to 13:00, dusk 17:00 to 19:00) and the next one takes over on a smoothstep across the four hours between. Night and dawn are dark, day and dusk light, so the theme turns light at 09:00 and dark at 21:00; there the nearer phase shows whole and the change glides over 1.5 seconds. While the theme is on, the Silk Waves effect's appearance follows it, not Windows, so its day sky shows under the light phases.

Each month's colours hold until the 5th and then turn toward the next month's, reaching them at the month's end, as the Silk Waves sky does. The root `colors` are October's night: what a MaiCord without variants shows.

## Colours

Derived from Silk Waves' own palette (`effects/silk-waves/silk-waves.hlsl`): per month a day sky (top and bottom) and a night glow.

| Phase | Base | Surfaces | Accent | Text |
|---|---|---|---|---|
| Night | Dark | Near-black (value 0.035 to 0.13) with a faint tint of the month's night glow | The night glow's hue at luminance 0.155 | Near-white and a light grey of the same tint |
| Dawn | Dark | Lifted dark (value 0.07 to 0.19) tinted halfway between the night glow and the day sky's bottom | The day sky's bottom hue at luminance 0.175 | As at night |
| Day | Light | White mixed with 5 to 30 % of the month's day sky top | The day sky's bottom hue at luminance 0.13 | Near-black and a dark grey of the sky's hue, solved for 5:1 on the darkest surface |
| Dusk | Light | White mixed with 9 to 40 % of the day sky's bottom and the night glow | Their hue at luminance 0.10 | As by day; notifications a deeper red that keeps 3:1 |

Four months, for example:

| Month and phase | Chat | Sidebar | Cards | Accent | Text | Muted text |
|---|---|---|---|---|---|---|
| January, night | `#121314` | `#0e0e0f` | `#18191a` | `#556caa` | `#e6e9f2` | `#aeb2bd` |
| April, dawn | `#1f181b` | `#191415` | `#271e21` | `#b25677` | `#f2e4e9` | `#bdabb1` |
| July, day | `#edfbf9` | `#e0f7f5` | `#f6fdfc` | `#0c7171` | `#141f1e` | `#3c6460` |
| October, dusk | `#f2e7d8` | `#ebdac2` | `#f8f2e9` | `#804d07` | `#211c15` | `#5a4b36` |

## Contrast

The worst case over every surface (server rail, sidebar, chat, cards, inputs), month, step of a month turning toward the next and step between two phases of one base:

| Pair | Night | Dawn | Day | Dusk | Target |
|---|---|---|---|---|---|
| Text | 11.3:1 | 10.9:1 | 8.4:1 | 7.9:1 | 4.5:1 |
| Muted text | 6.4:1 | 6.2:1 | 5.0:1 | 5.0:1 | 4.5:1 |
| Links on the chat and sidebar | 3.1:1 | 3.1:1 | 4.5:1 | 4.4:1 | 3:1 |
| Text on accent | 4.7:1 | 4.6:1 | 5.8:1 | 7.0:1 | 4.5:1 |

The catalog's build checks text and muted text on every surface and the accent on the chat and sidebar in every phase, month and step; MaiCord's own contrast warnings stay silent for it at every quarter hour of the 1st, 12th, 20th and 31st of every month.

## Install

Install it from MaiCord's Themes page, or download [`theme.json`](theme.json) and choose **Settings > Appearance > Import theme…**.
