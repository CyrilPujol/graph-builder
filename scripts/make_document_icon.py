"""Regenerate the GraphML document icons from the Graph Builder logo.

This is an asset-maintenance script, not needed by app users or builds.
Run it with Pillow installed when changing the design below.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / 'assets/icons'
SIZE = 1024


def main():
    canvas = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # A document page distinguishes GraphML files from the application itself.
    page = [(160, 48), (700, 48), (864, 212), (864, 970), (160, 970)]
    draw.polygon(page, fill='white')
    draw.line(page + [page[0]], fill='#9ba5b1', width=17, joint='curve')
    draw.polygon([(700, 48), (700, 212), (864, 212)],
                 fill='#e6ebf0')
    draw.line([(700, 48), (700, 212), (864, 212)],
              fill='#9ba5b1', width=15, joint='curve')

    # The current logo is kept as an independent source asset. Replace or
    # redraw it here without changing the app icon.
    logo = Image.open(ICONS / 'graph_builder.png').convert('RGBA')
    logo = logo.crop((32, 32, 480, 480)).resize((615, 615), Image.Resampling.LANCZOS)
    canvas.alpha_composite(logo, (205, 270))

    png = ICONS / 'graphml_document.png'
    canvas.save(png)
    canvas.save(ICONS / 'graphml_document.ico', format='ICO',
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                       (64, 64), (128, 128), (256, 256)])

    canvas.save(ICONS / 'graphml_document.icns', format='ICNS')


if __name__ == '__main__':
    main()
