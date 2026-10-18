"""Rebuild the Morphaic mosaic-M icon using the project's Pillow dependency."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'assets'
ASSETS.mkdir(exist_ok=True)
SIZE = 256
TILES = [('#fafaf7', [(48, 66), (88, 66), (88, 190), (48, 190)]),
         ('#d4d9df', [(96, 71), (128, 108), (128, 158), (96, 121)]),
         ('#f3f5f6', [(136, 108), (168, 71), (168, 121), (136, 158)]),
         ('#aebac7', [(176, 66), (208, 66), (208, 190), (176, 190)])]
svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">',
       '<rect x="4" y="4" width="248" height="248" rx="54" fill="#171b23" stroke="#737e8c" stroke-width="3"/>']
image = Image.new('RGBA', (1024, 1024))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((16, 16, 1008, 1008), radius=216, fill='#171b23', outline='#737e8c', width=12)
for color, points in TILES:
    draw.polygon([(x*4, y*4) for x, y in points], fill=color)
    svg.append(f'<polygon points="{" ".join(f"{x},{y}" for x,y in points)}" fill="{color}"/>')
svg.append('</svg>')
(ASSETS / 'morphaic.svg').write_text('\n'.join(svg)+'\n', encoding='utf-8')
image.resize((512, 512), Image.Resampling.LANCZOS).save(ASSETS / 'morphaic.png')
image.save(ASSETS / 'morphaic.ico', sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
print(ASSETS / 'morphaic.ico')
