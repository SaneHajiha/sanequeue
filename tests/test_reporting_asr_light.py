from array import array
from contextlib import nullcontext
import io
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import wave

from sanequeue.reporting.asr_light import transcribe,main,LocalASRFailure,RATE


class Samples:
    def __init__(self,values):self.values=list(values)
    def __len__(self):return len(self.values)
    def __getitem__(self,key):return Samples(self.values[key]) if isinstance(key,slice) else self.values[key]
    def astype(self,kind):return self
    def __truediv__(self,value):return Samples(item/value for item in self.values)


class Numpy:
    @staticmethod
    def frombuffer(raw,dtype):
        assert dtype=='<i2'
        return Samples(struct.unpack('<'+'h'*(len(raw)//2),raw))
    @staticmethod
    def pad(samples,pad):return Samples(samples.values+[0]*pad[1])
    @staticmethod
    def any(samples):return any(samples.values)


class Detector:
    def __init__(self,parts):self.parts=parts;self.ready=[];self.read_sizes=[];self.flushed=False
    def accept_waveform(self,samples):self.read_sizes.append(len(samples))
    def flush(self):self.ready=list(self.parts);self.flushed=True
    def empty(self):return not self.ready
    @property
    def front(self):return self.ready[0]
    def pop(self):self.ready.pop(0)


class ASRLightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.assets=[self.root/name for name in ('model.onnx','tokens.txt','vad.onnx')]
        for asset in self.assets:asset.write_bytes(b'model-test')
        self.audio=self.root/'audio.wav';self.wav()

    def wav(self,seconds=1,channels=1,rate=RATE):
        with wave.open(str(self.audio),'wb') as output:
            output.setnchannels(channels);output.setsampwidth(2);output.setframerate(rate)
            output.writeframes(array('h',[1000]*(int(seconds*rate)*channels)).tobytes())

    def runtime(self,parts=(),text='گفتار فارسی'):
        detector=Detector(parts);config=SimpleNamespace(silero_vad=SimpleNamespace())
        accepted=[]
        def stream():
            return SimpleNamespace(result=SimpleNamespace(text=text),accept_waveform=lambda rate,samples:accepted.append((rate,len(samples))))
        recognizer=SimpleNamespace(create_stream=stream,decode_stream=Mock())
        factory=Mock(return_value=recognizer)
        sherpa=SimpleNamespace(VadModelConfig=Mock(return_value=config),
            VoiceActivityDetector=Mock(return_value=detector),OfflineRecognizer=SimpleNamespace(from_nemo_ctc=factory))
        return lambda:(Numpy,sherpa),detector,config,factory,accepted

    def run_asr(self,runtime,**kwargs):return transcribe(self.audio,*self.assets,runtime_factory=runtime,**kwargs)

    def test_silence_does_not_load_recognizer_and_reads_bounded_windows(self):
        runtime,detector,config,factory,accepted=self.runtime()
        result=self.run_asr(runtime)
        self.assertEqual(result['text'],'');self.assertEqual(result['segments'],[])
        self.assertEqual(result['normalized_text'],'');factory.assert_not_called()
        self.assertTrue(detector.flushed);self.assertTrue(all(size==512 for size in detector.read_sizes))
        self.assertEqual(config.num_threads,1);self.assertEqual(config.provider,'cpu')
        self.assertEqual(config.silero_vad.max_speech_duration,30)
        self.assertEqual(result['analysis']['speech_seconds'],0)

    def test_zero_vad_false_positive_is_not_sent_to_asr(self):
        part=SimpleNamespace(start=0,samples=Samples([0]*RATE))
        runtime,_,_,factory,_=self.runtime([part]);result=self.run_asr(runtime)
        factory.assert_not_called();self.assertEqual(result['segments'],[])

    def test_segment_offsets_keep_original_timeline_and_cpu_settings(self):
        self.wav(5)
        runtime,_,_,factory,accepted=self.runtime([SimpleNamespace(start=2*RATE,samples=Samples([1]*(2*RATE)))])
        result=self.run_asr(runtime)
        self.assertEqual(result['segments'],[dict(start=2,end=4,text='گفتار فارسی')])
        self.assertEqual(accepted,[(RATE,2*RATE)])
        self.assertEqual(factory.call_args.kwargs['num_threads'],1)
        self.assertEqual(factory.call_args.kwargs['provider'],'cpu')
        self.assertEqual(factory.call_args.kwargs['decoding_method'],'greedy_search')
        self.assertEqual(result['analysis']['audio_seconds'],5)
        self.assertEqual(result['analysis']['speech_seconds'],2)
        self.assertEqual(result['analysis']['engine'],'sherpa_onnx_persian_ctc')
        self.assertEqual(result['analysis']['vad'],'silero')
        for metric in ('wall_seconds','cpu_seconds'):self.assertGreaterEqual(result['analysis'][metric],0)

    def test_long_speech_split_at_thirty_seconds_without_overlap(self):
        self.wav(35)
        parts=[SimpleNamespace(start=RATE,samples=Samples([1]*(33*RATE))),
               SimpleNamespace(start=33*RATE,samples=Samples([1]*(3*RATE)))]
        runtime,_,_,_,accepted=self.runtime(parts)
        result=self.run_asr(runtime)
        self.assertEqual([(s['start'],s['end']) for s in result['segments']],[(1,31),(31,34),(34,35)])
        self.assertTrue(all(size<=30*RATE for _,size in accepted))
        self.assertEqual(result['analysis']['speech_seconds'],34)

    def test_pcm_format_language_duration_and_truncated_input_are_rejected(self):
        runtime,*_=self.runtime()
        with self.assertRaisesRegex(LocalASRFailure,'asr_language_not_supported'):self.run_asr(runtime,language='en')
        self.wav(channels=2)
        with self.assertRaisesRegex(LocalASRFailure,'asr_requires_mono_pcm16_16khz'):self.run_asr(runtime)
        self.wav(seconds=2)
        with self.assertRaisesRegex(LocalASRFailure,'asr_audio_duration_limit'):self.run_asr(runtime,maximum_seconds=1)
        raw=self.audio.read_bytes();self.audio.write_bytes(raw[:-100])
        with self.assertRaisesRegex(LocalASRFailure,'asr_truncated_audio'):self.run_asr(runtime)

    def test_vad_thirty_point_zero_sixteen_seconds_has_no_tiny_tail_or_overlap(self):
        self.wav(31)
        length=30*RATE+256
        runtime,_,_,_,accepted=self.runtime([SimpleNamespace(start=RATE//2,samples=Samples([1]*length))])
        result=self.run_asr(runtime);segments=result['segments']
        self.assertEqual(len(segments),2)
        self.assertEqual(segments[0]['start'],.5)
        self.assertEqual(segments[0]['end'],segments[1]['start'])
        self.assertEqual(segments[1]['end'],.5+length/RATE)
        self.assertEqual(sum(size for _,size in accepted),length)
        self.assertTrue(all(RATE//4<=size<=30*RATE for _,size in accepted))

    def test_asset_symlink_and_missing_assets_fail_before_runtime(self):
        runtime=Mock(side_effect=AssertionError('must not import runtime'))
        self.assets[0].unlink()
        with self.assertRaisesRegex(LocalASRFailure,'asr_local_asset_unavailable'):self.run_asr(runtime)
        runtime.assert_not_called()
        self.assets[0].write_bytes(b'x')
        link=self.root/'alias.onnx'
        try:link.symlink_to(self.assets[0])
        except OSError:return
        with self.assertRaisesRegex(LocalASRFailure,'asr_local_asset_unavailable'):
            transcribe(self.audio,link,*self.assets[1:],runtime_factory=runtime)

    def test_output_limit_and_engine_failure_hide_private_messages(self):
        runtime,*_=self.runtime([SimpleNamespace(start=0,samples=Samples([1]*RATE))],text='x'*(1024*1024+1))
        with self.assertRaisesRegex(LocalASRFailure,'asr_output_limit'):self.run_asr(runtime)
        runtime=Mock(side_effect=RuntimeError('/private/secret model path'))
        with self.assertRaisesRegex(LocalASRFailure,'^asr_engine_failed$'):self.run_asr(runtime)

    def test_cli_private_exclusive_output_and_no_transcript_stdout(self):
        output=self.root/'result.json';stdout=io.StringIO();stderr=io.StringIO()
        result=dict(text='private transcript',segments=[],normalized_text='private transcript',analysis={})
        args=['--audio',str(self.audio),'--model',str(self.assets[0]),'--tokens',str(self.assets[1]),
              '--vad',str(self.assets[2]),'--output',str(output)]
        with patch('sanequeue.reporting.asr_light.transcribe',return_value=result),\
             patch('sanequeue.reporting.asr_light._quiet_native',return_value=nullcontext()),\
             patch('sys.stdout',stdout),patch('sys.stderr',stderr):
            self.assertEqual(main(args),0)
            self.assertEqual(main(args),2)
        self.assertEqual(stdout.getvalue(),'');self.assertNotIn('private transcript',stderr.getvalue())
        self.assertEqual(json.loads(output.read_text(encoding='utf-8')),result)
        if os.name!='nt':self.assertEqual(output.stat().st_mode&0o777,0o600)


if __name__=='__main__':unittest.main()
