"""Project portability, transactionality and settings regression tests."""
import copy
import io
import json
import zipfile
import pathlib
import tempfile
from PIL import Image
import pymupdf
import collage as C
import projects as P


def fixture():
    b = io.BytesIO(); Image.effect_noise((48, 32), 80).convert('RGB').save(b, 'PNG')
    doc = pymupdf.open(); doc.new_page(width=72, height=100)
    store = {'image': C.open_source('original.png', b.getvalue()),
             'pdf': C.open_source('original.pdf', doc.tobytes()),
             'grain': C.open_source('texture.png', b.getvalue()),
             'unused': C.open_source('unused.png', b.getvalue())}
    p = C.clean(dict(w=1, h=1, dpi=30, grain=.2, grain_source_id='grain', pts=[[.2,.3]], m2c='#123456'))
    specs = [dict(id='image', w=1, page=0), dict(id='pdf', w=1, page=0)]
    files = [dict(id=s['id'], name=store[s['id']].name, w=1, page=1, original_w=store[s['id']].w_in,
                  pdf=store[s['id']].pdf, pages=store[s['id']].pages, aspect=store[s['id']].aspect, assumed=False, edited=True) for s in specs]
    snapshot = dict(P=p, settings=dict(w=1,h=1,dpi=30,bg=p['bg'],seed=1,unit='mm',fmt='png',
                    exportMode='3d',lumFmt='3dm',lum=dict(relief_mm=17),cut={},map=dict(m2c='#123456')),
                    files=files,strokes=[[[.1,.2],[.3,.4]]],cpts=[[0,0],[.4,.6],[1,1]],lines=True)
    return dict(p=p,sources=specs,snapshot=snapshot,view=dict(zoom=1.5,x=12,y=-4)), store


def test_portable_archive_and_embedded_png():
    req, store = fixture(); expected = C.compose(req['p'], req['sources'], store, final=True)[1]
    for kind in ('project','png'):
        data, filename = P.save(req, store, kind)
        assert filename.endswith('.morphaic' if kind == 'project' else '.png')
        if kind == 'png':
            with Image.open(io.BytesIO(data)) as im:
                im.load(); assert im.tobytes() == expected.tobytes()
        before = dict(store); out = P.load(data, store); snap = out['snapshot']
        assert all(store[k] is v for k,v in before.items())
        assert len(store) == len(before)+3
        assert snap['P']['grain_source_id'] != 'grain'
        assert snap['strokes'] == req['snapshot']['strokes'] and snap['cpts'] == req['snapshot']['cpts']
        assert snap['settings']['lum']['relief_mm'] == 17 and snap['settings']['exportMode'] == '3d'
        assert snap['settings']['map']['m2c'] == '#123456'
        specs = [dict(id=f['id'],w=f['w'],page=f['page']-1) for f in snap['files']]
        actual = C.compose(snap['P'], specs, store, final=True)[1]
        assert actual.tobytes() == expected.tobytes()
        for old,new in zip(req['snapshot']['files'],snap['files']):
            assert store[new['id']].data == before[old['id']].data
        assert out['view'] == req['view']


def rewrite(data, mutate):
    with zipfile.ZipFile(io.BytesIO(data)) as z: entries={n:z.read(n) for n in z.namelist()}
    mutate(entries)
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        for n,v in entries.items(): z.writestr(n,v)
    return b.getvalue()


def rejects(data, store):
    before=dict(store)
    try: P.load(data,store)
    except ValueError: pass
    else: raise AssertionError('invalid project accepted')
    assert store == before


def test_invalid_archive_is_transactional():
    req,store=fixture(); data,_=P.save(req,store)
    rejects(data[:-20],store)
    rejects(rewrite(data,lambda e:e.update({'../spoof':b'bad'})),store)
    rejects(rewrite(data,lambda e:e.update({'manifest.json':b' '*(P.MAX_MANIFEST_BYTES+1)})),store)
    def corrupt(e):
        name=next(n for n in e if n.startswith('sources/'));e[name]=b'corrupt'
    rejects(rewrite(data,corrupt),store)
    def poison(e):
        m=json.loads(e['manifest.json']);m['snapshot']['settings']['__proto__']={};e['manifest.json']=json.dumps(m).encode()
    rejects(rewrite(data,poison),store)


def test_settings_partial_and_validation():
    req,store=fixture(); current=dict(p=req['p'])
    out=P.parse_settings('{"rot":42}',current,store)
    assert out['p']['rot']==42 and out['p']['m2c']=='#123456' and 'unit' not in out
    text=C.settings_text({**req['p'],'unit':'mm','grid_visible':True},req['sources'],store,True).decode()
    out=P.parse_settings(text,current,store)
    assert out['unit']=='mm' and out['grid_visible'] and out['lines']
    for text in ('{bad','{"unknown":1}','{"rot":NaN}','{"shape_weights":{"custom":101}}','{"grain_source_id":"missing"}'):
        try: P.parse_settings(text,current,store)
        except ValueError: pass
        else: raise AssertionError(text)


def test_png_crc_and_invalid_state():
    req,store=fixture(); data,_=P.save(req,store,'png')
    damaged=bytearray(data);position=data.index(b'moRp');damaged[position+8]^=1
    rejects(bytes(damaged),store)
    data,_=P.save(req,store)
    for key,value in [('inkOn',{}),('bg','red'),('w',1000)]:
        def poison(entries):
            m=json.loads(entries['manifest.json']);m['snapshot']['settings'][key]=value
            entries['manifest.json']=json.dumps(m).encode()
        rejects(rewrite(data,poison),store)
    rejects(rewrite(data,lambda e:e.update({'preview.png':b'corrupt preview'})),store)


