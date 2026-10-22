"""Portable editable projects: ZIP originals plus JSON; optionally inside a PNG.

No archive paths are extracted. Session registries are updated only after every
member, checksum, source decoder and state validator has succeeded.
"""
import copy
import hashlib
import io
import json
import math
import re
from pathlib import Path
import struct
import uuid
import zipfile
import zlib

from PIL import Image
import collage
import luminosity
import shapes

MAX_PROJECT_BYTES = 1024**3
MAX_MANIFEST_BYTES = 4 * 1024**2
MAX_MEMBERS = 1024
PARAMETERS = set(collage.clean({}))
EXTRAS = {'unit', 'grid_visible', 'stencil_id', 'luminosity'}
SETTINGS = {'w','h','touched','dpi','fmt','bg','exportMode','lumFmt','lum','cut','unit','seed','grid','map','inkOn'}
FILE_KEYS = {'id','name','w','original_w','page','pages','aspect','pdf','assumed','edited'}
LUM_KEYS = set(luminosity.clean({})) | {'source_name','source_aspect'}
CUT_KEYS = {'cut_shape','multi_shape','shape_weights','shape_locks','custom_shape','stencil_name','stencil_id'}
MAP_KEYS = {k for k in PARAMETERS if k.startswith(('m1','m2','m3','node_','line_','anim'))} | {'smoothness','pace','map_file','triptych_file'}


def _tree(value, depth=0):
    if depth > 24: raise ValueError('Project settings are nested too deeply.')
    if isinstance(value, dict):
        for k,v in value.items():
            if not isinstance(k,str) or k in ('__proto__','prototype','constructor'):
                raise ValueError('Unsafe settings key.')
            _tree(v,depth+1)
    elif isinstance(value,(list,tuple)):
        if len(value)>20000: raise ValueError('Too many settings values.')
        for v in value: _tree(v,depth+1)
    elif isinstance(value,(int,float)):
        try: finite=math.isfinite(value)
        except OverflowError: finite=False
        if not finite: raise ValueError('Settings numbers must be finite.')
    elif value is not None and not isinstance(value,(str,bool)):
        raise ValueError('Settings must contain JSON values.')
    elif isinstance(value,str) and len(value)>20000:
        raise ValueError('Settings text is too long.')


def _object(value, allowed, label):
    if not isinstance(value,dict): raise ValueError(label+' must be an object.')
    unknown=set(value)-set(allowed)
    if unknown: raise ValueError('Unknown '+label+': '+', '.join(sorted(unknown)))
    _tree(value)
    return value


