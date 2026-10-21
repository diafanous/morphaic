"""Optional OpenGL compositing. Pillow still prepares exact masks and transforms."""
import logging
import subprocess
import sys
from array import array
from functools import lru_cache

from PIL import Image, ImageColor

log = logging.getLogger(__name__)


class Compositor:
    def __init__(self, size):
        import moderngl
        self.ctx = moderngl.create_standalone_context(require=330)
        self.resources = []
        try:
            renderer = self.ctx.info.get('GL_RENDERER', '')
            if any(word in renderer.lower() for word in ('llvmpipe', 'softpipe', 'software', 'gdi generic')):
                raise RuntimeError('Only a software OpenGL renderer is available')
            if max(size) > self.ctx.info['GL_MAX_TEXTURE_SIZE']:
                raise RuntimeError('Selected resolution exceeds the GPU texture limit')
            self.renderer, self.size = renderer, size
            self.texture = self.ctx.texture(size, 4)
            self.resources.append(self.texture)
            self.fbo = self.ctx.framebuffer(color_attachments=[self.texture])
            self.resources.append(self.fbo)
            self.program = self.ctx.program(vertex_shader='''
                #version 330
                in vec2 position; in vec2 uv; out vec2 texcoord;
                void main(){gl_Position=vec4(position,0,1);texcoord=uv;}
            ''', fragment_shader='''
                #version 330
                uniform sampler2D image; uniform sampler2D mask;
                in vec2 texcoord; out vec4 color;
                void main(){color=vec4(texture(image,texcoord).rgb,texture(mask,texcoord).r);}
            ''')
            self.resources.append(self.program)
            self.program['image'].value=0;self.program['mask'].value=1
            self.vertices=self.ctx.buffer(reserve=64);self.resources.append(self.vertices)
            self.quad=self.ctx.vertex_array(self.program,[(self.vertices,'2f 2f','position','uv')])
            self.resources.append(self.quad)
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func=moderngl.SRC_ALPHA,moderngl.ONE_MINUS_SRC_ALPHA
        except Exception:
            self.close();raise

    def clear(self, background):
        self.fbo.use();self.ctx.viewport=(0,0,*self.size)
        self.fbo.clear(*(v/255 for v in ImageColor.getrgb(background)),1)

    def paste(self, tile, mask, position):
        import moderngl
        mask = (mask.getchannel('A') if mask.mode=='RGBA' else mask) if mask is not None else Image.new('L',tile.size,255)
        x,y=position;w,h=tile.size;cw,ch=self.size
        left,right=2*x/cw-1,2*(x+w)/cw-1
        top,bottom=1-2*y/ch,1-2*(y+h)/ch
        self.vertices.write(array('f',[left,top,0,0,right,top,1,0,left,bottom,0,1,right,bottom,1,1]))
        image_tex=self.ctx.texture(tile.size,3,tile.convert('RGB').tobytes(),alignment=1)
        mask_tex=None
        try:
            mask_tex=self.ctx.texture(tile.size,1,mask.tobytes(),alignment=1)
            for unit,texture in enumerate((image_tex,mask_tex)):
                texture.filter=(moderngl.NEAREST,moderngl.NEAREST);texture.use(unit)
            self.quad.render(moderngl.TRIANGLE_STRIP)
        finally:
            image_tex.release()
            if mask_tex is not None:mask_tex.release()

    def image(self):
        return Image.frombytes('RGB',self.size,self.fbo.read(components=3,alignment=1)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    def close(self):
        for resource in reversed(self.resources):resource.release()
        self.resources.clear();self.ctx.release()


def create(size):
    try:return Compositor(size)
    except Exception as error:
        log.warning('GPU compositing unavailable; using CPU: %s',error)
        return None


@lru_cache(maxsize=1)
def capabilities():
    try:
        renderer=Compositor((2,2))
        try:return {'available':True,'renderer':renderer.renderer,'reason':''}
        finally:renderer.close()
    except Exception as error:
        return {'available':False,'renderer':'CPU','reason':str(error)}


@lru_cache(maxsize=1)
def video_encoder():
    """Test actual encoding, not merely whether FFmpeg lists a codec."""
    import imageio_ffmpeg
    codecs=['h264_videotoolbox'] if sys.platform=='darwin' else ['h264_nvenc','h264_qsv','h264_amf']
    for codec in codecs:
        try:
            result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i',
                'color=c=black:s=128x128:d=0.1','-frames:v','1','-c:v',codec,'-pix_fmt','yuv420p','-f','null','-'],
                capture_output=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode==0:return codec
        except (OSError,subprocess.TimeoutExpired):pass
    return 'libx264'
