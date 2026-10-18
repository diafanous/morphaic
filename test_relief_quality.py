"""Dense relief regression checks: .venv/Scripts/python test_relief_quality.py."""
import io
import json
import struct
from unittest.mock import patch

import numpy as np
from PIL import Image

import collage
import luminosity


def fixture():
    pixels = np.tile(np.arange(256, dtype=np.uint8), (32, 1))
    image = Image.fromarray(pixels)
    buf = io.BytesIO()
    image.save(buf, 'PNG')
    return {'ramp': collage.open_source('ramp.png', buf.getvalue())}


def options(**changes):
    return dict(source='import', source_id='ramp', width_mm=7.1, height_mm=7.1,
                spacing_mm=.01, relief_mm=8, base_mm=2, **changes)


def assert_closed(vertices, faces):
    """Every directed edge has one opposing edge, including walls and base."""
    forward = (faces.astype(np.uint64) << 32) | np.roll(faces, -1, axis=1)
    backward = (np.roll(faces.astype(np.uint64), -1, axis=1) << 32) | faces
    forward, backward = np.sort(forward.ravel()), np.sort(backward.ravel())
    assert np.array_equal(forward, backward)
    assert np.all(forward[1:] != forward[:-1])
    volume = 0
    for start in range(0, len(faces), 32_768):
        triangles = vertices[faces[start:start + 32_768]]
        volume += np.einsum('ij,ij->i', triangles[:, 0],
                            np.cross(triangles[:, 1], triangles[:, 2])).sum() / 6
    assert volume > 0


def test_point_zero_one_mesh_above_old_limit_and_binary_stl():
    model = luminosity.mesh({}, [], fixture(), options())
    vertices, faces = np.asarray(model['vertices']), np.asarray(model['faces'])
    assert model['grid'] == [711, 711]
    assert len(vertices) == 508_362 and len(faces) == 1_016_720
    assert vertices.nbytes + faces.nbytes < 25 * 1024**2
    assert np.all(faces < len(vertices))
    assert np.allclose(vertices.max(axis=0), [7.1, 7.1, 10])
    assert np.allclose(vertices.min(axis=0), [0, 0, 0])
    assert_closed(vertices, faces)

    data = luminosity.stl(model, 'binary')
    assert struct.unpack_from('<I', data, 80)[0] == len(faces)
    assert len(data) == 84 + 50 * len(faces)
    # Verify normal and coordinates across chunk boundaries and the last base facet.
    for index in (0, 32_767, 32_768, len(faces) - 1):
        values = struct.unpack_from('<12fH', data, 84 + index * 50)
        triangle = vertices[faces[index]]
        assert np.allclose(values[3:12], triangle.ravel(), atol=1e-6)
        assert np.allclose(values[:3], luminosity.normal(*triangle), atol=1e-6)
        assert values[-1] == 0


def test_fine_export_and_preview_contracts():
    small = {**options(), 'width_mm': 1, 'height_mm': 1}
    data, name = luminosity.export({}, [], fixture(), small, 'stl')
    estimate = luminosity.mesh_estimate(luminosity.clean(small), 'stl')
    assert name.endswith('-mm.stl') and len(data) == estimate['binary_stl_bytes']
    model = luminosity.mesh({}, [], fixture(), small)
    assert len(model['vertices']) == 10_602
    # Tuple-compatible rows retain callers' winding/edge iteration contract.
    face = model['faces'][0]
    assert face[1:] + face[:1] == (1, 102, 0)
    preview = luminosity.mesh({}, [], fixture(), {**small, 'width_mm': 5000, 'height_mm': 5000}, preview=True)
    assert preview['preview'] and max(preview['grid']) <= 81
    assert json.loads(json.dumps(preview))['units'] == 'mm'


def test_memory_budget_is_machine_dependent_and_includes_export():
    p = luminosity.clean(options())
    geometry = luminosity.mesh_estimate(p)
    binary = luminosity.mesh_estimate(p, 'stl')
    assert binary['estimated_memory_bytes'] - geometry['estimated_memory_bytes'] == binary['binary_stl_bytes']
    with patch.object(luminosity, 'available_memory', return_value=1024**3):
        assert luminosity.grid_size(p) == (711, 711)
        assert luminosity.check_resources(p, 'stl')['vertices'] > 500_000
    with patch.object(luminosity, 'available_memory', return_value=64 * 1024**2):
        try:
            luminosity.check_resources(p, 'stl')
        except ValueError as error:
            assert 'GiB' in str(error) and 'increase mesh spacing' in str(error)
        else:
            raise AssertionError('memory-heavy export accepted on low-memory host')
    with patch.object(luminosity, 'available_memory', return_value=None):
        try:
            luminosity.grid_size({**p, 'width_mm': 5000, 'height_mm': 5000})
        except ValueError as error:
            assert '32-bit' in str(error)
        else:
            raise AssertionError('unrepresentable mesh accepted')


if __name__ == '__main__':
    for name, fn in sorted(globals().copy().items()):
        if name.startswith('test_'):
            fn()
            print('ok ', name)
