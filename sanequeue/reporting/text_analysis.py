"""Deterministic Persian search normalization and extractive assistance.

This is not sentiment inference, a generative summary, or an employee rating.
Original text is always retained; ambiguous spoken phone groups are not guessed.
"""
import re
import unicodedata

_VALUES=dict(zip(('صفر','یک','دو','سه','چهار','پنج','شش','هفت','هشت','نه','ده','یازده','دوازده','سیزده','چهارده','پانزده','شانزده','هفده','هجده','نوزده'),range(20)))
_VALUES.update(dict(zip(('بیست','سی','چهل','پنجاه','شصت','هفتاد','هشتاد','نود'),range(20,100,10))))
_VALUES.update(dict(zip(('صد','دویست','سیصد','چهارصد','پانصد','ششصد','هفتصد','هشتصد','نهصد'),range(100,1000,100))))
_ALIASES={'یه':'یک','پونصد':'پانصد','شیشصد':'ششصد','هیشده':'هجده','شونزده':'شانزده'}
_SCALES={'هزار':1000,'میلیون':1000000,'میلیارد':1000000000}
_WORDS=set(_VALUES)|set(_SCALES)|set(_ALIASES)
_RUN=re.compile(r'(?<!\w)(?:'+ '|'.join(sorted(_WORDS,key=len,reverse=True))+r')(?:\s+(?:(?:و)\s+)?(?:'+ '|'.join(sorted(_WORDS,key=len,reverse=True))+r'))*(?!\w)')


def normalize_persian(text):
    if not isinstance(text,str) or len(text)>1024*1024:raise ValueError('invalid_transcript_text')
    text=''.join(str(unicodedata.digit(char)) if char.isdecimal() else char for char in text)
    text=text.replace('ي','ی').replace('ك','ک')
    def convert(match):
        words=[_ALIASES.get(word,word) for word in match.group().split() if word!='و']
        if len(words)>40:return match.group()
        if all(word in _VALUES and _VALUES[word]<10 for word in words):
            return ''.join(str(_VALUES[word]) for word in words)
        if words[0]=='صفر':return match.group()
        total=current=0;last_scale=float('inf');previous=None
        for word in words:
            if word in _SCALES:
                scale=_SCALES[word]
                if scale>=last_scale:return match.group()
                total+=(current or 1)*scale;current=0;last_scale=scale;previous=None
            else:
                value=_VALUES[word]
                # Repeated hundreds or ascending groups may encode a phone or
                # multiple values. Keep that phrase rather than invent a sum.
                if previous is not None and (value>=previous or previous<20):return match.group()
                current+=value;previous=value
        return str(total+current)
    return _RUN.sub(convert,text)


def enrich(result,language='fa'):
    if not isinstance(result,dict) or not isinstance(result.get('text'),str):raise ValueError('invalid_transcript_result')
    result=dict(result);text=result['text']
    result['normalized_text']=normalize_persian(text) if language=='fa' else text
    sentences=[sentence.strip() for sentence in re.split(r'[.!؟?\n]+',text) if sentence.strip()]
    lexicon={'follow_up':('پیگیری','تماس مجدد','follow up'),'billing':('فاکتور','پرداخت','هزینه','invoice','payment'),
             'complaint':('شکایت','ناراضی','complaint'),'technical':('خطا','خرابی','قطع','error','fault')}
    terms=[dict(category=category,matches=[word for word in words if word in text.lower()])
           for category,words in lexicon.items() if any(word in text.lower() for word in words)]
    analysis=dict(result.get('analysis') or {})
    analysis.update(assistance_method='deterministic_keywords_and_excerpts',
        excerpts=sentences[:3],topics=terms,normalization='conservative_fa_rules' if language=='fa' else 'unchanged',
        generated_summary=False,sentiment=None,automated_decision=False,
        accuracy_requires_human_review=True)
    result['analysis']=analysis
    return result
