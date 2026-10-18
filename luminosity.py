"""Grayscale height maps and closed relief meshes. All model coordinates are mm."""
import base64
import io
import math
import os
import struct
from collections.abc import Sequence

import numpy as np
from PIL import Image, ImageFilter

import collage
import mounting

MAX_MAP_PIXELS = 16_000_000
# Exports reserve headroom for the rest of the app and the operating system.
# This is a resource check, not a quality ceiling: larger machines can export
# larger models without changing an arbitrary vertex limit.
MEMORY_FRACTION = 0.6
STL_CHUNK_FACES = 32_768
SPEC = dict(width_mm=(1, 5000, 100), height_mm=(1, 5000, 100),
            relief_mm=(0, 100, 10), base_mm=(0.1, 50, 2),
            spacing_mm=(0.01, 20, 0.5), gamma=(0.2, 5, 1),
            contrast=(0.1, 4, 1), smooth_mm=(0, 10, 0))


class PackedTriples(Sequence):
    """Compact mesh storage with tuple rows for the existing mesh consumers.

    Export meshes avoid millions of Python tuples, floats and integer objects.
    NumPy/Manifold consume the backing array directly; preview still returns
    ordinary JSON-compatible lists.
    """

    def __init__(self, values):
        self.values = values

    def __len__(self):
        return len(self.values)

    def __getitem__(self, key):
        value = self.values[key]
        return value.tolist() if isinstance(key, slice) else tuple(value.tolist())

    def __iter__(self):
        for row in self.values:
            yield tuple(row.tolist())

    def __array__(self, dtype=None, copy=None):
        result = np.asarray(self.values, dtype=dtype)
        return result.copy() if copy else result


def available_memory():
    """Available physical RAM, when the host exposes it (Windows and POSIX)."""
    if os.name == 'nt':
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                        ('total_physical', ctypes.c_ulonglong),
                        ('available_physical', ctypes.c_ulonglong),
                        ('total_pagefile', ctypes.c_ulonglong),
                        ('available_pagefile', ctypes.c_ulonglong),
                        ('total_virtual', ctypes.c_ulonglong),
                        ('available_virtual', ctypes.c_ulonglong),
                        ('extended_virtual', ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.available_physical
    else:
        try:
            return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
        except (ValueError, OSError, AttributeError):
            pass
    return None


def mesh_estimate(p, fmt=None):
    """Counts, binary STL size and conservative peak working-memory estimate.

    Counts are exact for the plain relief; mounting adds topology. The estimate
    includes height-map conversion, packed mesh arrays, export buffers, and
    larger conversion/boolean working space for 3DM and mounting.
    """
    nx = math.ceil(p['width_mm'] / p['spacing_mm']) + 1
    ny = math.ceil(p['height_mm'] / p['spacing_mm']) + 1
    vertices = nx * ny + 2 * nx + 2 * ny - 3
    faces = 2 * vertices - 4
    binary_bytes = 84 + 50 * faces
    # RGB/grayscale image conversion, float64 vertices and uint32 faces.
    memory = 24 * vertices + 12 * faces + 16 * nx * ny
    if fmt == 'stl':
        # A binary facet is 50 bytes; ASCII can be substantially larger.
        memory += binary_bytes if p['encoding'] == 'binary' else 400 * faces
    elif fmt == '3dm':
        # Rhino mesh objects, encoded/base64 result and its decoded copy.
        memory += 320 * vertices + 80 * faces
    if p['cleat']:
        # Boolean geometry and mounting's separate parts/combined Python lists.
        memory += 700 * vertices + 300 * faces
    return dict(grid=[nx, ny], vertices=vertices, triangles=faces,
                binary_stl_bytes=binary_bytes,
                estimated_memory_bytes=memory + 16 * 1024**2)


def check_resources(p, fmt=None):
    estimate = mesh_estimate(p, fmt)
    if estimate['vertices'] > np.iinfo(np.uint32).max or (fmt == 'stl' and estimate['triangles'] > 0xffffffff):
        raise ValueError('mesh exceeds the 32-bit mesh/STL index range; increase mesh spacing in mm or reduce model size')
    available = available_memory()
    if available and estimate['estimated_memory_bytes'] > available * MEMORY_FRACTION:
        needed = estimate['estimated_memory_bytes'] / 1024**3
        budget = available * MEMORY_FRACTION / 1024**3
        size = estimate['binary_stl_bytes'] / 1024**3
        raise ValueError(f'mesh needs approximately {needed:.2f} GiB of working memory '
                         f'({budget:.2f} GiB available export budget); '
                         f'plain binary STL would be {size:.2f} GiB. '
                         'Close other apps, increase mesh spacing in mm or reduce model size')
    return estimate


def demo_image():
    """A small local ripple image for trying the viewer without importing a file."""
    w, h = 480, 360
    im = Image.new('L', (w, h))
    pixels = []
    for y in range(h):
        for x in range(w):
            u, v = (x / (w-1) - .5)*3, (y / (h-1) - .5)*2.25
            r = math.hypot(u+.3, v-.1)
            z = .5 + .25*math.cos(10*r)*math.exp(-r*r/2) + .2*math.sin(3*u)*math.cos(3*v)
            pixels.append(round(min(1,max(0,z))*255))
    im.putdata(pixels)
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


def clean(raw):
    p = {}
    for key, (lo, hi, default) in SPEC.items():
        value = float(raw.get(key, default))
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f'{key} must be between {lo} and {hi}')
        p[key] = value
    p['invert'] = bool(raw.get('invert', False))
    p['source'] = raw.get('source', 'collage')
    if p['source'] not in ('collage', 'import'):
        raise ValueError('choose current collage or imported image')
    p['source_id'] = str(raw.get('source_id', ''))
    p['encoding'] = raw.get('encoding', 'binary')
    if p['encoding'] not in ('ascii', 'binary'):
        raise ValueError('STL encoding must be ascii or binary')
    p.update(mounting.clean(raw))
    return p


