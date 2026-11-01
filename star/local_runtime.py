"""Manage a user-supplied llama.cpp executable from STAR Desktop.

STAR's .exe does not bundle third-party model weights or llama.cpp CUDA libraries.
Only an explicitly selected llama-server.exe is started, with fixed arguments,
loopback networking, and no shell expansion. This is a local inference adapter.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import threading
from .model_fleet import inspect_models_dir


class Runtime:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.log_file = None
        self.log_path: Path | None = None
        self.lock = threading.Lock()
        self.mode: str | None = None
        # The process stop() is waiting for. The wait happens outside `lock`, so status() (called from the
        # UI thread on every state refresh) answers at once instead of freezing the window for up to 15 s.
        self._stopping: subprocess.Popen | None = None

    def _close_log(self) -> None:
        if self.log_file:
            try:
                self.log_file.close()
            finally:
                self.log_file = None

    def _ready_to_start(self, busy_message: str) -> None:
        """Called with `lock` held: refuse while a process runs or is stopping; release a dead one's log."""
        if self._stopping is not None:
            raise RuntimeError('STAR Brain is still stopping; try again in a moment')
        if self.process and self.process.poll() is None:
            raise RuntimeError(busy_message)
        # A process that exited by itself still holds its log file open; close it before opening a new one.
        self.process = None
        self._close_log()

    @staticmethod
    def _speculative_flags(speculative: str, max_draft_tokens: int) -> list[str]:
        """Strict opt-in experiment; unsupported llama.cpp builds fail normally.

        ngram-simple reuses patterns from generated context and needs no second
        draft model. It can also SLOW decoding down: benchmark before use.
        """
        if type(speculative) is not str or speculative not in ("off", "ngram-simple"):
            raise ValueError("Unknown speculative decoding mode")
        if type(max_draft_tokens) is not int or not 4 <= max_draft_tokens <= 64:
            raise ValueError("Speculative draft length must be an integer from 4 to 64")
        if speculative == "off":
            return []
        return ["--spec-type", "ngram-simple", "--spec-draft-n-max", str(max_draft_tokens)]

    @staticmethod
    def arguments(executable: Path, model: Path, *, port=8080, context=4096, gpu_layers=25,
                  projector: Path | None = None, speculative: str = "off",
                  max_draft_tokens: int = 16) -> list[str]:
        executable=executable.expanduser().resolve(strict=True)
        model=model.expanduser().resolve(strict=True)
        if executable.name.lower()!='llama-server.exe' or executable.suffix.lower()!='.exe':
            raise ValueError('Choose the llama-server.exe supplied with llama.cpp')
        if model.suffix.lower()!='.gguf' or model.stat().st_size<100000:
            raise ValueError('Choose a downloaded GGUF model file (at least 100 KB)')
        # Whole numbers only, as router_arguments requires: 8080.5 used to reach the command line.
        if (type(port) is not int or not 1024<=port<=65535 or type(context) is not int
                or not 512<=context<=32768 or type(gpu_layers) is not int or not 0<=gpu_layers<=1000):
            raise ValueError('Invalid port, context length or GPU layers')
        args = [str(executable), '-m', str(model), '--host', '127.0.0.1',
                '--port', str(port), '--ctx-size', str(context), '-ngl', str(gpu_layers), '--jinja']
        if projector is not None:
            proj = projector.expanduser().resolve(strict=True)
            if proj.suffix.lower() != '.gguf':
                raise ValueError('Vision projector must be a GGUF file')
            args += ['--mmproj', str(proj)]
        return args + Runtime._speculative_flags(speculative, max_draft_tokens)

    @staticmethod
    def router_arguments(executable: Path, models_dir: Path, *, port=8080,
                         context=4096, gpu_layers=25, max_loaded=1,
                         speculative: str = "off", max_draft_tokens: int = 16) -> list[str]:
        """Dynamic llama.cpp model router, bound strictly to loopback.

        One resident model prevents multiple heavy GGUFs from exhausting RAM.
        """
        executable = Path(executable).expanduser()
        if executable.is_symlink():
            raise ValueError('Server executable must not be a symlink')
        exe = executable.resolve(strict=True)
        if exe.name.lower() != 'llama-server.exe' or not exe.is_file():
            raise ValueError('Choose an installed llama-server.exe')
        inventory = inspect_models_dir(Path(models_dir))
        if (type(port) is not int or not 1024 <= port <= 65535
                or type(context) is not int or not 512 <= context <= 32768
                or type(gpu_layers) is not int or not 0 <= gpu_layers <= 1000
                or max_loaded != 1):
            raise ValueError('Invalid local model router limits')
        return [str(exe), '--models-dir', str(inventory.directory),
                '--models-max', '1', '--host', '127.0.0.1',
                '--port', str(port), '--ctx-size', str(context),
                '-ngl', str(gpu_layers), '-np', '1', '--jinja'] + Runtime._speculative_flags(
                    speculative, max_draft_tokens)

    def start_router(self, executable: Path, models_dir: Path, log_path: Path,
                     *, port=8080, context=4096, gpu_layers=25,
                     speculative: str = "off", max_draft_tokens: int = 16):
        """Start only an explicitly requested, locally installed model router."""
        with self.lock:
            self._ready_to_start('Stop the current managed STAR Brain before starting model router')
            argv = self.router_arguments(executable, models_dir, port=port,
                                         context=context, gpu_layers=gpu_layers,
                                         speculative=speculative,
                                         max_draft_tokens=max_draft_tokens)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._close_log()
            self.log_file = log_path.open('ab')
            self.log_path = log_path
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            try:
                self.process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                    stdout=self.log_file, stderr=subprocess.STDOUT, creationflags=flags)
                self.mode = 'router'
            except Exception:
                self.log_file.close()
                self.log_file = None
                self.mode = None
                raise
            return self.process.pid

    def router_running(self) -> bool:
        with self.lock:
            return bool(self.mode == 'router' and self._stopping is None
                        and self.process and self.process.poll() is None)

    def start(self, executable: Path, model: Path, log_path: Path, *, port=8080,
              context=4096, gpu_layers=25, projector: Path | None = None,
              speculative: str = "off", max_draft_tokens: int = 16):
        with self.lock:
            self._ready_to_start('llama.cpp is already running')
            argv=self.arguments(executable,model,port=port,context=context,gpu_layers=gpu_layers,
                                projector=projector, speculative=speculative,
                                max_draft_tokens=max_draft_tokens)
            log_path.parent.mkdir(parents=True,exist_ok=True)
            self._close_log()
            self.log_file=log_path.open('ab')
            self.log_path=log_path
            flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
            try:
                self.process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=self.log_file,
                    stderr=subprocess.STDOUT,creationflags=flags)
            except Exception:
                self.log_file.close();self.log_file=None
                raise
            self.mode = 'single'
            return self.process.pid

    def stop(self):
        with self.lock:
            process = self.process
            if not process:
                self.mode = None
                return
            owner = self._stopping is None
            if owner:
                self._stopping = process
                if process.poll() is None:
                    process.terminate()
        if not owner:
            # Another caller (a Stop click, then closing the window) is already stopping it: wait as well,
            # so this caller also returns only once the process is gone.
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
            return
        try:
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            with self.lock:
                self._stopping = None
                # Forget the process only once it has really exited; otherwise it still holds the port.
                if self.process is process and process.poll() is not None:
                    self.process = None
                    self.mode = None
                    self._close_log()

    def status(self):
        with self.lock:
            if self._stopping is not None:return 'stopping'
            if not self.process:return 'not started'
            return 'running' if self.process.poll() is None else f'exited ({self.process.returncode})'
