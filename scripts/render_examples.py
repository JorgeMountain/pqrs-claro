"""Hoja de inspección visual de todas las páginas de los ejemplos ficticios."""

from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
tiles = []
for path in sorted((root / "examples").glob("*.pdf")):
    with pymupdf.open(path) as doc:
        for number, page in enumerate(doc, 1):
            pix = page.get_pixmap(matrix=pymupdf.Matrix(0.62, 0.62), alpha=False)
            picture = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            tile = Image.new("RGB", (400, 570), "#ecf0eb")
            tile.paste(picture, (15, 32))
            ImageDraw.Draw(tile).text((15, 10), f"{path.name} / {number}", fill="#183e30")
            tiles.append(tile)
sheet = Image.new("RGB", (1600, ((len(tiles) + 3) // 4) * 570), "white")
for index, tile in enumerate(tiles):
    sheet.paste(tile, ((index % 4) * 400, (index // 4) * 570))
out = root / "output/qa/examples.png"
out.parent.mkdir(parents=True, exist_ok=True)
sheet.save(out)
print(out)
