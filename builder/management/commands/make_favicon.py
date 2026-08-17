"""Generate static/favicon.ico (and favicon.svg) from scratch.

Written with the standard library only — no image dependency — because the icon
is a handful of rectangles: an ascending bar chart on the brand navy, matching
the workbook's header colour.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

NAVY = (31, 56, 100, 255)      # #1F3864 — the workbook header fill
TEAL = (63, 191, 168, 255)     # accent, tallest bar
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)

SIZES = (16, 32, 48, 64)


def _rounded(size: int) -> float:
    return max(2.0, size * 0.18)


def _draw(size: int) -> list[list[tuple[int, int, int, int]]]:
    """Return an RGBA pixel grid for one icon size."""
    radius = _rounded(size)
    pixels = [[CLEAR] * size for _ in range(size)]

    # Background with rounded corners.
    for y in range(size):
        for x in range(size):
            dx = min(x + 0.5, size - x - 0.5)
            dy = min(y + 0.5, size - y - 0.5)
            if dx < radius and dy < radius:
                if (radius - dx) ** 2 + (radius - dy) ** 2 > radius ** 2:
                    continue
            pixels[y][x] = NAVY

    # Three ascending bars, the tallest in the accent colour.
    pad = max(1, round(size * 0.20))
    gap = max(1, round(size * 0.07))
    usable = size - pad * 2
    bar_w = max(1, (usable - gap * 2) // 3)
    heights = (0.34, 0.58, 0.86)
    colours = (WHITE, WHITE, TEAL)
    baseline = size - pad

    for index, (fraction, colour) in enumerate(zip(heights, colours)):
        left = pad + index * (bar_w + gap)
        top = baseline - max(2, round(usable * fraction))
        for y in range(max(0, top), baseline):
            for x in range(left, min(left + bar_w, size - pad)):
                if 0 <= x < size and 0 <= y < size:
                    pixels[y][x] = colour
    return pixels


def _png(pixels) -> bytes:
    height = len(pixels)
    width = len(pixels[0])
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # no filter
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    header = struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _ico(images: list[tuple[int, bytes]]) -> bytes:
    """Wrap PNG payloads in an ICO container (PNG-in-ICO, supported since Vista)."""
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries, blobs = bytearray(), bytearray()
    for size, payload in images:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size, 0 if size >= 256 else size,
            0, 0, 1, 32, len(payload), offset,
        )
        blobs += payload
        offset += len(payload)
    return header + bytes(entries) + bytes(blobs)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img">
  <title>Acquisition P&amp;L</title>
  <rect width="64" height="64" rx="12" fill="#1F3864"/>
  <rect x="13" y="34" width="10" height="17" rx="2" fill="#FFFFFF"/>
  <rect x="27" y="26" width="10" height="25" rx="2" fill="#FFFFFF"/>
  <rect x="41" y="16" width="10" height="35" rx="2" fill="#3FBFA8"/>
</svg>
"""


class Command(BaseCommand):
    help = "Regenerate static/favicon.ico and static/favicon.svg."

    def handle(self, *args, **options):
        static_dir = Path(settings.BASE_DIR) / "static"
        static_dir.mkdir(parents=True, exist_ok=True)

        images = [(size, _png(_draw(size))) for size in SIZES]
        ico_path = static_dir / "favicon.ico"
        ico_path.write_bytes(_ico(images))

        svg_path = static_dir / "favicon.svg"
        svg_path.write_text(SVG, encoding="utf-8")

        png_path = static_dir / "icon-192.png"
        png_path.write_bytes(_png(_draw(192)))

        self.stdout.write(self.style.SUCCESS(
            f"Wrote {ico_path.name} ({ico_path.stat().st_size} bytes, "
            f"sizes {', '.join(str(s) for s in SIZES)}), "
            f"{svg_path.name} and {png_path.name}."
        ))