def _number(value,lo,hi,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:
        raise ValueError(label+' is out of range.')
    return value


def _params(raw,store):
    _object(raw,PARAMETERS|EXTRAS,'parameter')
    for key,spec in {**collage.SPEC,**collage.effects.SPEC}.items():
        if key in raw: _number(raw[key],spec[0],spec[1],key)
    for key in ('shape_weights','shape_locks','line_shape_colors','node_end_shapes'):
        if key in raw: _object(raw[key],shapes.NAMES,key)
    for key in ('multi_shape','node_by_shape','line_by_shape','line_tone_gradient','line_opacity_gradient'):
        if key in raw and not isinstance(raw[key],bool): raise ValueError(key+' must be true or false.')
    if 'grain_source_id' in raw and (not isinstance(raw['grain_source_id'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{0,128}',raw['grain_source_id'])):
        raise ValueError('Invalid custom grain source identifier.')
    if 'gradient_stops' in raw:
        stops=raw['gradient_stops']
        if not isinstance(stops,list) or not 1<=len(stops)<=16: raise ValueError('Use between 1 and 16 gradient stops.')
        for stop in stops:
            _object(stop,{'position','color'},'gradient stop')
            _number(stop.get('position'),0,1,'Gradient stop position')
            if not isinstance(stop.get('color'),str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',stop['color']): raise ValueError('Invalid gradient color.')
    try: p=collage.clean(raw)
    except (TypeError,ValueError,OverflowError) as error: raise ValueError('Invalid parameters: '+str(error)) from error
    if p['grain_source_id'] and p['grain_source_id'] not in store:
        raise ValueError('Custom grain source is unavailable. Import it first.')
    return p


def _points(points,limit,label):
    if not isinstance(points,list) or len(points)>limit: raise ValueError('Invalid '+label+'.')
    for pt in points:
        if not isinstance(pt,(list,tuple)) or len(pt)!=2: raise ValueError('Invalid '+label+' point.')
        for value in pt: _number(value,0,1,label)
    return copy.deepcopy(points)


def _snapshot(raw,p,specs,store):
    _object(raw,{'P','settings','files','strokes','cpts','lines','template','view'},'snapshot')
    _object(raw.get('P',{}),PARAMETERS|EXTRAS,'snapshot parameter')
    s=copy.deepcopy(_object(raw.get('settings',{}),SETTINGS,'snapshot setting'))
    for key in ('w','h','dpi','seed'):
        if key in s: _number(s[key],0 if key in ('w','h','seed') else 10,{'w':200,'h':200,'dpi':1200,'seed':9999}[key],key)
    for key in ('touched','grid','inkOn'):
        if key in s and not isinstance(s[key],bool): raise ValueError(key+' must be true or false.')
    if 'bg' in s and (not isinstance(s['bg'],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',s['bg'])):
        raise ValueError('Invalid background color.')
    enums={'unit':('in','cm','mm'),'fmt':('png','tif','pdf','gif','mp4','map','triptych','lum-png','lum-tif','indesign','txt'),
           'exportMode':('2d','3d'),'lumFmt':('stl','obj','3dm')}
    for key,choices in enums.items():
        if key in s and s[key] not in choices: raise ValueError('Invalid '+key+'.')
    if 'map' in s:
        _object(s['map'],MAP_KEYS,'map setting'); cleaned=_params({**p,**s['map']},store)
        s['map']={k:cleaned[k] for k in s['map']}
    if 'cut' in s:
        _object(s['cut'],CUT_KEYS,'cut setting')
        cut=shapes.clean(s['cut'])
        s['cut']={**{k:v for k,v in cut.items() if k in CUT_KEYS},'stencil_id':str(s['cut'].get('stencil_id',''))[:128]}
    if 'lum' in s:
        lum=_object(s['lum'],LUM_KEYS,'luminosity setting'); s['lum']={**luminosity.clean(lum),**{k:lum[k] for k in ('source_name','source_aspect') if k in lum}}
        if s['lum']['source_id'] and s['lum']['source_id'] not in store: raise ValueError('Luminosity source is unavailable.')
    files=raw.get('files',[])
    if not isinstance(files,list) or len(files)>500: raise ValueError('Too many source files.')
    if len(files)!=len(specs): raise ValueError('Source list does not match the snapshot.')
    result=[]
    for f,spec in zip(files,specs):
        _object(f,FILE_KEYS,'source metadata')
        if f.get('id')!=spec['id'] or f.get('w')!=spec['w'] or f.get('page',1)!=spec['page']+1:
            raise ValueError('Source dimensions or page differ from the snapshot.')
        src=store[spec['id']]
        item=dict(id=spec['id'],name=src.name,w=spec['w'],original_w=f.get('original_w',src.w_in),
                  page=spec['page']+1,pages=src.pages,aspect=src.aspect,pdf=src.pdf,
                  assumed=src.assumed,edited=bool(f.get('edited',False)))
        _number(item['original_w'],.000001,1e6,'Original source width')
        result.append(item)
    strokes=raw.get('strokes',[])
    if not isinstance(strokes,list) or len(strokes)>2000: raise ValueError('Too many guide strokes.')
    strokes=[_points(stroke,10000,'stroke') for stroke in strokes]
    return dict(P=copy.deepcopy(p),settings=s,files=result,strokes=strokes,
                cpts=_points(raw.get('cpts',[[0,0],[1,1]]),256,'curve'),lines=bool(raw.get('lines',False)))


def _specs(raw,store):
    if not isinstance(raw,list) or len(raw)>500: raise ValueError('Invalid source list.')
    out=[]
    for spec in raw:
        _object(spec,{'id','w','page'},'source specification')
        identity=spec.get('id')
        if not isinstance(identity,str) or identity not in store: raise ValueError('Source image is unavailable.')
        width=_number(spec.get('w'),.001,400,'Source width')
        page=_number(spec.get('page',0),0,store[identity].pages-1,'Source page')
        if int(page)!=page: raise ValueError('Source page must be a whole number.')
        out.append(dict(id=identity,w=width,page=int(page)))
    return out


def _view(raw):
    raw=_object(raw or {},{'zoom','x','y'},'view')
    return dict(zoom=_number(raw.get('zoom',1),.001,1000,'Zoom'),
                x=_number(raw.get('x',0),-1e9,1e9,'Pan'),y=_number(raw.get('y',0),-1e9,1e9,'Pan'))


def _json(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')


def _digest(data): return hashlib.sha256(data).hexdigest()


def _drawing(p,specs,store,as_map=False,preview=False):
    if not as_map:
        return collage.compose(p,specs,store,final=True,long_edge=480 if preview else None)[1]
    if not preview:
        data,_=collage.export({**p,'map_file':'png'},specs,store,'map')
        with Image.open(io.BytesIO(data)) as image: return image.copy()
    # Render directly from vector map to keep the archive preview small at any
    # canvas size, without a JPEG round trip or full-resolution intermediate.
    with collage.pymupdf.open(stream=collage.migration_pdf(p,specs,store),filetype='pdf') as doc:
        page=doc[0];ratio=480/max(page.rect.width,page.rect.height)
        pix=page.get_pixmap(matrix=collage.pymupdf.Matrix(ratio,ratio),alpha=False)
        image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        image.thumbnail((480,480),Image.Resampling.LANCZOS)
        return image


def save(request,store,kind='project'):
    if kind not in ('project','png'): raise ValueError('Unknown project format.')
    p=_params(request.get('p',{}),store); specs=_specs(request.get('sources',[]),store)
    snapshot=_snapshot(request.get('snapshot',{}),p,specs,store)
    identities={s['id'] for s in specs}
    if p['grain_source_id']: identities.add(p['grain_source_id'])
    lum=snapshot['settings'].get('lum',{})
    if lum.get('source_id'): identities.add(lum['source_id'])
    members={}; sources=[]
    for index,identity in enumerate(sorted(identities)):
        src=store[identity]; path=f'sources/{index}.bin';members[path]=src.data
        sources.append(dict(id=identity,name=src.name,path=path,sha256=_digest(src.data)))
    manifest=dict(format='morphaic project',schema_version=1,snapshot=snapshot,sources=sources,
                  specs=specs,view=_view(request.get('view')),template=None)
    template=request.get('template')
    if template and template.get('id'):
        import indesign
        _tree(template)
        item=indesign.TEMPLATES.get(template.get('id'))
        if not item: raise ValueError('InDesign template is unavailable.')
        data=Path(item['path']).read_bytes(); members['template/original.bin']=data
        manifest['template']=dict(name=item['name'],frames=item['frames'],path='template/original.bin',sha256=_digest(data),
                                   mapping=template.get('mapping',{}),fit=template.get('fit','contain'),title=str(template.get('title',''))[:255])
    if specs:
        preview=_drawing(p,specs,store,as_map=bool(request.get('map')),preview=True)
        b=io.BytesIO();preview.save(b,'PNG',optimize=True);members['preview.png']=b.getvalue()
    members['manifest.json']=_json(manifest)
    if len(members['manifest.json'])>MAX_MANIFEST_BYTES: raise ValueError('Project settings are too large.')
    if sum(map(len,members.values()))>MAX_PROJECT_BYTES: raise ValueError('Project exceeds 1 GiB.')
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path,data in members.items(): z.writestr(path,data)
    archive=b.getvalue()
    if kind=='project':
        if len(archive)>MAX_PROJECT_BYTES: raise ValueError('Project exceeds 1 GiB.')
        return archive,'morphaic-project.morphaic'
    if not specs: raise ValueError('Add an image or PDF before saving a project PNG.')
    im=_drawing(p,specs,store,as_map=bool(request.get('map'))); b=io.BytesIO();im.save(b,'PNG')
    png=b.getvalue();chunk=b'moRp'+archive
    output=png[:-12]+struct.pack('>I',len(archive))+chunk+struct.pack('>I',zlib.crc32(chunk)&0xffffffff)+png[-12:]
    if len(output)>MAX_PROJECT_BYTES: raise ValueError('Project PNG exceeds 1 GiB.')
    return output,'morphaic-project.png'


def _embedded(data):
    offset=8; result=None;ended=False
    while offset<len(data):
        if offset+12>len(data): raise ValueError('Truncated project PNG.')
        size=struct.unpack('>I',data[offset:offset+4])[0];end=offset+12+size
        if end>len(data): raise ValueError('Truncated project PNG chunk.')
        kind=data[offset+4:offset+8];payload=data[offset+8:end-4]
        if zlib.crc32(data[offset+4:end-4])&0xffffffff!=struct.unpack('>I',data[end-4:end])[0]:
            raise ValueError('Project PNG checksum failed.')
        if kind==b'moRp':
            if result is not None: raise ValueError('Duplicate embedded project.')
            result=payload
        offset=end
        if kind==b'IEND': ended=True;break
    if result is None or not ended or offset!=len(data): raise ValueError('PNG has no valid embedded Morphaic project.')
    return result


def load(data,store):
    if not isinstance(data,bytes) or len(data)>MAX_PROJECT_BYTES: raise ValueError('Project exceeds 1 GiB.')
    if data.startswith(b'\x89PNG\r\n\x1a\n'): data=_embedded(data)
    staged={};template_item=None;template_path=None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos=z.infolist();names=[i.filename for i in infos]
            if len(infos)>MAX_MEMBERS or len(set(names))!=len(names): raise ValueError('Duplicate or excessive archive members.')
            if any(i.file_size<0 or i.flag_bits&1 or i.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) for i in infos): raise ValueError('Unsupported archive encoding.')
            if sum(i.file_size for i in infos)>MAX_PROJECT_BYTES: raise ValueError('Expanded project exceeds 1 GiB.')
            if 'manifest.json' not in names or z.getinfo('manifest.json').file_size>MAX_MANIFEST_BYTES: raise ValueError('Missing or oversized project manifest.')
            manifest=json.loads(z.read('manifest.json'));_tree(manifest)
            _object(manifest,{'format','schema_version','snapshot','sources','specs','view','template'},'project manifest')
            if manifest.get('format')!='morphaic project' or manifest.get('schema_version')!=1: raise ValueError('Unsupported Morphaic project version.')
            records=manifest['sources']
            if not isinstance(records,list) or len(records)>500: raise ValueError('Too many project sources.')
            allowed={'manifest.json','preview.png'};old={};remap={}
            for index,record in enumerate(records):
                _object(record,{'id','name','path','sha256'},'archived source')
                path=f'sources/{index}.bin'
                if record['path']!=path or record['id'] in old: raise ValueError('Invalid archived source identity or path.')
                identity=record['id'];_number(len(identity),1,128,'Source identity length')
                blob=z.read(path)
                if _digest(blob)!=record['sha256']: raise ValueError('Source checksum failed.')
                name=record['name']
                if not isinstance(name,str) or len(name)>255: raise ValueError('Invalid source name.')
                old[identity]=collage.open_source(name,blob);new=uuid.uuid4().hex
                remap[identity]=new;staged[new]=old[identity];allowed.add(path)
            p=_params(manifest['snapshot']['P'],old);specs=_specs(manifest['specs'],old)
            snap=_snapshot(manifest['snapshot'],p,specs,old);view=_view(manifest.get('view'))
            for f in snap['files']: f['id']=remap[f['id']]
            if p['grain_source_id']: snap['P']['grain_source_id']=remap[p['grain_source_id']]
            lum=snap['settings'].get('lum',{})
            if lum.get('source_id'): lum['source_id']=remap[lum['source_id']]
            template=manifest.get('template');public_template=None
            if template:
                import indesign
                _object(template,{'name','frames','path','sha256','mapping','fit','title'},'template')
                name=template['name'];suffix=Path(name).suffix.lower()
                if suffix not in ('.indd','.indt','.idml') or template['path']!='template/original.bin': raise ValueError('Invalid template format.')
                blob=z.read('template/original.bin');allowed.add('template/original.bin')
                if len(blob)>indesign.MAX_TEMPLATE_BYTES or _digest(blob)!=template['sha256']: raise ValueError('Template checksum or size failed.')
                frames=template['frames']
                if not isinstance(frames,list) or len(frames)>10000 or any(not isinstance(f,dict) or 'key' not in f for f in frames): raise ValueError('Invalid template frames.')
                mapping=template.get('mapping',{})
                if not isinstance(mapping,dict) or set(mapping)-{str(f['key']) for f in frames}: raise ValueError('Invalid template assignments.')
                choices={'collage','initial','migration','final','map',''}|{f'source:{i+1}' for i in range(len(specs))}
                if any(v not in choices for v in mapping.values()) or template.get('fit') not in ('contain','cover'): raise ValueError('Invalid template assignments or fit.')
                identity=uuid.uuid4().hex;template_path=Path(indesign.SESSION.name)/(identity+suffix)
                template_item=dict(id=identity,name=name,path=str(template_path),frames=frames)
                public_template={k:v for k,v in template_item.items() if k!='path'}
                public_template.update(mapping=mapping,fit=template['fit'],title=str(template.get('title',''))[:255])
            if set(names)-allowed: raise ValueError('Unexpected archive member or unsafe path.')
            if 'preview.png' in names:
                if z.getinfo('preview.png').file_size>4*1024**2: raise ValueError('Oversized preview image.')
                with Image.open(io.BytesIO(z.read('preview.png'))) as preview:
                    if preview.format!='PNG' or max(preview.size)>480: raise ValueError('Invalid preview image.')
                    preview.verify()
        if template_item:
            template_path.write_bytes(blob)
            indesign.TEMPLATES[template_item['id']]=template_item
        store.update(staged)
        return dict(snapshot=snap,view=view,template=public_template)
    except (ValueError,KeyError,TypeError,IndexError,OverflowError,RecursionError,OSError,zipfile.BadZipFile,NotImplementedError,RuntimeError) as error:
        if template_path is not None: template_path.unlink(missing_ok=True)
        raise ValueError('Cannot open project: '+str(error)) from error


def parse_settings(text,current,store):
    if not isinstance(text,str) or len(text.encode('utf-8'))>MAX_MANIFEST_BYTES: raise ValueError('Settings text exceeds 4 MiB.')
    try: document=json.loads(text);_tree(document)
    except (ValueError,RecursionError) as error: raise ValueError('Settings must be valid finite JSON: '+str(error)) from error
    out={}
    if isinstance(document,dict) and document.get('format')=='morphaic settings':
        _object(document,{'format','schema_version','parameters','units','guides','portion_linework','sources','luminosity'},'settings document')
        if document.get('schema_version')!=1: raise ValueError('Unsupported settings schema.')
        raw=document.get('parameters',{})
        if 'units' in document:
            if document['units'] not in ('in','cm','mm'): raise ValueError('Unknown settings unit.')
            out['unit']=document['units']
        if 'guides' in document:
            guides=_object(document['guides'],{'grid_visible'},'guide setting')
            if 'grid_visible' in guides: out['grid_visible']=bool(guides['grid_visible'])
        if 'portion_linework' in document: out['lines']=bool(document['portion_linework'])
        if 'luminosity' in document:
            lum=_object(document['luminosity'],LUM_KEYS,'luminosity setting')
            out['luminosity']={**current.get('luminosity',{}),**lum}
            luminosity.clean(out['luminosity'])
    else: raw=document
    _object(raw,PARAMETERS|EXTRAS,'parameter')
    out['p']=_params({**current.get('p',{}),**raw},store)
    return out
