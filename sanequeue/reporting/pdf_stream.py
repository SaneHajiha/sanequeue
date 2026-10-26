"""Private, bounded queue-visit PDF rendering; no browser, HTML, URLs or fonts fetched.

ReportLab keeps its PDF objects until save, so PDF deliberately has a much lower
row/page ceiling than CSV/XLSX. Only one <=200-row source batch is passed here.
Persian shaping is applied after logical line wrapping, then Unicode bidi.
"""
from datetime import datetime
from functools import lru_cache
import io
import os
from pathlib import Path
import stat
import threading
import unicodedata
from zoneinfo import ZoneInfo

from .exports import persian_date,table

MAX_ROWS=1000
MAX_PAGES=100
MAX_BYTES=8*1024*1024
FONT_PATH=Path(__file__).resolve().parents[2]/'assets'/'fonts'/'Vazirmatn-Regular.ttf'
FONT_NAME='SaneQueueReport'
_FONT_LOCK=threading.Lock()
_MAIN=(0,1,2,3,4,7,8,9,10)
_WIDTHS=(40,104,106,102,122,58,55,102,89)
_BIDI_CONTROLS=set('\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069')


class PdfFailure(RuntimeError):
    """Safe public reason; never include report data or filesystem paths."""


def _text(value):
    value='' if value is None else str(value)
    if len(value)>512:raise PdfFailure('pdf_field_limit')
    return ''.join(ch for ch in value if unicodedata.category(ch)!='Cc' and ch not in _BIDI_CONTROLS)


def _dependencies():
    try:
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from arabic_reshaper import ArabicReshaper
        from bidi.algorithm import get_display
    except ImportError:raise PdfFailure('pdf_dependency_unavailable') from None
    with _FONT_LOCK:
        if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            try:
                if FONT_PATH.is_symlink():raise ValueError()
                fd=os.open(FONT_PATH,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)|getattr(os,'O_NONBLOCK',0))
                with os.fdopen(fd,'rb') as font:
                    meta=os.fstat(font.fileno())
                    if not stat.S_ISREG(meta.st_mode) or not 0<meta.st_size<=2*1024*1024:raise ValueError()
                    data=font.read(2*1024*1024+1)
                if len(data)>2*1024*1024:raise ValueError()
                pdfmetrics.registerFont(TTFont(FONT_NAME,io.BytesIO(data)))
            except Exception:
                # ReportLab font-parser exceptions are intentionally not exposed.
                raise PdfFailure('pdf_font_unavailable') from None
    reshape=ArabicReshaper(configuration={'delete_harakat':False,'shift_harakat_position':True})
    return Canvas,pdfmetrics,reshape,get_display


class _BoundedOutput:
    def __init__(self,stream,maximum,check):self.stream=stream;self.maximum=maximum;self.check=check;self.written=0
    def write(self,data):
        self.check()
        if self.written+len(data)>self.maximum:raise PdfFailure('pdf_byte_limit')
        result=self.stream.write(data);self.written+=len(data);return result
    def tell(self):return self.stream.tell()


