"""Cut images/PDFs into sections, scatter + layer them on a canvas, export PNG / TIFF / PDF.

All geometry is in inches, so a 1000px preview and a 600 dpi export of the same params are the same picture.
"""
import io
import json
import math
import os
import random
import re
import zipfile
import tempfile
import time
from contextlib import closing
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pymupdf
import shapes
import effects
from pillow_heif import register_heif_opener
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

register_heif_opener()

MAX_PIXELS = 400_000_000   # output cap: RGB at the cap is ~1.2 GB
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
ASSUMED_DPI = 300          # images that carry no dpi tag
PREVIEW_SRC = 1600         # long edge of the cached preview copy of each source
POOL = ThreadPoolExecutor(os.cpu_count() or 4)
IDENT = list(range(256))

# key: (min, max, default). Anything the client sends is clamped to this.
SPEC = dict(
    cw=(0.05, 1, 0.25), ch=(0.05, 1, 0.25),                   # section size, fraction of source
    ps=(0.1, 1, 1), pn=(1, 6, 2),                             # portion of each file used (1 = all of it), portions per file
    scale=(0.1, 4, 1), var=(0, 0.9, 0), rot=(0, 180, 0),     # section scale, scale spread, max rotation (deg)
    scatter=(0, 1, 0), density=(0.1, 1, 1),                   # drift from home spot, share of sections used
    gn=(2, 24, 8), gs=(0, 1, 0), gi=(0, 1, 0),                # guide grid: nodes across, pull to nearest node, node jitter
    draw=(0, 1, 0), blur=(0, 1, 0),                           # pull toward drawn strokes, edge softness
    con=(-1, 1, 0), lb=(0, 254, 0), lw=(1, 255, 255), lg=(0.2, 5, 1),   # contrast, levels black / white / gamma
    layers=(1, 16, 1), opacity=(0.05, 1, 1), seed=(0, 9999, 1),
    w=(0.001, 200, 8.5), h=(0.001, 200, 11), dpi=(10, 1200, 300), pv=(200, 3000, 1000),  # canvas in, dpi, preview px
    m1o=(0, 1, 0.8), m2o=(0, 1, 0.8), m3o=(0, 1, 1),          # migration map: line opacity per layer
    m1a=(0, 1, 1), m2a=(0, 1, 0), m3a=(0, 1, 0),              # migration map: paper opacity per layer (0 = no paper)
    m1w=(.05, 12, .6), m2w=(.05, 12, .6), m3w=(.05, 12, .6), # map stroke widths in PDF points
    m2so=(0, 1, .8), m2eo=(0, 1, .8), m2_gradient_opacity=(0, 1, 0),
    smoothness=(4, 24, 12), pace=(3, 30, 6),   # animation: frame rate, seconds
    node_end_size=(0.25, 6, 1),
)
COLORS = dict(bg="#f4f2ee", m1c="#8a8a90", m2c="#ff5a36", m3c="#18181b",   # canvas, map tone per layer
              m1p="#f4f2ee", m2p="#f4f2ee", m3p="#f4f2ee", m2_gradient_end="#18181b")
LINE_SHAPE_COLORS = dict(zip(shapes.NAMES, ('#9fbdd4','#a9c4b3','#d9a4a7','#b4bddd','#bfd4ca','#bca18b','#cc9386','#d7c8ae')))


