"""Literal full-token search; untrusted input cannot add FTS operators."""
import re
import unicodedata

_MAP=str.maketrans('يك٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹','یک01234567890123456789')

def normalize(value):
    value=unicodedata.normalize('NFKC',value).translate(_MAP).replace('\u200c',' ')
    return ''.join(c for c in value if unicodedata.category(c)!='Mn').casefold()

def expression(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=256:
        raise ValueError('invalid_transcript_search')
    tokens=re.findall(r'[^\W_]+',normalize(value),flags=re.UNICODE)
    if not tokens or len(tokens)>12 or any(len(token)>64 for token in tokens):
        raise ValueError('invalid_transcript_search')
    return ' AND '.join('"'+token+'"' for token in tokens)


class DeadlineArchive:
    """Read-only facade applying one request deadline to every short reader."""
    def __init__(self,archive,deadline):
        self.path=archive.path;self.pbx=archive.pbx;self.deadline=deadline

    def reader(self):
        from .store import Archive,QueryDeadline
        import time
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise QueryDeadline('transcript_search_deadline')
        return Archive(self.path,pbx=self.pbx,read_seconds=min(.2,remaining)).reader()
