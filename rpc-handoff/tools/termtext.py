"""Render terminal text lines (Ubuntu Sans Mono, subpixel-like AA) into ThingsBoard RPC terminal screenshots."""
from PIL import Image, ImageDraw, ImageFont

FONT = '/usr/share/fonts/truetype/ubuntu/UbuntuSansMono[wght].ttf'
PITCH = 9.0
X0 = 338.0          # left edge of character cell 0
COLOR = (167, 167, 167)


def render_line(img, text, start_cell, baseline, size=16.0, color=COLOR):
    """Draw text into img starting at character cell start_cell; baseline = y of the bottom of non-descender glyphs."""
    s = 3  # supersampling factor
    f = ImageFont.truetype(FONT, int(round(size * s)))
    width = int(PITCH * (len(text) + 2)) + 4
    height = 34
    mask = Image.new('L', (width * s, height * s), 0)
    d = ImageDraw.Draw(mask)
    top = 24  # baseline position inside the strip
    for i, ch in enumerate(text):
        d.text(((2 + PITCH * i) * s, top * s), ch, font=f, fill=255, anchor='ls')
    # subpixel: R, G, B take the three horizontal subsamples, vertical average over s rows
    mp = mask.load()
    x_origin = X0 + PITCH * start_cell - 2
    ox = int(x_origin)
    oy = baseline - top
    px = img.load()
    taps = (1 / 9, 2 / 9, 3 / 9, 2 / 9, 1 / 9)   # FreeType-like LCD filter, softens the colour fringes
    for y in range(height):
        sub = [sum(mp[i, y * s + j] for j in range(s)) / (255 * s) for i in range(width * s)]
        filt = [sum(t * sub[i + k - 2] for k, t in enumerate(taps) if 0 <= i + k - 2 < len(sub))
                for i in range(len(sub))]
        for x in range(width):
            cov = [min(1.0, filt[x * s + k]) for k in range(3)]
            if max(cov) == 0:
                continue
            X, Y = ox + x, oy + y
            bg = px[X, Y]
            px[X, Y] = tuple(int(bg[c] * (1 - cov[c]) + color[c] * cov[c]) for c in range(3))


def clear(img, x1, y1, x2, y2):
    ImageDraw.Draw(img).rectangle((x1, y1, x2, y2), fill=(0, 0, 0))
