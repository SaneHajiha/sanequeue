import csv
from datetime import date, datetime
import io
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from zoneinfo import ZoneInfo
from sanequeue.reporting.exports import persian_date, csv_bytes, xlsx_bytes


class ExportTests(unittest.TestCase):
    def row(self):
        return dict(id='a'*64,queue='8001',caller='09123456789',agent='=untrusted',outcome='transferred',
                    entered=datetime(2026,10,25,23,6,22,tzinfo=ZoneInfo('Asia/Tehran')).timestamp(),
                    answered=None,ended=None,wait_seconds=3,talk_seconds=None,segment_ended_by=None,coverage='observed')

    def test_persian_calendar_anchors_and_explicit_out_of_range(self):
        for gregorian,persian in [('2024-03-20','1403/01/01'),('2025-03-20','1403/12/30'),
                                  ('2025-03-21','1404/01/01'),('2026-03-21','1405/01/01'),
                                  ('2026-10-25','1405/08/03')]:
            self.assertEqual(persian_date(date.fromisoformat(gregorian)),persian)
        self.assertIn('Gregorian',persian_date(date(2100,1,1)))

    def test_localized_csv_dates_nulls_and_formula_neutralization(self):
        content=csv_bytes([self.row()],'fa').decode('utf-8-sig')
        rows=list(csv.reader(io.StringIO(content)))
        self.assertEqual(rows[0][0],'صف')
        self.assertEqual(rows[1][4],'1405/08/03 23:06:22')
        self.assertEqual(rows[1][2],"'=untrusted")
        self.assertEqual(rows[1][8],'')
        english=list(csv.reader(io.StringIO(csv_bytes([self.row()],'en').decode('utf-8-sig'))))
        self.assertEqual(english[1][4],'2026-10-25 23:06:22')

    def test_xlsx_text_identity_safe_cells_rtl_freeze_and_filter(self):
        output=xlsx_bytes([self.row()],'fa',period='2026-10-25')
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with ZipFile(io.BytesIO(output)) as archive:
            for name in archive.namelist():ET.fromstring(archive.read(name))
            sheet=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            cells={cell.get('r'):cell for cell in sheet.findall('.//s:c',ns)}
            self.assertEqual(cells['B5'].get('t'),'inlineStr')
            self.assertEqual(cells['B5'].find('.//s:t',ns).text,'09123456789')
            self.assertEqual(cells['C5'].find('.//s:t',ns).text,'=untrusted')
            self.assertEqual(sheet.findall('.//s:f',ns),[])
            self.assertNotIn('I5',cells)
            self.assertEqual(sheet.find('.//s:sheetView',ns).get('rightToLeft'),'1')
            self.assertEqual(sheet.find('.//s:pane',ns).get('ySplit'),'4')
            self.assertEqual(sheet.find('s:autoFilter',ns).get('ref'),'A4:L5')
        with self.assertRaises(ValueError):xlsx_bytes([self.row()]*201)
        with self.assertRaises(ValueError):csv_bytes([],language='unknown')


if __name__=='__main__':unittest.main()
