"""Open a recording below a trusted root without following symlinks.

Callers must authorize the opaque database identifier before resolving a path.
The open descriptor, rather than a later pathname lookup, is streamed.
"""
import os
from pathlib import Path, PurePosixPath
import re
import stat


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
