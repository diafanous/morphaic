"""Template-driven placement through the user's installed Windows InDesign."""
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path

import collage

SESSION = tempfile.TemporaryDirectory(prefix='morphaic-templates-')
TEMPLATES = {}
LOCK = threading.Lock()
MAX_TEMPLATE_BYTES = 150 * 1024**2


def available():
    if os.name != 'nt':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'InDesign.Application\CLSID'):
            return True
    except OSError:
        return False


def run_script(config):
    if not available():
        raise ValueError('Template export requires Adobe InDesign installed on Windows.')
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    with LOCK, tempfile.TemporaryDirectory(prefix='morphaic-indesign-') as temporary:
        folder = Path(temporary)
        result_path = folder / 'result.json'
        config = {**config, 'result': str(result_path)}
        script = folder / 'job.jsx'
        script.write_text('var request = '+json.dumps(config, ensure_ascii=True)+';\n'+
                          (root / 'windows' / 'indesign.jsx').read_text(encoding='utf-8'), encoding='utf-8')
        # The script path is an argument, never interpolated into PowerShell code.
        runner = root / 'windows' / 'run-indesign.ps1'
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                     '-File', str(runner), '-ScriptPath', str(script)],
                                    capture_output=True, timeout=240, creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as error:
            raise ValueError('InDesign did not finish in four minutes. Check for an InDesign dialog, then retry.') from error
        if not result_path.exists():
            message = result.stderr.decode(errors='replace').strip()
            raise ValueError('InDesign could not process the template. Open InDesign once and finish any startup dialogs. '+message[:300])
        data = json.loads(result_path.read_text(encoding='utf-8-sig'))
        if not data.get('ok'):
            raise ValueError(data.get('error', 'InDesign template operation failed'))
        return data


def import_template(name, data):
    suffix = Path(name).suffix.lower()
    if suffix not in ('.indd', '.indt', '.idml'):
        raise ValueError('Choose an InDesign .indd, .indt or .idml template.')
    if not data or len(data) > MAX_TEMPLATE_BYTES:
        raise ValueError('Choose a template smaller than 150 MB.')
    identity = uuid.uuid4().hex
    path = Path(SESSION.name) / (identity+suffix)
    path.write_bytes(data)
    try:
        result = run_script({'operation': 'inspect', 'template': str(path)})
        if not result.get('frames'):
            raise ValueError('The template has no image frames. Add a rectangle, oval or polygon frame in InDesign first.')
        item = {'id': identity, 'name': Path(name).name, 'path': str(path), 'frames': result['frames']}
        TEMPLATES[identity] = item
        return {k: v for k, v in item.items() if k != 'path'}
    except Exception:
        path.unlink(missing_ok=True)
        raise


def export_template(raw, specs, store, options):
    template = TEMPLATES.get(str(options.get('template_id', '')))
    if not template:
        raise ValueError('Import an InDesign template first.')
    frames = {str(frame['key']) for frame in template['frames']}
    mapping = options.get('mapping', {})
    if not isinstance(mapping, dict):
        raise ValueError('Choose a drawing for each template frame.')
    choices = {'collage', 'initial', 'migration', 'final', 'map'} | {f'source:{i+1}' for i in range(len(specs))}
    if any(value and (key not in frames or value not in choices) for key, value in mapping.items()):
        raise ValueError('A selected drawing or frame is no longer available. Review the template assignments.')
    selected = {key: value for key, value in mapping.items() if key in frames and value in choices}
    if not selected:
        raise ValueError('Assign at least one drawing to a template frame.')
    fit = options.get('fit', 'contain')
    if fit not in ('contain', 'cover'):
        raise ValueError('Choose fit entire image or fill frame.')
    # Stage beside the finished document; embed replaced graphics so the package
    # remains portable after the temporary folder goes away.
    with tempfile.TemporaryDirectory(prefix='morphaic-layout-') as temporary:
        folder = Path(temporary)
        drawings = {}
        maps = None
        for choice in sorted(set(selected.values())):
            if choice == 'collage':
                data, _ = collage.export(raw, specs, store, 'png')
                extension = '.png'
            elif choice in ('initial', 'migration', 'final', 'map'):
                maps = maps or collage.migration_pdfs(raw, specs, store)
                names = {'initial': 'collage-1-initial.pdf', 'migration': 'collage-2-migration.pdf',
                         'final': 'collage-3-final.pdf', 'map': 'collage-map-layers.pdf'}
                data, extension = maps[names[choice]], '.pdf'
            else:
                spec = specs[int(choice.split(':')[1])-1]
                source, page, _ = collage._spec(spec, store)
                image = collage.raster(source, page, dpi=300)
                buf = io.BytesIO(); image.save(buf, 'PNG'); data, extension = buf.getvalue(), '.png'
            path = folder / (choice.replace(':', '-')+extension)
            path.write_bytes(data);drawings[choice] = str(path)
        title = str(options.get('title', '')).strip()[:200] or 'Morphaic drawing'
        run_script({'operation': 'export', 'template': template['path'], 'output': str(folder),
                    'mapping': selected, 'drawings': drawings, 'fit': fit, 'title': title, 'seed': int(raw.get('seed', 1))})
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for filename in ('morphaic-layout.indd', 'morphaic-layout.idml', 'morphaic-layout.pdf'):
                path = folder / filename
                if not path.exists():
                    raise ValueError('InDesign did not produce the completed layout.')
                archive.write(path, filename)
            archive.writestr('settings.json', collage.settings_text(raw, specs, store))
            archive.writestr('README.txt', 'Morphaic template export\n\nPlaced drawings are embedded. Other template content and links remain as supplied.\nThe original template is unchanged.\n')
        return output.getvalue(), 'morphaic-indesign.zip'
