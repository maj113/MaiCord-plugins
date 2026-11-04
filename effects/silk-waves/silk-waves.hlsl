// Silk Waves: a silky ribbon and glitter inspired by the PS3 menu background, as a pass graph (interface 3). An
// independent work: no code, data or textures from anyone else; matched against the original by eye and against
// recordings. How it works, in full: HOW-IT-WORKS.md beside this file.
//
// The wave is a 19 x 19 cloth (stretch and bend springs, random pushes, damping, one edge driven along a Lissajous
// curve, the other pulled outward), simulated one texel per node in a persistent float target. Its nodes are bent
// by a trivariate cubic B-spline free-form deformation whose 11 x 7 x 7 lattice is a closed-form travelling wave,
// and become the control points of a bicubic B-spline surface, drawn as a 128 x 128 vertex grid additively into a
// float target: each vertex is lit by its surface density and facing, so the sheet glows where it folds. A full-screen
// pass lays the wave over a monthly day or night sky and tone maps it with a black crush, with a glare from whatever
// goes past white. 2,048 glitter flakes, simulated in the same persistent target (born on the ribbon, drifting,
// spinning), flash when their spin turns them toward a light. The look follows the time of day.
// Credit: linkev's PlayStation-3-XMB (MIT) was the earlier port and the inspiration; this one shares no code with it.
//
// @effect   name="Silk Waves" authors="MaiCord" license="MIT" version="1.2.0" derived_from="https://github.com/linkev/PlayStation-3-XMB|linkev (Mart)|MIT"
// @knob month   choice "By date|January|February|March|April|May|June|July|August|September|October|November|December" = 0 "Month"
// @knob sky     choice "Clock|Night when dark|Day|Night" = 1 "Day and night"
// @knob speed   float 0..3 = 1 "Wave speed"
// @knob waves   float 0..2 = 1 "Wave brightness"
// @knob glitter float 0..2 = 1 "Glitter"
// @knob glare   float 0..2 = 1 "Glare"
// @uses blue_noise clock appearance
// @blend normal
// @target state rgba32f 64x173 persistent
// @target light rgba16f 100%
// @target glow  rgba16f 25%
// @target bloom rgba16f 25%
// @pass state to=state in=state
// @pass wave vs=wave_vs grid=128x128 to=light in=state blend=add clear
// @pass glare to=glow in=state,light
// @pass bloom to=bloom in=glow
// @pass compose in=state,light,bloom
// @pass glint vs=glint_vs quads=4096 in=state blend=add
#define MC_GRAPH
#include <maicord/sdk/background.hlsli>

#define knob_month   ((int)mc_knobs[0].x)
#define knob_sky     ((int)mc_knobs[0].y)
#define knob_speed   (mc_knobs[0].z)
#define knob_waves   (mc_knobs[0].w)
#define knob_glitter (mc_knobs[1].x)
#define knob_glare   (mc_knobs[1].y)

static const float kPi = 3.14159265;

// ---- the clock ---------------------------------------------------------------------------------------------------
// The wave runs on its own clock t, kept in the state target: 0.0002 per 60 Hz step (T = 10 t, 0.12 per second).
// t wraps from 10 to 0 (every 14 minutes): the lattice cross-fades from the old cycle to the new over 1.8 s, and the
// driven edge, which follows a lagging copy of t, races back and shakes the sheet.
static const float kStep = 2.0e-4, kWrap = 10.0, kFade = 0.0216, kStartClock = 0.8, kStartLag = 0.7982;

// Steps of the 60 Hz simulation this frame (a fraction is fine: the model is stable well past 8).
float frame_steps() { return clamp(mc.delta * 60.0 * knob_speed, 0.0, 8.0); }

// ---- the cloth (19 x 19 nodes; state rows 0-18 positions, 19-37 velocities and t, 38-56 control points, 57-75 the
// control points a frame ago and the 60 Hz steps between, 76 the time of day's mood) -------------------------------
static const float kRest = 0.306, kTension = 0.25, kDamping = 2.0e-4, kPush = 0.1, kPull = 0.04;
static const float2 kEdge = float2(0.4, 0.2);           // the driven edge's Lissajous extent (y, z)

// The driven edge (column 18): row i traces a Lissajous curve, each row a nineteenth of a unit behind the last.
float3 driven_edge(int row, float t) {
    const float tau = row / 19.0 + t;
    return float3(0.0, kEdge.x * (0.5 + 0.5 * sin(11.0 * tau)), kEdge.y * 0.5 * (1.0 + cos(15.0 * tau)));
}

float3 cloth_node(int row, int column) { return mc_target0.Load(int3(column, row, 0)).xyz; }

// ---- the sky -----------------------------------------------------------------------------------------------------
// The picture is radiance; the tone map shows it as saturate(exposure * (radiance - 0.061)), a black
// crush that keeps the top of the night sky black and the lines warm over the sky's glow. Our palette, per month:
// a day sky (top, bottom) and a night glow at the bottom, written as the colours they show at their preset's exposure.
static const float3 kDaySky[24] = {
    float3(.851, .863, .886), float3(.663, .682, .722),
    float3(.91, .812, .416), float3(.761, .604, .11),
    float3(.651, .812, .384), float3(.369, .604, .173),
    float3(.941, .659, .745), float3(.824, .4, .549),
    float3(.373, .722, .455), float3(.122, .478, .227),
    float3(.745, .596, .878), float3(.478, .322, .722),
    float3(.282, .824, .769), float3(.059, .549, .549),
    float3(.306, .604, .902), float3(.102, .247, .62),
    float3(.831, .478, .878), float3(.557, .173, .643),
    float3(.949, .725, .29), float3(.784, .471, .047),
    float3(.725, .541, .333), float3(.431, .29, .133),
    float3(.933, .416, .322), float3(.659, .149, .118)
};
static const float3 kNightGlow[12] = {
    float3(.353, .376, .439), float3(.431, .353, .118), float3(.243, .353, .133), float3(.478, .267, .345),
    float3(.118, .333, .188), float3(.341, .251, .478), float3(.063, .345, .353), float3(.078, .243, .502),
    float3(.369, .102, .431), float3(.494, .306, .024), float3(.259, .157, .039), float3(.431, .118, .094)
};
static const float kMonthStart[12] = { 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334 };

