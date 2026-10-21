"""Animation resolution, real GPU compositing and export estimate regressions."""
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg
import numpy as np
from PIL import Image
import collage as C


def fixture():
    image=Image.effect_noise((96,64),70).convert('RGBA')
    image.putalpha(Image.linear_gradient('L').resize(image.size))
    buf=io.BytesIO();image.save(buf,'PNG')
    return {'a':C.open_source('a.png',buf.getvalue())},[{'id':'a','w':1,'page':0}]


def test_dimensions_default_to_full_and_preserve_aspect():
    assert C.animation_size(C.clean({'w':10,'h':5,'dpi':300}))==(3000,1500)
    assert C.animation_size(C.clean({'w':10,'h':5,'dpi':300,'anim_resolution':'1080'}))==(1080,540)
    assert C.animation_size(C.clean({'w':1,'h':.5,'dpi':100,'anim_resolution':'2160'}))==(100,50)
    assert C.clean({'anim_resolution':'garbage'})['anim_resolution']=='full'
    assert C.clean({'anim_renderer':'garbage'})['anim_renderer']=='cpu'
    assert C.clean({'gifmb':1})['anim_resolution']=='full'


def test_encoded_gif_and_mp4_use_chosen_resolution():
    store,specs=fixture()
    raw=dict(w=1,h=.75,dpi=64,rot=30,scatter=.6,pace=3,smoothness=4)
    gif=Image.open(io.BytesIO(C.process_gif({**raw,'gifmb':.001},specs,store)))
    assert gif.size==(64,48) and gif.is_animated and gif.info['loop']==0
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'test.mp4';path.write_bytes(C.process_mp4(raw,specs,store))
        reader=imageio_ffmpeg.read_frames(str(path));meta=next(reader)
        assert meta['size']==(64,48)
        assert len(list(reader))==C.animation_timing(C.clean(raw))[0]


def test_gpu_matches_cpu_with_shapes_feather_opacity_and_rotation():
    import animation_gpu
    status=animation_gpu.capabilities()
    if not status['available']:
        print('GPU parity skipped:',status['reason']);return
    store,specs=fixture()
    raw=dict(w=1,h=.75,dpi=128,rot=35,scatter=.6,opacity=.6,layers=2,blur=.15,cut_shape='ellipse')
    cpu=next(C.animation_frames(raw,specs,store,sample=True))
    gpu=next(C.animation_frames({**raw,'anim_renderer':'gpu'},specs,store,sample=True))
    difference=np.abs(np.asarray(cpu,dtype=float)-np.asarray(gpu,dtype=float))
    assert difference.max()<=3 and difference.mean()<.6,(difference.max(),difference.mean())


def test_gpu_fallback_keeps_requested_resolution():
    import animation_gpu
    store,specs=fixture();raw=dict(w=1,h=.75,dpi=48,rot=20)
    expected=next(C.animation_frames(raw,specs,store,sample=True))
    with patch.object(animation_gpu,'Compositor',side_effect=RuntimeError('GPU unavailable')):
        actual=next(C.animation_frames({**raw,'anim_renderer':'gpu'},specs,store,sample=True))
    assert actual.size==(48,36) and actual.tobytes()==expected.tobytes()


def test_gpu_runtime_failure_falls_back_for_gif_and_mp4():
    import animation_gpu
    if not animation_gpu.capabilities()['available']:return
    store,specs=fixture();raw=dict(w=1,h=.75,dpi=48,rot=20,scatter=.5,pace=3,smoothness=4,anim_renderer='gpu')
    with patch.object(animation_gpu.Compositor,'paste',side_effect=RuntimeError('GPU texture allocation failed')):
        gif=Image.open(io.BytesIO(C.process_gif(raw,specs,store)))
        assert gif.size==(48,36) and gif.n_frames==36
        data=C.process_mp4(raw,specs,store)
        assert data[4:8]==b'ftyp'
        estimate=C.animation_estimate(raw,specs,store,'gif')
        assert estimate['renderer']=='cpu' and 'GPU failed' in estimate['reason']


def test_estimate_reports_selected_dimensions_frames_and_measured_range():
    store,specs=fixture();raw=dict(w=1,h=.75,dpi=48,pace=3,smoothness=4)
    result=C.animation_estimate(raw,specs,store,'gif')
    assert (result['width'],result['height'])==(48,36)
    assert result['frames']==C.animation_timing(C.clean(raw))[0]
    assert 0<result['seconds_low']<=result['seconds_high']
    assert result['renderer']=='cpu' and result['approximate'] is True


def test_gpu_exports_decode_and_odd_mp4_dimensions_are_padded():
    store,specs=fixture()
    raw=dict(w=1,h=.75,dpi=129,rot=35,scatter=.7,pace=3,smoothness=4,anim_renderer='gpu')
    gif=Image.open(io.BytesIO(C.process_gif(raw,specs,store)))
    assert gif.size==(129,97) and gif.n_frames==36
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'gpu.mp4';path.write_bytes(C.process_mp4(raw,specs,store))
        reader=imageio_ffmpeg.read_frames(str(path));meta=next(reader)
        assert meta['size']==(130,98)
        assert len(list(reader))==36


def test_estimate_http_and_gpu_capabilities():
    import json,threading,urllib.request
    import server
    store,specs=fixture()
    http=server.Server(('127.0.0.1',0),server.Handler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{http.server_port}'
    try:
        with patch.dict(server.STORE,store):
            data=json.dumps({'p':dict(w=1,h=.75,dpi=48),'sources':specs,'format':'gif'}).encode()
            with urllib.request.urlopen(urllib.request.Request(url+'/animation-estimate',data=data)) as response:
                result=json.load(response);assert response.status==200 and result['width']==48
            with urllib.request.urlopen(url+'/animation-capabilities') as response:
                result=json.load(response);assert isinstance(result['available'],bool)
    finally:http.shutdown();http.server_close()


if __name__=='__main__':
    for name,fn in sorted(globals().copy().items()):
        if name.startswith('test_'):fn();print('ok',name)