def grid_size(p, preview=False):
    nx = math.ceil(p['width_mm'] / p['spacing_mm']) + 1
    ny = math.ceil(p['height_mm'] / p['spacing_mm']) + 1
    if preview:
        # Keep the live viewer responsive; preserve the chosen quality in exports.
        ratio = max(1, (nx - 1) / 80, (ny - 1) / 80)
        return max(2, math.ceil((nx - 1) / ratio) + 1), max(2, math.ceil((ny - 1) / ratio) + 1)
    check_resources(p)
    return nx, ny


def source_image(raw, specs, store, p, size):
    if p['source'] == 'import':
        if p['source_id'] not in store:
            raise ValueError('import an image for the luminosity map first')
        src = store[p['source_id']]
        if src.pdf:
            raise ValueError('the luminosity import must be an image')
        im = collage.raster(src)
    else:
        # Render enough pixels for the requested map, independently of print DPI.
        cp = collage.clean(raw)
        _, im = collage.compose(cp, specs, store, final=True, long_edge=max(size))
    if im.mode == 'RGBA':
        paper = Image.new('RGBA', im.size, 'white')
        im = Image.alpha_composite(paper, im)
    return im.convert('RGB').resize(size, Image.Resampling.LANCZOS)


def height_map(raw, specs, store, p, size):
    im = source_image(raw, specs, store, p, size)
    # Rec.709 weights on the source's 8-bit RGB values; white is highest by default.
    im = im.convert('L', (0.2126, 0.7152, 0.0722, 0))
    radius = p['smooth_mm'] * ((size[0] / p['width_mm'] + size[1] / p['height_mm']) / 2)
    if radius:
        im = im.filter(ImageFilter.GaussianBlur(radius))
    lut = []
    for value in range(256):
        value = min(1, max(0, (value / 255 - 0.5) * p['contrast'] + 0.5)) ** (1 / p['gamma'])
        lut.append(round(255 * (1 - value if p['invert'] else value)))
    return im.point(lut)


def mesh(raw, specs, store, options, preview=False):
    p = clean(options)
    nx, ny = grid_size(p, preview)
    im = height_map(raw, specs, store, p, (nx, ny))
    perimeter_count = 2 * nx + 2 * ny - 4
    vertex_count = nx * ny + perimeter_count + 1
    vertices = np.empty((vertex_count, 3), dtype=np.float64)
    faces = np.empty((2 * vertex_count - 4, 3), dtype=np.uint32)
    surface = vertices[:nx * ny].reshape(ny, nx, 3)
    surface[:, :, 0] = np.linspace(0, p['width_mm'], nx)[None, :]
    surface[:, :, 1] = np.linspace(0, p['height_mm'], ny)[:, None]
    surface[:, :, 2] = p['base_mm'] + np.asarray(im)[::-1] * (p['relief_mm'] / 255)
    columns = np.arange(nx - 1, dtype=np.uint32)
    for y in range(0, ny - 1, 128):
        end = min(y + 128, ny - 1)
        a = (np.arange(y, end, dtype=np.uint32)[:, None] * nx + columns).ravel()
        triangles = faces[2*y*(nx-1):2*end*(nx-1)].reshape(-1, 2, 3)
        triangles[:, 0, 0], triangles[:, 0, 1], triangles[:, 0, 2] = a, a + 1, a + nx + 1
        triangles[:, 1, 0], triangles[:, 1, 1], triangles[:, 1, 2] = a, a + nx + 1, a + nx
    # Counterclockwise perimeter, duplicate it at z=0, then close walls and base.
    perimeter = np.concatenate((np.arange(nx, dtype=np.uint32),
                                np.arange(1, ny, dtype=np.uint32) * nx + nx - 1,
                                (ny - 1) * nx + np.arange(nx - 2, -1, -1, dtype=np.int64),
                                np.arange(ny - 2, 0, -1, dtype=np.uint32) * nx)).astype(np.uint32)
    start, center = nx * ny, vertex_count - 1
    vertices[start:center, :2] = vertices[perimeter, :2]
    vertices[start:center, 2] = 0
    vertices[center] = (p['width_mm'] / 2, p['height_mm'] / 2, 0)
    a, b = perimeter, np.roll(perimeter, -1)
    c = np.arange(start, center, dtype=np.uint32)
    d = np.roll(c, -1)
    walls = faces[2*(nx-1)*(ny-1):].reshape(-1, 3, 3)
    walls[:, 0, 0], walls[:, 0, 1], walls[:, 0, 2] = a, c, d
    walls[:, 1, 0], walls[:, 1, 1], walls[:, 1, 2] = a, d, b
    walls[:, 2, 0], walls[:, 2, 1], walls[:, 2, 2] = center, d, c
    model = dict(vertices=vertices.tolist() if preview else PackedTriples(vertices),
                faces=faces.tolist() if preview else PackedTriples(faces), units='mm', grid=[nx, ny],
                width_mm=p['width_mm'], height_mm=p['height_mm'],
                depth_mm=p['base_mm'] + p['relief_mm'], preview=preview)
    return mounting.apply(model,p,preview)


