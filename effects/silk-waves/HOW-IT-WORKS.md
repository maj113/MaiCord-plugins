# How Silk Waves works

Silk Waves is a silky ribbon with glitter, inspired by the PS3 menu background. It is our own implementation,
matched against the original by eye and against recordings. This note walks through the shader
(`silk-waves.hlsl`) from the simulation to the last pixel. All constants below are the ones in the shader.

The effect is an interface-3 pass graph: six passes over four targets.

| Pass | Draws | Into | Reads |
| --- | --- | --- | --- |
| 1 `state` | every texel of the state | `state`, 64 x 173 RGBA32F, persistent | `state` (last frame) |
| 2 `wave` | a 128 x 128 vertex grid, added | `light`, RGBA16F, full size | `state` |
| 3 `glare` | full target | `glow`, RGBA16F, quarter size | `state`, `light` |
| 4 `bloom` | full target | `bloom`, RGBA16F, quarter size | `glow` |
| 5 `compose` | full screen | the output | `state`, `light`, `bloom` |
| 6 `glint` | 4,096 quads, added | the output | `state` |

The state target holds everything that lives from frame to frame:

| Rows | Columns | Holds |
| --- | --- | --- |
| 0-18 | 0-18 | cloth node positions (w = 1 marks a started sheet) |
| 19-37 | 0-18 | node velocities, and the wave clock t in w |
| 38-56 | 0-18 | the surface's control points now, and the edge's lagging clock in w |
| 57-75 | 0-18 | the control points a frame ago, and the 60 Hz steps between in w |
| 76 | 0-5 | the time of day's mood, worked out once a frame |
| 77-108 | 0-63 | each flake's place and age |
| 109-140 | 0-63 | its velocity and ageing rate |
| 141-172 | 0-63 | its orientation (a quaternion) |

A new target is all zero, so a texel that reads zero is one to start.

## Time

Everything moves on 60 Hz steps, whatever the frame rate: a frame takes
`s = clamp(delta · 60 · speed, 0, 8)` steps (fractions are fine). The wave has its own clock `t`, advanced by
`0.0002 · s`, and the lattice runs on `T = 10 t` (0.12 per second at speed 1). `t` wraps from 10 to 0 every 14
minutes. The edge follows a lagging copy, `lag += (t − lag)(1 − 0.9^s)`, so at the wrap it races back and shakes
the sheet.

## The cloth

The ribbon's skeleton is a 19 x 19 sheet of nodes, one texel each. Each step:

- **Springs.** For each neighbour `j` one apart (rest length `L = 0.306`, stiffness `K = 0.25`) and two apart
  (rest `2L`, stiffness `10 K`, which resists bending), with `d = p_j − p`:
  `F += d · (|d| − rest) · stiffness / |d|`.
- **Push.** A uniform random vector `u` in [−1, 1]³ per node and frame: `v += s F + √s · 0.1 · u`.
- **Move and damp.** `p += v · 0.0002 s`, then `v −= v · 0.0002 s`.
- **The free edge** (column 0) is pulled outward: `v.x += 0.04 s`.
- **The driven edge** (column 18) is placed on a Lissajous curve, each row a nineteenth behind the last:
  with `τ = row / 19 + lag`, `p = (0, 0.4 (½ + ½ sin 11τ), 0.1 (1 + cos 15τ))`.

A new target starts from a sheet of our own run of this model (a flat start run through five wraps of the clock),
packed as two 11:11:10-bit words per node in the shader, at `t = 0.8`. The first frame then looks like any other.

## The lattice deformation

Each node becomes a control point through a free-form deformation, a trivariate cubic B-spline over an
11 x 7 x 7 lattice spanning a box of 5.677 x 1 x 1 from `(0, −0.47, 0)`, with 8 x 4 x 4 cells.

First the ribbon's sides flare out toward its near end. With `x = node.x − flare` and `u = saturate(x / 5)`, the
node's y and z are scaled by `0.3` where `x < 0`, else by `1.3 − cos(π x / 2)(1 − smoothstep(u))`.

The lattice nodes only move in x (with their position `u` along the ribbon, 0 to 1) and in y (with `u` and their
position `w` across). The x shift is `5.677 (1.3 u² + 0.2 u − 0.15)`. The y shift is `h(u, T) + r(w, T) − 0.47`,
where the height is a travelling wave that grows along the ribbon, a slow bob and a wandering bump:

```
h(u, T) = 0.24 (1 + tanh(u − ½)) (3 + sin 2T) sin(7.85 u − 2.5 T − 1.25)
        + ½ sin(T / 4)
        + exp(−50 (u − (sin(T / 10) + 0.2) / 1.2)²)
```

and the ripple across is `r(w, T) = ⅛ sin(T − 6.28 w)`, where `w = min(i, 3) / 4` for the lattice row `i` across. Since the nodes move only
in x and y, the y weights of the B-spline sum out and each control point costs four lattice columns. The result is
scaled by `(3.2, scale_y, scale_z)` from the time of day's preset.

