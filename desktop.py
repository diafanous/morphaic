"""Launch morphaic in a standalone desktop window."""

from __future__ import annotations

import logging
import os
import sys
import threading
import tempfile
import traceback
from pathlib import Path
from urllib.request import urlopen


class DesktopAPI:
    def __init__(self):
        self._window = None
        self._fullscreen = False
        self._maximized = False

    def _bind(self, window):
        self._window = window
        window.events.maximized += lambda: setattr(self, "_maximized", True)
        window.events.restored += lambda: setattr(self, "_maximized", False)

    def set_fullscreen(self, enabled=None):
        enabled = not self._fullscreen if enabled is None else bool(enabled)
        if enabled != self._fullscreen:
            self._window.toggle_fullscreen()
            self._fullscreen = enabled
        return self._fullscreen

    def window_action(self, action):
        if action == 'close':
            self._window.destroy()
        elif action == 'minimize':
            self._window.minimize()
        elif action == 'maximize':
            if self._fullscreen:
                self.set_fullscreen(False)
            elif self._maximized:
                self._window.restore()
            else:
                self._window.maximize()
        else:
            raise ValueError('Unknown window action')

    def window_state(self):
        return {'x': self._window.x, 'y': self._window.y, 'width': self._window.width, 'height': self._window.height,
                'maximized': self._maximized or self._fullscreen}

    def resize_window(self, width, height, x=None, y=None):
        if not self._maximized and not self._fullscreen:
            self._window.resize(max(840, min(8192, int(width))), max(620, min(8192, int(height))))
            if x is not None and y is not None:
                self._window.move(int(x), int(y))

    def choose_folder(self):
        import webview
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None


def app_icon() -> str:
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return str(root / 'assets' / ('morphaic.ico' if sys.platform == 'win32' else 'morphaic.png'))


def create_desktop_window(webview, url, smoke=False):
    api = DesktopAPI()
    window = webview.create_window(
        'morphaic smoke test' if smoke else 'morphaic 1.1.0', url,
        width=840 if smoke else 1280, height=620 if smoke else 900,
        min_size=(840, 620), frameless=True, easy_drag=False, js_api=api,
    )
    api._bind(window)
    return window


def webview_storage_path() -> Path:
    """Keep WebView2's profile in a stable, per-user writable folder."""
    if sys.platform=='darwin':
        path = Path.home()/'Library'/'Application Support'/'Morphaic'/'WebView'
        path.mkdir(parents=True,exist_ok=True)
        return path
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    path = Path(local_app_data) / "Morphaic" / "WebView2"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_gui_smoke_test(url: str, webview) -> None:
    """Exercise the packaged native window, WebView2 backend, and bundled UI."""
    result: dict[str, str | None] = {"error": None, "title": None}
    window = create_desktop_window(webview, url, smoke=True)

    def on_loaded() -> None:
        try:
            title = window.evaluate_js("document.title")
            has_controls = window.evaluate_js(
                "['open', 'pick', 'go', 'unit', 'animpreview', 'node_end_size', 'exportfolder', 'resetAll', 'canvasMenu', 'gradientStops', 'grainImport'].every(id => document.getElementById(id))"
            )
            if str(title).strip().lower() != "morphaic" or not has_controls:
                raise RuntimeError("desktop smoke test loaded an unexpected page")
            if sys.platform == 'win32' and str(window.native.FormBorderStyle) != 'None':
                raise RuntimeError('native title bar should be replaced by app controls')
            if not window.evaluate_js("Boolean(document.querySelector('#windowControls:not([hidden])'))"):
                raise RuntimeError('window control bubble is missing')
            if not window.evaluate_js("document.querySelector('#windowControls').getBoundingClientRect().right <= innerWidth"):
                raise RuntimeError('window controls overflow the header')
            window._js_api.set_fullscreen(True)
            window._js_api.set_fullscreen(False)
            result["title"] = str(title)
        except Exception as error:
            result["error"] = str(error)
        finally:
            window.destroy()

    def on_timeout() -> None:
        result["error"] = "desktop smoke test timed out waiting for the morphaic page"
        write_smoke_error(result["error"])
        try:
            window.destroy()
        except Exception as error:
            write_smoke_error(f"{result['error']}\nCould not close the test window: {error}")

    window.events.loaded += on_loaded
    timeout = threading.Timer(45, on_timeout)
    timeout.daemon = True
    timeout.start()
    try:
        webview.start(storage_path=str(webview_storage_path()), icon=app_icon())
    finally:
        timeout.cancel()

    if result["error"]:
        raise RuntimeError(result["error"])
    if result["title"] is None:
        raise RuntimeError("desktop smoke test closed before the morphaic page loaded")


