"""Explicit caller-number display policies and scoped stable pseudonyms."""
import hashlib
import hmac
import json
import re
import unicodedata


def normalize_number(value):
    text = ''.join(str(unicodedata.digit(c)) if c.isdecimal() else c for c in str(value or ''))
    text = re.sub(r'[\s().-]', '', text)
    return text if re.fullmatch(r'\+?[0-9]{2,24}', text) else ''


def display_number(value, mode, *, secret, tenant, pbx, version='1'):
    if mode not in ('full', 'masked', 'pseudonymous', 'hidden'):
        raise ValueError('invalid_number_policy')
    number = normalize_number(value)
    if not number or mode == 'hidden':
        return ''
    if mode == 'full':
        return number
    if mode == 'masked':
        # Short internal numbers should not be disclosed by overlapping prefixes.
        return number[:4] + '*' * (len(number) - 8) + number[-4:] if len(number) >= 11 else '***'
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError('pseudonym_secret_too_short')
    message = json.dumps([str(tenant), str(pbx), str(version), number], ensure_ascii=False, separators=(',', ':')).encode()
    # Preserve the full digest: four hex characters are insufficient for a directory.
    return 'Caller #' + hmac.new(secret, message, hashlib.sha256).hexdigest().upper()