class Document:
    """Append formatted batches and finalize once; the caller owns private output.

    ``check`` is the worker's load/deadline/current-authority/lease fence, called
    at each PDF page and at final serialization. No source query is issued here.
    ``body`` rows use exports.table's 12-field contract and are already masked.
    """
    def __init__(self,output,language,*,start,end,queues,outcome=None,check=None,
                 max_bytes=MAX_BYTES,max_rows=MAX_ROWS,max_pages=MAX_PAGES):
        if language not in ('fa','en'):raise ValueError('invalid_pdf_language')
        if not 1<=max_bytes<=MAX_BYTES or not 1<=max_rows<=MAX_ROWS or not 1<=max_pages<=MAX_PAGES:raise ValueError('invalid_pdf_limits')
        self.language=language;self.fa=language=='fa';self.check=check or (lambda:None)
        self.max_rows=max_rows;self.max_pages=max_pages;self.rows=0;self.pages=0;self.closed=False
        self.width=841.8898;self.height=595.2756;self.margin=32;self.bottom=44
        self.headers=table([],language)[0];self.start=start;self.end=end
        if not self.fa:self.headers[7:9]=['Wait (s)','Known talk (s)']
        self.queues=tuple(queues);self.outcome=outcome
        self.outcome_label=(table([dict(queue='',id='',entered=start,outcome=outcome,coverage='observed')],language)[1][0][3]
                            if outcome else ('همه' if self.fa else 'all'))
        self.check()
        Canvas,self.metrics,self.reshape,self.bidi=_dependencies()
        self.visual=lru_cache(maxsize=2048)(self._visual)
        self.pdf=Canvas(_BoundedOutput(output,max_bytes,self.check),pagesize=(self.width,self.height),
            pageCompression=1,invariant=1)
        self.pdf.setTitle('گزارش مراجعه‌های صف' if self.fa else 'Queue visit report')
        self.pdf.setAuthor('SaneQueue');self.pdf.setCreator('SaneQueue private reporting worker')
        self._new_page()

    def _visual(self,text):
        text=_text(text)
        rtl=any(unicodedata.bidirectional(ch) in ('AL','R') for ch in text)
        return self.bidi(self.reshape.reshape(text),base_dir='R') if rtl else text

    def _width(self,text,size):return self.metrics.stringWidth(self.visual(text),FONT_NAME,size)

    def _lines(self,value,width,size,max_lines=3):
        text=_text(value)
        if not text:return ['']
        if self._width(text,size)<=width:return [text]
        lines=[];remaining=text
        while remaining:
            if len(lines)>=max_lines:raise PdfFailure('pdf_field_limit')
            low,high=1,len(remaining)
            while low<high:
                mid=(low+high+1)//2
                if self._width(remaining[:mid],size)<=width:low=mid
                else:high=mid-1
            if self._width(remaining[:low],size)>width:raise PdfFailure('pdf_field_limit')
            cut=low
            if cut<len(remaining):
                whitespace=remaining.rfind(' ',0,cut+1)
                if whitespace>cut//2:cut=whitespace
            lines.append(remaining[:cut].rstrip());remaining=remaining[cut:].lstrip()
        return lines

    def _draw(self,text,x,y,size=8,color='#183047',right=False):
        self.pdf.setFillColor(color);self.pdf.setFont(FONT_NAME,size)
        method=self.pdf.drawRightString if right else self.pdf.drawString
        method(x,y,self.visual(_text(text)))

    def _stamp(self,value):
        local=datetime.fromtimestamp(value,ZoneInfo('Asia/Tehran'))
        return (persian_date(local.date()) if self.fa else local.date().isoformat())+local.strftime(' %H:%M:%S')

    def _footer(self):
        text=('صفحه '+str(self.pages)+' | '+str(self.rows)+' مراجعه تا این صفحه' if self.fa else
              'Page '+str(self.pages)+' | '+str(self.rows)+' visits through this page')
        self._draw(text,self.width-self.margin if self.fa else self.margin,23,7,'#607386',right=self.fa)
        self._draw('SaneQueue',self.margin if self.fa else self.width-self.margin,23,7,'#607386',right=not self.fa)

    def _new_page(self):
        self.check()
        if self.pages:
            self._footer();self.pdf.showPage()
        if self.pages>=self.max_pages:raise PdfFailure('pdf_page_limit')
        self.pages+=1
        pdf=self.pdf;pdf.setFillColor('#10283f');pdf.rect(0,self.height-80,self.width,80,fill=1,stroke=0)
        title='گزارش مراجعه‌های صف' if self.fa else 'Queue visit report'
        self._draw(title,self.width-self.margin if self.fa else self.margin,self.height-37,18,'#ffffff',right=self.fa)
        subtitle='گزارش خصوصی | مراجعه به صف، نه کل مکالمه' if self.fa else 'Private report | Queue visits, not whole conversations'
        self._draw(subtitle,self.width-self.margin if self.fa else self.margin,self.height-60,9,'#d5e3ef',right=self.fa)
        if self.fa:
            # Keep date/time values as independent LTR runs. A single RTL
            # sentence would visually swap the date and time sub-runs.
            edge=self.width-self.margin
            self._draw('شروع:',edge,self.height-101,8,right=True)
            self._draw(self._stamp(self.start),edge-34,self.height-101,8,right=True)
            self._draw('پایان (شامل نیست):',edge-270,self.height-101,8,right=True)
            self._draw(self._stamp(self.end),edge-370,self.height-101,8,right=True)
        else:self._draw(self._stamp(self.start)+' to '+self._stamp(self.end)+' | End exclusive',self.margin,self.height-101,8)
        queue_text=', '.join(self.queues)
        filters=('صف‌ها: '+queue_text+' | نتیجه: '+self.outcome_label if self.fa else
                 'Queues: '+queue_text+' | Outcome: '+self.outcome_label)
        # Every selected queue is listed; overlong filter lists fail explicitly.
        for index,line in enumerate(self._lines(filters,self.width-2*self.margin,8,2)):
            self._draw(line,self.width-self.margin if self.fa else self.margin,self.height-117-index*12,8,right=self.fa)
        note=('تهران | تاریخ شمسی | زمان نامعلوم خالی است | شماره‌ها طبق مجوز درخواست' if self.fa else
              'Asia/Tehran | Gregorian dates | Unknown times are blank | Numbers follow request policy')
        self._draw(note,self.width-self.margin if self.fa else self.margin,self.height-145,7.5,'#607386',right=self.fa)
        self.y=self.height-157
        columns=list(zip(_MAIN,_WIDTHS))
        if self.fa:columns.reverse()
        x=self.margin
        pdf.setFillColor('#e6eef5');pdf.rect(x,self.y-29,sum(_WIDTHS),29,fill=1,stroke=0)
        for index,width in columns:
            for offset,line in enumerate(self._lines(self.headers[index],width-10,7,3)):
                self._draw(line,x+width-5 if self.fa else x+5,self.y-11-offset*8,7,right=self.fa)
            x+=width
        self.y-=29

    def append(self,body):
        if self.closed:raise ValueError('pdf_document_closed')
        if len(body)>200:raise PdfFailure('pdf_batch_limit')
        if self.rows+len(body)>self.max_rows:raise PdfFailure('pdf_row_limit')
        for row in body:
            if len(row)!=12:raise ValueError('invalid_pdf_row')
            cells={index:self._lines(row[index],width-10,7.8,3) for index,width in zip(_MAIN,_WIDTHS)}
            height=max(19,max(map(len,cells.values()))*9+6)+15
            if self.y-height<self.bottom:self._new_page()
            if self.y-height<self.bottom:raise PdfFailure('pdf_field_limit')
            pdf=self.pdf
            pdf.setFillColor('#f2f6fa' if self.rows%2==0 else '#ffffff')
            pdf.rect(self.margin,self.y-height,sum(_WIDTHS),height,fill=1,stroke=0)
            columns=list(zip(_MAIN,_WIDTHS))
            if self.fa:columns.reverse()
            x=self.margin
            for index,width in columns:
                for offset,line in enumerate(cells[index]):
                    self._draw(line,x+width-5 if self.fa else x+5,self.y-12-offset*9,7.8,right=self.fa)
                x+=width
            # The remaining three fields are explicit and readable, including
            # the opaque visit ID. Never silently omit them to fit a table.
            if self.fa:
                edge=self.width-self.margin-5
                for label,value,label_x,value_x,maximum in (
                    ('پاسخ:',row[5],edge,edge-31,130),
                    ('پایان صف:',row[6],edge-184,edge-236,130),
                    ('شناسه:',row[11],edge-389,edge-424,330)):
                    if self._width(_text(value),6.6)>maximum:raise PdfFailure('pdf_field_limit')
                    self._draw(label,label_x,self.y-height+5,6.6,'#607386',right=True)
                    self._draw(_text(value),value_x,self.y-height+5,6.6,'#607386',right=True)
            else:
                secondary='Answered: '+_text(row[5])+' | Segment ended: '+_text(row[6])+' | Visit ID: '+_text(row[11])
                if self._width(secondary,6.6)>self.width-2*self.margin-10:raise PdfFailure('pdf_field_limit')
                self._draw(secondary,self.margin+5,self.y-height+5,6.6,'#607386')
            pdf.setStrokeColor('#d8e2eb');pdf.line(self.margin,self.y-height,self.width-self.margin,self.y-height)
            self.y-=height;self.rows+=1

    def close(self):
        if self.closed:return
        self.check()
        if not self.rows:
            self._draw('در این بازه مراجعه‌ای ثبت نشده است.' if self.fa else 'No queue visits in this period.',
                self.width-self.margin if self.fa else self.margin,self.y-30,10,right=self.fa)
        self._footer();self.pdf.save();self.closed=True;self.visual.cache_clear()

    def abort(self):
        self.closed=True
        if hasattr(self,'visual'):self.visual.cache_clear()
