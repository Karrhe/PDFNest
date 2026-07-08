from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QPainter


def png_bytes_for_size(source: QImage, size: int) -> bytes:
    canvas = QImage(size, size, QImage.Format_ARGB32)
    canvas.fill(QColor(0, 0, 0, 0))
    scaled = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter = QPainter(canvas)
    painter.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    if not canvas.save(buffer, "PNG"):
        raise RuntimeError(f"Failed to encode {size}px icon")
    return bytes(data)


def build_ico(source_path: Path, target_path: Path) -> None:
    source = QImage(str(source_path))
    if source.isNull():
        raise RuntimeError(f"Failed to load icon source: {source_path}")

    sizes = [16, 32, 48, 64, 128, 256]
    images = [(size, png_bytes_for_size(source, size)) for size in sizes]

    header_size = 6 + 16 * len(images)
    offset = header_size
    entries = []
    chunks = []
    for size, payload in images:
        entries.append(
            struct.pack(
                "<BBBBHHII",
                0 if size == 256 else size,
                0 if size == 256 else size,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        chunks.append(payload)
        offset += len(payload)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("wb") as handle:
        handle.write(struct.pack("<HHH", 0, 1, len(images)))
        handle.write(b"".join(entries))
        handle.write(b"".join(chunks))


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: make_windows_icon.py SOURCE_PNG TARGET_ICO", file=sys.stderr)
        return 2
    build_ico(Path(sys.argv[1]), Path(sys.argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
