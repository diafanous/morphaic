"""Native PDF axial gradients, clipped to migration line strokes."""
import math


class LineGradients:
    def __init__(self,page,oc=0):
        self.page=page;self.doc=page.parent;self.functions={};self.counter=0
        kind,value=self.doc.xref_get_key(page.xref,'Resources')
        if kind=='xref':self.resources=int(value.split()[0])
        else:
            self.resources=self.object(value if kind=='dict' else '<<>>')
            self.doc.xref_set_key(page.xref,'Resources',f'{self.resources} 0 R')
        self.oc=oc
        if oc:self.doc.xref_set_key(self.resources,'Properties/MapLineGradient',f'{oc} 0 R')

    def object(self,definition,stream=None):
        xref=self.doc.get_new_xref();self.doc.update_object(xref,definition)
        if stream is not None:self.doc.update_stream(xref,stream)
        return xref

    @staticmethod
    def numbers(values):return ' '.join(f'{value:.8f}' for value in values)

    def function(self,start,end):
        key=tuple(start),tuple(end)
        if key not in self.functions:
            self.functions[key]=self.object(f'<< /FunctionType 2 /Domain [0 1] /C0 [{self.numbers(start)}] /C1 [{self.numbers(end)}] /N 1 >>')
        return self.functions[key]

    def shading(self,coords,start,end,space):
        fn=self.function(start,end)
        return self.object(f'<< /ShadingType 2 /ColorSpace /{space} /Coords [{self.numbers(coords)}] /Function {fn} 0 R /Extend [true true] >>')

    def draw(self,start,end,start_color,end_color,start_opacity,end_opacity,width):
        # PDF coordinates run bottom-up; application geometry runs top-down.
        a=(start[0],self.page.rect.height-start[1]);b=(end[0],self.page.rect.height-end[1])
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        if length<1e-8:return
        coords=(*a,*b)
        shade=self.shading(coords,start_color,end_color,'DeviceRGB')
        if math.isclose(start_opacity,end_opacity,abs_tol=1e-8):
            state=self.object(f'<< /Type /ExtGState /ca {start_opacity:.8f} /CA {start_opacity:.8f} /BM /Normal >>')
        else:
            alpha=self.shading(coords,(start_opacity,),(end_opacity,),'DeviceGray')
            mask=self.object(f'<< /Type /XObject /Subtype /Form /BBox [0 0 {self.page.rect.width} {self.page.rect.height}] '
                f'/Group << /S /Transparency /CS /DeviceGray /I true >> /Resources << /Shading << /Alpha {alpha} 0 R >> >> >>',b'/Alpha sh')
            state=self.object(f'<< /Type /ExtGState /BM /Normal /SMask << /S /Luminosity /G {mask} 0 R /BC [0] >> >>')
        self.counter+=1;name=f'MapGradient{self.counter}'
        self.doc.xref_set_key(self.resources,f'Shading/{name}',f'{shade} 0 R')
        self.doc.xref_set_key(self.resources,f'ExtGState/{name}',f'{state} 0 R')
        nx,ny=-dy/length*width/2,dx/length*width/2
        corners=[(a[0]+nx,a[1]+ny),(b[0]+nx,b[1]+ny),(b[0]-nx,b[1]-ny),(a[0]-nx,a[1]-ny)]
        path=' '.join(self.numbers(point)+(' m' if i==0 else ' l') for i,point in enumerate(corners))
        content=f'q\n'+('/OC /MapLineGradient BDC\n' if self.oc else '')+f'{path} h W n\n/{name} gs /{name} sh\n'+('EMC\n' if self.oc else '')+'Q\n'
        stream=self.object('<<>>',content.encode('ascii'))
        contents=' '.join(f'{xref} 0 R' for xref in self.page.get_contents()+[stream])
        self.doc.xref_set_key(self.page.xref,'Contents',f'[{contents}]')