def test_settings_reject_invalid_nested_values():
    req,store=fixture();current=dict(p=req['p'])
    for raw in ({'grain_source_id':5},{'multi_shape':{}},{'gradient_stops':[{'position':0,'color':'#ffffff','wrong':1}]}):
        try: P.parse_settings(json.dumps(raw),current,store)
        except ValueError: pass
        else: raise AssertionError(raw)
    try: P.parse_settings('{"rot":'+('9'*400)+'}',current,store)
    except ValueError: pass
    else: raise AssertionError('huge integer accepted')


def test_template_roundtrip_no_indesign_execution():
    import indesign
    req,store=fixture()
    root=pathlib.Path(__file__).parent/'work'/'test-tmp';root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as folder:
        original=pathlib.Path(folder)/'original.idml';original.write_bytes(b'original template bytes')
        frames=[dict(key='page1-frame1',name='Drawing')]
        identity='test-template-project';indesign.TEMPLATES[identity]=dict(id=identity,name='design.idml',path=str(original),frames=frames)
        req['template']=dict(id=identity,mapping={'page1-frame1':'collage'},fit='contain',title='A drawing')
        try:
            data,_=P.save(req,store);before=dict(indesign.TEMPLATES)
            rejects(rewrite(data,lambda e:e.update({'../template':b'bad'})),store)
            assert indesign.TEMPLATES==before
            result=P.load(data,store)['template'];new_id=result['id']
            assert new_id!=identity and result['frames']==frames and result['mapping']==req['template']['mapping']
            assert result['title']=='A drawing'
            restored=pathlib.Path(indesign.TEMPLATES[new_id]['path'])
            assert restored.read_bytes()==original.read_bytes()
            restored.unlink();del indesign.TEMPLATES[new_id]
        finally: del indesign.TEMPLATES[identity]


def test_imported_luminosity_source_and_map_format():
    req,store=fixture()
    req['snapshot']['settings']['fmt']='lum-png'
    req['snapshot']['settings']['lum']={'source':'import','source_id':'unused','source_name':'unused.png','source_aspect':1.5}
    data,_=P.save(req,store);result=P.load(data,store)
    lum=result['snapshot']['settings']['lum']
    assert lum['source_id']!='unused' and store[lum['source_id']].data==store['unused'].data
    assert result['snapshot']['settings']['fmt']=='lum-png'
    req['snapshot']['settings']['fmt']='indesign'
    data,_=P.save(req,store)
    assert P.load(data,store)['snapshot']['settings']['fmt']=='indesign'


def test_default_empty_template():
    req,store=fixture();req['template']={'id':'','name':'','frames':[],'mapping':{},'fit':'contain','title':''}
    data,_=P.save(req,store)
    assert P.load(data,store)['template'] is None


def test_reject_foreign_map_keys():
    req,store=fixture();req['snapshot']['settings']['map']['grain_source_id']='grain'
    try: P.save(req,store)
    except ValueError: pass
    else: raise AssertionError('Foreign map settings accepted')


def test_text_format_and_cut_map_independence():
    req,store=fixture();req['snapshot']['settings']['fmt']='txt'
    req['snapshot']['settings']['map'].update(node_by_shape=True,node_end_shapes={'ellipse':'arrow'})
    req['p'].update(node_by_shape=True,node_end_shapes={'ellipse':'arrow'})
    data,_=P.save(req,store);snap=P.load(data,store)['snapshot']
    assert snap['settings']['fmt']=='txt'
    cut=snap['settings']['cut'];assert 'node_by_shape' not in cut and 'node_end_shapes' not in cut
    merged={**snap['P'],**snap['settings']['map'],**cut}
    assert merged['node_by_shape'] and merged['node_end_shapes']['ellipse']=='arrow'


def test_project_png_and_archive_preview_show_map():
    req,store=fixture();req['map']=True;req['snapshot']['settings']['fmt']='map'
    expected_bytes,_=C.export({**req['p'],'map_file':'png'},req['sources'],store,'map')
    with Image.open(io.BytesIO(expected_bytes)) as image: expected=image.copy()
    data,_=P.save(req,store,'png')
    with Image.open(io.BytesIO(data)) as image:
        assert image.size==expected.size and image.tobytes()==expected.tobytes()
    snap=P.load(data,store)['snapshot'];assert snap['settings']['fmt']=='map'
    specs=[dict(id=f['id'],w=f['w'],page=f['page']-1) for f in snap['files']]
    restored,_=C.export({**snap['P'],**snap['settings']['map'],**snap['settings']['cut'],'map_file':'png'},specs,store,'map')
    with Image.open(io.BytesIO(restored)) as image: assert image.tobytes()==expected.tobytes()
    archive,_=P.save(req,store)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        with Image.open(io.BytesIO(z.read('preview.png'))) as preview:
            assert max(preview.size)<=480
            assert preview.getpixel((0,0))!=C.compose(req['p'],req['sources'],store,final=True,long_edge=480)[1].getpixel((0,0))


if __name__ == '__main__':
    for name,func in list(globals().items()):
        if name.startswith('test_'): func();print(name,'OK')
