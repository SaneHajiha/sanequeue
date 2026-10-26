"""Open a recording below a trusted root without following symlinks.

Callers must authorize the opaque database identifier before resolving a path.
The open descriptor, rather than a later pathname lookup, is streamed.
"""
import os
import math
from pathlib import Path, PurePosixPath
import re
import stat
import time
import wave


class AudioDurationUnavailable(ValueError):
    """No trustworthy duration within the small metadata-reading budget."""


class _MetadataReader:
    """Restrict an already authorized stream; never open a path or decode audio."""
    name=''
    def __init__(self,stream,maximum_bytes,seconds):
        self.stream=stream;self.size=os.fstat(stream.fileno()).st_size
        self.remaining=maximum_bytes;self.deadline=time.monotonic()+seconds;self.operations=0
    def check(self):
        self.operations+=1
        if self.operations>1024 or time.monotonic()>=self.deadline:
            raise AudioDurationUnavailable('recording_duration_budget_exceeded')
    def read(self,size=-1):
        self.check()
        # Mutagen's Ogg parser requests read() after seeking to the last 64 KiB.
        # Resolve it to the known descriptor extent; never allow an unbounded
        # whole-file allocation or bypass the cumulative actual-byte budget.
        if size==-1:size=self.size-self.stream.tell()
        if not isinstance(size,int) or size<0 or size>256*1024:
            raise AudioDurationUnavailable('recording_duration_budget_exceeded')
        value=self.stream.read(min(size,self.remaining+1))
        self.remaining-=len(value)
        if self.remaining<0:raise AudioDurationUnavailable('recording_duration_budget_exceeded')
        return value
    def seek(self,offset,whence=0):
        self.check()
        if not isinstance(offset,int) or whence not in (0,1,2):raise AudioDurationUnavailable('recording_duration_invalid_seek')
        target=offset if whence==0 else self.stream.tell()+offset if whence==1 else self.size+offset
        if not 0<=target<=self.size:raise AudioDurationUnavailable('recording_duration_invalid_seek')
        return self.stream.seek(target)
    def tell(self):
        self.check();return self.stream.tell()


def _compressed_duration(stream):
    # Only file-object metadata readers. No decoder process, URL, or GPU runtime.
    from mutagen import File
    from mutagen.mp3 import MP3
    from mutagen.oggvorbis import OggVorbis
    from mutagen.oggopus import OggOpus
    audio=File(fileobj=stream,options=[MP3,OggVorbis,OggOpus])
    if audio is None or getattr(audio.info,'sketchy',False):raise AudioDurationUnavailable('recording_duration_invalid_metadata')
    return audio.info.length


def duration_seconds(stream,*,maximum_bytes=512*1024,seconds=.25):
    """Bounded WAV/MP3/Ogg metadata duration; absence is never a guessed value.

    Mutagen is optional for MP3/Ogg. Its parser runs cooperatively under bounded
    I/O/seek operations; this is not a full media validation/decode or a worker.
    Caller owns the authorized regular descriptor; its position is restored.
    """
    if not 1<=maximum_bytes<=1024*1024 or not 0<seconds<=.5:raise ValueError('invalid_duration_budget')
    original=stream.tell()
    try:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise AudioDurationUnavailable('recording_duration_invalid_source')
        reader=_MetadataReader(stream,maximum_bytes,seconds);reader.seek(0);header=reader.read(12);reader.seek(0)
        if header[:4]==b'RIFF' and header[8:12]==b'WAVE':
            with wave.open(reader,'rb') as audio:
                rate=audio.getframerate();frames=audio.getnframes()
                # A truncated data payload is not evidence for its declared duration.
                if frames*audio.getnchannels()*audio.getsampwidth()>reader.size-reader.tell():
                    raise AudioDurationUnavailable('recording_duration_invalid_metadata')
                duration=frames/rate
        elif header.startswith((b'ID3',b'OggS')) or len(header)>=2 and header[0]==255 and header[1]&224==224:
            duration=_compressed_duration(reader)
        else:raise AudioDurationUnavailable('recording_duration_unsupported')
        reader.check()
        if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or not 0<duration<=7*86400:
            raise AudioDurationUnavailable('recording_duration_invalid_metadata')
        return float(duration)
    except AudioDurationUnavailable:raise
    except ImportError:raise AudioDurationUnavailable('recording_duration_parser_unavailable') from None
    except Exception:raise AudioDurationUnavailable('recording_duration_invalid_metadata') from None
    finally:stream.seek(original)


def open_recording(root, reference):
    if not isinstance(reference, str) or len(reference) > 1024 or '\\' in reference or '\x00' in reference:
        raise ValueError('invalid_recording_reference')
    relative = PurePosixPath(reference)
    if relative.is_absolute() or not relative.parts or any(p in ('.', '..') for p in relative.parts):
        raise ValueError('invalid_recording_reference')
    root = Path(root).absolute()
    if root.is_symlink():
        raise ValueError('recording_root_symlink')
    if os.name == 'nt':
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('recording_symlink')
        fd = os.open(current, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    else:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in relative.parts[:-1]:
                next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = next_directory
            fd = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode):
        os.close(fd)
        raise ValueError('recording_not_regular')
    return fd, metadata.st_size


def byte_range(value, size):
    if value is None:
        return 0, max(0, size - 1), False
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
    if not match or not size or not any(match.groups()):
        raise ValueError('invalid_audio_range')
    left, right = match.groups()
    if not left:
        count = int(right)
        if count < 1:
            raise ValueError('invalid_audio_range')
        return max(0, size - count), size - 1, True
    start = int(left)
    end = min(size - 1, int(right)) if right else size - 1
    if start >= size or end < start:
        raise ValueError('invalid_audio_range')
    return start, end, True
