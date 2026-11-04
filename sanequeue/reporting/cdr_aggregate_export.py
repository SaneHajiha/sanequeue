"""Bounded output for globally authorized PBX aggregate tables."""
import csv
import io
from . import builder_exports, pdf_stream


def render(headers,rows,format,*,start,end,title):
    if format not in ('csv','xlsx','pdf') or not isinstance(headers,list) or not 1<=len(headers)<=15:raise ValueError('invalid_cdr_aggregate_export')
    if len(rows)>1000 or any(len(row)!=len(headers) for row in rows):raise ValueError('cdr_aggregate_export_limit')
    if format=='pdf' and len(rows)>150:raise pdf_stream.PdfFailure('pdf_row_limit')
    if format=='csv':
        output=io.StringIO(newline='');writer=csv.writer(output)
        def safe(value):
            if value is None:return ''
            value=str(value)
            return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else value
        writer.writerow([safe(value) for value in headers]);writer.writerows([[safe(value) for value in row] for row in rows])
        return output.getvalue().encode('utf-8-sig')
    output=io.BytesIO()
    if format=='xlsx':writer=builder_exports.Workbook(output,'fa',headers=headers,max_bytes=8*1024*1024,max_columns=15,title=title)
    else:writer=pdf_stream.CustomDocument(output,'fa',headers=headers,max_columns=15,grouped=True,global_cdr=True,
        start=start,end=end,queues=[],max_rows=150,max_pages=100,max_bytes=8*1024*1024,filter_items=[title])
    try:
        for i in range(0,len(rows),200):writer.append(rows[i:i+200])
        writer.close()
    except BaseException:
        writer.abort();raise
    return output.getvalue()