def normal(a, b, c):
    u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
    n = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
    length = math.sqrt(sum(x*x for x in n)) or 1
    return tuple(x / length for x in n)


def stl(model, encoding):
    vertices, faces = model['vertices'], model['faces']
    buf = io.BytesIO()
    if encoding == 'binary':
        if len(faces) > 0xffffffff:
            raise ValueError('binary STL cannot contain more than 4,294,967,295 triangles')
        buf.write(b'morphaic luminosity relief; coordinates in millimeters'.ljust(80, b'\0'))
        buf.write(struct.pack('<I', len(faces)))
        points = np.asarray(vertices, dtype=np.float64)
        indices = np.asarray(faces, dtype=np.uint32)
        dtype = np.dtype([('normal', '<f4', (3,)), ('vertices', '<f4', (3, 3)), ('attribute', '<u2')])
        for offset in range(0, len(faces), STL_CHUNK_FACES):
            triangles = points[indices[offset:offset + STL_CHUNK_FACES]]
            normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            lengths = np.linalg.norm(normals, axis=1)
            normals /= np.where(lengths > 0, lengths, 1)[:, None]
            records = np.zeros(len(triangles), dtype=dtype)
            records['normal'], records['vertices'] = normals, triangles
            buf.write(records.tobytes())
    else:
        buf.write(b'solid morphaic_mm\n')
        for face in faces:
            a, b, c = [vertices[i] for i in face]
            line = '  facet normal ' + ' '.join(f'{v:.9g}' for v in normal(a, b, c)) + '\n    outer loop\n'
            for vertex in (a, b, c):
                line += '      vertex ' + ' '.join(f'{v:.9g}' for v in vertex) + '\n'
            buf.write((line + '    endloop\n  endfacet\n').encode('ascii'))
        buf.write(b'endsolid morphaic_mm\n')
    return buf.getvalue()


def three_dm(model):
    import rhino3dm
    doc = rhino3dm.File3dm()
    doc.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Millimeters
    doc.Settings.ModelAbsoluteTolerance = 0.001
    for part in model.get('parts',[dict(name='morphaic luminosity relief (mm)',vertices=model['vertices'],faces=model['faces'])]):
        shape = rhino3dm.Mesh()
        for vertex in part['vertices']:
            shape.Vertices.Add(*vertex)
        for face in part['faces']:
            shape.Faces.AddFace(*face)
        shape.Normals.ComputeNormals()
        shape.Compact()
        attributes = rhino3dm.ObjectAttributes()
        attributes.Name = part['name']
        attributes.SetUserString('morphaic mounting',str(model.get('mounting',{})))
        doc.Objects.AddMesh(shape, attributes)
    return base64.b64decode(doc.Encode())


def export(raw, specs, store, options, fmt):
    if fmt not in ('stl', '3dm', 'png', 'tif'):
        raise ValueError('choose STL, 3DM, PNG or TIF for the luminosity map')
    p = clean(options)
    if fmt in ('png', 'tif'):
        dpi = collage.clean(raw)['dpi']
        size = (max(1, round(p['width_mm'] / 25.4 * dpi)), max(1, round(p['height_mm'] / 25.4 * dpi)))
        if size[0] * size[1] > MAX_MAP_PIXELS:
            raise ValueError('luminosity map exceeds 16 MP; reduce model size or DPI')
        im = height_map(raw, specs, store, p, size)
        buf = io.BytesIO()
        im.save(buf, 'PNG' if fmt == 'png' else 'TIFF', dpi=(dpi, dpi),
                **({'compression': 'tiff_deflate'} if fmt == 'tif' else {}))
        data = buf.getvalue()
    else:
        check_resources(p, fmt)
        model = mesh(raw, specs, store, p)
        data = stl(model, p['encoding']) if fmt == 'stl' else three_dm(model)
    return data, f'collage-luminosity{"-mm" if fmt in ("stl", "3dm") else ""}.{fmt}'
