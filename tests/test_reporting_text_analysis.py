import unittest
from sanequeue.reporting.text_analysis import normalize_persian,enrich


class TextAnalysisTests(unittest.TestCase):
    def test_conservative_number_normalization_preserves_original_semantics(self):
        self.assertEqual(normalize_persian('پونصد و بیست هزار تومن'),'520000 تومن')
        self.assertEqual(normalize_persian('یک میلیون و دویست هزار تومان'),'1200000 تومان')
        self.assertEqual(normalize_persian('کد صفر نه یک دو سه'),'کد 09123')
        self.assertEqual(normalize_persian('کد ۱۲۳۴'),'کد 1234')
        self.assertEqual(normalize_persian('صفر نهصد و دوازده'),'صفر نهصد و دوازده')
        self.assertEqual(normalize_persian('بیست و سی'),'بیست و سی')

    def test_original_retained_no_sentiment_or_automated_decision(self):
        original='درخواست پیگیری فاکتور دارم. لطفا تماس مجدد بگیرید.'
        result=enrich(dict(text=original,segments=[]))
        self.assertEqual(result['text'],original)
        self.assertFalse(result['analysis']['generated_summary'])
        self.assertIsNone(result['analysis']['sentiment'])
        self.assertFalse(result['analysis']['automated_decision'])
        self.assertEqual(result['analysis']['excerpts'][0],'درخواست پیگیری فاکتور دارم')


if __name__=='__main__':unittest.main()
