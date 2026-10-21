"""Map output and line styling regressions."""
import io
from pathlib import Path
from unittest.mock import patch
import pymupdf
from PIL import Image
import collage as C
import shapes
import server


def fixture():
    b=io.BytesIO();Image.new('RGB',(90,60),'white').save(b,'PNG')
    return {'a':C.open_source('a.png',b.getvalue())},[{'id':'a','w':3}],dict(w=3,h=2,dpi=80,scatter=.8,rot=35,cw=.2,ch=.2)


def test_map_export_is_always_one_file_even_with_legacy_linework():
    store,specs,raw=fixture()
    with patch.object(C,'portions_pdf',side_effect=AssertionError('map must not export extra linework')):
        data,name=C.export(raw,specs,store,'map',lines=True)
    assert name=='collage-map.pdf' and data.startswith(b'%PDF')
    assert len(pymupdf.open(stream=data,filetype='pdf'))==1


def test_map_rasters_match_shown_map_at_selected_dpi():
    store,specs,raw=fixture()
    doc=pymupdf.open(stream=C.migration_pdf(raw,specs,store),filetype='pdf')
    expected=doc[0].get_pixmap(dpi=80,alpha=False)
    for fmt in ('png','tif'):
        data,name=C.export({**raw,'map_file':fmt},specs,store,'map',lines=True)
        im=Image.open(io.BytesIO(data)).convert('RGB')
        assert name=='collage-map.'+fmt and im.size==(240,160)
        assert im.tobytes()==expected.samples
    data,_=C.export({**raw,'map_file':'png','dpi':160},specs,store,'map')
    assert Image.open(io.BytesIO(data)).size==(480,320)


def test_stroke_width_tone_and_opacity_reach_vector_output():
    store,specs,raw=fixture()
    p={**raw,'m1w':.25,'m2w':2.5,'m3w':1.25,'m2c':'#336699','m2o':.35}
    doc=pymupdf.open(stream=C.migration_pdf(p,specs,store),filetype='pdf')
    drawings=doc[0].get_drawings()
    for layer,width in [('1 initial',.25),('2 migration',2.5),('3 final',1.25)]:
        assert all(abs(d['width']-width)<1e-6 for d in drawings if d.get('layer')==layer and d.get('type') in ('s','fs'))
    lines=[d for d in drawings if d.get('layer')=='2 migration' and d['type']=='s']
    assert lines and all(abs(d['stroke_opacity']-.35)<1e-5 for d in lines)
    assert all(max(abs(a-b) for a,b in zip(d['color'],(.2,.4,.6)))<1e-5 for d in lines)


def test_line_colors_follow_cut_shape_independent_of_marker():
    store,specs,raw=fixture()
    raw.update(multi_shape=True,shape_weights={'rectangle':50,'triangle':50},line_by_shape=True,
               line_shape_colors={'rectangle':'#ff0000','triangle':'#0000ff'},node_start='none',node_end='none',m1o=0,m3o=0)
    def groups(settings):
        p=C.clean(settings);pieces=C.layout(p,C._sizes(specs,store),p['w'],p['h'])
        expected={}
        for pc in pieces:
            end=C.migration_line_end(p,pc)
            if end is None:continue
            color=C._rgb(p['line_shape_colors'][shapes.shape_for(p,pc)])
            expected.setdefault(color,[]).append(tuple(round(v*72,3) for point in (pc[7:9],end) for v in point))
        doc=pymupdf.open(stream=C.migration_pdf(settings,specs,store),filetype='pdf')
        actual={}
        for d in doc[0].get_drawings():
            if d.get('layer')!='2 migration' or d['type']!='s':continue
            segments=[tuple(round(v,3) for point in item[1:] for v in point) for item in d['items'] if item[0]=='l']
            if segments:actual.setdefault(d['color'],[]).extend(segments)
        return expected,actual
    expected,actual=groups(raw)
    assert len(expected)==2 and actual==expected
    # The endpoint geometry can change with marker style; shape-to-colour assignment cannot.
    _,with_markers=groups({**raw,'node_end':'square','node_by_shape':True,'node_end_shapes':{'rectangle':'ring','triangle':'plus'}})
    assert set(expected)<=set(with_markers)


def test_line_style_validation_and_saved_defaults():
    p=C.clean({'m2w':float('nan'),'line_shape_colors':{'rectangle':'nope','triangle':'#00ff00','unknown':'#ffffff'}})
    assert p['m2w']==.6 and p['line_shape_colors']['triangle']=='#00ff00'
    assert p['line_shape_colors']['rectangle'].startswith('#') and 'unknown' not in p['line_shape_colors']
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as folder,patch.object(server,'SETTINGS_PATH',Path(folder)/'settings.json'):
        server.save_map_defaults({'line_by_shape':True,'line_shape_colors':{'triangle':'#123456'},'m2w':2.2})
        saved=server.map_defaults()
        assert saved['line_by_shape'] and saved['line_shape_colors']['triangle']=='#123456' and saved['m2w']==2.2


