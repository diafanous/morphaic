"""Shared cut stencils for raster pieces and vector migration outlines."""
import hashlib
import math

from PIL import Image, ImageDraw

NAMES = ('rectangle', 'ellipse', 'triangle', 'diamond', 'hexagon', 'star', 'heart', 'custom')
NODE_STYLES = ('none', 'dot', 'ring', 'square', 'plus', 'arrow', 'cut')


def clean(raw):
    weights = raw.get('shape_weights', {'rectangle': 100})
    if not isinstance(weights, dict):
        raise ValueError('cut shape shares must be an object')
    weights = {key: float(weights.get(key, 0)) for key in NAMES}
    if any(not math.isfinite(value) or not 0 <= value <= 100 for value in weights.values()):
        raise ValueError('cut shape shares must be between 0 and 100')
    points = raw.get('custom_shape', [])
    if not isinstance(points, list):
        raise ValueError('custom cut must be a list of points')
    custom = []
    for x, y in points[:512]:
        x, y = float(x), float(y)
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError('custom cut points must be finite')
        custom.append((min(1, max(0, x)), min(1, max(0, y))))
    if weights['custom'] and len(custom) < 3:
        raise ValueError('draw a custom stencil before using it')
    if sum(weights.values()) <= 0:
        weights['rectangle'] = 100
    total = sum(weights.values())
    if total > 100 + 1e-8:
        raise ValueError('cut shape percentages cannot exceed 100%')
    weights['rectangle'] += max(0, 100 - total)
    selected = raw.get('cut_shape', 'rectangle')
    if selected not in NAMES or selected == 'custom' and len(custom) < 3:
        selected = 'rectangle'
    styles = raw.get('node_end_shapes', {})
    if not isinstance(styles, dict):
        styles = {}
    return dict(cut_shape=selected, multi_shape=bool(raw.get('multi_shape', False)),
                shape_weights=weights, shape_locks={key:bool((raw.get('shape_locks') or {}).get(key,False)) for key in NAMES} if isinstance(raw.get('shape_locks'),dict) else {}, custom_shape=custom, stencil_name=str(raw.get('stencil_name', '')).strip()[:80], node_by_shape=bool(raw.get('node_by_shape', False)),
                node_end_shapes={key: value for key, value in styles.items() if key in NAMES and value in NODE_STYLES})


def stencil(raw):
    name = ' '.join(str(raw.get('name', '')).split())
    if not name or len(name) > 80:
        raise ValueError('give the stencil a name of 1 to 80 characters')
    points = clean({'custom_shape': raw.get('points', [])})['custom_shape']
    if len(points) < 3:
        raise ValueError('a stencil needs at least three points')
    area = abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points, points[1:]+points[:1]))) / 2
    if area < 1e-6:
        raise ValueError('the stencil needs an outline with area')
    return {'name': name, 'points': points}


def shape_for(p, pc):
    if not p.get('multi_shape'):
        return p.get('cut_shape', 'rectangle')
    # Independent of motion, output resolution, and layer z-order.
    seed = repr((int(p['seed']), pc[0], pc[1])).encode()
    value = int.from_bytes(hashlib.blake2b(seed, digest_size=8).digest(), 'big') / 2**64
    weights = p['shape_weights']
    target = value * sum(weights.values())
    total = 0
    for name in NAMES:
        total += weights[name]
        if target < total:
            return name
    return 'rectangle'


def polygon(name, custom=()):
    if name == 'rectangle':
        return [(0, 0), (1, 0), (1, 1), (0, 1)]
    if name == 'triangle':
        return [(0.5, 0), (1, 1), (0, 1)]
    if name == 'diamond':
        return [(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)]
    if name == 'custom':
        return list(custom)
    if name == 'heart':
        pts = []
        for i in range(96):
            t = i * 2 * math.pi / 96
            x = 16 * math.sin(t)**3
            y = 13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t)
            pts.append((0.5 + x / 32, (12 - y) / 29))
        return pts
    n = {'ellipse': 64, 'hexagon': 6, 'star': 10}[name]
    return [(0.5 + (0.22 if name == 'star' and i % 2 else 0.5)*math.cos(i*2*math.pi/n-math.pi/2),
             0.5 + (0.22 if name == 'star' and i % 2 else 0.5)*math.sin(i*2*math.pi/n-math.pi/2)) for i in range(n)]


def mask(name, custom, size):
    factor = 3 if max(size) <= 1024 else 1
    w, h = size[0]*factor, size[1]*factor
    im = Image.new('L', (w, h), 0)
    draw = ImageDraw.Draw(im)
    if name == 'ellipse':
        draw.ellipse((0, 0, w-1, h-1), fill=255)
    else:
        draw.polygon([(x*(w-1), y*(h-1)) for x, y in polygon(name, custom)], fill=255)
    return im.resize(size, Image.Resampling.LANCZOS) if factor > 1 else im


def outline(p, pc, initial=False, size=None):
    cx, cy, w, h, angle = (*pc[7:11], 0) if initial else (*pc[2:6], pc[6])
    if size is not None:
        w = h = size
    s, c = math.sin(math.radians(angle)), math.cos(math.radians(angle))
    points = []
    for x, y in polygon(shape_for(p, pc), p.get('custom_shape', [])):
        x, y = (x - 0.5)*w, (y - 0.5)*h
        points.append((cx + x*c + y*s, cy - x*s + y*c))
    return points + points[:1]


def end_style(p, pc):
    return p.get('node_end_shapes', {}).get(shape_for(p, pc), p['node_end']) if p.get('node_by_shape') else p['node_end']


def counts(p, pieces):
    result = {name: 0 for name in NAMES}
    for pc in pieces:
        result[shape_for(p, pc)] += 1
    return result
