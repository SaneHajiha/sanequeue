"""Isolated CPU Persian NeMo-CTC adapter, streaming Silero VAD before ASR.

Run only in the separately limited subprocess worker (one CPU thread, bounded
wall clock and MemoryMax). Model installation/licensing is an operator task.
Nothing is downloaded. PCM must already be authorized, mono PCM16 at 16 kHz.
VAD API: https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/vad-with-non-streaming-asr.py
"""
import argparse
from contextlib import contextmanager
import importlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import time
import wave

RATE=16000
WINDOW=512
MAX_BYTES=128*1024*1024
MAX_RESULT=2*1024*1024


class LocalASRFailure(RuntimeError):pass


def _asset(value):
    path=Path(value).absolute()
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents) or not path.is_file():
        raise LocalASRFailure('asr_local_asset_unavailable')
    return path


def _runtime():
    for name in ('OMP_NUM_THREADS','OMP_THREAD_LIMIT','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[name]='1'
    try:return importlib.import_module('numpy'),importlib.import_module('sherpa_onnx')
    except ImportError:raise LocalASRFailure('asr_runtime_unavailable') from None


def transcribe(audio,model,tokens,vad,*,maximum_seconds=1800,language='fa',runtime_factory=None):
    wall_start=time.monotonic();cpu_start=time.process_time()
    if language!='fa':raise LocalASRFailure('asr_language_not_supported')
    if isinstance(maximum_seconds,bool) or not isinstance(maximum_seconds,(int,float)) or not math.isfinite(maximum_seconds) or not 1<=maximum_seconds<=1800:
        raise LocalASRFailure('asr_invalid_budget')
    audio,model,tokens,vad=map(_asset,(audio,model,tokens,vad))
    flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)|getattr(os,'O_NONBLOCK',0)
    segments=[];recognizer=None;text_bytes=0;last_end=0;consumed=0;speech_frames=0
    try:
        fd=os.open(audio,flags)
        with os.fdopen(fd,'rb') as source:
            metadata=os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size>MAX_BYTES:raise LocalASRFailure('asr_audio_size_limit')
            with wave.open(source,'rb') as recording:
                if recording.getnchannels()!=1 or recording.getsampwidth()!=2 or recording.getframerate()!=RATE or recording.getcomptype()!='NONE':
                    raise LocalASRFailure('asr_requires_mono_pcm16_16khz')
                frames=recording.getnframes()
                if not 0<frames<=maximum_seconds*RATE:raise LocalASRFailure('asr_audio_duration_limit')
                np,sherpa=(runtime_factory or _runtime)()
                config=sherpa.VadModelConfig();config.silero_vad.model=str(vad)
                config.sample_rate=RATE;config.num_threads=1;config.provider='cpu'
                config.silero_vad.window_size=WINDOW
                config.silero_vad.min_silence_duration=.25
                config.silero_vad.min_speech_duration=.25
                config.silero_vad.max_speech_duration=30
                detector=sherpa.VoiceActivityDetector(config,buffer_size_in_seconds=35)
                def drain():
                    nonlocal recognizer,text_bytes,last_end,speech_frames
                    while not detector.empty():
                        front=detector.front;start=front.start;samples=front.samples
                        if isinstance(start,bool) or not isinstance(start,int) or start<0:raise LocalASRFailure('asr_invalid_vad_output')
                        # Clip final zero-padding and any detector boundary
                        # overlap, preserving the original recording timeline.
                        stop=min(start+len(samples),frames)
                        begin=max(start,last_end);last_end=max(last_end,stop)
                        total=max(0,stop-begin);width=30*RATE
                        tail=total%width
                        if total>width and 0<tail<RATE//4:
                            # VAD's 512-sample boundaries can yield 30.016s.
                            # Do not send the 16ms remainder to a CTC encoder.
                            pieces=(total+width-1)//width
                            width=(total+pieces-1)//pieces
                        for offset in range(begin,max(begin,stop),width):
                            finish=min(offset+width,stop)
                            chunk=samples[offset-start:finish-start]
                            if not np.any(chunk):continue
                            speech_frames+=finish-offset
                            if recognizer is None:
                                recognizer=sherpa.OfflineRecognizer.from_nemo_ctc(model=str(model),tokens=str(tokens),
                                    num_threads=1,sample_rate=RATE,feature_dim=80,decoding_method='greedy_search',provider='cpu',debug=False)
                            stream=recognizer.create_stream();stream.accept_waveform(RATE,chunk)
                            recognizer.decode_stream(stream);text=stream.result.text
                            if not isinstance(text,str):raise LocalASRFailure('asr_invalid_output')
                            text=text.strip()
                            if not text:continue
                            text_bytes+=len(text.encode('utf-8'))
                            if text_bytes>1024*1024 or len(segments)>=10000:raise LocalASRFailure('asr_output_limit')
                            segments.append(dict(start=offset/RATE,end=finish/RATE,text=text))
                        detector.pop()
                while consumed<frames:
                    raw=recording.readframes(min(WINDOW,frames-consumed))
                    if len(raw)%2 or not raw:raise LocalASRFailure('asr_truncated_audio')
                    count=len(raw)//2;consumed+=count
                    samples=np.frombuffer(raw,dtype='<i2').astype('float32')/32768.0
                    if count<WINDOW:samples=np.pad(samples,(0,WINDOW-count))
                    detector.accept_waveform(samples);drain()
                detector.flush();drain()
        text=' '.join(item['text'] for item in segments)
        peak=None
        if sys.platform.startswith('linux'):
            try:
                import resource
                peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
            except (ImportError,OSError,ValueError):pass
        result=dict(text=text,segments=segments,normalized_text=text,
                    analysis=dict(engine='sherpa_onnx_persian_ctc',vad='silero',cpu_threads=1,
                        audio_seconds=frames/RATE,speech_seconds=speech_frames/RATE,
                        wall_seconds=max(0,time.monotonic()-wall_start),cpu_seconds=max(0,time.process_time()-cpu_start),
                        peak_rss_mib=peak,human_review_required=True))
        if len(json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf-8'))>MAX_RESULT:raise LocalASRFailure('asr_output_limit')
        return result
    except LocalASRFailure:raise
    except (OSError,EOFError,wave.Error):raise LocalASRFailure('asr_invalid_audio') from None
    except Exception:raise LocalASRFailure('asr_engine_failed') from None


@contextmanager
def _quiet_native():
    # Dedicated CLI process only: suppress native model diagnostics containing
    # private paths. The caller receives one safe reason code after restoration.
    saved=[];null=None
    try:
        sys.stdout.flush();sys.stderr.flush();null=os.open(os.devnull,os.O_WRONLY)
        for descriptor in (1,2):
            saved.append((descriptor,os.dup(descriptor)));os.dup2(null,descriptor)
        yield
    finally:
        for descriptor,copy in saved:os.dup2(copy,descriptor);os.close(copy)
        if null is not None:os.close(null)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Isolated Persian CPU ASR; no downloads')
    for name in ('audio','model','tokens','vad','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--maximum-seconds',type=float,default=1800)
    parser.add_argument('--language',default='fa')
    args=parser.parse_args(argv);target=Path(args.output).absolute();created=False
    try:
        if target.is_symlink() or target.exists() or any(parent.is_symlink() for parent in target.parents) or not target.parent.is_dir():
            raise LocalASRFailure('asr_output_unavailable')
        with _quiet_native():
            result=transcribe(args.audio,args.model,args.tokens,args.vad,maximum_seconds=args.maximum_seconds,language=args.language)
        payload=json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf-8')
        if len(payload)>MAX_RESULT:raise LocalASRFailure('asr_output_limit')
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0),0o600);created=True
        with os.fdopen(fd,'wb') as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
        return 0
    except (LocalASRFailure,OSError,ValueError) as error:
        if created:target.unlink(missing_ok=True)
        print(str(error) if isinstance(error,LocalASRFailure) else 'asr_output_unavailable',file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
