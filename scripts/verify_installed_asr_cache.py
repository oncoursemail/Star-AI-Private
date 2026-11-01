"""Exercise pinned, offline speech-model loading without native engines or weights."""
from hashlib import sha256
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.senses import setup
from star.voice import engines


def main() -> None:
    checks = 0
    with TemporaryDirectory() as temporary:
        folder = Path(temporary)
        weights = folder / 'model.bin'
        original = b'verified speech snapshot'
        weights.write_bytes(original)
        model = setup.AsrModel('small.en', 'publisher/speech', 'fixed-revision', len(original),
                               sha256(original).hexdigest(), 'local verification fixture')
        lookups = []

        def download(name, **kwargs):
            lookups.append((name, kwargs))
            assert kwargs == {'local_files_only': True, 'revision': 'fixed-revision'}
            return str(folder)

        modules = {'faster_whisper.utils': SimpleNamespace(download_model=download)}
        with patch.dict(setup.ASR_MODELS, {'small.en': model}, clear=True), patch.dict(sys.modules, modules):
            assert setup.installed_asr_path('small.en') == str(folder)
            assert lookups == [('small.en', {'local_files_only': True, 'revision': 'fixed-revision'})]
            checks += 1
            assert setup.installed_asr_path('owner-model') is None and len(lookups) == 1
            checks += 1
            for bad in (b'short', b'x' * len(original)):
                weights.write_bytes(bad)
                try:
                    setup.installed_asr_path('small.en')
                except RuntimeError:
                    checks += 1
                else:
                    raise AssertionError('Corrupt installed weights were accepted')
            weights.unlink()
            try:
                setup.installed_asr_path('small.en')
            except RuntimeError:
                checks += 1
            else:
                raise AssertionError('Missing installed weights were accepted')
            weights.write_bytes(original)

            calls = []

            def whisper(source, **kwargs):
                calls.append((source, kwargs))
                if kwargs['device'] == 'cuda':
                    raise RuntimeError('simulated unavailable CUDA provider')
                return object()

            with patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=whisper)}), \
                    patch.object(engines, 'add_nvidia_dll_dirs'), patch('star.home.paths.root', return_value=folder):
                before = len(lookups)
                asr = engines.FasterWhisperASR('small.en', device='cuda')
                assert asr.device == 'cpu' and asr.model_name == 'small.en'
                assert [source for source, kwargs in calls] == [str(folder), str(folder)]
                assert len(lookups) == before + 1
                checks += 1
                calls.clear()
                weights.write_bytes(b'broken')
                try:
                    engines.FasterWhisperASR('small.en', device='cuda')
                except RuntimeError:
                    assert not calls
                    checks += 1
                else:
                    raise AssertionError('Corrupt cache reached native loader or alias fallback')
                calls.clear()
                with patch('star.home.paths.root', return_value=None):
                    engines.FasterWhisperASR('base.en', device='cpu')
                assert calls[0][0] == 'base.en'
                checks += 1
                calls.clear()
                engines.FasterWhisperASR('owner-model', device='cpu')
                assert calls[0][0] == 'owner-model'
                checks += 1
    print(f'Installed ASR cache: {checks} offline, corruption and stable-fallback checks passed')


if __name__ == '__main__':
    main()
