"""Metadata fixtures test duration parsing, not perceptual audio validity."""
import builtins
import importlib.util
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from sanequeue.reporting.audio import duration_seconds,AudioDurationUnavailable


def mp3_metadata():
    # Four MPEG-1 Layer III frames plus an explicit Xing frame-count header.
    frame=bytearray(b'\xff\xfb\x90\x00'+bytes(413))
    frame[36:48]=b'Xing'+struct.pack('>II',1,4)
    return bytes(frame)+(b'\xff\xfb\x90\x00'+bytes(413))*3


def _ogg_page(packet,sequence,flags,granule):
    header=b'OggS'+bytes([0,flags])+struct.pack('<QII',granule,123,sequence)+bytes(4)+bytes([1,len(packet)])
    data=bytearray(header+packet);crc=0
    for value in data:
        crc^=value<<24
        for _ in range(8):crc=((crc<<1)^0x04c11db7 if crc&0x80000000 else crc<<1)&0xffffffff
    data[22:26]=struct.pack('<I',crc);return bytes(data)


def ogg_metadata():
    # Ogg Opus identification, comment and EOS granule-position metadata.
    # Packet data are not claimed to be a full audible test conversation.
    head=b'OpusHead'+struct.pack('<BBHIhB',1,1,312,8000,0,0)
    tags=b'OpusTags'+struct.pack('<II',0,0)
    return _ogg_page(head,0,2,0)+_ogg_page(tags,1,0,0)+_ogg_page(b'\xf8\xff\xfe',2,4,48312)


def vorbis_metadata():
    head=b'\x01vorbis'+struct.pack('<IBIiiiBB',0,1,8000,0,64000,0,0xb8,1)
    tags=b'\x03vorbis'+struct.pack('<II',0,0)+b'\x01'
    return _ogg_page(head,0,2,0)+_ogg_page(tags,1,0,0)+_ogg_page(b'\0',2,4,8000)


class AudioDurationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def parse(self,data,**options):
        path=self.root/'recording';path.write_bytes(data)
        with path.open('rb') as stream:
            stream.seek(2);result=duration_seconds(stream,**options)
            self.assertEqual(stream.tell(),2);self.assertFalse(stream.closed)
            return result

    def test_pcm_wav_duration_and_truncated_payload(self):
        path=self.root/'real.wav'
        with wave.open(str(path),'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(bytes(32000))
        data=path.read_bytes();self.assertEqual(self.parse(data),2)
        with self.assertRaises(AudioDurationUnavailable):self.parse(data[:-100])

    @unittest.skipUnless(importlib.util.find_spec('mutagen'),'Mutagen dependency required; missing-parser denial is tested separately')
    def test_real_mp3_and_ogg_metadata_parsers(self):
        self.assertAlmostEqual(self.parse(mp3_metadata()),4*1152/44100,places=5)
        self.assertAlmostEqual(self.parse(ogg_metadata()),1,places=5)
        self.assertAlmostEqual(self.parse(vorbis_metadata()),1,places=5)

    def test_missing_parser_is_explicit_and_never_returns_fake_duration(self):
        original=builtins.__import__
        def missing(name,*args,**kwargs):
            if name=='mutagen' or name.startswith('mutagen.'):raise ImportError('not installed')
            return original(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=missing):
            for data in (mp3_metadata(),ogg_metadata()):
                with self.assertRaisesRegex(AudioDurationUnavailable,'^recording_duration_parser_unavailable$'):self.parse(data)

    def test_cumulative_bytes_read_seek_operations_and_deadline_are_bounded(self):
        def scanning(reader):
            for _ in range(20):reader.seek(0);reader.read(100)
            return 1
        with patch('sanequeue.reporting.audio._compressed_duration',side_effect=scanning):
            with self.assertRaisesRegex(AudioDurationUnavailable,'budget_exceeded'):self.parse(mp3_metadata(),maximum_bytes=200)
        def seeking(reader):
            for _ in range(1025):reader.seek(0)
            return 1
        with patch('sanequeue.reporting.audio._compressed_duration',side_effect=seeking):
            with self.assertRaisesRegex(AudioDurationUnavailable,'budget_exceeded'):self.parse(mp3_metadata())
        with patch('sanequeue.reporting.audio.time',SimpleNamespace(monotonic=lambda:1)):
            # A parser-free wall-clock progression is deterministic and isolated.
            with patch('sanequeue.reporting.audio.time.monotonic',side_effect=[0,1]):
                with self.assertRaisesRegex(AudioDurationUnavailable,'budget_exceeded'):self.parse(mp3_metadata())

    def test_parser_cannot_scan_unbounded_read_or_seek_outside_descriptor(self):
        for operation in (lambda reader:reader.read(),lambda reader:reader.seek(10**12),lambda reader:reader.seek(-1)):
            with patch('sanequeue.reporting.audio._compressed_duration',side_effect=operation):
                with self.assertRaises(AudioDurationUnavailable):self.parse(mp3_metadata())
        with patch('sanequeue.reporting.audio._compressed_duration',side_effect=lambda reader:reader.read()):
            with self.assertRaisesRegex(AudioDurationUnavailable,'budget_exceeded'):self.parse(mp3_metadata()+bytes(300000))
        for invalid in (b'not audio',b'OggS'+bytes(40)):
            with self.assertRaises(AudioDurationUnavailable):self.parse(invalid)


if __name__=='__main__':unittest.main()
