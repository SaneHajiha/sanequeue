"""Bounded human-readable exports without spreadsheet engines or formulas."""
import csv
from datetime import datetime
import io
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED
from zoneinfo import ZoneInfo


def persian_date(date):
    """Gregorian-to-Persian day arithmetic for the supported modern era."""
    if not 1900 <= date.year <= 2099:
        return date.isoformat() + ' (Gregorian)'
    year, month, day = date.year - 1600, date.month - 1, date.day - 1
    days = 365*year + (year+3)//4 - (year+99)//100 + (year+399)//400
    days += sum((31,28,31,30,31,30,31,31,30,31,30,31)[:month]) + day
    if month > 1 and date.year % 4 == 0 and (date.year % 100 != 0 or date.year % 400 == 0):
        days += 1
    days -= 79
    cycles, days = divmod(days, 12053)
    four, days = divmod(days, 1461)
    jy = 979 + 33*cycles + 4*four
    if days >= 366:
        extra, days = divmod(days-1, 365)
        jy += extra
    jm = 1
    while jm < 12 and days >= (31 if jm <= 6 else 30):
        days -= 31 if jm <= 6 else 30
        jm += 1
    return f'{jy:04d}/{jm:02d}/{days+1:02d}'


def table(rows, language='en'):
    if language not in ('fa', 'en'):
        raise ValueError('invalid_export_language')
    if len(rows) > 200:
        raise ValueError('export_row_limit')
    fa = language == 'fa'
    headers = (['صف','شماره تماس‌گیرنده','کارشناس','نتیجه','ورود (تهران)','پاسخ (تهران)',
                'پایان بخش صف (تهران)','انتظار (ثانیه)','مکالمه معلوم (ثانیه)','قطع بخش صف','پوشش شواهد','شناسه مراجعه'] if fa else
               ['Queue','Caller number','Agent','Outcome','Entered (Tehran)','Answered (Tehran)',
                'Queue segment ended (Tehran)','Wait (seconds)','Known talk (seconds)','Queue segment ended by','Evidence coverage','Visit ID'])
    labels = {'answered':'پاسخ‌داده','abandoned':'رهاشده','transferred':'منتقل‌شده',
              'waiting':'منتظر؛ پایان نامشخص','connected':'پاسخ؛ پایان نامشخص','unknown':'نامشخص',
              'exitwithtimeout':'پایان مهلت','exitempty':'خروج؛ صف خالی','exitwithkey':'خروج با کلید',
              'reentered_without_end':'ورود مجدد؛ پایان نامشخص','caller':'تماس‌گیرنده','agent':'کارشناس',
              'observed':'ثبت‌شده','missing_entry':'شروع گمشده','missing_end':'پایان گمشده'}
    def label(value):
        return labels.get(value, value) if fa else value
    def stamp(value):
        if value is None:
            return ''
        local = datetime.fromtimestamp(value, ZoneInfo('Asia/Tehran'))
        return (persian_date(local.date()) if fa else local.date().isoformat()) + local.strftime(' %H:%M:%S')
    body = [[str(row['queue']),str(row.get('caller') or ''),str(row.get('agent') or ''),label(row['outcome']),
             stamp(row['entered']),stamp(row.get('answered')),stamp(row.get('ended')),
             row.get('wait_seconds'),row.get('talk_seconds'),label(row.get('segment_ended_by') or ''),
             label(row['coverage']),row['id']] for row in rows]
    return headers, body


def csv_bytes(rows, language='en'):
    headers, body = table(rows, language)
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in body:
        writer.writerow(["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else v for v in row])
    return ('\ufeff'+output.getvalue()).encode('utf-8')


def xlsx_bytes(rows, language='en', *, period=''):
    """Inline strings preserve phone numbers/IDs and cannot become formulas."""
    headers, body = table(rows, language)
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    tag = lambda name: '{'+ns+'}'+name
    ET.register_namespace('', ns)
    sheet = ET.Element(tag('worksheet'))
    views = ET.SubElement(sheet,tag('sheetViews'))
    view = ET.SubElement(views,tag('sheetView'),workbookViewId='0',rightToLeft='1' if language=='fa' else '0',zoomScale='100',showGridLines='0')
    ET.SubElement(view,tag('pane'),ySplit='4',topLeftCell='A5',activePane='bottomLeft',state='frozen')
    cols = ET.SubElement(sheet,tag('cols'))
    for index,width in enumerate((10,20,14,18,26,26,26,16,22,20,18,68),1):
        attributes=dict(min=str(index),max=str(index),width=str(width),customWidth='1')
        if index==12:attributes['hidden']='1'
        ET.SubElement(cols,tag('col'),attributes)
    data = ET.SubElement(sheet,tag('sheetData'))
    title = 'گزارش مراجعه‌های صف' if language=='fa' else 'Queue visit report'
    note = ('منطقه زمانی: تهران | زمان نامعلوم خالی است | '+period if language=='fa' else
            'Timezone: Asia/Tehran | Unknown values are blank | '+period)
    values = [[title],[note],[],headers]+body
    for row_number, values_row in enumerate(values,1):
        row_node = ET.SubElement(data,tag('row'),r=str(row_number),ht='30' if row_number in (1,4) else '22',customHeight='1')
        for index, value in enumerate(values_row):
            if value is None:
                continue
            ref = chr(65+index)+str(row_number)
            style = '1' if row_number in (1,4) else '0'
            if isinstance(value,(float,int)):
                cell = ET.SubElement(row_node,tag('c'),r=ref,s=style,t='n')
                ET.SubElement(cell,tag('v')).text=str(value)
            else:
                cell=ET.SubElement(row_node,tag('c'),r=ref,s=style,t='inlineStr')
                text=ET.SubElement(ET.SubElement(cell,tag('is')),tag('t'),{'{http://www.w3.org/XML/1998/namespace}space':'preserve'})
                text.text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value))[:32767]
    ET.SubElement(sheet,tag('autoFilter'),ref=f'A4:L{len(values)}')
    merges=ET.SubElement(sheet,tag('mergeCells'),count='2')
    ET.SubElement(merges,tag('mergeCell'),ref='A1:L1')
    ET.SubElement(merges,tag('mergeCell'),ref='A2:L2')
    styles=f'''<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF12283F"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    output=io.BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml','''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>''')
        archive.writestr('_rels/.rels','''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
        archive.writestr('xl/workbook.xml',f'''<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{'گزارش صف' if language=='fa' else 'Queue visits'}" sheetId="1" r:id="rId1"/></sheets></workbook>''')
        archive.writestr('xl/_rels/workbook.xml.rels','''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''')
        archive.writestr('xl/styles.xml',styles)
        archive.writestr('xl/worksheets/sheet1.xml',ET.tostring(sheet,encoding='utf-8',xml_declaration=True))
    return output.getvalue()