def write_smoke_error(message: str | None = None) -> None:
    log_path = os.environ.get("COLLAGE_SMOKE_LOG")
    if not log_path:
        temp_dir = Path(tempfile.gettempdir())
        log_path = str(temp_dir / "morphaic-smoke-error.log")
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        detail = message if message is not None else traceback.format_exc()
        Path(log_path).write_text(detail, encoding="utf-8")
    except OSError:
        pass


def configure_smoke_logging(webview) -> None:
    log_path = os.environ.get("COLLAGE_WEBVIEW_LOG")
    if not log_path:
        return

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    logger = webview.logger
    for handler in tuple(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False


def verify_packaged_formats():
    """Exercise the codecs and data files inside the frozen executable."""
    import io
    import collage
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB',(64,48),'#ed6139').save(buf,'HEIF',quality=90)
    source = collage.open_source('smoke.heic',buf.getvalue())
    specs, store = [{'id':'smoke','w':1,'page':0}], {'smoke':source}
    raw = dict(w=1,h=.75,dpi=32,rot=35,scatter=.6,smoothness=4,pace=3)
    for fmt in ('png','tif','pdf','gif','mp4','map','triptych','txt'):
        data,name = collage.export(raw,specs,store,fmt)
        if len(data)<100:
            raise RuntimeError(f'packaged {fmt} export produced no data')
        if fmt=='mp4' and data[4:8]!=b'ftyp':
            raise RuntimeError('packaged MP4 encoder produced an invalid file')
    import luminosity
    relief = dict(width_mm=20,height_mm=15,spacing_mm=2,source='collage')
    for fmt in ('stl','3dm','png','tif'):
        data,_ = luminosity.export(raw,specs,store,relief,fmt)
        if len(data)<100:
            raise RuntimeError(f'packaged luminosity {fmt} export produced no data')
    collage.export({**raw,'cut_shape':'star'},specs,store,'png')
    collage.export({**raw,'exposure':.5,'saturation':.7,'grain':.3,'gradient_amount':.5},specs,store,'png')
    luminosity.export(raw,specs,store,{**relief,'width_mm':1,'height_mm':1,'spacing_mm':.01},'stl')
    luminosity.export(raw,specs,store,{**relief,'width_mm':100,'height_mm':75,'spacing_mm':5,'cleat':True},'3dm')


def main() -> int:
    server = None
    server_thread = None
    smoke_test = "--smoke-test" in sys.argv[1:]
    server_smoke_test = "--server-smoke-test" in sys.argv[1:]
    try:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Diafanous.Morphaic.Test')
        # Keep optional desktop imports inside the handled startup path so a
        # missing WebView2/runtime dependency cannot produce a frozen-app dialog.
        if smoke_test or server_smoke_test:
            os.environ["PYWEBVIEW_LOG"] = "DEBUG"
        import webview
        from server import Handler, Server
        if smoke_test or server_smoke_test:
            configure_smoke_logging(webview)

        # Bind to an OS-assigned loopback port so this app can run alongside the
        # browser version or another desktop instance without port conflicts.
        server = Server(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        if smoke_test or server_smoke_test:
            with urlopen(f"http://127.0.0.1:{port}/", timeout=10) as response:
                page = response.read().decode("utf-8")
                if response.status != 200 or "<!doctype html>" not in page.lower():
                    raise RuntimeError("desktop smoke test could not load the bundled UI")
            with urlopen(f"http://127.0.0.1:{port}/version", timeout=10) as response:
                if response.status != 200 or not response.read():
                    raise RuntimeError("desktop smoke test could not read the server version")
            if smoke_test:
                verify_packaged_formats()
                run_gui_smoke_test(f"http://127.0.0.1:{port}", webview)
            return 0

        create_desktop_window(webview, f"http://127.0.0.1:{port}")
        webview.start(storage_path=str(webview_storage_path()), icon=app_icon())
        return 0
    except Exception as error:
        if smoke_test or server_smoke_test:
            write_smoke_error()
            return 1

        message = f"morphaic could not start.\n\n{error}"
        try:
            import ctypes

            if sys.platform=='darwin':
                from AppKit import NSAlert
                alert = NSAlert.alloc().init()
                alert.setMessageText_('morphaic could not start')
                alert.setInformativeText_(str(error))
                alert.runModal()
            else:
                ctypes.windll.user32.MessageBoxW(0, message, "morphaic", 0x10)
        except Exception:
            pass
        return 1
    finally:
        if server:
            if server_thread and server_thread.is_alive():
                server.shutdown()
            server.server_close()
            if server_thread:
                server_thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
