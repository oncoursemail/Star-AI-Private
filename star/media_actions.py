"""Bridge actions for media: the "where to generate" page, the image engine on this PC, and
a project's visual references. Plain functions, so they are tested without the Qt window.

  mediaStatus        the choices with their notes, the image engine's state, sizes, FFmpeg found or not
  mediaStartComfy    start the ComfyUI installed in Settings' folder, on 127.0.0.1 only
  mediaFreeMemory    ask ComfyUI to unload its models (gives the graphics memory back to games)
  listReferences     the project's pinned reference images
  pinReference       pin an image the owner picked (file picker), with a label and a note
  unpinReference     remove STAR's copy of one reference
  compareReference   reference | output side by side, measured facts, the vision model's differences
  imageAbNext        the next unpicked pair of the owner's blind A/B test (two pictures, sides at random)
  imageAbPick        store the owner's pick (left / right / same) and return the summary
  imageAbSummary     counts, the new pipeline's win rate, the sign-test p-value
  imageAbMake        draw one more pair from a prompt: the old pipeline and the new one (minutes)
"""
from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from . import image_gen, media_places, references

MEDIA_ACTIONS = frozenset({'mediaStatus', 'mediaStartComfy', 'mediaFreeMemory',
                           'listReferences', 'pinReference', 'unpinReference', 'compareReference',
                           'imageAbNext', 'imageAbPick', 'imageAbSummary', 'imageAbMake'})
# These talk to ComfyUI or a model and must not run on the interface thread.
SLOW_MEDIA_ACTIONS = frozenset({'mediaStatus', 'mediaStartComfy', 'mediaFreeMemory', 'compareReference', 'imageAbMake'})


class ComfyLauncher:
    """Starts the owner's ComfyUI install for this session and stops what it started."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @staticmethod
    def python_for(base: Path) -> Path | None:
        """ComfyUI's own Python for an install folder (the one `setup_comfyui.sh` makes, or the portable one)."""
        candidates = [base / '.venv' / 'Scripts' / 'python.exe', base / '.venv' / 'bin' / 'python',
                      base.parent / 'python_embeded' / 'python.exe']
        return next((path for path in candidates if path.is_file()), None)

    @staticmethod
    def command(folder: str, port: int) -> tuple[list[str], Path]:
        base = Path(folder).expanduser()
        if not folder or not (base / 'main.py').is_file():
            raise ValueError('Set the ComfyUI folder in Settings → Where STAR generates first '
                             '(the folder that contains main.py).')
        python = ComfyLauncher.python_for(base)
        if python is None:
            raise ValueError("ComfyUI's own Python was not found in that folder (.venv). "
                             'Run scripts/media/setup_comfyui.sh code first.')
        # 127.0.0.1 only: ComfyUI has no sign-in, so it must never listen on the network.
        return [str(python), 'main.py', '--listen', '127.0.0.1', '--port', str(port), '--disable-auto-launch'], base

    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, settings, home: Path, *, wait_seconds: float = 120.0,
              is_up: Callable[[], bool] | None = None) -> dict:
        """Start ComfyUI and wait until it answers (measured: 25 to 28 s on the owner's PC).

        A start that never answers is stopped again, so a hung process is not left holding the
        graphics card (seen once, right after another ComfyUI had been killed by force).
        """
        check = is_up or (lambda: image_gen.status(settings)['running'])
        if check():
            return {'started': False, 'running': True, 'message': 'ComfyUI is already running.'}
        with self._lock:
            if not self.running():
                command, folder = self.command(effective_comfy_home(settings), settings.comfy_port)
                from .gpu_helper import HELPER
                HELPER.yield_to('the image engine is using the graphics card')   # never both on the card
                logs = home / 'logs'
                logs.mkdir(parents=True, exist_ok=True)
                with open(logs / 'comfyui.log', 'ab') as log:
                    self._process = subprocess.Popen(
                        command, cwd=str(folder), stdout=log, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                        env={**os.environ, 'PYTHONUTF8': '1'})
        finish = time.monotonic() + wait_seconds
        while time.monotonic() < finish:
            if check():
                return {'started': True, 'running': True, 'message': 'ComfyUI started on this PC (127.0.0.1 only).'}
            if not self.running():
                raise RuntimeError('ComfyUI stopped right after starting. Its messages are in the STAR data '
                                   'folder under logs/comfyui.log.')
            time.sleep(1.0)
        self.stop()
        raise TimeoutError(f'ComfyUI did not answer within {int(wait_seconds)} seconds, so STAR stopped it again. '
                           'Try Start ComfyUI once more; if it repeats, its messages are in the STAR data folder '
                           'under logs/comfyui.log.')

    def stop(self) -> None:
        """Stop the ComfyUI this launcher started (never one the owner started themselves)."""
        process, self._process = self._process, None
        if process is None or process.poll() is not None:
            return
        if os.name == 'nt':
            # The environment's python.exe is a small launcher with the real interpreter as its child:
            # end the whole tree, or the child would keep the port and the graphics memory.
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
        else:
            process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


