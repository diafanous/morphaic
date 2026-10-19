"""Color and grain effects shared by the preview, still and process renderers.

Color edits operate on source RGB before cutting; alpha is never graded. Grain is
applied to the assembled canvas. Its lattice is anchored in inches (one grain-size
unit is one pixel at 300 DPI), so changing export DPI does not change its scale.
"""
import math
import re

import numpy as np
from PIL import Image, ImageEnhance, ImageStat


SPEC = dict(exposure=(-3, 3, 0), temperature=(-1, 1, 0), tint=(-1, 1, 0),
            saturation=(0, 2, 1), grain=(0, 1, 0), grain_size=(.25, 8, 1),
            grain_dpi=(1, 9600, 300), gradient_amount=(0, 1, 0))
DEFAULT_STOPS = ({'position': 0, 'color': '#000000'}, {'position': 1, 'color': '#ffffff'})


def number(value, lo, hi, default):
    """Untrusted form/settings numbers must be finite before they reach Pillow."""
    try:
        value = float(value)
        return min(max(value, lo), hi) if math.isfinite(value) else default
    except (TypeError, ValueError, OverflowError):
        return default


def clean(raw):
    p = {key: number(raw.get(key), lo, hi, default) for key, (lo, hi, default) in SPEC.items()}
    source = raw.get('grain_source_id', '')
    p['grain_source_id'] = source if isinstance(source, str) and re.fullmatch(r'[a-zA-Z0-9_-]{0,128}', source) else ''
    name = raw.get('grain_source_name', '')
    p['grain_source_name'] = re.sub(r'[\x00-\x1f\x7f]', '', name).strip()[:255] if isinstance(name, str) else ''
    stops = raw.get('gradient_stops')
    valid = {}
    for stop in stops[:16] if isinstance(stops, list) else []:
        if not isinstance(stop, dict) or not isinstance(stop.get('color'), str):
            continue
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', stop['color']):
            continue
        try:
            position = float(stop.get('position'))
        except (ValueError, TypeError, OverflowError):
            continue
        if math.isfinite(position):
            valid[min(1, max(0, position))] = stop['color'].lower()
    if not valid:
        p['gradient_stops'] = [dict(stop) for stop in DEFAULT_STOPS]
    else:
        p['gradient_stops'] = [{'position': position, 'color': color} for position, color in sorted(valid.items())]
    return p


def gradient_lut(stops):
    """A luminance lookup with linear RGB interpolation and clamped end colors."""
    stops = [(s['position'], tuple(int(s['color'][i:i+2], 16) for i in (1, 3, 5))) for s in stops]
    lut, index = [], 0
    for level in range(256):
        t = level / 255
        while index + 1 < len(stops) and stops[index + 1][0] < t:
            index += 1
        a, ca = stops[index]
        b, cb = stops[min(index+1, len(stops)-1)]
        weight = min(1, max(0, (t-a)/(b-a))) if b > a else 0
        lut.append(tuple(round(x + (y-x)*weight) for x, y in zip(ca, cb)))
    return [rgb[channel] for channel in range(3) for rgb in lut]


def grade(im, p):
    """Exposure in linear-light stops, warm/cool, green/magenta, saturation, map."""
    exposure, temperature, tint = p['exposure'], p['temperature'], p['tint']
    if exposure == temperature == tint == 0 and p['saturation'] == 1 and p['gradient_amount'] == 0:
        return im
    alpha = im.getchannel('A') if im.mode == 'RGBA' else None
    rgb = im.convert('RGB') if im.mode != 'RGB' else im
    if exposure or temperature or tint:
        tables = []
        for balance in (.65*temperature + .2*tint, -.4*tint, -.65*temperature + .2*tint):
            gain = 2 ** (exposure + balance)
            for level in range(256):
                encoded = level / 255
                linear = encoded / 12.92 if encoded <= .04045 else ((encoded + .055)/1.055) ** 2.4
                linear = min(1, max(0, linear*gain))
                value = linear*12.92 if linear <= .0031308 else 1.055*linear**(1/2.4)-.055
                tables.append(round(value*255))
        rgb = rgb.point(tables)
    if p['saturation'] != 1:
        rgb = ImageEnhance.Color(rgb).enhance(p['saturation'])
    if p['gradient_amount']:
        mapped = rgb.convert('L').point(gradient_lut(p['gradient_stops']), mode='RGB')
        rgb = mapped if p['gradient_amount'] == 1 else Image.blend(rgb, mapped, p['gradient_amount'])
    if alpha is not None:
        rgb = rgb.convert('RGBA')
        rgb.putalpha(alpha)
    return rgb