At the wrap, the lattice cross-fades from the old cycle to the new over the first `0.0216` of `t` (1.8 s): the
height and ripple are blended from `T + 100` to `T`.

Then the scene turns: a rotation by the preset's angle about the axis `(−0.9942, 0.0868, 0.0654)` (Rodrigues'
formula), and an offset of `(−8.2, −1.088, −8.4)`.

## The surface

The 19 x 19 control points span a uniform bicubic B-spline surface of 16 x 16 patches. The wave pass draws it as a
128 x 128 grid of vertices, eight per patch, `16 / 127` of a patch apart. Each vertex evaluates the position and both
tangents from the sixteen control points around it.

## The camera and the framing

A perspective camera at the origin looking down −z: a 53° vertical field of view at 16:9, near 0.1, far 1000. The
focal scale is `fy = 1 / tan 26.5° = 2.00569` and `fx = fy / (16 / 9)`.

The scene is composed in that 16:9 frame, which is then scaled to cover the window. A narrower window keeps the
53° top to bottom and loses the sides; a wider one keeps the 16:9 width and loses some top and bottom, so the
ribbon's far ends, where the flakes blur out of focus, stay off screen. The sky is cropped the same way.

## The line shading

The sheet is drawn additively, so its folds pile up. Each vertex is lit in clip space, `c = (fx x, fy y, −1.0002 z)`.
With the tangents scaled the same way, `n = across × along`:

- the **density** `k = |c · n| / |c|² · density`, how much surface crowds onto the screen around the vertex;
- the **facing** `cos = |c · n| / (|c| |n|)`.

The pixel's light is `rim · (brightness · k · line(k) + sheen · k · sheen(cos · k))`, with the two curves read per
pixel from the interpolated products:

```
line(k)  = k ≤ 0.375 ? 0.5 − 1.92 max(k − 0.125, 0) : 0.02 saturate(4 (0.625 − k))
sheen(v) = v < 0.058 ? 0.99 smoothstep(0.031, 0.058, v) : 0.99 (1 + ((v − 0.058) / 0.0354)²)^−1.53
```

`line` keeps the lines steady while they're resolved and fades them as they crowd; `sheen` is a narrow band that lights
the folds as they turn. The light is grey-white, a little brighter to the right (`0.847` to `0.925` across), and
fades over the mesh's outer tenth on all four sides (`rim`).

## The sky

The picture is radiance, shown through the tone map below. Each month has three colours of our own: the day sky's
top and bottom, and the night's glow at the bottom. From the 5th to the 30th they turn slowly, through HSV the
short way round the hue, toward the next month's.

The sky has its own clock: `hour = 24 (x² (3 − 2x) + 2.7 x (1 − x)(1 − 2x))` with `x = h / 24`, slow in the evening
so dusk lingers.

- **Day**: `base = lerp(top, bottom, smoothstep(0, 1, y))`. The sun's strength is
  `sun = saturate(sin((hour − 5.5) π / 13))^0.8` and a soft patch stands at `((hour − 6) / 12, 0.75 − 0.5 sun)`.
  The colour to show is `shown = min(sun (base + 0.12 exp(−6 |spot − uv|²)), 0.98)`, turned back into radiance
  through the day preset's tone map (exposure 1.05, white 0.9), so the day sky shows the palette's colours.
- **Night**: `bottom = (glow / (1.41 · 1.006) + 0.061) · 0.74`, and the sky is
  `lerp(0.13 bottom, bottom, y^1.35) · (0.95 + 0.1 x)`. The black crush leaves the upper half black and deepens the
  colour where it fades, which is what warms the lines over it.

The day picture fades in from midnight to 5:12 and out from 18:30 to 20:18:
`night = 1 − smoothstep(0, 5.2, h) (1 − smoothstep(18.5, 20.3, h))`.

## The tone map and the glare

The tone map is an exposure above a black point, then a Reinhard curve with the preset's white level `W`:

```
x       = max(E · (L − 0.061), 0)        E = exposure · 1.006
display = x (1 + x / W²) / (1 + x)
```

At `W = 1` this is just the linear map with a black crush, which keeps the top of the night sky black.

Only light beyond white glares. The glare pass, at a quarter size, averages `max(tone(sky + light) − 1, 0)` over
sixteen taps of the light target. The bloom pass blurs that at two widths:
`0.25 (centre + four diagonal taps at 1.06 texels) + 0.1 (four straight taps at 4 texels)`. The compose pass adds
it, times the Glare knob, after the clamp, then dithers.

## The time of day

Four presets, held around keyframes and blended with smoothsteps:
`dawn = smoothstep(1, 5, h)`, `day = smoothstep(7, 11, h)`, `dusk = smoothstep(13, 17, h)`,
`night = smoothstep(19, 23, h)`, and the weights (night, dawn, day, dusk) are
`(1 − dawn + night, dawn (1 − day), day (1 − dusk), dusk (1 − night))`.

