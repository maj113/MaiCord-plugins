A silky wave inspired by the PS3 menu background: a ribbon of folded translucent layers that drifts and turns over a monthly day or night sky, glowing where it folds, with tiny flakes around it that glint as they spin. The colours follow the month and the time of day.

It is an unofficial fan work, not affiliated with or endorsed by Sony. It is our own implementation, matched against the original by eye and against recordings: no code, textures or other data from anyone else, and the month and day and night colours are our own.

It needs a MaiCord that draws pass graphs (effects interface 3); an older one doesn't list it.

## Knobs

- **Month**: follow the date (each month's colours turn slowly toward the next month's from the 5th), or one month.
- **Day and night**: follow the clock (the sky turns to night whenever the appearance is dark, so the light day sky never sits under a dark theme's text); the clock, but the whole look at night whenever the appearance is dark (the default); always day, for light themes; always night. With the Silk Waves theme, which turns light by day and dark at night, the sky follows it.
- **Wave speed**: 1 is the natural pace, a wave about every 21 seconds.
- **Wave brightness**, **Glitter** and **Glare**: 1 is the intended level.

It asks for 75 % resolution at 30 frames per second; you can change both.

## How it works

Six passes; the first is a simulation that keeps its state on the GPU. The full story, with the equations, is in `HOW-IT-WORKS.md` beside the shader.

- **The cloth.** The ribbon's skeleton is a 19 x 19 sheet of masses joined by springs to their neighbours and, ten times stiffer, to the nodes two away. Every node gets a small random push each step, the sheet is lightly damped, one edge is driven along a slow Lissajous curve and the other is pulled outward. It runs at 60 steps a second whatever the frame rate, one texel per node. Its clock wraps every 14 minutes: the wave cross-fades into its new cycle and the driven edge races back, shaking the sheet and throwing flakes wide. It starts from a sheet of our own run of the same model, so the first frame looks right.
- **The wave.** The nodes are bent by a free-form deformation: a lattice whose nodes follow a closed-form travelling wave that grows along the ribbon, plus a slow bob, a wandering bump and a ripple across the ribbon. They become the control points of a bicubic B-spline surface, drawn as a 128 x 128 grid of vertices and added into a float target. Each vertex is lit by how densely the surface crowds onto the screen and by how it faces the eye, which is why the folds glow.
- **The flakes.** 2,048 flakes are born at vertices of the ribbon's mesh (random ones, and now and then a streak walking along the ribbon), thrown within a cone around the way that vertex is moving (sometimes backwards), faster where the ribbon moves faster, and flattened onto the screen plane. They drift with a little drag and random jostling, each with a small steady push of its own that carries it slowly toward or away from the camera, spin about an axis that turns with their age, and fade in and out over a 4 to 11 second life. Each is a flat disc lit by a lamp: it glints when its face turns toward the half vector (a few percent at any moment, each for about a fifth of a second) and then gets a small glare halo too. Out of focus, nearer than 7.4 or beyond 12.8, a flake grows and blurs into a soft bokeh disc.
- **The picture.** A full-screen pass adds the wave to the sky and tone maps it: a linear exposure with a black crush, which keeps the top of the night sky black and makes the lines warm over the sky's glow. Light beyond white glares softly, blurred at a quarter size; the flakes are added last. The 16:9 picture, sky included, is scaled to cover the window: a narrower window loses the sides, a wider one a little top and bottom, so the ribbon always runs past both edges and keeps its place over the glow.
- **The time of day.** Four presets (night, dawn, day, dusk) are held around keyframes (night to 1:00, dawn 5:00 to 7:00, day 11:00 to 13:00, dusk 17:00 to 19:00, night from 23:00) and blend smoothly between them: the line brightness and sheen, the exposure and white level, the camera's tilt, the ribbon's flare and depth, and the flakes' size. The day sky fades in after midnight and out between 18:30 and 20:18, and its sun runs on a clock that is slow in the evening, so dusk lingers.

## Tuned by eye

These were matched by eye against recordings and could still move a little:

- the shape of the line and sheen curves, and the line pattern at small densities;
- the flakes' colour (our own thin-film tint);
- the day sky's brightness through its day, and the glare's width;
- the night sky, which our night palette stands for all night;
- the cloth's starting sheet, from our own run. How folded the ribbon is, and so how bright, and how often its near edge comes close enough for bokeh discs, depends on that state and drifts as the cloth runs.

## Credits

**PlayStation 3 XMB Waves Recreation** by linkev (Mart), MIT License, was the earlier port of this effect and the inspiration for it: https://github.com/linkev/PlayStation-3-XMB

This version shares no code with it; it is MIT licensed as well.
