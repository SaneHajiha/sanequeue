import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from sanequeue.reporting.asr import LocalASR, ASRFailure


class LocalASRTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ('engine','model','vad'):(self.root/name).write_bytes(b'synthetic')
        self.audio=self.root/'speech.wav'
        with wave.open(str(self.audio),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0'*32000)
        self.engine=LocalASR(*(self.root/name for name in ('engine','model','vad')))

    def test_offline_arguments_budgets_and_cleanup(self):
        def process(command,**kwargs):
            self.assertNotIn('shell',kwargs)
            for flag in ('--no-gpu','--vad','-vm'):self.assertIn(flag,command)
            self.assertEqual(kwargs['timeout'],300)
            output=Path(command[command.index('-of')+1]).with_suffix('.json')
            output.write_text(json.dumps({'transcription':[{'offsets':{'from':0,'to':900},'text':'سلام'}]}))
            return subprocess.CompletedProcess(command,0)
        with patch('sanequeue.reporting.asr.subprocess.run',side_effect=process):
            result=self.engine.transcribe(self.audio,scratch=self.root/'scratch')
        self.assertEqual(result['text'],'سلام')
        self.assertTrue(result['human_review_required'])
        self.assertEqual(list((self.root/'scratch').iterdir()),[])

    def test_timeout_and_unavailable_output_are_explicit(self):
        with patch('sanequeue.reporting.asr.subprocess.run',side_effect=subprocess.TimeoutExpired('engine',300)):
            with self.assertRaisesRegex(ASRFailure,'asr_deadline'):
                self.engine.transcribe(self.audio,scratch=self.root/'scratch')
        with patch('sanequeue.reporting.asr.subprocess.run',return_value=subprocess.CompletedProcess([],1)):
            with self.assertRaisesRegex(ASRFailure,'asr_engine_failed'):
                self.engine.transcribe(self.audio,scratch=self.root/'scratch')

    def test_malformed_timestamps_are_not_trusted(self):
        def process(command,**kwargs):
            Path(command[command.index('-of')+1]).with_suffix('.json').write_text(json.dumps(
                {'transcription':[{'offsets':{'from':-1,'to':900},'text':'invalid'}]}))
            return subprocess.CompletedProcess(command,0)
        with patch('sanequeue.reporting.asr.subprocess.run',side_effect=process):
            with self.assertRaisesRegex(ASRFailure,'asr_invalid_output'):
                self.engine.transcribe(self.audio,scratch=self.root/'scratch')