| | Night | Dawn | Day | Dusk |
| --- | --- | --- | --- | --- |
| Line brightness | 0.9 | 1.12 | 0.7 | 1.06 |
| Sheen | 0.52 | 0.46 | 0.64 | 0.5 |
| Density scale | 1.76 | 1.87 | 1.87 | 1.76 |
| Exposure | 1.41 | 1.10 | 1.05 | 1.20 |
| White level | 1.0 | 1.0 | 0.9 | 1.0 |
| Camera turn (°) | 10 | 18.1 | 18.1 | 18.1 |
| Flake size | 0.054 | 0.054 | 0.047 | 0.047 |
| Flare | −1.834 | −1.34 | −1.34 | −1.834 |
| Scale y | 1.2 | 1.275 | 1.275 | 1.2 |
| Scale z | 3.0 | 2.89 | 2.89 | 3.0 |

Following the clock ("Clock"), a dark appearance pulls the sky toward night, so the light day picture never sits under
a dark theme's text; with "Night when dark" it pulls the weights too. "Day" (for light themes) and "Night" hold their
time whatever the appearance. The state pass works
the mood (and the month's colours) out once a frame into row 76; every later pass reads it there.

## The glitter

2,048 flakes, one texel per value in the state target. Their places are in the camera's frame moved 2 forward, so
the eye is at `(0, 0, 2)`, and they live in the box `(−10, −10, −12)` to `(10, 10, 7)`.

**Birth.** A free slot takes a vertex of the surface: a random one, or, one time in about sixteen while a streak
runs, the streak's. A streak starts every 300 steps of the wave clock after a short random wait, at a random point,
and walks along the ribbon one vertex every other step for 20 to 180 vertices. The vertex's velocity over one step
gives an axis, reversed 17 % of the time. The flake leaves within a 52° cone around it:

```
dir   = axis cos θ + (side cos φ + third sin φ) sin θ      θ = U · 52°, φ = U · 2π
speed = max(0.15, √(|v_vertex| · 0.19 · (1 + 0.28 r)))
v     = (dir.x, dir.y, 0) · speed                          (depth dropped, not renormalised)
```

with `r` uniform in [−1, 1]. Its orientation is uniformly random (Shoemake's method) and its ageing rate is
`0.0029 (1 + 0.5 r)` per step, a life of 4 to 11 seconds. A vertex that hardly moves gives no flake that frame. The
state pass updates the cloth and the flakes together, so it still holds last frame's control points while a flake is
born: the few births step the sixteen nodes around their vertex themselves (on a new target's first frame, from the
warm start), and are born on this frame's surface.

**Motion.** With `h = 0.0089` per step:

```
v   += h (√s · 0.225 · u + s ((0, −6.8e−5, 0) − 0.03 v)) + s · g
p   += s · h · v
age += s · rate
```

`u` is a fresh uniform jostle. `g` is a small push that belongs to the slot for good, normal with a deviation of
0.00052 per axis and step; it makes flakes drift steadily toward or away from the camera over their life, so far
ones leave the box at the back and near ones come close enough to blur. A flake is reborn when its age passes 1 or
it leaves the box.

**Spin.** The spin axis turns with age `a`: `ω = (sin 0.74π a, cos 0.34π a, cos 0.62π a)`, and each frame the
orientation turns by `|ω| · 2.74 / 60 · s` about `ω̂`.

**Depth of field.** From the eye, at distance `d`:

```
near = saturate((d − 7.4) / (6.1 − 7.4))^2.5        far = saturate((d − 12.8) / (16.9 − 12.8))^1.8
size = lerp(lerp(flake, 0.077, near), 0.87, far)
```

Out of focus a flake grows and turns into a soft bokeh disc: the disc's edge widens to `0.05 + 0.63 · blur`, its
profile becomes `1 − exp(−k · disc)` with `k = lerp(0.85, 3.8, near)`, and it darkens with its angular size.
Small or near flakes turn toward the camera.

**The glint.** Each flake is drawn twice. Its sprite is a flat disc facing along its orientation, lit two-sided
by a lamp at `(4.2, 2.6, −7.6)`:

```
light = 8 |n · l| + 75 · |n · ĥ|^35 · film(n)          ĥ = normalize(l + e)
pixel = disc · alpha · (1 − exp(−0.039 · light))
film(n) = (1, 0.89, 0.85) · lerp(1, 1.4 (½ + ½ cos 2π (1.7 |n.xy| + (0, 0.33, 0.67))), 0.35)
```

`film` is our own thin-film tint: warm white with pink, orange and blue. When the face turns toward the half vector
the flake also gets a camera-facing glare halo, `5.4 · size · |n · ĥ|^35` across, falling off as `exp(−4.4 r)`.
The alpha fades the flake in over its first 2 % of life and out over its last 6 %, near the box's walls, when it's
seen edge-on, and in a thin shell just short of the far focus. A sprite smaller than two pixels is drawn at two
pixels with its light spread, so it doesn't shimmer.

## Credits

linkev's PlayStation-3-XMB (MIT) was the earlier port of this effect and the inspiration for it:
https://github.com/linkev/PlayStation-3-XMB. This version shares no code with it, and is MIT licensed as well.
