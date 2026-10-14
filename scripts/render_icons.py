"""Render our editable SVG into PNG and a multi-resolution Windows ICO using Qt."""
from __future__ import annotations

import os
from pathlib import Path
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "filepilot" / "assets"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(renderer: QSvgRenderer, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def png(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Could not encode PNG")
    return bytes(data)


def dib(image: QImage) -> bytes:
    size = image.width()
    rgba = bytes(image.constBits())
    stride = image.bytesPerLine()
    pixels = bytearray()
    mask = bytearray()
    mask_stride = ((size + 31) // 32) * 4
    for y in reversed(range(size)):
        mask_row = bytearray(mask_stride)
        for x in range(size):
            offset = y * stride + x * 4
            r, g, b, a = rgba[offset:offset+4]
            pixels.extend((b, g, r, a))
            if a == 0:
                mask_row[x // 8] |= 0x80 >> (x % 8)
        mask.extend(mask_row)
    header = struct.pack("<IiiHHIIiiII", 40, size, size*2, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    return header + pixels + mask


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(ASSETS / "filepilot.svg"))
    if not renderer.isValid():
        raise RuntimeError("Invalid SVG source")
    payloads = [(size, png(render(renderer, size)) if size == 256 else dib(render(renderer, size)))
                for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(payloads))
    entries = bytearray()
    offset = 6 + len(payloads) * 16
    for size, payload in payloads:
        side = 0 if size == 256 else size
        entries.extend(struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(payload), offset))
        offset += len(payload)
    (ASSETS / "filepilot.ico").write_bytes(header + entries + b"".join(payload for _, payload in payloads))
    (ASSETS / "filepilot.png").write_bytes(png(render(renderer, 512)))
    preview = ROOT / "artifacts" / "icon-preview.png"
    preview.parent.mkdir(exist_ok=True)
    preview.write_bytes(png(render(renderer, 512)))
    print("Rendered SVG, PNG and nine Windows icon sizes:", SIZES)


if __name__ == "__main__":
    main()