def test_line_gradients_and_node_opacities_are_independent():
    store,specs,raw=fixture()
    raw.update(m2c='#ff0000',m2_gradient_end='#0000ff',line_tone_gradient=True,
               line_opacity_gradient=True,m2o=.2,m2_gradient_opacity=.9,m2so=.3,m2eo=.7,
               node_start='dot',node_end='square')
    pc=(0,(0,0,1,1),2.75,1,.5,.5,0,.25,1,.5,.5)
    doc=pymupdf.open(stream=C._map_doc(raw,specs,store,(2,),pieces=[pc]),filetype='pdf')
    drawing=doc[0].get_drawings()
    from PIL import Image
    pix=doc[0].get_pixmap(dpi=100,alpha=False)
    pixels=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    start,end=pixels.getpixel((50,100)),pixels.getpixel((250,100))
    assert start[0]>start[2] and end[2]>end[0]
    assert start[1]>160 and end[1]<80
    nodes=[d for d in drawing if d['type']=='fs']
    assert any(abs(d['fill_opacity']-.3)<1e-5 for d in nodes)
    assert any(abs(d['fill_opacity']-.7)<1e-5 for d in nodes)
    assert all(abs(d['stroke_opacity']-d['fill_opacity'])<1e-5 for d in nodes)


def test_tone_gradient_targets_destination_cut_color_not_marker():
    store,specs,raw=fixture()
    raw.update(multi_shape=True,shape_weights={'rectangle':50,'triangle':50},line_by_shape=True,
               line_shape_colors={'rectangle':'#ff0000','triangle':'#0000ff'},line_tone_gradient=True,
               m2c='#00ff00',node_start='none',node_end='none',m1o=0,m3o=0)
    doc=pymupdf.open(stream=C.migration_pdf(raw,specs,store),filetype='pdf')
    import numpy as np
    pix=doc[0].get_pixmap(dpi=150,alpha=False)
    colors=np.frombuffer(pix.samples,dtype=np.uint8).reshape(-1,3).astype(float)/255
    assert ((colors[:,0]>.9)&(colors[:,1]<.4)&(colors[:,2]<.4)).any()
    assert ((colors[:,2]>.9)&(colors[:,1]<.4)&(colors[:,0]<.4)).any()
    assert ((colors[:,1]>.9)&(colors[:,0]<.4)&(colors[:,2]<.4)).any()


def test_gradient_has_no_opacity_seams_at_full_resolution():
    import numpy as np
    store,specs,raw=fixture()
    raw.update(w=4,h=1,m2w=6,m2c='#000000',m2o=.5,line_tone_gradient=True,
               m2_gradient_end='#ff0000',node_start='none',node_end='none')
    pc=(0,(0,0,1,1),3.5,.5,.5,.5,0,.5,.5,.5,.5)
    doc=pymupdf.open(stream=C._map_doc(raw,specs,store,(2,),pieces=[pc]),filetype='pdf')
    pix=doc[0].get_pixmap(dpi=100,alpha=False)
    image=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,3)
    green=image[50,55:345,1]
    assert green.max()-green.min()<=2,(green.min(),green.max())


def test_gradient_is_vector_and_respects_pdf_layer_visibility():
    store,specs,raw=fixture()
    raw.update(line_tone_gradient=True,line_opacity_gradient=True,m2_gradient_opacity=.2,
               node_start='none',node_end='none',m1o=0,m3o=0,m1p='#ffffff')
    doc=pymupdf.open(stream=C.migration_pdf(raw,specs,store),filetype='pdf')
    assert doc[0].get_images()==[]
    migration=next(xref for xref,layer in doc.get_ocgs().items() if layer['name']=='2 migration')
    doc.set_layer(-1,on=[xref for xref in doc.get_ocgs() if xref!=migration],off=[migration])
    hidden=pymupdf.open(stream=doc.tobytes(),filetype='pdf')
    pix=hidden[0].get_pixmap(dpi=80,alpha=False)
    assert all(value==255 for value in pix.samples)


def test_triptych_pdf_is_one_page_with_raster_panels_and_vector_map():
    store,specs,raw=fixture()
    raw.update(triptych_file='pdf',line_tone_gradient=True)
    data,name=C.export(raw,specs,store,'triptych',lines=True)
    assert name=='collage-triptych.pdf' and data.startswith(b'%PDF')
    doc=pymupdf.open(stream=data,filetype='pdf');assert len(doc)==1
    # Each 240×160 panel and the two 12px gaps retain the selected 80 DPI.
    assert abs(doc[0].rect.width-744*72/80)<.001
    assert abs(doc[0].rect.height-160*72/80)<.001
    images=doc[0].get_images(full=True)
    assert images and all(image[2:4]==(240,160) for image in images)
    assert doc[0].get_xobjects()  # the map is a vector Form XObject
    raw['triptych_file']='png'
    png,name=C.export(raw,specs,store,'triptych')
    assert name=='collage-triptych.png' and Image.open(io.BytesIO(png)).size==(744,160)


if __name__=='__main__':
    for name,fn in sorted(globals().copy().items()):
        if name.startswith('test_'):fn();print('ok',name)
