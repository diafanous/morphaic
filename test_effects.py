"""Run with .venv/Scripts/python test_effects.py (also works under pytest)."""
import io
import json

import numpy as np
from PIL import Image, ImageChops

import collage as C
import effects as E


def source(im, name='image.png'):
    buf = io.BytesIO()
    im.save(buf, 'PNG', dpi=(100, 100))
    return C.open_source(name, buf.getvalue())


def same(a, b):
    assert a.mode == b.mode and a.size == b.size
    assert a.tobytes() == b.tobytes()


def test_defaults_preserve_source_and_alpha_without_a_flat_preset():
    im = Image.fromarray(np.random.default_rng(12).integers(0, 256, (160, 200, 3), dtype=np.uint8))
    p, result = C.compose({'w': 2, 'h': 1.6, 'dpi': 100}, [{'id': 'image', 'w': 2}], {'image': source(im)}, final=True)
    same(im, result)
    alpha = im.convert('RGBA')
    alpha.putalpha(Image.linear_gradient('L').resize(im.size))
    assert E.grade(alpha, p) is alpha
    assert E.grain(alpha, p, 100) is alpha
    assert p['var'] == p['rot'] == p['scatter'] == p['draw'] == 0 and p['layers'] == 1


def test_grading_preserves_alpha_and_has_expected_color_directions():
    im = Image.new('RGBA', (4, 1), (100, 100, 100, 123))
    im.putalpha(Image.frombytes('L', (4, 1), bytes([0, 50, 180, 255])))
    for settings in ({'exposure': 1}, {'temperature': 1}, {'tint': 1}, {'saturation': 0}, {'gradient_amount': 1}):
        adjusted = E.grade(im, C.clean(settings))
        same(adjusted.getchannel('A'), im.getchannel('A'))
    assert E.grade(im, C.clean({'exposure': 1})).getpixel((0, 0))[0] > 100
    assert E.grade(im, C.clean({'exposure': -1})).getpixel((0, 0))[0] < 100
    warm = E.grade(im, C.clean({'temperature': 1})).getpixel((0, 0))
    cool = E.grade(im, C.clean({'temperature': -1})).getpixel((0, 0))
    magenta = E.grade(im, C.clean({'tint': 1})).getpixel((0, 0))
    assert warm[0] > warm[2] and cool[0] < cool[2] and magenta[0] > magenta[1]
    color = Image.new('RGB', (2, 2), (190, 60, 20))
    gray = E.grade(color, C.clean({'saturation': 0})).getpixel((0, 0))
    assert gray[0] == gray[1] == gray[2]


def test_neutral_odd_dimensions_do_not_resample_individual_cut_edges():
    for w, h in ((201, 157), (199, 151), (101, 100), (403, 307), (13, 11), (3, 7)):
        im = Image.fromarray(np.random.default_rng(12).integers(0, 256, (h, w, 3), dtype=np.uint8))
        store = {'image': source(im)}
        specs = [{'id': 'image', 'w': w/100}]
        _, actual = C.compose({'w': w/100, 'h': h/100, 'dpi': 100}, specs, store, final=True)
        same(im, actual)
        _, preview = C.compose({'w': w/100, 'h': h/100, 'pv': 800}, specs, store)
        same(im.resize(preview.size, Image.Resampling.BILINEAR), preview)


def test_gradient_uses_luminance_and_interpolates_multiple_stops():
    ramp = Image.frombytes('L', (3, 1), bytes([0, 128, 255])).convert('RGB')
    settings = {'gradient_amount': 1, 'gradient_stops': [
        {'position': 1, 'color': '#ffffff'}, {'position': 0, 'color': '#0000ff'},
        {'position': 128/255, 'color': '#ff0000'}]}
    mapped = E.grade(ramp, C.clean(settings))
    assert [mapped.getpixel((x, 0)) for x in range(3)] == [(0, 0, 255), (255, 0, 0), (255, 255, 255)]
    half = E.grade(ramp, C.clean({**settings, 'gradient_amount': .5}))
    assert half.getpixel((0, 0)) == (0, 0, 127)
    assert E.grade(Image.new('RGB', (1, 1), (0, 255, 0)), C.clean(settings)).getpixel((0, 0)) != (0, 255, 0)


def test_effect_settings_are_finite_and_invalid_stops_are_sanitized():
    p = C.clean({'grain': float('nan'), 'exposure': float('inf'), 'saturation': 'bad',
                 'grain_size': -9, 'tint': 9, 'layers': float('nan'), 'grain_source_id': '../file', 'grain_source_name': ' paper\x00\n.png ',
                 'gradient_stops': [None, {'position': float('nan'), 'color': '#ffffff'},
                                    {'position': 1, 'color': 'red'}, {'position': 'bad', 'color': '#123456'}]})
    assert p['grain'] == p['exposure'] == 0 and p['saturation'] == 1
    assert p['grain_size'] == .25 and p['tint'] == 1 and p['layers'] == 1
    assert p['grain_source_id'] == '' and p['gradient_stops'] == list(E.DEFAULT_STOPS)
    assert p['grain_source_name'] == 'paper.png'
    bounded = C.clean({'gradient_stops': [{'position': 4, 'color': '#ABCDEF'}, {'position': -1, 'color': '#123456'}]})
    assert bounded['gradient_stops'] == [{'position': 0, 'color': '#123456'}, {'position': 1, 'color': '#abcdef'}]