COMFY_ENV = 'STAR_COMFY_HOME'


def find_comfy_home(*, env: dict | None = None, data_dir: Path | None = None, search_from: tuple = (),
                    user_home: Path | None = None) -> str:
    """The ComfyUI install STAR may start when the owner has not chosen a folder, or '' if there is none.

    A fixed, short list and nothing else (no disk search): the folder named by STAR_COMFY_HOME; a `media/ComfyUI`
    folder inside STAR's own data folder; and `media/ComfyUI` next to STAR's own folder or up to four levels above
    it, which is where `scripts/media/setup_comfyui.sh` puts it when MEDIA_HOME is the project's `media` folder; and
    `Documents/starai/media/ComfyUI` in the user's profile (the installed app does not run from the project).
    The folders above STAR count only when they are inside the user's own profile, so a folder that another user of
    this PC could create (for example one at the root of a drive) is never run. A folder counts only when it
    has `main.py` and ComfyUI's own Python, exactly what the launcher needs.
    """
    env = os.environ if env is None else env

    def usable(path: Path) -> bool:
        try:
            return (path / 'main.py').is_file() and ComfyLauncher.python_for(path) is not None
        except OSError:
            return False

    named = str(env.get(COMFY_ENV, '') or '').strip()
    if named and usable(Path(named).expanduser()):
        return str(Path(named).expanduser())
    try:
        mine = (data_dir if data_dir is not None else _app_data()) / 'media' / 'ComfyUI'
        if usable(mine):
            return str(mine)
        profile = (user_home if user_home is not None else Path.home()).resolve()
        for start in (search_from or _code_places()):
            start = Path(start).resolve()
            for level in [start, *list(start.parents)[:4]]:
                try:
                    level.relative_to(profile)
                except ValueError:
                    break                       # left the user's profile: stop climbing
                if level == profile:
                    break
                found = level / 'media' / 'ComfyUI'
                if usable(found):
                    return str(found)
        # The project's own media folder in the user's profile, for an installed app that runs from elsewhere.
        project_media = profile / 'Documents' / 'starai' / 'media' / 'ComfyUI'
        if usable(project_media):
            return str(project_media)
    except (OSError, RuntimeError):
        return ''
    return ''


def _app_data() -> Path:
    from .desktop_core import app_data
    return app_data()


def _code_places() -> tuple:
    """Where STAR runs from: its source folder, and the program's folder when it is a built app."""
    places = [Path(__file__).resolve().parents[1]]
    if getattr(sys, 'frozen', False):
        places.append(Path(sys.executable).resolve().parent)
    return tuple(places)


def detect_comfy_home() -> str:
    return find_comfy_home()


def effective_comfy_home(settings) -> str:
    """The folder chosen in Settings; when none is chosen, the one found on its own. A chosen folder is never replaced."""
    chosen = str(getattr(settings, 'comfy_home', '') or '').strip()
    return chosen or detect_comfy_home()


