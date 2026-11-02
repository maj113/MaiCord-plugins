"""Effect previews: a still and a short clip rendered by effect_render.exe on WARP, encoded as PNG and APNG.

The catalog limits are 256 KiB for a preview and 2 MiB for a loop; the renderer's picture shrinks down a ladder
until it fits (noise-heavy effects such as film grain compress badly).
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

from PIL import Image

import effects

PREVIEW_MAX_BYTES = 256 * 1024
LOOP_MAX_BYTES = 2 * 1024 * 1024
STILL_TIME = 2.0
STILL_SIZES = ((960, 540), (800, 450), (640, 360), (480, 270))
# (width, height, frames per second, seconds); the first that fits is kept. The clip starts at STILL_TIME.
LOOP_LADDER = ((480, 270, 15, 3), (480, 270, 10, 3), (320, 180, 12, 3), (320, 180, 10, 2), (240, 135, 10, 2),
               (160, 90, 8, 2))
BENCH_FRAMES = 300
BENCH_REPEATS = 3
CALIBRATION_ITERATIONS = 4
CALIBRATION_SOURCE = """// Calibration for the cost class: a fixed amount of arithmetic per pixel.
#include <maicord/sdk/background.hlsli>
float4 background(float2 pixel) {
    const float2 p = pixel / mc.resolution;
    float3 c = float3(0.0, 0.0, 0.0);
    [loop] for (int i = 0; i < %d; ++i) {
        const float k = (float)i;
        c += 0.5 + 0.5 * sin(float3(p.x * (3.0 + k), p.y * (5.0 + k), (p.x + p.y) * (7.0 + k)) + mc.time * (1.0 + k * 0.1));
    }
    return float4(c * (1.0 / %d.0), 1.0);
}
"""


class Renderer:
    def __init__(self, executable: Path, blue_noise: Path, work: Path):
        self.executable, self.blue_noise, self.work = executable, blue_noise, work
        work.mkdir(parents=True, exist_ok=True)

    def _arguments(self, cso: Path, blend: str, uses: list, knobs: list) -> list:
        return [str(self.executable), "--cso", str(cso), "--blend", blend, "--uses", ",".join(uses),
                "--blue", str(self.blue_noise), "--knobs", ",".join(f"{v:.6f}" for v in knobs)]

    def _run(self, arguments: list) -> str:
        result = subprocess.run(arguments, capture_output=True, text=True)
        if result.returncode:
            raise effects.EffectError(f"effect_render failed: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout

    def frames(self, cso: Path, blend: str, uses: list, knobs: list, size: tuple, fps: float, count: int,
               start: float) -> list:
        """RGB images of `count` frames at `size`, with dip scaled so the picture keeps its proportions."""
        out = self.work / "frames.rgba"
        self._run(self._arguments(cso, blend, uses, knobs) + [
            "--size", f"{size[0]}x{size[1]}", "--dip", f"{size[0] / 960:.6f}", "--fps", str(fps), "--t0", str(start),
            "--frames", str(count), "--out", str(out)])
        data = out.read_bytes()
        stride = size[0] * size[1] * 4
        return [Image.frombytes("RGBA", size, data[i * stride:(i + 1) * stride]).convert("RGB") for i in range(count)]

    def milliseconds(self, cso: Path, blend: str, uses: list, knobs: list) -> float:
        """Milliseconds per frame at 960x540 over BENCH_FRAMES frames: the best of BENCH_REPEATS runs."""
        arguments = self._arguments(cso, blend, uses, knobs) + ["--bench", str(BENCH_FRAMES)]
        return min(float(self._run(arguments)) for _ in range(BENCH_REPEATS))


def png_bytes(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, "PNG", optimize=True)
    return stream.getvalue()


def apng_bytes(frames: list, fps: int) -> bytes:
    stream = io.BytesIO()
    frames[0].save(stream, "PNG", save_all=True, append_images=frames[1:], duration=round(1000 / fps), loop=0,
                   optimize=True)
    return stream.getvalue()


def still(renderer: Renderer, cso: Path, blend: str, uses: list, knobs: list) -> tuple[bytes, tuple]:
    for size in STILL_SIZES:
        data = png_bytes(renderer.frames(cso, blend, uses, knobs, size, 24, 1, STILL_TIME)[0])
        if len(data) <= PREVIEW_MAX_BYTES:
            return data, size
    raise effects.EffectError("the preview does not fit 256 KiB at any size")


def loop(renderer: Renderer, cso: Path, blend: str, uses: list, knobs: list) -> tuple[bytes, dict]:
    for width, height, fps, seconds in LOOP_LADDER:
        frames = renderer.frames(cso, blend, uses, knobs, (width, height), fps, fps * seconds, STILL_TIME)
        data = apng_bytes(frames, fps)
        if len(data) <= LOOP_MAX_BYTES:
            return data, {"width": width, "height": height, "fps": fps, "seconds": seconds}
    raise effects.EffectError("the loop does not fit 2 MiB at any size")