float3 hsv_of(float3 c) {
    const float high = max(c.r, max(c.g, c.b)), low = min(c.r, min(c.g, c.b)), range = high - low;
    float hue = 0.0;
    if (range > 1e-5)
        hue = high == c.r ? (c.g - c.b) / range : high == c.g ? 2.0 + (c.b - c.r) / range : 4.0 + (c.r - c.g) / range;
    return float3(frac(hue / 6.0), high > 0.0 ? range / high : 0.0, high);
}
float3 rgb_of(float3 hsv) {
    const float3 k = saturate(abs(frac(hsv.x + float3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0);
    return hsv.z * lerp(1.0, k, hsv.y);
}
// Through HSV, the hue the short way round, as the month turns.
float3 month_mix(float3 a, float3 b, float w) {
    float3 x = hsv_of(a), y = hsv_of(b);
    y.x += round(x.x - y.x);
    float3 m = lerp(x, y, w);
    m.x = frac(m.x);
    return rgb_of(m);
}

// ---- the time of day ---------------------------------------------------------------------------------------------
// The look changes through the day: four presets (night, dawn, day, dusk) held around keyframes at
// 0-1 night, 5-7 dawn, 11-13 day, 17-19 dusk and 23-24 night, with a smoothstep between neighbours. The sky has its own
// clocks: the day picture fades in from midnight to 5:12 and out from 18:30 to 20:18, and its sun runs on a curved
// clock that is slow in the evening, so dusk lingers.
struct Mood {
    float sky;          // 0 the day picture, 1 the night picture
    float2 sun;         // the sun's strength, and where it stands across the sky
    float brightness;   // the lines
    float sheen;        // the folds' sheen
    float density;      // the scale of the density k
    float exposure;
    float white;        // the tone map's white level
    float turn;         // the camera's turn, degrees
    float flake;        // a flake's size in focus
    float flare;        // x where the grid's sides flare out
    float3 scale;       // the deformation's output scale
    float3 top, bottom; // the month's day sky
    float3 glow;        // and its night glow
};
// Night, dawn, day, dusk.
static const float4 kBrightness = float4(0.9, 1.12, 0.7, 1.06), kSheen = float4(0.52, 0.46, 0.64, 0.5);
static const float4 kDensity = float4(1.76, 1.87, 1.87, 1.76), kExposure = float4(1.41, 1.10, 1.05, 1.20);
static const float4 kWhite = float4(1.0, 1.0, 0.9, 1.0), kTurn = float4(10.0, 18.1, 18.1, 18.1);
static const float4 kFlakeSize = float4(0.054, 0.054, 0.047, 0.047), kFlare = float4(-1.834, -1.34, -1.34, -1.834);
static const float4 kScaleY = float4(1.2, 1.275, 1.275, 1.2), kScaleZ = float4(3.0, 2.89, 2.89, 3.0);

Mood mood() {
    Mood m;
    const float h = knob_sky == 2 ? 12.0 : knob_sky == 3 ? 0.0 : mc_ambient.day * 24.0;
    const float dawn = smoothstep(1.0, 5.0, h), day = smoothstep(7.0, 11.0, h), dusk = smoothstep(13.0, 17.0, h);
    const float night = smoothstep(19.0, 23.0, h);
    float4 w = float4(1.0 - dawn + night, dawn * (1.0 - day), day * (1.0 - dusk), dusk * (1.0 - night));
    m.sky = 1.0 - smoothstep(0.0, 5.2, h) * (1.0 - smoothstep(18.5, 20.3, h));
    const float x = h / 24.0, hour = 24.0 * (x * x * (3.0 - 2.0 * x) + 2.7 * x * (1.0 - x) * (1.0 - 2.0 * x));
    // The light follows the sun on that clock: none before 5:30 or after 18:30.
    m.sun = float2(pow(saturate(sin((hour - 5.5) * kPi / 13.0)), 0.8), (hour - 6.0) / 12.0);
    // The day picture is light: under a dark appearance's text, following the clock shows the night sky instead.
    // "Night when dark" turns the whole mood to night with it; "Day" and "Night" are as chosen.
    if (knob_sky <= 1)
        m.sky = max(m.sky, mc_ambient.dark);
    if (knob_sky == 1)
        w = lerp(w, float4(1.0, 0.0, 0.0, 0.0), mc_ambient.dark);
    m.brightness = dot(w, kBrightness);
    m.sheen = dot(w, kSheen);
    m.density = dot(w, kDensity);
    m.exposure = dot(w, kExposure) * 1.006;
    m.white = dot(w, kWhite);
    m.turn = dot(w, kTurn);
    m.flake = dot(w, kFlakeSize);
    m.flare = dot(w, kFlare);
    m.scale = float3(3.2, dot(w, kScaleY), dot(w, kScaleZ));
    m.top = m.bottom = m.glow = 0.0;                    // the palette: month_colour(), stored with the mood
    return m;
}

// One of the month's colours (0 the day sky's top, 1 its bottom, 2 the night glow); from the 5th to the 30th it
// turns slowly (through HSV) toward the next month's.
float3 month_colour(uint which) {
    int month = knob_month - 1;
    float turn = 0.0;
    if (knob_month == 0) {
        month = clamp((int)mc_ambient.month - 1, 0, 11);
        turn = smoothstep(5.0, 30.0, mc_ambient.year * 365.0 - kMonthStart[month] + 1.0);
    }
    const int next = month == 11 ? 0 : month + 1;
    const float3 now = which == 2 ? kNightGlow[month] : kDaySky[month * 2 + which];
    const float3 later = which == 2 ? kNightGlow[next] : kDaySky[next * 2 + which];
    return turn > 0.0 ? month_mix(now, later, turn) : now;
}

// The state pass works the mood out once a frame into the last row of the cloth's block (texels 0-5); every later
// pass reads it there.
static const uint kMoodRow = 76;
float4 mood_texel(Mood m, uint index) {
    return index == 0 ? float4(m.brightness, m.sheen, m.density, m.exposure)
         : index == 1 ? float4(m.white, m.turn, m.flake, m.flare)
         : index == 2 ? float4(m.scale.yz, m.sky, m.sun.x)
         : float4(month_colour(min(index, 5u) - 3u), index == 3 ? m.sun.y : 0.0);
}
Mood stored_mood() {
    float4 v[6];
    [unroll] for (int i = 0; i < 6; ++i)
        v[i] = mc_target0.Load(int3(i, kMoodRow, 0));
    Mood m;
    m.brightness = v[0].x; m.sheen = v[0].y; m.density = v[0].z; m.exposure = v[0].w;
    m.white = v[1].x; m.turn = v[1].y; m.flake = v[1].z; m.flare = v[1].w;
    m.scale = float3(3.2, v[2].xy); m.sky = v[2].z; m.sun = float2(v[2].w, v[3].w);
    m.top = v[3].xyz; m.bottom = v[4].xyz; m.glow = v[5].xyz;
    return m;
}

// ---- the deformation and the camera ------------------------------------------------------------------------------
static const float3 kBox = float3(5.677, 1.0, 1.0);     // the lattice's box (8 x 4 x 4 cells)
static const float kOriginY = -0.47;
// The model transform: a turn about (-0.994, 0.087, 0.065) by the time of day's angle (see mood()), then an offset;
// the camera looks down -z with a 53 degree vertical field of view at 16:9 (near 0.1, far 1000).
static const float3 kAxis = float3(-0.9942, 0.0868, 0.0654);
static const float3 kOffset = float3(-8.2, -1.088, -8.4);
static const float kFocalY = 2.00569, kFocalX = 2.00569 / (16.0 / 9.0);

float4 bspline(float t) {
    const float s = 1.0 - t, t2 = t * t;
    return float4(s * s * s, 3.0 * t2 * t - 6.0 * t2 + 4.0, -3.0 * t2 * t + 3.0 * t2 + 3.0 * t + 1.0, t2 * t) / 6.0;
}
float4 bspline_slope(float t) {
    const float s = 1.0 - t;
    return float4(-s * s, 3.0 * t * t - 4.0 * t, -3.0 * t * t + 2.0 * t + 1.0, t * t) * 0.5;
}

// The lattice's height offset along the ribbon (u 0..1) at wave time T: a travelling wave that grows along the
// ribbon, a slow bob and a wandering bump. The across-ribbon ripple is added in deform().
float lattice_height(float u, float T) {
    const float bump = u - (sin(0.1 * T) + 0.2) / 1.2;
    return 0.24 * (1.0 + tanh(u - 0.5)) * (3.0 + sin(2.0 * T)) * sin(7.85 * u - 2.5 * T - 1.25)
         + 0.5 * sin(0.25 * T) + exp(-50.0 * bump * bump);
}

// A trivariate cubic B-spline free-form deformation over the lattice, scaled by `scale` on the way out. Its nodes
// only move in x (with u) and y (with u and the across-ribbon w), so the y weights sum out. Just after the clock
// wraps (fade < 1) the lattice is still partly the old cycle's (T + 100).
float3 deform(float3 g, float T, float fade, float3 scale) {
    const float3 box = (g - float3(0.0, kOriginY, 0.0)) / kBox;
    const float3 s = clamp(box, 0.0, 0.999) * float3(8.0, 4.0, 4.0);
    const float3 cell = floor(s);
    const float4 bx = bspline(s.x - cell.x), bz = bspline(s.z - cell.z);
    float2 ripple = 0.0;                                // (the old cycle's, this cycle's)
    [unroll] for (int c = 0; c < 4; ++c) {
        const float w = 6.28 * clamp(cell.z + c - 1.0, 0.0, 3.0) * 0.25;
        ripple += bz[c] * sin(float2(T + 100.0, T) - w) * 0.125;
    }
    float2 shift = 0.0;
    [loop] for (int a = 0; a < 4; ++a) {
        const float u = clamp(cell.x + a - 1.0, 0.0, 7.0) * 0.125;
        const float height = lerp(lattice_height(u, T + 100.0) + ripple.x, lattice_height(u, T) + ripple.y, fade);
        shift += bx[a] * float2(kBox.x * (1.3 * u * u + 0.2 * u - 0.15), kBox.y * height + kOriginY);
    }
    return (box + float3(shift, 0.0)) * scale;
}

// A cloth node as the surface's control point, in camera space, with the time of day's flare, scale and turn.
float3 control_point(float3 node, float t, Mood m) {
    const float x = node.x - m.flare, u = saturate(x * 0.2);
    const float flare = x < 0.0 ? 0.3 : 1.3 - cos(x * kPi * 0.5) * (1.0 - u * u * (3.0 - 2.0 * u));
    const float3 p = deform(float3(node.x, node.yz * flare), 10.0 * t, saturate(t / kFade), m.scale);
    float s, c;
    sincos(radians(m.turn), s, c);
    return p * c + cross(kAxis, p) * s + kAxis * dot(kAxis, p) * (1.0 - c) + kOffset;
}

// The bicubic B-spline surface over the control points (16 x 16 patches; uv in patches): position and the two
// tangents, in camera space. Reads the state's control block starting at `block` (38 now, 57 a frame ago).
void surface(float2 uv, int block, out float3 position, out float3 along, out float3 across) {
    const int2 patch = min(int2(uv), 15);
    const float2 f = uv - patch;
    const float4 bu = bspline(f.x), bv = bspline(f.y), du = bspline_slope(f.x), dv = bspline_slope(f.y);
    position = along = across = 0.0;
    [loop] for (int a = 0; a < 4; ++a) {
        float3 row = 0.0, row_slope = 0.0;
        [unroll] for (int b = 0; b < 4; ++b) {
            const float3 c = mc_target0.Load(int3(patch.x + b, block + patch.y + a, 0)).xyz;
            row += bu[b] * c;
            row_slope += du[b] * c;
        }
        position += bv[a] * row;
        along += bv[a] * row_slope;
        across += dv[a] * row;
    }
}

// The 16:9 clip space the scene is composed in, and the scale that fits it to this output: the 16:9 frame scaled to
// cover the window. A narrower window keeps the 53 degrees top to bottom and loses the sides; a wider one keeps the
// 16:9 width and loses some top and bottom, rather than showing the ribbon's far ends (where the flakes blur out of
// focus). The sky is cropped the same way (frame_uv).
float4 clip_of(float3 p) { return float4(kFocalX * p.x, kFocalY * p.y, -1.0002 * p.z - 0.2002, -p.z); }
float2 output_scale() {
    const float stretch = 16.0 / 9.0 * mc.resolution.y / mc.resolution.x;
    return stretch >= 1.0 ? float2(stretch, 1.0) : float2(1.0, 1.0 / stretch);
}
// A point of the window (uv) as a point of the 16:9 frame.
float2 frame_uv(float2 uv) { return 0.5 + (uv - 0.5) / output_scale(); }


// ---- the warm start: a sheet from our own run of this model (our seed, a flat start, five wraps of the clock), two
// nodes per row: position and velocity, each packed as 11, 11 and 10 bits over the ranges below -------------------
static const float3 kWarmLow = float3(-0.5, -0.8, -0.8), kWarmSpan = float3(6.2, 2.2, 1.8), kWarmSpeed = 24.0;
static const uint4 kWarm[181] = {
    uint4(2906191770,2228755344,2449172255,2161822228),uint4(2301935314,3306521363,2607879810,1171993695),
    uint4(1923972644,2259061680,2435382735,1536345199),uint4(1856515414,1658852928,2284369144,1876716180),
    uint4(2275796104,1944040486,2741285927,1121557426),uint4(2791754706,2162400616,2246300514,1574552614),
    uint4(2586139404,1654797278,2040898205,1957731016),uint4(2330006078,2391703991,2074159572,2773959953),
    uint4(2342873457,1427895360,2287974662,2748971992),uint4(2346750117,2149581824,2691505977,1432249741),
    uint4(2394052333,2296404984,2049996425,2971319362),uint4(2339073582,1189078083,2242473416,1970003248),
    uint4(2502401369,1733409459,2389032206,2049510576),uint4(2640512154,1366094569,2221114433,2288741690),
    uint4(2342308830,2044480215,2791508868,2178691550),uint4(2548079387,1322674915,2514533039,2901472354),
    uint4(2094881387,2052967612,1972945416,3267937070),uint4(1570466221,2166760562,1608454478,1865104927),
    uint4(1424064758,2308217864,2380101797,2149581824),uint4(2649691896,1931758791,2234625661,1940024401),
    uint4(2267987483,2149196743,2431305154,2649349417),uint4(2376674657,618468668,2351090956,2018661532),
    uint4(2422457506,2056811226,2653121596,2274827627),uint4(2464357336,1394297885,2485089146,2334590023),
    uint4(2233801506,2963254396,2451237555,2691198481),uint4(2334241360,1062794535,2161824255,3038819579),
    uint4(2006493591,1943862727,1360609619,1829891152),uint4(1159741705,1298023710,1134299280,2888943203),
    uint4(2279225509,2149581824,1785237159,1516490065),uint4(1869110863,2808924806,1965563352,3151740007),
    uint4(2011219345,2597203065,1709376791,2615610917),uint4(1524704458,1662151731,1659112535,2728087420),
    uint4(1725850624,1003805702,1541542797,2384683846),uint4(1936087869,1767877649,1944416993,2891441547),
    uint4(1709099644,2820635557,1629784592,3563140188),uint4(1537167797,1881357279,1633599822,1633936477),
    uint4(1625600241,2195307012,1252282520,2955418643),uint4(2044612685,1138129797,2098718885,2149581824),
    uint4(1419994845,1688243369,1046826612,2133080917),uint4(1486882319,1524712114,1197835697,2401238010),
    uint4(1080419670,3714312788,925160693,2828391280),uint4(933598349,2283295089,1214202921,2170825384),
    uint4(1067787220,1784734524,1273459566,2758048812),uint4(958501641,2372488620,1445302945,2795832121),
    uint4(879090242,2741044007,1206278632,3161040334),uint4(1315512700,2115943460,1911109951,2773619744),
    uint4(2238245077,3160521542,2677967045,2644478586),uint4(1947682981,2149581824,1319046988,1768543400),
    uint4(1138970359,2133449744,1625816729,2371892228),uint4(916653615,2127977501,1223013838,2958891822),
    uint4(870706537,2976126021,958702855,2686731098),uint4(1054856350,2485964124,950299711,1725906210),
    uint4(1260940259,1696168832,1088279422,2435021631),uint4(1218906910,1410259841,1289763511,1712860496),
    uint4(1336314459,1499182192,1529278964,2102315943),uint4(2238067117,980822854,2082873648,3211330865),
    uint4(2707292417,1362031831,1914212517,2149581824),uint4(1314490248,1617378707,1423830826,1369768956),
    uint4(1218236095,1504119864,1835095652,942185744),uint4(1495401992,1994879902,1486818712,3085149381),
    uint4(1314710847,2040939006,1822559443,1758809136),uint4(1524475015,1708955015,1394564130,2149960336),
    uint4(1746756528,1544813516,1373553501,1746738048),uint4(1503398631,1156291796,1642160795,2079445524),
    uint4(1554016798,2379551659,2229113315,2279883911),uint4(1407070553,2771680274,1574721851,1517147154),
    uint4(2019248293,2149581824,2308253610,1264196492),uint4(1989551926,703425145,2149111529,2741065046),
    uint4(2228979311,2925874627,2119869985,1852294165),uint4(2052787630,2221814538,1964668234,2896757664),
    uint4(2207700196,1721785640,2279382146,1922899487),uint4(2262529056,2359049466,2526694321,1075544955),
    uint4(1977228122,1659402918,2169780989,1274506219),uint4(2061005458,2087412444,1758886450,841661179),
    uint4(1930717642,2129128487,1796573528,2314040406),uint4(1578316014,2095057514,2199820453,2149581824),
    uint4(2635593527,1805808709,2492884699,2284578052),uint4(2463938166,1814033755,3008996882,3304428265),
    uint4(2471855559,3529077891,2589168983,1029126883),uint4(2593355010,2736839856,2568256664,1297960357),
    uint4(2883206208,2489091408,2480337860,2523224634),uint4(3008834419,1154800138,2572770052,2543990106),
    uint4(2937594533,1054962538,2425539147,2381929722),uint4(2543047159,2170819403,2320374159,2591409250),
    uint4(2706831674,1868544704,2576574679,2018362763),uint4(2351001765,2149581824,2438489817,1517112120),
    uint4(2191150712,2359645432,1994081820,2241469146),uint4(2408938948,1524306932,2383863133,1691214502),
    uint4(2409139437,2717551517,2388061315,2673933018),uint4(2707096612,1134185315,2824645580,2765556791),
    uint4(2732145515,2212920722,2887588605,2009877706),uint4(2782153394,2602101954,2631502414,2190642521),
    uint4(2866063845,2917383511,2647818634,3181325437),uint4(2639040807,1700875385,2811275462,937689736),
    uint4(2912540840,2438767159,2380454053,2149581824),uint4(1943279235,1452747737,1754598970,2564751734),
    uint4(1834200516,1537186853,2358510965,2846090158),uint4(2450681084,2733390585,2417124507,1721756510),
    uint4(2211580981,1516053557,2241260500,1968669691),uint4(2434270074,2087044379,2509495040,1945590233),
    uint4(2568035009,1838736468,2488840777,2043408565),uint4(2379340281,698391931,2241229203,697195225),
    uint4(2060572971,904033467,2362683585,2559937442),uint4(2295496803,3428518699,2015510616,1641242954),
    uint4(2271369381,2149581824,1556926086,2182437245),uint4(1489741354,2955369148,1385121220,1645902799),
    uint4(1389196635,1923816461,1623934207,2172901982),uint4(1464736915,2400898366,1267674170,2423338162),
    uint4(1322683358,2502816640,1591178102,1847524414),uint4(1444647701,1605133545,1670763189,3018134049),
    uint4(1776013896,1779824067,1582561766,2270565151),uint4(1590978954,1291116070,1448714535,1666183998),
    uint4(1255424198,2107529775,1523493001,2065315382),uint4(1922682921,2299300886,2090870949,2149581824),
    uint4(1543808747,2761759416,1325825690,1978041495),uint4(982228544,2253941443,1221369290,2433890700),
    uint4(1426908548,732358047,1297059083,2929284248),uint4(1246743735,1319111393,1297087558,2074062415),
    uint4(1305762791,2049168221,1280744314,1477792484),uint4(1293384466,2304818416,1398487736,1488257793),
    uint4(1066955337,2467877964,907512299,921812172),uint4(823468412,800722499,1259845933,1213807369),
    uint4(923857076,1466586014,1783722110,1044890713),uint4(1943861413,2149581824,1644824400,2254195191),
    uint4(1841999591,1299272577,1615851150,2350904269),uint4(1674470938,2971562901,1804455354,2786728925),
    uint4(1636861260,1528663375,1838185720,1906295419),uint4(1695777949,1759732849,1276376118,1994142856),
    uint4(1595145156,1504306074,1242788723,1667908482),uint4(1242919687,867306433,1159203503,882199704),
    uint4(1423565384,1986659448,991607277,3566730400),uint4(1071319431,2510210465,831914285,2556560499),
    uint4(1263780056,1316654226,1914294437,2149581824),uint4(2299514726,3206812835,1897015088,2480685786),
    uint4(1851135668,2770176947,2219855454,895288596),uint4(2412942843,1507945480,1679289785,2401434933),
    uint4(1901671764,1487160268,1771652322,2254986195),uint4(1604127888,1745707956,2077959203,1844070170),
    uint4(1495096267,1679133489,1943616368,2405209429),uint4(1855808243,2669497097,1637571228,2225812257),
    uint4(1511631406,1490891428,1662886354,2275646140),uint4(1327112540,2011820657,1641986304,2740237206),
    uint4(2023209125,2149581824,2342086563,2447586335),uint4(2270957338,2695312273,2702915294,2003197037),
    uint4(2652468823,2866352982,2438786564,1541041473),uint4(2187423128,2598535937,2342620484,2112083191),
    uint4(2355201236,1830255557,2153823350,1722310048),uint4(2283969544,1384893734,2275333033,2836562706),
    uint4(2321552199,1771498664,2330047218,1957786802),uint4(2711435906,3185159544,2337843773,1654715395),
    uint4(2190836189,2057840103,2220474732,2194345435),uint4(2279559472,2229272459,2207735973,2149581824),
    uint4(2552282919,2586618952,2757574361,2874940561),uint4(3193888387,2762945643,3378157073,1876611971),
    uint4(3084996031,2745707183,2896270689,1691050914),uint4(2691007736,2359313393,2632350868,2430196694),
    uint4(2602910766,1957004410,3169149919,1852203993),uint4(2510682981,2124590222,2858640156,1742211813),
    uint4(2833826474,2308537646,2846044736,2114535896),uint4(3046720069,1205208538,2866041308,2505671585),
    uint4(2782310765,2631256831,2752827686,1927207986),uint4(2354634917,2149581824,2895875820,1864039469),
    uint4(3009425010,1134613494,2850020893,2648867840),uint4(3294549418,3013610534,2942557523,1490643914),
    uint4(2942686444,1696254933,3051693190,2066510458),uint4(2946999336,2057913253,2733089727,1775938422),
    uint4(2989114197,1015583912,2724825849,1483233903),uint4(2821141142,2803028989,3265555008,2908088996),
    uint4(3915409935,1964608417,3809991146,1273537501),uint4(3562078621,1813825933,3537389851,1814168543),
    uint4(3117744351,2670010914,2375796901,2149581824),uint4(3327913602,1507738222,3114245651,3265410152),
    uint4(3072069048,1611717784,3055058259,1130242988),uint4(2694634744,2056827999,2841666722,1541731588),
    uint4(2850128950,2292259949,3047269344,2984903657),uint4(2820494189,2690784020,3382833952,2819224303),
    uint4(3038870203,1974073998,3030626905,916239279),uint4(3622029840,1566588496,3781091750,2469229412),
    uint4(3725894052,1323826082,3373457696,2838097143),uint4(3642050760,2061998876,2887465071,2334432414),
    uint4(2266962085,2149581824,0,0)
};
// A node of the warm start: its position and velocity.
void warm_node(uint index, out float3 position, out float3 velocity) {
    const uint4 pair = kWarm[index >> 1];
    const uint2 word = (index & 1u) ? pair.zw : pair.xy;
    const float3 scale = 1.0 / float3(2047.0, 2047.0, 1023.0);
    position = float3(word.x & 2047u, (word.x >> 11) & 2047u, word.x >> 22) * scale * kWarmSpan + kWarmLow;
    velocity = (float3(word.y & 2047u, (word.y >> 11) & 2047u, word.y >> 22) * scale - 0.5) * kWarmSpeed;
}
// ---- pass 1, the state: the cloth (rows 0-76, columns 0-18) and the glitter flakes (rows 77-172) ---------------
// One frame of a node's simulation from the state the frame before: its position, velocity, the clock and the
// edge's lagging copy of it.
void step_node(int row, int column, out float3 node, out float3 velocity, out float t, out float lag) {
    const float4 held = mc_target0.Load(int3(column, 19 + row, 0));
    const float steps = frame_steps();
    node = cloth_node(row, column);
    velocity = held.xyz;
    t = held.w;
    lag = mc_target0.Load(int3(0, 38, 0)).w;
    // Springs to the neighbours on each side, then to the nodes two away (bending, ten times stiffer).
    static const int2 kNeighbours[8] = { int2(0, -1), int2(0, 1), int2(-1, 0), int2(1, 0),
                                         int2(0, -2), int2(0, 2), int2(-2, 0), int2(2, 0) };
    float3 force = 0.0;
    [loop] for (int s = 0; s < 8; ++s) {
        const int2 other = int2(row, column) + kNeighbours[s];
        if (all(other >= 0) && all(other <= 18)) {
            const float3 d = cloth_node(other.x, other.y) - node;
            const float length_ = max(length(d), 1e-6);
            force += d * ((length_ - kRest * (s < 4 ? 1.0 : 2.0)) * kTension * (s < 4 ? 1.0 : 10.0) / length_);
        }
    }
    const float3 push = mc_hash4(float2(row * 19 + column + 32768, mc.frame)).xyz * 2.0 - 1.0;
    velocity += steps * force + sqrt(steps) * kPush * push;
    node += velocity * (kStep * steps);
    velocity -= velocity * (kDamping * steps);
    t += kStep * steps;
    if (t > kWrap)
        t = 0.0;
    lag += (t - lag) * (1.0 - pow(0.9, steps));         // a tenth of the way to t per step
    if (column == 0)
        velocity.x += kPull * steps;                    // the free edge is pulled outward
    if (column == 18) {
        node = driven_edge(row, lag);
        velocity = 0.0;
    }
}

// A node after this frame's step, or on a new target's first frame from the warm start (`past`: a step before it).
void node_after(int row, int column, bool fresh, bool past, out float3 node, out float3 velocity, out float t,
                out float lag) {
    [branch] if (fresh) {
        warm_node(row * 19 + column, node, velocity);
        t = kStartClock;
        lag = kStartLag;
        if (past) {
            node = column == 18 ? driven_edge(row, kStartLag - kStep) : node - velocity * kStep;
            t -= kStep;
        }
    } else {
        step_node(row, column, node, velocity, t, lag);
    }
}

// ---- the glitter flakes (state rows 77-108 place and age, 109-140 velocity and ageing rate, 141-172 orientation;
// one particle per column and row of each block). Places are in the camera's frame moved 2 forward. ----------------
static const int kFlakeRow = 77;
static const float kTick = 0.0089, kDrag = 0.03, kKick = 0.225, kGravity = -6.8e-5, kSpin = 2.74 / 60.0;
static const float3 kBoundsLow = float3(-10.0, -10.0, -12.0), kBoundsHigh = float3(10.0, 10.0, 7.0);
static const float3 kEye = float3(0.0, 0.0, 2.0), kLamp = float3(4.2, 2.6, -7.6);

float4 quaternion_product(float4 a, float4 b) {
    return float4(a.w * b.xyz + b.w * a.xyz + cross(a.xyz, b.xyz), a.w * b.w - dot(a.xyz, b.xyz));
}
float3 rotate(float4 q, float3 v) { return v + 2.0 * cross(q.xyz, cross(q.xyz, v) + q.w * v); }

// The emitter: births come from vertices of the ribbon's mesh, sixteen random ones on about half the frames and,
// while a streak runs, one every other frame stepping along the ribbon from a random start. Here every free slot is
// filled at once, so a birth takes a random vertex, or (one in sixteen while a streak runs) the streak's. The streaks
// are laid out on the wave clock: one per 300 steps of 60 Hz, after a short wait.
uint2 birth_vertex(float4 r, float choice, bool fresh) {
    uint2 vertex = uint2(r.xy * 127.0);                 // (along, across), 0-126 each
    float t = kStartClock;                              // the wave clock after this frame's step
    if (!fresh) {
        t = mc_target0.Load(int3(0, 19, 0)).w + kStep * frame_steps();
        if (t > kWrap)
            t = 0.0;
    }
    const float frame_ = floor(t / kStep);
    const float slot = floor(frame_ / 300.0), since = frame_ - slot * 300.0;
    const float4 streak = mc_hash4(float2(slot, 4242.0));
    const float start = floor(streak.z * 127.0), step = floor((since - floor(streak.x * 34.0)) * 0.5);
    const float length_ = min(floor(80.0 * (2.0 * streak.w - 1.0)) + 100.0, 128.0 - start);
    if (step >= 0.0 && step < length_ && choice < 0.06)
        vertex = uint2(start + step, floor(streak.y * 127.0));
    return vertex;
}

// A new flake at a vertex whose surface point is `p` now and `before` a step earlier, launched in a 52 degree cone
// about the direction the vertex is moving (the other way one time in six), flattened onto the screen plane, at a
// speed that grows with the vertex's; `settled` places a first-frame flake partway through its life. A vertex that
// hardly moves gives no flake this frame: the slot stays empty (at the end of a life, unseen) and tries again on the
// next.
void spawn(float3 p, float3 before, float steps, float4 a, float4 b, float4 c, bool settled, out float4 place,
           out float4 motion, out float4 orientation) {
    // Its velocity over one 60 Hz step, in the particles' units.
    const float3 drift = (p - before) / (max(steps, 1e-6) * kTick);
    const float pace = length(drift);
    const float rate = max(0.001, 0.0029 * (1.0 + 0.5 * (2.0 * b.z - 1.0)));
    // A uniformly random orientation (Shoemake).
    const float r1 = sqrt(1.0 - c.x), r2 = sqrt(c.x);
    orientation = float4(r1 * sin(2.0 * kPi * c.y), r1 * cos(2.0 * kPi * c.y), r2 * sin(2.0 * kPi * c.z), r2 * cos(2.0 * kPi * c.z));
    if (steps < 1e-3 || pace < 1e-4) {
        place = float4(p + float3(0.0, 0.0, 2.0), 1.0);
        motion = float4(0.0, 0.0, 0.0, rate);
        return;
    }
    const float3 axis = drift / pace * (b.x < 0.17 ? -1.0 : 1.0);
    // A side axis from the largest of three perpendiculars, and the third axis.
    const float3 s1 = float3(0.0, axis.z, -axis.y), s2 = float3(-axis.z, 0.0, axis.x), s3 = float3(axis.y, -axis.x, 0.0);
    const float l1 = dot(s1, s1), l2 = dot(s2, s2), l3 = dot(s3, s3);
    const float3 side = normalize(l1 >= l2 && l1 >= l3 ? s1 : l2 >= l3 ? s2 : s3), third = cross(axis, side);
    const float tilt = a.z * radians(52.0), around = a.w * 2.0 * kPi;
    const float3 direction = axis * cos(tilt) + (side * cos(around) + third * sin(around)) * sin(tilt);
    const float speed = max(0.15, sqrt(pace * 0.19 * (1.0 + 0.28 * (2.0 * b.y - 1.0))));
    const float3 velocity = float3(direction.xy * speed, 0.0);   // the depth is dropped, not renormalised
    const float age = settled ? b.w : 0.0;
    place = float4(p + float3(0.0, 0.0, 2.0) + velocity * (kTick * age / rate), age);
    motion = float4(velocity, rate);
}

// A flake's frame: drift, jostle, age and spin. It is reborn when its life ends or it leaves its box.
bool flake_moves(float id, inout float4 place, inout float4 motion, inout float4 orientation) {
    const float steps = frame_steps();
    const float3 kick = mc_hash4(float2(id, mc.frame)).xyz * 2.0 - 1.0;
    // The jostling is not quite white: each slot also keeps a small push of its own (normal, 0.00052 per axis and
    // step), so flakes drift steadily over their life, toward or away from the camera too.
    const float4 r = mc_hash4(float2(id + 40960.0, 7.0));
    const float2 radius = sqrt(-2.0 * log(max(r.xz, 1e-7)));
    const float3 drift = float3(radius.x * cos(2.0 * kPi * r.y), radius.x * sin(2.0 * kPi * r.y), radius.y * cos(2.0 * kPi * r.w)) * 0.00052;
    motion.xyz += kTick * (sqrt(steps) * kKick * kick + steps * (float3(0.0, kGravity, 0.0) - kDrag * motion.xyz)) + steps * drift;
    place.xyz += steps * kTick * motion.xyz;
    place.w += steps * motion.w;
    // Spin about an axis that turns with age.
    const float3 spin = float3(sin(0.74 * kPi * place.w), cos(0.34 * kPi * place.w), cos(0.62 * kPi * place.w));
    const float angle = length(spin) * kSpin * steps;
    orientation = normalize(quaternion_product(float4(normalize(spin) * sin(0.5 * angle), cos(0.5 * angle)), orientation));
    return place.w > 0.99999 || any(place.xyz < kBoundsLow) || any(place.xyz > kBoundsHigh);
}

// The state pass. A cloth texel steps its node (block 0 its position, 1 its velocity and the clock, 2 its control
// point now with the edge's clock in w, 3 the control point a frame ago with the steps between). A flake texel moves
// its flake (block 0 its place and age, 1 its velocity and ageing rate, 2 its orientation); a newborn flake needs the
// surface around its vertex this frame, but the state still holds last frame's control points, so it steps the
// sixteen nodes around the vertex itself (only births pay for it; on a new target's first frame both its points come
// from the warm start). One loop over nodes serves both.
float4 state(float4 position : SV_Position) : SV_Target {
    const uint2 texel = uint2(position.xy);
    const bool fresh = mc_target0.Load(int3(0, 0, 0)).w == 0.0, flake = texel.y >= (uint)kFlakeRow;
    const uint block = flake ? (texel.y - kFlakeRow) >> 5 : texel.y / 19u;
    float4 value = 0.0;
    [branch] if (texel.y == kMoodRow) {
        if (texel.x < 6u)
            value = mood_texel(mood(), texel.x);
    } else if (!flake && texel.x >= 19u) {
        // Unused.
    } else if (!flake && block == 3 && !fresh) {
        value = float4(mc_target0.Load(int3(texel.x, texel.y - 19u, 0)).xyz, frame_steps());
    } else {
        const int2 slot = int2(texel.x, (texel.y - kFlakeRow) & 31u);
        const float id = slot.y * 64 + slot.x;
        float4 place = 0.0, motion = 0.0, orientation = 0.0, a = 0.0, b = 0.0, c = 0.0;
        bool settled = false, born = false;
        float2 uv = 0.0;
        int2 origin = int2(texel.x, texel.y - block * 19u);     // the node (column, row), or the patch's corner
        float4 bu = float4(1.0, 0.0, 0.0, 0.0), bv = bu;        // a cloth texel's node counts whole
        int count = 1;
        bool control = block >= 2;                              // whether the loop needs control points
        [branch] if (flake) {
            place = mc_target0.Load(int3(slot + int2(0, kFlakeRow), 0));
            motion = mc_target0.Load(int3(slot + int2(0, kFlakeRow + 32), 0));
            orientation = mc_target0.Load(int3(slot + int2(0, kFlakeRow + 64), 0));
            // A slot that has never held a flake (a new target) fills partway through a life; one whose flake died
            // fills anew.
            settled = motion.w == 0.0;
            born = settled;
            [branch] if (!settled)
                born = flake_moves(id, place, motion, orientation);
            count = 0;
            [branch] if (born) {
                a = mc_hash4(float2(id + 8192.0, mc.frame));
                b = mc_hash4(float2(id + 16384.0, mc.frame));
                c = mc_hash4(float2(id + 24576.0, mc.frame));
                const uint2 vertex = birth_vertex(a, c.w, fresh);
                uv = float2(vertex >> 3) + float2(vertex & 7u) * (16.0 / 127.0);
                origin = min(int2(uv), 15);
                bu = bspline(uv.x - origin.x);
                bv = bspline(uv.y - origin.y);
                count = fresh ? 32 : 16;
                control = true;
            }
        }
        const Mood m = mood();
        float3 node = 0.0, velocity = 0.0, now = 0.0, before = 0.0, row_ = 0.0;
        float t = 0.0, lag = 0.0;
        [loop] for (int i = 0; i < count; ++i) {
            const bool past = flake ? i >= 16 : block == 3;
            const int across = flake ? (i >> 2) & 3 : 0, along = flake ? i & 3 : 0;
            node_after(origin.y + across, origin.x + along, fresh, past, node, velocity, t, lag);
            [branch] if (control)
                row_ += bu[along] * control_point(node, t, m);
            if (along == 3 || !flake) {
                if (past)
                    before += bv[across] * row_;
                else
                    now += bv[across] * row_;
                row_ = 0.0;
            }
        }
        if (!flake) {
            value = block == 0 ? float4(node, 1.0) : block == 1 ? float4(velocity, t) : block == 2 ? float4(now, lag) : float4(before, 1.0);
        } else {
            [branch] if (born) {
                float3 along_, across_;
                if (!fresh)
                    surface(uv, 38, before, along_, across_);
                spawn(now, before, fresh ? 1.0 : frame_steps(), a, b, c, settled, place, motion, orientation);
            }
            value = block == 0 ? place : block == 1 ? motion : orientation;
        }
    }
    return value;
}

// ---- pass 2: the wave, additively into the light target ------------------------------------------------------
struct WaveVertex {
    float4 position : SV_Position;
    float4 shade : TEXCOORD0;   // k, facing times k, brightness times k, sheen times k: the curves are read per pixel
    float rim : TEXCOORD1;
};

// How the sheet's lines read at density k (k grows as the surface crowds into fewer pixels): steady while
// resolved, fading out as they crowd.
float line_level(float k) { return k <= 0.375 ? 0.5 - 1.92 * max(k - 0.125, 0.0) : 0.02 * saturate((0.625 - k) * 4.0); }
// The sheen: a narrow band of facing times density, so the sheet lights up along its turning folds.
float sheen_level(float u) {
    const float x = (u - 0.058) / 0.0354;
    return u < 0.058 ? 0.99 * smoothstep(0.031, 0.058, u) : 0.99 * pow(1.0 + x * x, -1.53);
}
// The mesh fades over its outer tenth on all four sides.
float rim(float n) { return min(1.0, min(n, 127.0 - n) * (10.0 / 127.0)); }

WaveVertex wave_vs(uint vertex_id : SV_VertexID, uint instance_id : SV_InstanceID) {
    const uint2 grid = mc_grid_point(vertex_id, instance_id);
    // Eight vertices per patch, 16/127 of a patch apart.
    const float2 uv = float2(grid >> 3) + float2(grid & 7u) * (16.0 / 127.0);
    float3 p, along, across;
    surface(uv, 38, p, along, across);
    // Shaded in the 16:9 clip space: the density k is the surface's area element seen from the eye over distance.
    const float4 clip = clip_of(p);
    const float3 scale = float3(kFocalX, kFocalY, -1.0002);
    const float3 normal = cross(across * scale, along * scale);
    const float distance_ = length(clip.xyz);
    const float facing = abs(dot(clip.xyz, normal)) / distance_;
    const Mood m = stored_mood();
    const float k = facing / distance_ * m.density;
    const float cosine = facing / max(length(normal), 1e-12);
    WaveVertex output;
    output.shade = float4(k, cosine * k, m.brightness * k, m.sheen * k);
    output.rim = rim(grid.x) * rim(grid.y);
    output.position = float4(clip.xy * output_scale(), 0.0, clip.w);
    return output;
}

float4 wave(WaveVertex input) : SV_Target {
    const float light = input.rim * (input.shade.z * line_level(input.shade.x) + input.shade.w * sheen_level(input.shade.y));
    // Grey-white, a little brighter to the right.
    const float tint = lerp(0.847, 0.925, input.position.x / mc_pass.size.x);
    return float4((light * tint * knob_waves).xxx, 0.0);
}


// ---- the sky picture ---------------------------------------------------------------------------------------------
static const float kBlack = 0.061;

// The tone map: exposure above the black point, then a Reinhard curve with the preset's white level (at a white
// level of 1 it is the identity, so the night is a plain linear map with a black crush). Unclamped.
float3 tone(float3 radiance, Mood m) {
    const float3 x = max(m.exposure * (radiance - kBlack), 0.0);
    return x * (1.0 + x / (m.white * m.white)) / (1.0 + x);
}

float3 day_sky(float3 top, float3 bottom, float2 uv, float2 sun) {
    const float3 base = lerp(top, bottom, smoothstep(0.0, 1.0, uv.y));
    // The light follows the sun (see mood()): a soft bright patch crossing the sky.
    const float2 spot = float2(sun.y, 0.75 - 0.5 * sun.x) - uv;
    // The colour to show, as radiance through the day preset's tone map (exposure 1.05, white 0.9).
    const float3 shown = min(sun.x * (base + 0.12 * exp(-dot(spot, spot) * 6.0)), 0.98);
    const float white2 = 0.9 * 0.9;
    const float3 x = (sqrt((1.0 - shown) * (1.0 - shown) + 4.0 * shown / white2) - (1.0 - shown)) * white2 * 0.5;
    return x / (1.05 * 1.006) + kBlack;
}
float3 night_sky(float3 glow, float2 uv) {
    // Rises from almost nothing at the top to the glow at the bottom, shaped by eye against recordings
    // (a tenth of the bottom's at the top, about 60 % at 30 % height); the crush leaves the upper half black and
    // deepens the colour where it fades, which is what warms the lines over it.
    const float3 bottom = (glow / (1.41 * 1.006) + kBlack) * 0.74;
    return lerp(bottom * 0.13, bottom, pow(saturate(uv.y), 1.35)) * (0.95 + 0.1 * uv.x);
}

float3 sky(float2 uv, Mood m) {
    float3 colour = 0.0;
    [branch] if (m.sky < 1.0)
        colour = day_sky(m.top, m.bottom, uv, m.sun) * (1.0 - m.sky);
    [branch] if (m.sky > 0.0)
        colour += night_sky(m.glow, uv) * m.sky;
    return colour;
}

// ---- pass 3: the glare source, a quarter-size copy of what the picture holds beyond white -------------------------
// Only light past the tone map's white glares (the night scene has none); the sky is smooth, so it is taken once.
float4 glare(float4 position : SV_Position) : SV_Target {
    const Mood m = stored_mood();
    const float2 texel = 1.0 / mc.resolution, uv = position.xy * (1.0 / mc_pass.size);
    const float3 base = sky(frame_uv(uv), m);
    float3 sum = 0.0;
    [loop] for (int y = -2; y <= 1; ++y)
        [loop] for (int x = -2; x <= 1; ++x) {
            const float3 light = mc_target1.SampleLevel(mc_linear_clamp, uv + (float2(x, y) * 2.0 + 1.0) * texel, 0).rgb;
            sum += max(tone(base + light, m) - 1.0, 0.0);
        }
    return float4(sum / 16.0, 0.0);
}

// ---- pass 4: the glare blurred at two widths (1.06 and 4 of its texels), still at a quarter size ---------------
float4 bloom(float4 position : SV_Position) : SV_Target {
    const float2 texel = 1.0 / mc_pass.size, uv = position.xy * texel;
    float3 near = mc_target2.SampleLevel(mc_linear_clamp, uv, 0).rgb, far = 0.0;
    [unroll] for (int i = 0; i < 4; ++i) {
        const float2 diagonal = float2(i & 1 ? 1.0 : -1.0, i & 2 ? 1.0 : -1.0);
        const float2 straight = float2(i == 0 ? 1.0 : i == 1 ? -1.0 : 0.0, i == 2 ? 1.0 : i == 3 ? -1.0 : 0.0);
        near += mc_target2.SampleLevel(mc_linear_clamp, uv + diagonal * texel * 1.06, 0).rgb;
        far += mc_target2.SampleLevel(mc_linear_clamp, uv + straight * texel * 4.0, 0).rgb;
    }
    return float4(near * 0.25 + far * 0.1, 0.0);
}

// ---- pass 5: the sky, the wave and the glare, tone mapped ------------------------------------------------------
float4 compose(float4 position : SV_Position) : SV_Target {
    const float2 uv = mc_uv(position.xy);
    const Mood m = stored_mood();
    const float3 glow = mc_target3.SampleLevel(mc_linear_clamp, uv, 0).rgb;
    const float3 radiance = sky(frame_uv(uv), m) + mc_target1.Load(int3(position.xy, 0)).rgb;
    return float4(saturate(tone(radiance, m)) + glow * knob_glare + mc_dither(position.xy), 1.0);
}

// ---- pass 6: the flakes, added over the tone-mapped picture -------------------------------------------------------
// Each flake is drawn twice: instances 0-2047 are its sprite, a flat disc on a quad that faces
// along its orientation (turned toward the camera when near or small), blurred into a soft disc out of focus;
// instances 2048-4095 are its glare, a camera-facing halo that only a flake in its highlight gets.
static const float4 kFocus = float4(6.1, 7.4, 12.8, 16.9); // near, in focus from, in focus to, far

// Our oil-film tint for the highlight, from the flake's facing (warm white with pink, orange and blue).
float3 film_tint(float3 normal) {
    const float3 film = 0.5 + 0.5 * cos(2.0 * kPi * (length(normal.xy) * 1.7 + float3(0.0, 0.33, 0.67)));
    return float3(1.0, 0.89, 0.85) * lerp(1.0, film * 1.4, 0.35);
}

struct GlintVertex {
    float4 position : SV_Position;
    float4 disc : TEXCOORD0;    // quad coordinate (0..1), blur, the blurred edge's steepness
    float4 normal : TEXCOORD1;  // the flake's face normal, and its alpha
    float4 place : TEXCOORD2;   // the corner in the particles' frame; 1 for a glare halo
    float3 halo : TEXCOORD3;    // a glare halo's colour
};

GlintVertex glint_vs(uint vertex_id : SV_VertexID, uint instance_id : SV_InstanceID) {
    const bool halo = instance_id >= 2048u;
    const uint id = instance_id & 2047u;
    const int2 slot = int2(id & 63u, (id >> 6) + kFlakeRow);
    const float4 place = mc_target0.Load(int3(slot, 0)), motion = mc_target0.Load(int3(slot + int2(0, 32), 0));
    const float4 q = normalize(mc_target0.Load(int3(slot + int2(0, 64), 0)));
    const float2 uv = mc_quad_corner(vertex_id);
    const float3 p = place.xyz, toward = kEye - p;
    const float d = length(toward);
    const float3 eye = toward / d;
    // Depth of field: blurred nearer than 7.4 and beyond 12.8, with a world size that grows out of focus.
    const float near_ = saturate((d - kFocus.y) / (kFocus.x - kFocus.y)), far_ = saturate((d - kFocus.z) / (kFocus.w - kFocus.z));
    const float near_blur = pow(near_, 2.5), far_blur = pow(far_, 1.8);
    const float size = lerp(lerp(stored_mood().flake, 0.077, near_blur), 0.87, far_blur);
    const float angle = 2.0 * atan(size / d) / 0.925;  // the angular size, as a fraction of the field of view
    // Near or small flakes turn toward the camera.
    const float facing_camera = saturate((d - kFocus.z + 0.4) / 0.2);
    const float4 turned = normalize(lerp(q, float4(0.0, 0.0, 0.0, 1.0), saturate(angle * 13.2 + near_blur * 0.72 + facing_camera)));
    const float3 face = rotate(q, float3(0.0, 0.0, 1.0));
    // Fades in over its first 2 % of life and out over its last 6 %, near the edges of its box, edge-on to the eye,
    // in a thin shell just short of the far focus, and darkens with blur.
    const float age = place.w;
    const float3 edge = saturate(5.0 * min(p - kBoundsLow, kBoundsHigh - p));
    const float3 fade = edge * edge * (3.0 - 2.0 * edge);
    const float shell = 1.0 + saturate((d - kFocus.z + 0.2) / 0.2) - saturate((d - kFocus.z + 0.6) / 0.2);
    const float edge_on = abs(halo ? eye.z : dot(eye, rotate(turned, float3(0.0, 0.0, 1.0))));
    const float alpha = (1.0 - pow(saturate(1.0 - edge_on), 4.0 / 3.0)) * min(age, 0.02) * 50.0 * (1.0 - max(age - 0.94, 0.0) / 0.06)
                      * shell * (1.0 - saturate(far_ * angle * 13.9)) * (1.0 - saturate(near_ * angle * 6.24)) * fade.x * fade.y * fade.z;
    const float highlight = pow(abs(dot(face, normalize(normalize(kLamp - p) + eye))), 35.0);
    float3 corner;
    float gain = 1.0;
    if (halo) {
        corner = p + size * 5.4 * highlight * float3(uv - 0.5, 0.0);
    } else {
        // At least two pixels across (a smaller sprite keeps its light).
        const float side = size * kFocalY * output_scale().y * 0.5 * mc_pass.size.y / max(d, 0.1);
        const float grow = max(2.0 / max(side, 1e-4), 1.0);
        gain = 1.0 / (grow * grow);
        corner = p + size * grow * ((uv.x - 0.5) * rotate(turned, float3(1.0, 0.0, 0.0)) + (uv.y - 0.5) * rotate(turned, float3(0.0, 1.0, 0.0)));
    }
    const float4 clip = clip_of(corner - kEye);
    GlintVertex output;
    output.position = float4(clip.xy * output_scale(), 0.0, clip.w);
    output.disc = float4(uv, saturate(near_blur + far_blur), lerp(0.85, 3.8, near_blur));
    output.normal = float4(face, alpha * gain * knob_glitter);
    output.place = float4(corner, halo ? 1.0 : 0.0);
    output.halo = alpha * (1.0 - exp(-0.039 * highlight * 75.0 * film_tint(face))) * 0.16 * knob_glitter;
    if (motion.w == 0.0 || clip.w < 0.1)
        output.position = float4(0.0, 0.0, 0.0, 1.0);   // nothing yet: a degenerate quad
    return output;
}

float4 glint(GlintVertex input) : SV_Target {
    const float r = length(input.disc.xy * 2.0 - 1.0);
    if (input.place.w > 0.5)
        return float4(input.halo * exp(-4.4 * min(r, 1.0)), 0.0);
    // A disc half the quad across, its edge widening with blur into a soft bokeh.
    const float blur = input.disc.z, width = 0.05 + 0.63 * blur;
    const float t = saturate((r - 0.5 + width) / (2.0 * width));
    const float disc = 1.0 - t * t * (3.0 - 2.0 * t);
    const float profile = lerp(disc, 1.0 - exp(-input.disc.w * disc), blur);
    // Two-sided: a faint diffuse light, and the tinted highlight as the face turns toward the half vector.
    const float3 face = normalize(input.normal.xyz), lamp = normalize(kLamp - input.place.xyz);
    const float highlight = pow(abs(dot(face, normalize(lamp + normalize(kEye - input.place.xyz)))), 35.0);
    const float3 light = abs(dot(face, lamp)) * 8.0 + highlight * 75.0 * film_tint(face);
    return float4(profile * input.normal.w * (1.0 - exp(-0.039 * light)), 0.0);
}