def _data_url(path: Path, side: int = 1600) -> str:
    from .pil_safe import Image
    with Image.open(path) as image:
        shown = image.convert('RGB')
        shown.thumbnail((side, side))
        out = io.BytesIO()
        shown.save(out, format='WEBP', quality=80, method=4)
    return 'data:image/webp;base64,' + base64.b64encode(out.getvalue()).decode('ascii')


def status(settings, home: Path) -> dict:
    from .video_understanding import VideoError, ffmpeg_tools
    try:
        ffmpeg_tools(getattr(settings, 'ffmpeg_dir', ''))
        ffmpeg = {'found': True, 'message': 'FFmpeg found.'}
    except VideoError as exc:
        ffmpeg = {'found': False, 'message': str(exc)}
    measured = media_places.measurements()
    return {'places': media_places.describe(settings, home),
            'images': image_gen.status(settings),
            'sizes': [{'id': key, 'label': image_gen.SIZE_LABELS[key]} for key in image_gen.SIZES],
            'can_start': bool(effective_comfy_home(settings)),
            'detected_home': '' if str(getattr(settings, 'comfy_home', '') or '').strip() else detect_comfy_home(),
            'ffmpeg': ffmpeg,
            'measured_on': str((measured.get('images', {}).get('pc', {}) or {}).get('date', '')),
            'references': len(references.entries(home, settings.project))}


def handle(action: str, body: dict, *, settings, home: Path, allowed_file: Callable[[Path], Path],
           launcher: ComfyLauncher | None = None, cancelled: Callable[[], bool] | None = None,
           ask: Callable | None = None) -> dict:
    """Run one media action. `allowed_file` checks a path against the files the owner picked."""
    if action not in MEDIA_ACTIONS:
        raise PermissionError('Action not permitted')
    project = settings.project
    if action == 'mediaStatus':
        return status(settings, home)
    if action == 'mediaStartComfy':
        if launcher is None:
            raise RuntimeError('Starting ComfyUI is not available here')
        return launcher.start(settings, home)
    if action == 'mediaFreeMemory':
        from .comfy import ComfyClient
        with ComfyClient(port=settings.comfy_port, timeout=10.0) as comfy:
            comfy.status()
            return {'freed': comfy.free()}
    if action == 'imageAbNext':
        from . import image_ab
        return {'pair': image_ab.next_pair(home), 'summary': image_ab.summarize(home)}
    if action == 'imageAbPick':
        from . import image_ab
        return {'summary': image_ab.pick(home, str(body.get('id', '')), str(body.get('side', '')))}
    if action == 'imageAbSummary':
        from . import image_ab
        return image_ab.summarize(home)
    if action == 'imageAbMake':
        from . import image_ab
        pair = image_ab.make_pair(settings, home, str(body.get('prompt', '')), cancel_event=None)
        return {'made': pair['id'], 'summary': image_ab.summarize(home)}
    if action == 'listReferences':
        return {'references': references.listing(home, project), 'limit': references.MAX_REFERENCES,
                'enabled': bool(getattr(settings, 'media_use_references', True))}
    if action == 'pinReference':
        source = allowed_file(Path(str(body.get('file', ''))))
        entry = references.pin(home, project, source, label=str(body.get('label', ''))[:80],
                               note=str(body.get('note', ''))[:400])
        return {'pinned': entry['id'], 'references': references.listing(home, project)}
    if action == 'unpinReference':
        removed = references.unpin(home, project, str(body.get('id', '')))
        return {'removed': removed, 'references': references.listing(home, project)}
    # compareReference
    chosen = body.get('file')
    candidate = allowed_file(Path(str(chosen))) if chosen else image_gen.latest(home)
    if candidate is None:
        raise ValueError('There is no generated image to compare yet. Create one, or choose a file to compare.')
    result = references.compare(settings, home, project, str(body.get('id', '')), candidate,
                                ask=ask, cancelled=cancelled)
    sheet = result.pop('side_by_side')
    return {**result, 'image': _data_url(sheet), 'saved': sheet.name, 'candidate': Path(candidate).name}