def test_procedural_grain_is_seeded_monochrome_and_keeps_physical_scale():
    p = C.clean({'grain': .7, 'grain_size': 4, 'seed': 67})
    low = Image.new('RGB', (100, 80), (128, 128, 128))
    high = Image.new('RGB', (300, 240), (128, 128, 128))
    result = E.grain(low, p, 100)
    same(result, E.grain(low, p, 100))
    assert ImageChops.difference(result, low).getbbox() is not None
    assert ImageChops.difference(result, E.grain(low, {**p, 'seed': 68}, 100)).getbbox() is not None
    pixels = np.asarray(result)
    assert np.array_equal(pixels[:, :, 0], pixels[:, :, 1]) and np.array_equal(pixels[:, :, 1], pixels[:, :, 2])
    # Every third high-DPI pixel center is the same physical location.
    assert np.array_equal(pixels, np.asarray(E.grain(high, p, 300))[1::3, 1::3])
    rgba = low.convert('RGBA')
    rgba.putalpha(72)
    same(E.grain(rgba, p, 100).getchannel('A'), rgba.getchannel('A'))


def test_custom_texture_is_used_and_bad_references_are_rejected():
    base = Image.new('RGB', (100, 100), (128, 128, 128))
    texture = Image.new('RGB', (8, 8), 'black')
    texture.paste('white', (0, 0, 4, 8))
    store = {'image': source(base), 'texture': source(texture, 'grain.png')}
    specs = [{'id': 'image', 'w': 1}]
    raw = {'w': 1, 'h': 1, 'dpi': 100, 'grain': .8, 'grain_size': 4, 'grain_source_id': 'texture', 'grain_source_name': 'grain.png'}
    _, custom = C.compose(raw, specs, store, final=True)
    _, procedural = C.compose({**raw, 'grain_source_id': ''}, specs, store, final=True)
    assert ImageChops.difference(custom, base).getbbox() is not None
    assert ImageChops.difference(custom, procedural).getbbox() is not None
    same(custom, C.compose(raw, specs, store, final=True)[1])
    assert json.loads(C.settings_text(raw, specs, store))['parameters']['grain_source_name'] == 'grain.png'
    _, disabled = C.compose({**raw, 'grain': 0}, specs, store, final=True)
    same(base, disabled)
    for bad_store in ({'image': store['image']}, {'image': store['image'], 'texture': C.Source('bad.pdf', b'', True, 1, 1, 1, False)}):
        try:
            C.compose(raw, specs, bad_store, final=True)
        except ValueError as error:
            assert 'grain' in str(error)
        else:
            raise AssertionError('missing/non-image custom grain was accepted')


def test_preview_export_animation_triptych_and_settings_share_effects():
    im = Image.new('RGB', (90, 90), (90, 120, 145))
    store, specs = {'image': source(im)}, [{'id': 'image', 'w': 1}]
    raw = {'w': 1, 'h': 1, 'dpi': 100, 'pv': 720, 'smoothness': 4, 'exposure': .3,
           'temperature': .2, 'saturation': .8, 'grain': .4, 'grain_size': 5,
           'gradient_amount': .25, 'gradient_stops': [{'position': 0, 'color': '#221122'}, {'position': 1, 'color': '#ffd899'}]}
    _, preview = C.compose(raw, specs, store)
    final_frame = None
    for frame in C.animation_frames(raw, specs, store):
        final_frame = frame
    assert preview.size == (720,720)
    same(C.compose(raw,specs,store,final=True)[1], final_frame)
    _, expected = C.compose(raw, specs, store, final=True)
    exported = Image.open(io.BytesIO(C.export(raw, specs, store, 'png')[0]))
    same(exported, expected)
    panels = Image.open(io.BytesIO(C.triptych(raw, specs, store)))
    gap = round(.15*raw['dpi'])
    same(panels.crop((expected.width+gap, 0, 2*expected.width+gap, expected.height)), expected)
    saved = json.loads(C.settings_text(raw, specs, store))['parameters']
    for key in E.SPEC:
        assert saved[key] == C.clean(raw)[key]
    assert saved['gradient_stops'] == raw['gradient_stops'] and saved['grain_source_id'] == ''


def test_custom_grain_dpi_controls_physical_scale():
    import numpy as np
    im = Image.new('RGB', (64, 64), '#888888')
    custom = np.tile(np.array([-1, -.5, .5, 1], dtype=np.float32), (16, 4))
    base = E.clean(dict(grain=1, grain_dpi=100)); base['seed'] = 1
    first = E.grain(im, base, 100, custom)
    doubled = dict(base, grain_dpi=200)
    assert ImageChops.difference(first, E.grain(im, doubled, 200, custom)).getbbox() is None
    assert ImageChops.difference(first, E.grain(im, doubled, 100, custom)).getbbox() is not None
    assert ImageChops.difference(first, E.grain(im, doubled, 100, (custom, 2))).getbbox() is None


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok ', name)