def clean(raw):
    p = {k: effects.number(raw.get(k, d), lo, hi, d) for k, (lo, hi, d) in SPEC.items()}
    p.update(effects.clean(raw))
    for k, d in COLORS.items():
        v = str(raw.get(k, ""))
        p[k] = v if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else d
    for k in ("m2s", "m2e"):   # start / end node colours: follow the line colour until set, so older settings look the same
        v = str(raw.get(k, ""))
        p[k] = v if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else p["m2c"]
    pts = [(min(max(float(x), 0), 1), min(max(float(y), 0), 1)) for x, y in list(raw.get("pts") or [])[:5000]]
    p["pts"] = pts[::max(1, -(-len(pts) // 400))]   # drawn points, thinned to <= 400 so the nearest-point search stays cheap
    c = raw.get("curve")
    p["curve"] = [min(max(round(float(v)), 0), 255) for v in c] if isinstance(c, list) and len(c) == 256 else IDENT
    for key, default, choices in [('node_start', 'dot', ('none', 'dot', 'ring', 'square', 'plus')), ('node_end', 'arrow', ('none', 'arrow', 'dot', 'ring', 'square', 'plus')), ('anim', 'collage', ('collage', 'map'))]:
        value = raw.get(key, default)
        p[key] = value if value in choices else default
    for key, default, choices in [('anim_resolution','full',('full','2160','1440','1080','720')), ('anim_renderer','cpu',('cpu','gpu'))]:
        value = str(raw.get(key, default))
        p[key] = value if value in choices else default
    p['map_file']=raw.get('map_file') if raw.get('map_file') in ('pdf','png','tif') else 'pdf'
    p['triptych_file']='pdf' if raw.get('triptych_file')=='pdf' else 'png'
    p['line_by_shape']=bool(raw.get('line_by_shape',False))
    p['line_tone_gradient']=bool(raw.get('line_tone_gradient',False))
    p['line_opacity_gradient']=bool(raw.get('line_opacity_gradient',False))
    for key in ('m2so','m2eo'):
        if key not in raw:p[key]=p['m2o']  # older maps used one opacity for lines and nodes
    colors=raw.get('line_shape_colors',{})
    if not isinstance(colors,dict):colors={}
    p['line_shape_colors']={key:colors[key] if isinstance(colors.get(key),str) and re.fullmatch(r'#[0-9a-fA-F]{6}',colors[key]) else default
                            for key,default in LINE_SHAPE_COLORS.items()}
    p.update(shapes.clean(raw))
    return p


def tone_lut(p):
    """Contrast, then levels, then the curve, as one 256-entry table."""
    b, g, c = p["lb"] / 255, p["lg"], 2 ** p["con"]
    w = max(p["lw"] / 255, b + 1 / 255)
    lut = []
    for v in range(256):
        x = min(max((v / 255 - 0.5) * c + 0.5, 0), 1)
        x = min(max((x - b) / (w - b), 0), 1) ** (1 / g)
        lut.append(p["curve"][round(x * 255)])
    return lut


def adjust(im, lut):
    if lut == IDENT:
        return im
    return im.point(lut * 3 + (IDENT if im.mode == "RGBA" else []))   # alpha untouched


@dataclass
class Source:
    name: str
    data: bytes
    pdf: bool
    pages: int
    w_in: float          # width read from the file, or ASSUMED_DPI guess
    aspect: float        # height / width
    assumed: bool        # True when w_in is a guess the user should override
    thumbs: dict = field(default_factory=dict)   # page -> preview-size RGB(A)


def _decode(data):
    im = Image.open(io.BytesIO(data))
    dpi = im.info.get("dpi")
    im = ImageOps.exif_transpose(im)
    im.load()
    if im.mode.startswith("I;16"):
        im = im.point(lambda v: v / 256)   # convert() alone clips 16-bit gray to white
    return im.convert("RGBA" if im.has_transparency_data else "RGB"), dpi


def open_source(name, data):
    try:
        if data[:5] == b"%PDF-":
            doc = pymupdf.open(stream=data, filetype="pdf")
            r = doc[0].rect
            src = Source(name, data, True, len(doc), r.width / 72, r.height / r.width, False)
        else:
            im, dpi = _decode(data)
            ok = dpi and float(dpi[0]) > 1   # dpi (1, 1) means "aspect ratio only"
            d = round(float(dpi[0]), 1) if ok else ASSUMED_DPI   # PNG stores px/metre: 300 dpi reads back as 299.9994
            src = Source(name, data, False, 1, im.width / d, im.height / im.width, not ok)
            src.thumbs[0] = im.copy()
            src.thumbs[0].thumbnail((PREVIEW_SRC, PREVIEW_SRC), Image.BILINEAR)
        return src
    except Exception as e:
        raise ValueError(f"can't read {name}") from e


def raster(src, page=0, dpi=None, long_edge=None):
    """One page at dpi / to long_edge px (PDF), or the full-resolution image."""
    if not src.pdf:
        return _decode(src.data)[0]
    pg = pymupdf.open(stream=src.data, filetype="pdf")[page]
    r = pg.rect
    z = dpi / 72 if dpi else long_edge / max(r.width, r.height)
    z = min(z, math.sqrt(150e6 / (r.width * r.height)))   # cap a page at 150 MP
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def thumb(src, page):
    if page not in src.thumbs:
        src.thumbs[page] = raster(src, page, long_edge=PREVIEW_SRC)
    return src.thumbs[page]


def _portions(p, si):
    """Rectangles (u0, v0, u1, v1) of source si that get cut: the whole file, or random portions of it."""
    if p["ps"] > 0.999:
        return [(0, 0, 1, 1)]
    g, s, out = random.Random(int(p["seed"]) * 131 + si), p["ps"], []
    for _ in range(int(p["pn"])):
        x, y = g.random() * (1 - s), g.random() * (1 - s)
        out.append((x, y, x + s, y + s))
    return out


def _grid(p, W, H):
    """Guide grid as cell edges (xs, ys) in inches: gn columns, square-ish rows. gi = 0 gives equal cells;
    more makes columns and rows progressively uneven (up to about twice as wide as their neighbours)."""
    gx, gy = int(p["gn"]), min(48, max(1, round(p["gn"] * H / W)))
    g = random.Random(int(p["seed"]) * 977 + 13)

    def edges(n, total):
        w = [1 + p["gi"] * 0.9 * (2 * g.random() - 1) for _ in range(n)]
        out = [0.0]
        for v in w:
            out.append(out[-1] + v / sum(w) * total)
        return out

    return edges(gx, W), edges(gy, H)


def _cells(xs, ys):
    return [((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2) for i in range(len(xs) - 1) for j in range(len(ys) - 1)]


def layout(p, sizes, W, H):
    """Sections bottom to top as (source, (u0, v0, u1, v1), cx, cy, w, h, angle, home_x, home_y, home_w, home_h).

    Inches, resolution-independent. Every section draws the same six random numbers whatever the sliders say,
    so dragging one slider moves the picture smoothly instead of reshuffling it.
    """
    rng = random.Random(int(p["seed"]))
    cols, rows = max(1, int(1 / p["cw"] + 0.5)), max(1, int(1 / p["ch"] + 0.5))
    cells = _cells(*_grid(p, W, H)) if p["gs"] > 0 else None
    pts = [(x * W, y * H) for x, y in p["pts"]] if p["draw"] > 0 else []
    parts = [_portions(p, si) for si in range(len(sizes))]
    out = []
    for _ in range(int(p["layers"])):
        layer, free = [], list(cells or [])   # each layer hands out every grid cell once, so sections spread over the grid instead of piling on a few
        for si, (sw, sh) in enumerate(sizes):
            for a0, b0, a1, b1 in parts[si]:
                fw, fh = (a1 - a0) / cols, (b1 - b0) / rows
                for r in range(rows):
                    for c in range(cols):
                        keep, sv, an, rx, ry, z = (rng.random() for _ in range(6))
                        if keep > p["density"]:
                            continue
                        s = p["scale"] * (1 + p["var"] * (2 * sv - 1))
                        u0, v0 = a0 + c * fw, b0 + r * fh
                        bx, by = (u0 + fw / 2) * W, (v0 + fh / 2) * H   # home: same relative place on the canvas as in the source
                        x, y = bx + (rx * W - bx) * p["scatter"], by + (ry * H - by) * p["scatter"]
                        if cells:
                            free = free or list(cells)   # more sections than cells: start another round
                            nx, ny = min(free, key=lambda c: (c[0] - x) ** 2 + (c[1] - y) ** 2)
                            free.remove((nx, ny))
                            x, y = x + (nx - x) * p["gs"], y + (ny - y) * p["gs"]
                        if pts:
                            qx, qy = min(pts, key=lambda q: (q[0] - x) ** 2 + (q[1] - y) ** 2)
                            x, y = x + (qx - x) * p["draw"], y + (qy - y) * p["draw"]
                        layer.append((z, (si, (u0, v0, u0 + fw, v0 + fh), x, y, sw * fw * s, sh * fh * s,
                                          p["rot"] * (2 * an - 1), bx, by, sw * fw, sh * fh)))
        out += [pc for _, pc in sorted(layer, key=lambda t: t[0])]
    return out


def _batches(pieces, ppi, budget=60e6):
    """Cap how many finished tiles sit in memory at once."""
    batch, px = [], 0
    for pc in pieces:
        batch.append(pc)
        px += pc[4] * pc[5] * ppi * ppi * 2
        if px >= budget:
            yield batch
            batch, px = [], 0
    if batch:
        yield batch


def render(p, items, ppi, resample, pieces=None, grain_texture=None, compositor=None):
    """items: [(PIL image, width_in, height_in)] -> RGB canvas of p.w x p.h inches at ppi."""
    W, H = p["w"], p["h"]
    cw, ch = max(1, round(W * ppi)), max(1, round(H * ppi))
    canvas = Image.new("RGB", (cw, ch), p["bg"])
    spin = Image.BICUBIC if resample == Image.LANCZOS else Image.BILINEAR

    # Unedited imports are one continuous image. Resampling fractional cut
    # boxes independently softens odd-size images and can introduce seams.
    neutral = (len(items) == 1 and p['scale'] == p['density'] == p['layers'] == p['opacity'] == p['ps'] == 1
               and p['var'] == p['rot'] == p['scatter'] == p['blur'] == p['gs'] == 0
               and (not p['pts'] or p['draw'] == 0) and not p['multi_shape'] and p['cut_shape'] == 'rectangle'
               and math.isclose(items[0][1], W) and math.isclose(items[0][2], H))
    if neutral and (pieces is None or pieces == layout(p, [(W, H)], W, H)):
        image = items[0][0].resize((cw, ch), resample)
        canvas.paste(image, (0, 0), image if image.mode == 'RGBA' else None)
        return effects.grain(canvas, p, ppi, grain_texture)

    def prep(pc):
        opacity = p['opacity'] * (pc[11] if len(pc) > 11 else 1)
        if opacity <= 0:
            return None
        si, (u0, v0, u1, v1), cx, cy, w, h, ang = pc[:7]
        im = items[si][0]
        l, r = round((cx - w / 2) * ppi), round((cx + w / 2) * ppi)
        t, b = round((cy - h / 2) * ppi), round((cy + h / 2) * ppi)
        tw, th, mx, my = max(r - l, 1), max(b - t, 1), (l + r) / 2, (t + b) / 2
        reach = (math.hypot(tw, th) if ang else max(tw, th)) / 2
        if mx + reach < 0 or mx - reach > cw or my + reach < 0 or my - reach > ch:
            return None   # off the canvas
        tile = im.resize((tw, th), resample, box=(u0 * im.width, v0 * im.height, u1 * im.width, v1 * im.height))
        rad = min(int(p["blur"] * 0.25 * min(tw, th)), (min(tw, th) - 1) // 2)
        shape = shapes.shape_for(p, pc)
        if shape != 'rectangle':
            tile = tile.convert('RGBA')
            stencil = shapes.mask(shape, p['custom_shape'], (tw, th))
            if rad >= 1:
                stencil = stencil.filter(ImageFilter.GaussianBlur(rad / 2))
            tile.putalpha(ImageChops.multiply(tile.getchannel('A'), stencil))
        if rad >= 1:   # feather the edge: fade alpha to 0 over ~2*rad px
            soft = Image.new("L", (tw, th), 0)
            soft.paste(255, (rad, rad, tw - rad, th - rad))
            tile = tile.convert("RGBA")
            tile.putalpha(ImageChops.multiply(tile.getchannel("A"), soft.filter(ImageFilter.GaussianBlur(rad / 2))))
        if ang:
            tile = tile.convert("RGBA").rotate(ang, spin, expand=True)   # Pillow premultiplies RGBA: no dark fringe
        mask = tile if tile.mode == "RGBA" else None                       # an RGBA mask pastes by its alpha
        if opacity < 1:
            a = tile.getchannel("A") if mask else Image.new("L", tile.size, 255)
            mask = a.point(lambda v: v * opacity)
        return tile, mask, (round(mx - tile.width / 2), round(my - tile.height / 2))

    if compositor is not None:
        compositor.clear(p['bg'])
    for batch in _batches(pieces if pieces is not None else layout(p, [(w, h) for _, w, h in items], W, H), ppi):
        for res in POOL.map(prep, batch):
            if res:
                if compositor is not None:compositor.paste(res[0],res[1],res[2])
                else:canvas.paste(res[0], res[2], res[1])
    if compositor is not None:canvas=compositor.image()
    return effects.grain(canvas, p, ppi, grain_texture)


def _spec(s, store):
    src = store[s["id"]]
    return src, min(max(int(s.get("page", 0)), 0), src.pages - 1), min(max(float(s["w"]), 0.001), 400)


def _grain_texture(p, store):
    source_id = p['grain_source_id']
    if not source_id:
        return None
    src = store.get(source_id)
    if src is None:
        raise ValueError('custom grain image is unavailable; import it again or choose procedural grain')
    if src.pdf:
        raise ValueError('custom grain must be an image, not a PDF')
    if not p['grain']:
        return None
    texture = effects.texture(thumb(src, 0))
    with Image.open(io.BytesIO(src.data)) as image:
        scale = max(image.size)/max(texture.shape)
    return texture, scale


def compose(raw, specs, store, final=False, long_edge=None):
    """raw: params, specs: [{id, w (inches), page}] -> (clean params, RGB image)."""
    p = clean(raw)
    if not specs:
        raise ValueError("add an image or PDF first")
    if final:
        ppi = long_edge / max(p['w'], p['h']) if long_edge else p["dpi"]
        if p["w"] * p["h"] * ppi * ppi > MAX_PIXELS:
            raise ValueError(f"{p['w'] * ppi:.0f} x {p['h'] * ppi:.0f} px is over the {MAX_PIXELS // 10**6} MP limit")
    else:
        ppi = p["pv"] / max(p["w"], p["h"])
    lut, items = tone_lut(p), []
    grain_texture = _grain_texture(p, store)
    for s in specs:
        src, pg, w = _spec(s, store)
        # a PDF only needs rasterising as sharp as its sections end up on the canvas
        im = raster(src, pg, dpi=min(max(ppi * p["scale"] * (1 + p["var"]), 72), 600)) if final else thumb(src, pg)
        items.append((effects.grade(adjust(im, lut), p), w, w * im.height / im.width))
    return p, render(p, items, ppi, Image.LANCZOS if final else Image.BILINEAR, grain_texture=grain_texture)


def corners(cx, cy, w, h, ang):
    """Corners of a w x h box turned ang degrees counter-clockwise on screen, as Image.rotate does."""
    s, c = math.sin(math.radians(ang)), math.cos(math.radians(ang))
    return [(cx + x * c + y * s, cy - x * s + y * c) for x, y in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _sizes(specs, store):
    out = []
    for s in specs:
        src, pg, w = _spec(s, store)
        t = thumb(src, pg)
        out.append((w, w * t.height / t.width))
    return out


LAYERS = {1: "1 initial", 2: "2 migration", 3: "3 final"}


def migration_line_end(p, pc):
    """Intersect the center-to-center path with the destination marker boundary."""
    bx, by, cx, cy = pc[7], pc[8], pc[2], pc[3]
    d = math.hypot(cx-bx, cy-by)
    if d < 1e-10:
        return None
    ux, uy = (cx-bx)/d, (cy-by)/d
    style, radius = shapes.end_style(p, pc), .045*p['node_end_size']
    if style in ('dot', 'ring'):
        trim = radius
    elif style == 'square':
        trim = radius/max(abs(ux), abs(uy))
    elif style == 'plus':
        ax, ay = abs(ux), abs(uy)
        reach = lambda span, component: span/component if component else math.inf
        trim = max(min(reach(radius, ax), reach(radius*.3, ay)),
                   min(reach(radius*.3, ax), reach(radius, ay)))
    elif style == 'arrow' and d >= .05:
        trim = min(.12*p['node_end_size'], d/3)
    elif style == 'cut':
        # Ray/segment intersection with the actual stencil marker boundary.
        trim = 0
        boundary = shapes.outline(p, pc, size=2*radius)
        for a, b in zip(boundary, boundary[1:]):
            vx, vy = b[0]-a[0], b[1]-a[1]
            ax, ay = a[0]-cx, a[1]-cy
            den = (-ux)*vy - (-uy)*vx
            if abs(den) > 1e-12:
                t, u = (ax*vy-ay*vx)/den, (ax*(-uy)-ay*(-ux))/den
                if t >= 0 and 0 <= u <= 1:
                    trim = max(trim, t)
    else:
        trim = 0
    if d <= trim:
        return None
    return cx-ux*trim, cy-uy*trim


def _map_doc(raw, specs, store, layers, pieces=None, doc_only=False):
    """Vector PDF of the canvas holding the given map layers (1 initial, 2 migration, 3 final), no pixels.

    Initial = every section's outline where it was cut; final = where it landed; migration = lines joining
    corresponding corners (they show move, turn and scale at once) plus an arrow along each centre's path,
    with the guide grid and drawn strokes in faint lines when they were steering. Each layer has its own tone,
    line opacity and paper (colour + opacity; opacity 0 = no paper). With several layers they are also real PDF
    layers, so a viewer that supports them can switch each on and off.
    """
    p = clean(raw)
    if not specs:
        raise ValueError("add an image or PDF first")
    W, H = p["w"], p["h"]
    if pieces is None:   # the animation passes sections caught part-way along their journey
        pieces = layout(p, _sizes(specs, store), W, H)
    doc = pymupdf.open()
    page = doc.new_page(width=W * 72, height=H * 72)
    oc = {n: doc.add_ocg(LAYERS[n]) if len(layers) > 1 else 0 for n in layers}
    pt = lambda q: (q[0] * 72, q[1] * 72)

    def ink(n, draw, closed=True, fill=0, soft=1, key=None, color=None, opacity=None):
        tone=color if color is not None else p[key or f"m{n}c"]
        col, op = _rgb(tone) if isinstance(tone,str) else tone, p[f"m{n}o"] if opacity is None else opacity
        sh = page.new_shape()
        draw(sh)
        sh.finish(color=col, fill=col if fill else None, width=p[f'm{n}w'], closePath=closed, stroke_opacity=op * soft, fill_opacity=op * fill, oc=oc[n])
        sh.commit()

    def initial(sh):
        seen = set()
        for pc in pieces:
            if pc[7:] not in seen:   # each layer re-uses the same home spots
                seen.add(pc[7:])
                sh.draw_polyline([pt(q) for q in shapes.outline(p, pc, initial=True)])

    def final(sh):
        for pc in pieces:
            sh.draw_polyline([pt(q) for q in shapes.outline(p, pc)])

    def lines(sh, cut_shape=None):
        for pc in pieces:
            if cut_shape is not None and shapes.shape_for(p,pc)!=cut_shape:
                continue
            # home_x/home_y are the center of the section's initial cut outline.
            end = migration_line_end(p, pc)
            if end is not None:
                sh.draw_line(pt(pc[7:9]), pt(end))

    def gradient_lines():
        from map_gradients import LineGradients
        writer=LineGradients(page,oc[2])
        for pc in pieces:
            end=migration_line_end(p,pc)
            if end is None:continue
            target=p['line_shape_colors'][shapes.shape_for(p,pc)] if p['line_by_shape'] else p['m2c']
            if p['line_tone_gradient'] and not p['line_by_shape']:target=p['m2_gradient_end']
            end_color=_rgb(target)
            start_color=_rgb(p['m2c']) if p['line_tone_gradient'] else end_color
            start_op=p['m2o'];end_op=p['m2_gradient_opacity'] if p['line_opacity_gradient'] else start_op
            writer.draw(pt(pc[7:9]),pt(end),start_color,end_color,start_op,end_op,p['m2w'])

    def markers(sh, key, at_start=False, only_style=None):
        for pc in pieces:
            (bx, by), (cx, cy) = pc[7:9], pc[2:4]
            if at_start:
                bx, by, cx, cy = cx, cy, bx, by
            scale = 1 if at_start else p['node_end_size']
            style, radius = (p[key] if at_start else shapes.end_style(p, pc)), .045*scale
            if only_style is not None and style != only_style:
                continue
            if style == 'cut':
                sh.draw_polyline([pt(q) for q in shapes.outline(p, pc, size=2*radius)])
                continue
            if style in ('dot', 'ring'):
                sh.draw_circle(pt((cx, cy)), radius * 72)
                continue
            if style == 'square':
                sh.draw_rect(pymupdf.Rect((cx-radius)*72, (cy-radius)*72, (cx+radius)*72, (cy+radius)*72))
                continue
            if style == 'plus':
                a = .3
                cross = [(-a,-1),(a,-1),(a,-a),(1,-a),(1,a),(a,a),(a,1),(-a,1),(-a,a),(-1,a),(-1,-a),(-a,-a),(-a,-1)]
                sh.draw_polyline([pt((cx+x*radius,cy+y*radius)) for x,y in cross])
                continue
            if style != 'arrow':
                continue
            d = math.hypot(cx - bx, cy - by)
            if d < 0.05:   # barely moved: no arrow
                continue
            ux, uy, n = (cx - bx) / d, (cy - by) / d, min(0.12*scale, d / 3)
            sh.draw_polyline([pt((cx, cy)), pt((cx - (ux + 0.4 * uy) * n, cy - (uy - 0.4 * ux) * n)),
                              pt((cx - (ux - 0.4 * uy) * n, cy - (uy + 0.4 * ux) * n))])

    def grid(sh):
        xs, ys = _grid(p, W, H)
        for x in xs:
            sh.draw_line(pt((x, 0)), pt((x, H)))
        for y in ys:
            sh.draw_line(pt((0, y)), pt((W, y)))

    def strokes(sh):
        sh.draw_polyline([pt((x * W, y * H)) for x, y in p["pts"]])

    for n in layers:
        if p[f"m{n}a"] > 0:
            page.draw_rect(page.rect, color=None, fill=_rgb(p[f"m{n}p"]), fill_opacity=p[f"m{n}a"], oc=oc[n])
        if n == 1:
            ink(1, initial, fill=0.15)
        elif n == 2:
            if p["gs"] > 0:
                ink(2, grid, closed=False, soft=0.35)
            if p["draw"] > 0 and len(p["pts"]) > 1:
                ink(2, strokes, closed=False, soft=0.6)
            if p['line_tone_gradient'] or p['line_opacity_gradient']:
                gradient_lines()
            elif p['line_by_shape']:
                for cut_shape in shapes.NAMES:
                    ink(2,lambda sh,cut_shape=cut_shape:lines(sh,cut_shape),closed=False,color=p['line_shape_colors'][cut_shape])
            else:ink(2, lines, closed=False)
            ink(2, lambda sh: markers(sh, 'node_start', True), fill=0 if p['node_start'] == 'ring' else 1, key='m2s',opacity=p['m2so'])
            for style in shapes.NODE_STYLES:
                if style != 'none':
                    ink(2, lambda sh, style=style: markers(sh, 'node_end', only_style=style), fill=0 if style == 'ring' else 1, key='m2e',opacity=p['m2eo'])
        else:
            ink(3, final, fill=0.15)
    return doc if doc_only else doc.tobytes(deflate=True)


def migration_pdf(raw, specs, store):
    """All three layers in one PDF (also what the stage previews)."""
    return _map_doc(raw, specs, store, (1, 2, 3))


def migration_pdfs(raw, specs, store):
    """{file name: bytes}: each layer as its own PDF plus the one layered PDF (the InDesign export places these)."""
    out = {f"collage-{LAYERS[n].replace(' ', '-')}.pdf": _map_doc(raw, specs, store, (n,)) for n in (1, 2, 3)}
    out["collage-map-layers.pdf"] = migration_pdf(raw, specs, store)
    return out


def portions_pdf(raw, specs, store):
    """Vector linework, one page per source at its physical size: the file's outline, each selected portion
    in a heavy line with its number, and the cut grid inside it."""
    p = clean(raw)
    if not specs:
        raise ValueError("add an image or PDF first")
    if p["ps"] > 0.999:
        raise ValueError("portion linework needs a portion of file below 100%")
    cols, rows = max(1, int(1 / p["cw"] + 0.5)), max(1, int(1 / p["ch"] + 0.5))
    doc = pymupdf.open()
    for si, (w, h) in enumerate(_sizes(specs, store)):
        page = doc.new_page(width=w * 72, height=h * 72)
        page.draw_rect(page.rect, color=(0.6, 0.6, 0.6), width=0.5)
        for n, (a0, b0, a1, b1) in enumerate(_portions(p, si), 1):
            x0, y0, x1, y1 = a0 * w * 72, b0 * h * 72, a1 * w * 72, b1 * h * 72
            for c in range(1, cols):
                page.draw_line((x0 + (x1 - x0) * c / cols, y0), (x0 + (x1 - x0) * c / cols, y1), color=(0.45, 0.45, 0.45), width=0.3)
            for r in range(1, rows):
                page.draw_line((x0, y0 + (y1 - y0) * r / rows), (x1, y0 + (y1 - y0) * r / rows), color=(0.45, 0.45, 0.45), width=0.3)
            for row in range(rows):
                for col in range(cols):
                    u0, v0 = a0 + (a1-a0)*col/cols, b0 + (b1-b0)*row/rows
                    u1, v1 = a0 + (a1-a0)*(col+1)/cols, b0 + (b1-b0)*(row+1)/rows
                    pc = (si,(u0,v0,u1,v1),0,0,0,0,0,(u0+u1)*w/2,(v0+v1)*h/2,(u1-u0)*w,(v1-v0)*h)
                    if shapes.shape_for(p,pc) != 'rectangle':
                        page.draw_polyline([(x*72,y*72) for x,y in shapes.outline(p,pc,initial=True)],color=(0,0,0),width=.5)
            page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=1.5)
            size = max(6, min(w, h) * 72 * 0.04)
            page.insert_text((x0 + size * 0.4, y0 + size * 1.2), str(n), fontsize=size)
    return doc.tobytes(deflate=True)


def preview(raw, specs, store, as_map=False, show_grid=False):
    if as_map:   # the map is a PDF: rasterise its page so the stage can show it
        page = pymupdf.open(stream=migration_pdf(raw, specs, store), filetype="pdf")[0]
        z = clean(raw)["pv"] / max(page.rect.width, page.rect.height)
        return page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False).tobytes("jpeg", jpg_quality=90)
    p, im = compose(raw, specs, store)
    if show_grid:   # guide overlay, preview only: cell edges and a dot where each section will settle
        xs, ys = _grid(p, p["w"], p["h"])
        k, ink = im.width / p["w"], ImageDraw.Draw(im)
        t = max(1, im.width // 400)   # line weight follows the preview size so it stays visible when the stage scales it
        for x in xs:
            ink.line([(x * k, 0), (x * k, im.height)], fill=(255, 90, 54), width=t)
        for y in ys:
            ink.line([(0, y * k), (im.width, y * k)], fill=(255, 90, 54), width=t)
        for x, y in _cells(xs, ys):
            ink.ellipse([x * k - 2 * t, y * k - 2 * t, x * k + 2 * t, y * k + 2 * t], fill=(255, 90, 54))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _gif_items(p, specs, store):
    """Load originals at the selected animation resolution, including PDF sources."""
    lut, items, originals = tone_lut(p), [], []
    for s in specs:
        src, pg, w = _spec(s, store)
        ppi = animation_ppi(p)
        im = raster(src, pg, dpi=min(max(ppi*p['scale']*(1+p['var']),72),1200))
        originals.append(im)
        items.append((effects.grade(adjust(im, lut), p), w, w * im.height / im.width))
    return items, originals


def _gif_original(p, originals, ppi):
    """Put each unchanged source on the canvas before the collage process starts."""
    cw, ch = max(1, round(p["w"] * ppi)), max(1, round(p["h"] * ppi))
    canvas = Image.new("RGB", (cw, ch), p["bg"])
    cols = max(1, math.ceil(math.sqrt(len(originals))))
    rows = math.ceil(len(originals) / cols)
    for n, source in enumerate(originals):
        cell_w, cell_h = cw / cols, ch / rows
        im = source.copy()
        im.thumbnail((max(1, round(cell_w * .82)), max(1, round(cell_h * .82))), Image.LANCZOS)
        x = round((n % cols + .5) * cell_w - im.width / 2)
        y = round((n // cols + .5) * cell_h - im.height / 2)
        canvas.paste(im, (x, y))
    return canvas


def _gif_label(im, label):
    if im.width < 90 or im.height < 42:
        return im
    draw = ImageDraw.Draw(im)
    box = (10, 10, min(im.width - 10, 12 + len(label) * 7), 31)
    draw.rectangle(box, fill=(0, 0, 0))
    draw.text((14, 14), label, fill=(255, 255, 255))
    return im


def animation_timing(p):
    # Maintain smooth playback as duration changes, with bounded export work.
    frames = min(600, max(36, round(p['pace']*max(12, min(30, 2*p['smoothness'])))))
    return frames, frames/p['pace']


def animation_ppi(p):
    edge = max(p['w'],p['h'])*p['dpi']
    if p['anim_resolution'] != 'full':edge=min(edge,int(p['anim_resolution']))
    return edge/max(p['w'],p['h'])


def animation_size(p):
    ppi=animation_ppi(p)
    size=max(1,round(p['w']*ppi)),max(1,round(p['h']*ppi))
    if size[0]*size[1]>MAX_PIXELS:
        raise ValueError(f'{size[0]} x {size[1]} px is over the {MAX_PIXELS//10**6} MP limit; choose a smaller resolution')
    return size


def animation_pose(pieces, layer_ids, progress):
    t = max(0, min(1, progress)); t = t*t*(3-2*t)
    return [pc[:2] + tuple(pc[k+5]+(pc[k]-pc[k+5])*t for k in range(2,6))
            + (pc[6]*t,) + pc[7:] + (1 if layer == 0 else t,)
            for pc, layer in zip(pieces, layer_ids)]


def _layer_ids(p, sizes):
    counts = [0]+[len(layout(dict(p,layers=i),sizes,p['w'],p['h'])) for i in range(1,int(p['layers'])+1)]
    return [layer for layer in range(int(p['layers'])) for _ in range(counts[layer+1]-counts[layer])]


def _map_frame_fn(p, raw, specs, store):
    """progress 0..1 -> the migration map at the selected animation resolution."""
    sizes = _sizes(specs, store)
    pieces, layer_ids = layout(p, sizes, p['w'], p['h']), _layer_ids(p, sizes)

    def frame(progress):
        pose = [pc[:-1] for pc in animation_pose(pieces, layer_ids, progress)]   # drop the fade value the collage animation adds
        doc = _map_doc(raw, specs, store, (1, 2, 3), pieces=pose, doc_only=True)
        size = animation_size(p)
        z = max(size) / max(doc[0].rect.width, doc[0].rect.height)
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
        image=Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        return image if image.size==size else image.resize(size,Image.LANCZOS)
    return frame


def map_animation_frames(p, raw, specs, store):
    """The migration map animated: each line grows from its start node as the section's outline travels, turns and scales."""
    frame, (total, fps) = _map_frame_fn(p, raw, specs, store), animation_timing(p)
    lead, tail = max(1, round(.25*fps)), max(1, round(.75*fps))
    first, last, moving = frame(0), frame(1), total-lead-tail
    for _ in range(lead):
        yield first.copy()
    for i in range(moving):
        yield frame(i/max(1, moving-1))
    for _ in range(tail):
        yield last.copy()


def animation_frames(raw, specs, store, sample=False, report=None):
    """Copies separate, rotate and migrate together along one eased timeline."""
    p = clean(raw)
    report = {} if report is None else report
    report.update(renderer='cpu',reason='')
    if not specs:
        raise ValueError('add an image or PDF first')
    if p['anim'] == 'map':   # animate the migration drawing instead of the pictures
        if sample:yield _map_frame_fn(p,raw,specs,store)(.5)
        else:yield from map_animation_frames(p, raw, specs, store)
        return
    size=animation_size(p)
    ppi = animation_ppi(p)
    grain_texture = _grain_texture(p, store)
    items, originals = _gif_items(p, specs, store)
    sizes = [(w,h) for _,w,h in items]
    pieces = layout(p, sizes, p['w'], p['h'])
    layer_ids = _layer_ids(p, sizes)
    total,fps = animation_timing(p)
    lead,tail = max(1,round(.25*fps)),max(1,round(.75*fps))
    compositor=None
    if p['anim_renderer']=='gpu':
        import animation_gpu
        compositor=animation_gpu.create(size)
        report.update(renderer='gpu' if compositor is not None else 'cpu',
                      reason='' if compositor is not None else 'GPU resources unavailable for this resolution')

    def draw_frame(pose):
        nonlocal compositor
        try:return render(p,items,ppi,Image.BILINEAR,pose,grain_texture,compositor)
        except Exception as error:
            if compositor is None:raise
            import logging
            logging.getLogger(__name__).warning('GPU failed during rendering; continuing on CPU: %s',error)
            try:compositor.close()
            except Exception:pass
            compositor=None
            report.update(renderer='cpu',reason='GPU failed during rendering; using CPU')
            return render(p,items,ppi,Image.BILINEAR,pose,grain_texture)
    try:
        if sample:
            yield draw_frame(animation_pose(pieces,layer_ids,.5))
            return
        original = _gif_original(p, originals, ppi)
        for _ in range(lead):yield original.copy()
        moving = total-lead-tail
        for i in range(moving):
            progress = i/max(1,moving-1)
            frame = draw_frame(animation_pose(pieces,layer_ids,progress))
            fade = min(1,progress/.12);fade = fade*fade*(3-2*fade)
            yield Image.blend(original,frame,fade) if fade<1 else frame
        final = draw_frame(pieces)
        for _ in range(tail):yield final.copy()
    finally:
        if compositor is not None:compositor.close()


def process_gif(raw, specs, store):
    from PIL import GifImagePlugin
    p = clean(raw)
    if max(animation_size(p))>65535:raise ValueError('GIF dimensions must fit within 65535 pixels; choose a smaller resolution')
    count, fps = animation_timing(p)
    # Shared palette avoids color flicker between independently quantized frames.
    if p['anim'] == 'map':
        frame = _map_frame_fn(dict(p,anim_resolution='720'), raw, specs, store)
        samples = [frame(t) for t in (0, .5, 1)]
    else:
        items, originals = _gif_items(dict(p,anim_resolution='720'), specs, store)
        preview = render(p,items,720/max(p['w'],p['h']),Image.BILINEAR,grain_texture=_grain_texture(p,store))
        samples = originals+[preview]
    atlas = Image.new('RGB',(128*len(samples),128))
    for i,sample in enumerate(samples):
        atlas.paste(sample.convert('RGB').resize((128,128)),(128*i,0))
    palette = atlas.quantize(colors=256)
    # Stream indexed frames: full resolution must not require an entire movie in RAM.
    buf=io.BytesIO()
    with closing(animation_frames(raw,specs,store)) as frames:
        for i,im in enumerate(frames):
            indexed=im.quantize(palette=palette,dither=Image.Dither.NONE)
            if i==0:
                header,_=GifImagePlugin.getheader(indexed,info={'loop':0})
                for block in header:buf.write(block)
            duration=max(10,(round((i+1)*100/fps)-round(i*100/fps))*10)
            for block in GifImagePlugin.getdata(indexed,duration=duration,disposal=2):buf.write(block)
    buf.write(b';')
    return buf.getvalue()


def process_mp4(raw, specs, store):
    import imageio_ffmpeg
    p = clean(raw)
    _, fps = animation_timing(p)
    codec='libx264'
    if p['anim_renderer']=='gpu':
        import animation_gpu
        codec=animation_gpu.video_encoder()
    try:return _process_mp4(raw,specs,store,codec,fps)
    except (OSError,RuntimeError):
        if codec=='libx264':raise
        return _process_mp4(raw,specs,store,'libx264',fps)


def _process_mp4(raw,specs,store,codec,fps):
    import imageio_ffmpeg
    with tempfile.TemporaryDirectory(prefix='collage-video-') as folder:
        path = Path(folder) / 'collage-process.mp4'
        writer = None
        try:
            for im in animation_frames(raw, specs, store):
                size = (max(2, im.width + im.width % 2), max(2, im.height + im.height % 2))
                if im.size != size:
                    im = ImageOps.expand(im,(0,0,size[0]-im.width,size[1]-im.height),fill=clean(raw)['bg'])
                if writer is None:
                    writer = imageio_ffmpeg.write_frames(str(path), size, fps=fps, codec=codec,
                        pix_fmt_in='rgb24', pix_fmt_out='yuv420p', macro_block_size=1,
                        output_params=['-movflags', '+faststart'], ffmpeg_log_level='error')
                    writer.send(None)
                writer.send(im.tobytes())
        finally:
            if writer is not None:
                writer.close()
        data=path.read_bytes()
        if len(data)<100:raise RuntimeError('Video encoder produced no output')
        return data


def animation_estimate(raw,specs,store,fmt):
    if fmt not in ('gif','mp4'):raise ValueError('Choose GIF or MP4')
    p=clean(raw);size=animation_size(p);frames,fps=animation_timing(p)
    import animation_gpu
    status=animation_gpu.capabilities() if p['anim_renderer']=='gpu' else None
    renderer='gpu' if status and status['available'] and p['anim']=='collage' else 'cpu'
    reason='' if not status or status['available'] else status['reason']
    if renderer=='gpu':
        probe=animation_gpu.create(size)
        if probe is None:renderer='cpu';reason='Selected resolution exceeds available GPU resources'
        else:probe.close()
    selected=dict(raw,anim_renderer=renderer)
    start=time.perf_counter()
    report={}
    with closing(animation_frames(selected,specs,store,sample=True,report=report)) as sample:
        image=next(sample)
    if renderer=='gpu' and report['renderer']=='cpu':renderer='cpu';reason=report['reason']
    # Include the actual per-frame palette work in GIF estimates.
    if fmt=='gif':image.quantize(colors=256)
    elapsed=max(.001,time.perf_counter()-start)
    codec=animation_gpu.video_encoder() if fmt=='mp4' and p['anim_renderer']=='gpu' else 'libx264'
    seconds=elapsed*frames
    return dict(width=size[0]+(size[0]%2 if fmt=='mp4' else 0),height=size[1]+(size[1]%2 if fmt=='mp4' else 0),
        frames=frames,fps=fps,seconds_low=max(1,seconds*.6),seconds_high=max(2,seconds*1.8),
        approximate=True,renderer=renderer,encoder=codec if fmt=='mp4' else 'GIF (CPU)',reason=reason)


def _triptych_panels(raw, specs, store):
    p = clean(raw)
    dpi = p['dpi']
    width, height = max(1, round(p['w']*dpi)), max(1, round(p['h']*dpi))
    gap = max(1, round(.15*dpi))
    if (3*width+2*gap)*height > MAX_PIXELS:
        raise ValueError('triptych is over the 400 MP limit; reduce size or DPI')
    _, composed = compose(raw, specs, store, final=True)
    originals = []
    for s in specs:
        src, pg, _ = _spec(s, store)
        originals.append(raster(src,pg,dpi=min(dpi,600)))
    original = _gif_original(p, originals, dpi)
    return p,dpi,width,height,gap,original,composed


def triptych(raw, specs, store):
    """Original sources, final collage and styled migration map as three equal panels."""
    p,dpi,width,height,gap,original,composed=_triptych_panels(raw,specs,store)
    with pymupdf.open(stream=migration_pdf(raw,specs,store), filetype='pdf') as doc:
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(dpi/72,dpi/72),alpha=False)
        migration = Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    if migration.size != composed.size:
        migration = migration.resize(composed.size,Image.LANCZOS)
    result = Image.new('RGB',(3*width+2*gap,height),p['bg'])
    for i, panel in enumerate((original,composed,migration)):
        result.paste(panel,(i*(width+gap),0))
    buf = io.BytesIO()
    result.save(buf,'PNG',dpi=(round(dpi),round(dpi)),compress_level=3)
    return buf.getvalue()


def triptych_pdf(raw,specs,store):
    """One PDF page: two DPI-sized image panels and the original vector map."""
    p,dpi,width,height,gap,original,composed=_triptych_panels(raw,specs,store)
    scale=72/dpi
    with pymupdf.open() as doc:
        page=doc.new_page(width=(3*width+2*gap)*scale,height=height*scale)
        page.draw_rect(page.rect,color=None,fill=_rgb(p['bg']))
        for i,image in enumerate((original,composed)):
            left=i*(width+gap)*scale
            rect=pymupdf.Rect(left,0,left+width*scale,height*scale)
            page.insert_image(rect,pixmap=pymupdf.Pixmap(pymupdf.csRGB,image.width,image.height,image.tobytes(),False))
        left=2*(width+gap)*scale;rect=pymupdf.Rect(left,0,left+width*scale,height*scale)
        page.draw_rect(rect,color=None,fill=(1,1,1))
        with pymupdf.open(stream=migration_pdf(raw,specs,store),filetype='pdf') as migration:
            page.show_pdf_page(rect,migration,0,keep_proportion=False)
        return doc.tobytes(deflate=True)


def settings_text(raw, specs, store, lines=False):
    p = clean(raw)
    p.pop('pv',None)  # transient screen-preview resolution is not an edit
    sources = []
    for spec in specs:
        src, page, width = _spec(spec,store)
        sources.append({'name':src.name,'width_inches':width,'page':page+1})
    unit = raw.get('unit','in')
    document = {'format':'morphaic settings','schema_version':1,
                'units':unit if unit in ('in','cm','mm') else 'in',
                'parameters':p,'guides':{'grid_visible':bool(raw.get('grid_visible'))},
                'portion_linework':bool(lines),'sources':sources}
    if isinstance(raw.get('luminosity'), dict):
        document['luminosity'] = raw['luminosity']
    return (json.dumps(document,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


def export(raw, specs, store, fmt, lines=False):
    """-> (file bytes, file name). fmt: png / tif / pdf / gif, or map for the migration map (one vector PDF, the drawing the stage shows).
    Map exports are always one file. Other exports may bundle portion linework when lines=True."""
    if fmt not in ("png", "tif", "pdf", "gif", "mp4", "map", "triptych", "txt"):
        raise ValueError(f"unknown format {fmt!r}")
    stem = "collage-map-process" if clean(raw)["anim"] == "map" else "collage-process"   # what a GIF / MP4 shows
    if fmt=='txt':
        return settings_text(raw,specs,store,lines), 'collage-settings.txt'
    if fmt=='map':
        # Map exports are exactly one drawing; old portion-linework settings never bundle extras.
        p=clean(raw)
        data=migration_pdf(raw,specs,store)
        if p['map_file']=='pdf':return data,'collage-map.pdf'
        dpi=round(p['dpi']);size=max(1,round(p['w']*dpi)),max(1,round(p['h']*dpi))
        if size[0]*size[1]>MAX_PIXELS:raise ValueError('Map raster exceeds the 400 MP limit; lower the DPI or canvas size')
        with pymupdf.open(stream=data,filetype='pdf') as doc:
            pix=doc[0].get_pixmap(dpi=dpi,alpha=False)
            image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        if image.size!=size:image=image.resize(size,Image.LANCZOS)
        buf=io.BytesIO()
        if p['map_file']=='png':image.save(buf,'PNG',dpi=(dpi,dpi),compress_level=3)
        else:image.save(buf,'TIFF',dpi=(dpi,dpi),compression='tiff_adobe_deflate')
        return buf.getvalue(),'collage-map.'+p['map_file']
    if fmt in ('gif','mp4') and clean(raw)['anim']=='map':lines=False
    if fmt=='triptych':
        if clean(raw)['triptych_file']=='pdf':return triptych_pdf(raw,specs,store),'collage-triptych.pdf'
        return triptych(raw,specs,store),'collage-triptych.png'
    extra = portions_pdf(raw, specs, store) if lines else None   # cheap, so a bad request fails before the big render
    if fmt == "gif":
        files = {f"{stem}.gif": process_gif(raw, specs, store)}
    elif fmt == 'mp4':
        files = {f'{stem}.mp4': process_mp4(raw, specs, store)}
    else:
        p, im = compose(raw, specs, store, final=True)
        dpi, buf = round(p["dpi"]), io.BytesIO()
        if fmt == "png":
            im.save(buf, "PNG", dpi=(dpi, dpi), compress_level=3)
        elif fmt == "tif":
            im.save(buf, "TIFF", dpi=(dpi, dpi), compression="tiff_adobe_deflate")
        else:   # lossless Flate image on a page of the exact physical size
            doc = pymupdf.open()
            page = doc.new_page(width=p["w"] * 72, height=p["h"] * 72)
            page.insert_image(page.rect, pixmap=pymupdf.Pixmap(pymupdf.csRGB, im.width, im.height, im.tobytes(), False))
            buf.write(doc.tobytes(deflate=True))
        files = {f"collage.{fmt}": buf.getvalue()}
    if extra:
        files["collage-portions.pdf"] = extra
    if len(files) == 1:
        (name, data), = files.items()
        return data, name
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:   # stored, not deflated: PNG/TIFF/PDF are already compressed
        for name, data in files.items():
            z.writestr(name, data)
    return zbuf.getvalue(), "collage.zip"
