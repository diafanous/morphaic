"""py server.py [port]  ->  opens the UI at http://127.0.0.1:8765"""
import json
import os
import random
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser
import zipfile
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import collage
import indesign
import luminosity
import shapes
import projects

def resource_root():
    """Return the directory containing bundled data files when frozen."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


ROOT = resource_root()
STORE = {}   # id -> collage.Source, for this session only
ANIMATION_ESTIMATE_LOCK = threading.Lock()


def downloads_folder():
    if os.name == 'nt':
        import ctypes
        folder_id = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID('374DE290-123F-4565-9164-39C4925E467B').bytes_le)
        path = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(path)) == 0:
            result = Path(path.value)
            ctypes.windll.ole32.CoTaskMemFree(path)
            return result
    return Path.home() / 'Downloads'


SETTINGS_ROOT = (Path.home()/'Library'/'Application Support') if sys.platform=='darwin' else Path(os.environ.get('LOCALAPPDATA') or Path.home())
DEFAULT_SETTINGS_PATH = SETTINGS_ROOT / 'Morphaic' / 'settings.json'
LEGACY_SETTINGS_PATH = SETTINGS_ROOT / 'Collage' / 'settings.json'
SETTINGS_PATH = DEFAULT_SETTINGS_PATH
EXPORT_FOLDER = downloads_folder()
try:
    settings_file = SETTINGS_PATH if SETTINGS_PATH.exists() else LEGACY_SETTINGS_PATH
    saved_folder = json.loads(settings_file.read_text(encoding='utf-8')).get('export_folder')
    if saved_folder and Path(saved_folder).is_dir():
        EXPORT_FOLDER = Path(saved_folder)
except (OSError, ValueError, TypeError):
    pass


def set_export_folder(folder):
    global EXPORT_FOLDER
    selected = Path(folder.strip().strip('"')).expanduser().resolve()
    if not selected.is_dir():
        raise ValueError('choose an existing export folder')
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    update_settings({'export_folder': str(selected)})
    EXPORT_FOLDER = selected
    return selected


def read_settings():
    try:
        path = LEGACY_SETTINGS_PATH if SETTINGS_PATH == DEFAULT_SETTINGS_PATH and not SETTINGS_PATH.exists() else SETTINGS_PATH
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):
        return {}


SETTINGS_LOCK = threading.Lock()
MAP_KEYS = tuple(k for k in collage.SPEC if k.startswith('m') and k[1:2] in ('1','2','3')) + tuple(k for k in collage.COLORS if k.startswith('m')) + ('m2s','m2e','node_start','node_end','node_end_size','node_by_shape','node_end_shapes','line_by_shape','line_shape_colors','line_tone_gradient','line_opacity_gradient')


def update_settings(changes):
    with SETTINGS_LOCK:
        data = read_settings()
        data.update(changes)
        write_settings(data)


def write_settings(data):
    SETTINGS_PATH.parent.mkdir(parents=True,exist_ok=True)
    temporary = SETTINGS_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(data),encoding='utf-8')
    temporary.replace(SETTINGS_PATH)


def stencil_library():
    result = []
    items = read_settings().get('stencils', [])
    if not isinstance(items, list):
        return result
    for item in items:
        try:
            result.append({'id': str(item['id']), **shapes.stencil(item)})
        except (KeyError, ValueError, TypeError):
            continue
    return result


def save_stencil(raw):
    stencil = shapes.stencil(raw)
    with SETTINGS_LOCK:
        data = read_settings()
        library = stencil_library()
        sid = str(raw.get('id', ''))
        if sid and not any(item['id'] == sid for item in library):
            raise ValueError('saved stencil no longer exists; save it as a new stencil')
        sid = sid or uuid.uuid4().hex
        saved = {'id': sid, **stencil}
        library = [saved if item['id'] == sid else item for item in library]
        if not any(item['id'] == sid for item in library):
            library.append(saved)
        data['stencils'] = library
        write_settings(data)
    return saved


def map_defaults():
    raw = read_settings().get('map_defaults',{})
    if not isinstance(raw,dict) or not raw:
        return {}
    p = collage.clean(raw)
    return {k:p[k] for k in MAP_KEYS}


def save_map_defaults(raw):
    p = collage.clean(raw)
    defaults = {k:p[k] for k in MAP_KEYS}
    update_settings({'map_defaults':defaults})
    return defaults


def save_export(data, name, folder=None):
    destination = Path(folder) if folder is not None else EXPORT_FOLDER
    if destination == downloads_folder():
        destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise ValueError('export folder no longer exists; select another folder')
    name = Path(name).name
    stem, suffix = Path(name).stem, Path(name).suffix
    for number in range(10000):
        target = destination / (name if number == 0 else f'{stem} ({number}){suffix}')
        try:
            with target.open('xb') as output:
                output.write(data)
            return target.resolve()
        except FileExistsError:
            continue
    raise ValueError('too many files with this export name')
# Changes when the code does. A server still running older code reports a different one, so a new launch won't reuse it.
if getattr(sys, "frozen", False):
    # PyInstaller embeds Python modules in its archive, so their .py files are
    # not present beside the extracted data files. The executable's timestamp
    # is stable across launches and changes when the bundled app is replaced.
    STAMP = str(Path(sys.executable).stat().st_mtime_ns)
else:
    STAMP = str(max((ROOT / f).stat().st_mtime_ns for f in ("collage.py", "animation_gpu.py", "map_gradients.py", "effects.py", "server.py", "luminosity.py", "mounting.py", "shapes.py", "index.html", "studio.js", "controls.js", "iteration.js", "ui.css", "iteration.css", "glass.css", "canvas.js", "templates.js", "color-tools.js", "projects.js", "projects.py", "indesign.py")))
EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif", ".pdf", ".heic", ".heif"}


def add_source(name, data):
    s = collage.open_source(name, data)
    sid = uuid.uuid4().hex[:8]
    STORE[sid] = s
    return dict(id=sid, name=name, pdf=s.pdf, pages=s.pages, w=s.w_in, aspect=s.aspect, assumed=s.assumed)


def pick_files(folder, n):
    """n random images/PDFs from a folder (not its sub-folders) -> (chosen, how many it holds)."""
    d = Path(folder.strip().strip('"'))
    if not d.is_dir():
        raise ValueError(f"not a folder: {folder.strip()}")
    files = [f for f in d.iterdir() if f.suffix.lower() in EXT and f.is_file()]
    if not files:
        raise ValueError("no images or PDFs in that folder")
    return random.sample(files, min(max(n, 1), 50, len(files))), len(files)


@lru_cache
def font(weight):
    """Paper Mono woff2, read straight out of the zip in ./fonts (the linked folder)."""
    for z in (ROOT / "fonts").glob("*.zip"):
        with zipfile.ZipFile(z) as f:
            for n in f.namelist():
                if n.endswith(f"webfonts/PaperMono-{weight}.woff2"):
                    return f.read(n)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body=b"", ctype="application/json", **headers):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in headers.items():
                self.send_header(k.replace("_", "-"), v)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass   # the browser gave up on a stale preview

    def guarded(self, fn):
        host, origin = self.headers.get("Host", ""), self.headers.get("Origin")
        if host.split(":")[0] not in ("127.0.0.1", "localhost") or origin not in (None, "http://" + host):
            return self.reply(403, {"error": "forbidden"})   # DNS rebinding / cross-site POST
        try:
            fn()
        except (ValueError, KeyError, TypeError, IndexError, json.JSONDecodeError) as e:
            self.reply(415 if "can't read" in str(e) else 400, {"error": str(e) or "bad request"})
        except Exception as e:   # keep the server alive; the UI shows the message
            self.reply(500, {"error": f"{type(e).__name__}: {e}"})

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_GET(self):
        def go():
            if self.path == "/version":
                self.reply(200, STAMP.encode(), "text/plain")
            elif self.path == '/export-settings':
                self.reply(200, {'folder': str(EXPORT_FOLDER), 'map_defaults': map_defaults()})
            elif self.path == '/preferences':
                self.reply(200, {'skip_reset_warning': bool(read_settings().get('skip_reset_warning', False))})
            elif self.path == '/animation-capabilities':
                import animation_gpu
                self.reply(200, animation_gpu.capabilities())
            elif self.path == '/indesign/status':
                self.reply(200, {'available': indesign.available()})
            elif self.path == '/stencils':
                self.reply(200, {'stencils': stencil_library()})
            elif self.path == "/":
                self.reply(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path in ('/studio.js', '/controls.js', '/iteration.js', '/canvas.js', '/templates.js', '/color-tools.js', '/projects.js'):
                self.reply(200, (ROOT / self.path[1:]).read_bytes(), 'text/javascript; charset=utf-8')
            elif self.path in ('/ui.css', '/iteration.css', '/glass.css'):
                self.reply(200, (ROOT / self.path[1:]).read_bytes(), 'text/css; charset=utf-8')
            elif self.path == '/favicon.ico':
                self.reply(200, (ROOT / 'assets' / 'morphaic.ico').read_bytes(), 'image/x-icon')
            elif self.path.startswith("/font/") and self.path.endswith(".woff2") and self.path[6:-6] in ("Light", "Regular", "Medium"):
                f = font(self.path[6:-6])
                self.reply(200 if f else 404, f or b"", "font/woff2", Cache_Control="max-age=86400")
            else:
                self.reply(404, {"error": "not found"})
        self.guarded(go)

    def do_POST(self):
        def go():
            if self.path in ('/project/save', '/project/open', '/settings/parse'):
                limit = projects.MAX_PROJECT_BYTES if self.path == '/project/open' else 4 * 1024 * 1024
                if int(self.headers.get('Content-Length') or 0) > limit:
                    raise ValueError('Project or settings request is too large.')
                data = self.body()
                if self.path == '/project/open':
                    self.reply(200, projects.load(data, STORE))
                elif self.path == '/settings/parse':
                    req = json.loads(data)
                    self.reply(200, projects.parse_settings(req['text'], req['current'], STORE))
                else:
                    req = json.loads(data)
                    output, name = projects.save(req, STORE, req.get('kind', 'project'))
                    saved = save_export(output, name)
                    self.reply(200, {'path': str(saved), 'name': saved.name, 'bytes': len(output)})
            elif self.path == '/indesign/template':
                if int(self.headers.get('Content-Length') or 0) > indesign.MAX_TEMPLATE_BYTES:
                    raise ValueError('Choose a template smaller than 150 MB.')
                self.reply(200, indesign.import_template(unquote(self.headers.get('X-Name', 'template')), self.body()))
            elif self.path == '/indesign/export':
                req = json.loads(self.body())
                data, name = indesign.export_template(req['p'], req['sources'], STORE, req.get('template', {}))
                saved = save_export(data, name)
                self.reply(200, {'path': str(saved), 'name': saved.name})
            elif self.path == '/preferences':
                req = json.loads(self.body())
                value = req.get('skip_reset_warning')
                if not isinstance(value, bool):
                    raise ValueError('skip_reset_warning must be true or false')
                update_settings({'skip_reset_warning': value})
                self.reply(200, {'skip_reset_warning': value})
            elif self.path == '/export-settings':
                req = json.loads(self.body())
                self.reply(200, {'folder': str(set_export_folder(str(req['folder'])))})
            elif self.path == '/map-defaults':
                req = json.loads(self.body())
                self.reply(200, {'map_defaults': save_map_defaults(req['settings'])})
            elif self.path == '/stencils':
                self.reply(200, {'stencil': save_stencil(json.loads(self.body()))})
            elif self.path == "/source":
                self.reply(200, add_source(unquote(self.headers.get("X-Name", "untitled")), self.body()))
            elif self.path == "/folder-info":
                req = json.loads(self.body())
                _, total = pick_files(str(req["path"]), 1)
                self.reply(200, dict(total=total))
            elif self.path == "/folder":
                req = json.loads(self.body())
                files, total = pick_files(str(req["path"]), int(req["n"]))
                got, skipped = [], 0
                for f in files:
                    try:
                        got.append(add_source(f.name, f.read_bytes()))
                    except (ValueError, OSError):
                        skipped += 1
                self.reply(200, dict(sources=got, skipped=skipped, total=total))
            elif self.path == "/preview":
                req, t0 = json.loads(self.body()), time.perf_counter()
                jpg = collage.preview(req["p"], req["sources"], STORE, bool(req.get("map")), bool(req.get("grid")))
                p = collage.clean(req['p'])
                counts = shapes.counts(p, collage.layout(p, collage._sizes(req['sources'], STORE), p['w'], p['h']))
                self.reply(200, jpg, "image/jpeg", X_Ms=str(round((time.perf_counter() - t0) * 1000)), X_Cut_Counts=json.dumps(counts))
            elif self.path == '/luminosity/demo':
                self.reply(200, add_source('demo-ripples.png', luminosity.demo_image()))
            elif self.path == '/luminosity/preview':
                req = json.loads(self.body())
                self.reply(200, luminosity.mesh(req['p'], req['sources'], STORE, req['luminosity'], preview=True))
            elif self.path.startswith('/luminosity/export/'):
                req = json.loads(self.body())
                data, name = luminosity.export(req['p'], req['sources'], STORE, req['luminosity'], self.path[19:])
                saved = save_export(data, name)
                self.reply(200, {'path': str(saved), 'name': saved.name})
            elif self.path == '/animation-estimate':
                req = json.loads(self.body())
                if not ANIMATION_ESTIMATE_LOCK.acquire(blocking=False):
                    self.reply(429, {'error':'Another estimate is running; try again in a moment'})
                    return
                try:self.reply(200, collage.animation_estimate(req['p'],req['sources'],STORE,req.get('format','gif')))
                finally:ANIMATION_ESTIMATE_LOCK.release()
            elif self.path.startswith('/animation/'):
                fmt, req = self.path[11:], json.loads(self.body())
                if fmt not in ('gif', 'mp4'):
                    raise ValueError('choose GIF or MP4 for an animation preview')
                data, _ = collage.export(req['p'], req['sources'], STORE, fmt)
                self.reply(200, data, 'image/gif' if fmt == 'gif' else 'video/mp4')
            elif self.path.startswith("/export/"):
                fmt, req = self.path[8:], json.loads(self.body())
                if fmt == 'txt' and 'luminosity' in req:
                    req['p']['luminosity'] = luminosity.clean(req['luminosity'])
                data, name = collage.export(req["p"], req["sources"], STORE, fmt, bool(req.get("lines")))
                saved = save_export(data, name)
                self.reply(200, {'path': str(saved), 'name': saved.name})
            else:
                self.reply(404, {"error": "not found"})
        self.guarded(go)

    def do_DELETE(self):
        def go():
            STORE.pop(self.path.removeprefix("/source/"), None)
            self.reply(200, {})
        self.guarded(go)


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind a port that is already in use, so two servers (one maybe
    # running old code) would share it and the browser would reach either. Refuse instead.
    allow_reuse_address = os.name != "nt"


def running(port):
    """The STAMP of a collage server already on this port, else None."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/version", timeout=1) as r:
            return r.read().decode()
    except OSError:
        return None


if __name__ == "__main__":
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    for port in range(first, first + 10):
        if running(port) == STAMP:   # this exact code is already serving: just show it
            print(f"morphaic is already running at http://127.0.0.1:{port}")
            webbrowser.open(f"http://127.0.0.1:{port}")
            sys.exit()
        try:
            server = Server(("127.0.0.1", port), Handler)
            break
        except OSError:   # busy: another program, or collage still running older code
            continue
    else:
        sys.exit(f"ports {first}-{first + 9} are all busy")
    print(f"morphaic  http://127.0.0.1:{port}  (close this window to quit)")
    threading.Timer(0.4, webbrowser.open, [f"http://127.0.0.1:{port}"]).start()
    server.serve_forever()