def texture(im):
    """Bounded custom texture with zero mean; transparent pixels are neutral."""
    im = im.copy()
    im.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    luminance = im.convert('L')
    if im.mode == 'RGBA':
        neutral = Image.new('L', im.size, 128)
        neutral.paste(luminance, (0, 0), im.getchannel('A'))
        luminance = neutral
    mean = ImageStat.Stat(luminance).mean[0]
    return (np.asarray(luminance, dtype=np.float32) - mean) / 127.5


def _noise(x, y, seed):
    """Stateless integer hash: identical coordinates always have identical grain."""
    value = (x.astype(np.uint32)*np.uint32(374761393) + y.astype(np.uint32)*np.uint32(668265263)
             + np.uint32((seed*1442695041) & 0xffffffff))
    value = (value ^ (value >> 13))*np.uint32(1274126177)
    value ^= value >> 16
    return value.astype(np.float32)*(2.0/4294967295.0)-1


def grain(im, p, ppi, custom=None):
    """Add monochrome grain in bounded strips without a full-size float image.

    Fine grain is attenuated below a screen pixel to avoid preview moire. Imported
    textures repeat; procedural grain is non-repeating and derived from the seed.
    Both preserve alpha and favor midtones over clipped highlights and shadows.
    """
    amount = p['grain']
    if not amount:
        return im
    pitch = p['grain_size']*ppi/(p['grain_dpi'] if custom is not None else 300)
    if isinstance(custom, tuple):
        custom, scale = custom
        pitch *= scale
    strength = 64*amount*min(1, math.sqrt(pitch))
    seed = int(p['seed'])
    x = (np.arange(im.width, dtype=np.float64)+.5)/pitch-.5
    ix = np.floor(x).astype(np.int64)[None, :]
    fx = (x-np.floor(x)).astype(np.float32)[None, :]
    if custom is not None:
        ix += seed*53
        th, tw = custom.shape

        def sample(a, b):
            return custom[b % th, a % tw]
    else:
        def sample(a, b):
            return _noise(a, b, seed)
    output = im.copy()
    rows = max(1, min(128, 262144//im.width))
    for top in range(0, im.height, rows):
        bottom = min(im.height, top+rows)
        y = (np.arange(top, bottom, dtype=np.float64)+.5)/pitch-.5
        iy = np.floor(y).astype(np.int64)[:, None]
        fy = (y-np.floor(y)).astype(np.float32)[:, None]
        if custom is not None:
            iy += seed*97
        noise = ((sample(ix, iy)*(1-fx)+sample(ix+1, iy)*fx)*(1-fy)
                 +(sample(ix, iy+1)*(1-fx)+sample(ix+1, iy+1)*fx)*fy)
        box = (0, top, im.width, bottom)
        pixels = np.asarray(im.crop(box)).copy()
        rgb = pixels[:, :, :3].astype(np.float32)
        light = rgb[:, :, 0]*.299 + rgb[:, :, 1]*.587 + rgb[:, :, 2]*.114
        weight = .25+.75*(1-np.abs(light/127.5-1))
        rgb += (noise*weight*strength)[:, :, None]
        pixels[:, :, :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
        output.paste(Image.fromarray(pixels), (0, top))
    return output
