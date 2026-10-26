"""Small, streaming OOXML writer: inline text, no formulas or shared strings."""
import io
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from .exports import xlsx_bytes, table

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'


class SizeLimit(ValueError):
    pass


class _BoundedFile:
    def __init__(self, target, limit):self.target=target;self.limit=limit
    def write(self,data):
        if self.target.tell()+len(data)>self.limit:raise SizeLimit('export_byte_limit')
        return self.target.write(data)
    def tell(self):return self.target.tell()
    def seek(self,*args):return self.target.seek(*args)
    def flush(self):return self.target.flush()
    def seekable(self):return True


class Workbook:
    def __init__(self, output, language, *, period='', max_bytes=32*1024*1024, max_xml_bytes=64*1024*1024):
        self.language=language;self.row=0;self.xml_size=0;self.max_xml_bytes=max_xml_bytes;self.closed=False
        self.archive=ZipFile(_BoundedFile(output,max_bytes),'w',ZIP_DEFLATED,compresslevel=1)
        try:
            # Reuse the tested immediate-export style/relationship definitions.
            with ZipFile(io.BytesIO(xlsx_bytes([],language,period=period))) as template:
                for name in template.namelist():
                    if name!='xl/worksheets/sheet1.xml':self.archive.writestr(name,template.read(name))
                sheet=template.read('xl/worksheets/sheet1.xml')
            prefix=sheet.split(b'<sheetData',1)[0]+b'<sheetData>'
            self.sheet=self.archive.open('xl/worksheets/sheet1.xml','w')
            self._write(prefix)
            title='گزارش مراجعه‌های صف' if language=='fa' else 'Queue visit report'
            note=('زمان تهران؛ مقادیر نامعلوم خالی هستند | ' if language=='fa' else 'Asia/Tehran; unknown values are blank | ')+period
            self.append([[title],[note],[],table([],language)[0]])
        except Exception:
            try:
                if hasattr(self,'sheet'):self.sheet.close()
            except Exception:pass
            try:self.archive.close()
            except Exception:pass
            self.closed=True
            raise

    def _write(self,data):
        if self.xml_size+len(data)>self.max_xml_bytes:raise SizeLimit('export_uncompressed_limit')
        self.sheet.write(data);self.xml_size+=len(data)

    def append(self, rows):
        if len(rows)>200:raise ValueError('export_page_limit')
        for values in rows:
            self.row+=1
            node=ET.Element('row',r=str(self.row),ht='30' if self.row in (1,4) else '22',customHeight='1')
            for column,value in enumerate(values):
                if value is None:continue
                attrs=dict(r=chr(65+column)+str(self.row),s='1' if self.row in (1,4) else '0')
                if isinstance(value,(float,int)):
                    cell=ET.SubElement(node,'c',attrs,t='n');ET.SubElement(cell,'v').text=str(value)
                else:
                    cell=ET.SubElement(node,'c',attrs,t='inlineStr')
                    text=ET.SubElement(ET.SubElement(cell,'is'),'t',{'{http://www.w3.org/XML/1998/namespace}space':'preserve'})
                    text.text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value))[:32767]
            self._write(ET.tostring(node,encoding='utf-8'))

    def close(self):
        if self.closed:return
        try:
            self._write(('</sheetData><autoFilter ref="A4:L'+str(self.row)+'"/><mergeCells count="2"><mergeCell ref="A1:L1"/><mergeCell ref="A2:L2"/></mergeCells></worksheet>').encode())
        finally:
            self.closed=True
            try:self.sheet.close()
            finally:self.archive.close()

    def abort(self):
        if self.closed:return
        self.closed=True
        try:self.sheet.close()
        finally:self.archive.close()
