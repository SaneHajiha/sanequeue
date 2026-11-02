"""Optional offline CPU ASR adapter. Invoke from a bounded job worker only.

Model installation and licensing are explicit operator responsibilities. This
module never downloads models, contacts a provider or imports a GPU framework.
Inputs must already be authorized and converted to mono PCM16 at 16 kHz.
"""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave


class ASRFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalASR:
    executable: Path
    model: Path
    vad_model: Path
    threads: int = 1
    timeout_seconds: int = 300
    maximum_audio_seconds: int = 1800

    def transcribe(self, audio, *, scratch, language='fa'):
        if language not in ('fa', 'en') or not 1 <= self.threads <= 2:
            raise ValueError('invalid_asr_options')
        if not 1 <= self.timeout_seconds <= 900 or not 1 <= self.maximum_audio_seconds <= 3600:
            raise ValueError('invalid_asr_budget')
        for path in (self.executable, self.model, self.vad_model, Path(audio)):
            path = Path(path)
            if not path.is_file() or path.is_symlink():
                raise ASRFailure('asr_local_asset_unavailable')
        scratch = Path(scratch)
        if scratch.is_symlink():
            raise ValueError('asr_scratch_symlink')
        scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
        # The temporary directory contains audio/text and must not be served as
        # static content. The caller separately persists authorized job results.
        with tempfile.TemporaryDirectory(prefix='asr-', dir=scratch) as directory:
            root = Path(directory)
            prepared = root/'input.wav'
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
            fd = os.open(audio, flags)
            with os.fdopen(fd, 'rb') as source:
                if os.fstat(source.fileno()).st_size > 128 * 1024 * 1024:
                    raise ValueError('asr_audio_size_limit')
                with wave.open(source) as recording:
                    duration = recording.getnframes()/recording.getframerate()
                    if (recording.getnchannels() != 1 or recording.getsampwidth() != 2
                            or recording.getframerate() != 16000 or recording.getcomptype() != 'NONE'):
                        raise ValueError('asr_requires_mono_pcm16_16khz')
                    if not 0 < duration <= self.maximum_audio_seconds:
                        raise ValueError('asr_audio_duration_limit')
                source.seek(0)
                with prepared.open('wb') as target:
                    shutil.copyfileobj(source, target, 65536)
            prepared.chmod(0o600)
            output = root/'result'
            command = [str(self.executable), '-m', str(self.model), '-f', str(prepared),
                       '-l', language, '-t', str(self.threads), '--no-gpu', '--vad',
                       '-vm', str(self.vad_model), '-oj', '-of', str(output)]
            env = dict(os.environ, OMP_NUM_THREADS=str(self.threads), OMP_THREAD_LIMIT=str(self.threads),
                       OPENBLAS_NUM_THREADS=str(self.threads))
            # No transcript or recording path is emitted to the application log.
            with (root/'engine.log').open('wb') as log:
                try:
                    result = subprocess.run(command, stdout=log, stderr=log, env=env,
                                            timeout=self.timeout_seconds, check=False)
                except subprocess.TimeoutExpired:
                    raise ASRFailure('asr_deadline') from None
            if result.returncode:
                raise ASRFailure('asr_engine_failed')
            path = output.with_suffix('.json')
            if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                raise ASRFailure('asr_output_unavailable')
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                raw_segments = data['transcription']
                if not isinstance(raw_segments, list) or len(raw_segments) > 10000:
                    raise ValueError()
                segments = []
                for raw in raw_segments:
                    start = float(raw['offsets']['from'])/1000
                    end = float(raw['offsets']['to'])/1000
                    text = raw['text']
                    if (not isinstance(text, str) or len(text) > 16384
                            or not all(math.isfinite(v) for v in (start, end))
                            or not 0 <= start <= end <= duration + 2):
                        raise ValueError()
                    if text.strip():
                        segments.append(dict(start=start, end=end, text=text.strip()))
            except (ValueError, TypeError, KeyError):
                raise ASRFailure('asr_invalid_output') from None
            return dict(language=language, segments=segments, text=' '.join(s['text'] for s in segments),
                        audio_seconds=duration, vad=True, engine='whisper.cpp', cpu_only=True,
                        human_review_required=True, recording_offset_ms=None)
