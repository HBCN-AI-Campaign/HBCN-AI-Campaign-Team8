from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import re
import unicodedata
from dateutil.parser import parse as parse_date, parserinfo


class _DocumentMonths(parserinfo):
    # Locale-independent aliases; dateutil is already pinned in requirements.
    MONTHS = [tuple(english) + german for english, german in zip(parserinfo.MONTHS, (
        ('Januar',), ('Februar',), ('März', 'Maerz', 'Mär'), ('April',),
        ('Mai',), ('Juni',), ('Juli',), ('August',), ('September',),
        ('Oktober', 'Okt'), ('November',), ('Dezember', 'Dez')))]


_DOCUMENT_MONTHS = _DocumentMonths()


def _named_month_date(text):
    # dateutil otherwise guesses omitted components and ambiguous numeric dates.
    # Require one explicit day, named month and four-digit year before using it.
    word = r'[A-Za-zÄÖÜäöüß]+'
    match=re.fullmatch(r'(?P<day>\d{1,2})\.?\s*(?P<month>' + word + r')\.?\s+(?P<year>\d{4})', text)
    if not match:
        match=re.fullmatch(r'(?P<month>' + word + r')\.?\s*(?P<day>\d{1,2}),?\s*(?P<year>\d{4})', text)
    if not match:
        raise ValueError('ambiguous date')
    try:
        day,month,year=match.group('day','month','year')
        parsed=parse_date(f'{day} {month} {year}', parserinfo=_DOCUMENT_MONTHS, fuzzy=False,
                          default=datetime(2000, 1, 1)).date()
        if parsed.year!=int(year) or parsed.day!=int(day):raise ValueError('ambiguous date')
        return parsed.isoformat()
    except (ValueError, OverflowError):
        raise ValueError('ambiguous date') from None


def compact(value) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).casefold()


def decimal_value(raw) -> str:
    if isinstance(raw, bool):
        raise ValueError("invalid decimal")
    value=unicodedata.normalize("NFKC",str(raw)).strip()
    value=re.sub(r"^(?:CNY|RMB|USD|EUR|人民币|美元|欧元|￥|¥|\$)\s*", "",value,flags=re.I)
    value=re.sub(r"\s*(?:元|人民币|美元|欧元)$", "",value)
    if not re.fullmatch(r"[+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?",value):
        raise ValueError("ambiguous decimal")
    try:
        d=Decimal(value.replace(",",""))
        if not d.is_finite() or d<0:
            raise ValueError("invalid decimal")
        return format(d,"f")
    except InvalidOperation:
        raise ValueError("invalid decimal") from None


def normalize(value, data_type):
    if value is None or value == "" or value == []:
        return None
    if data_type in {"money","decimal"}:
        return decimal_value(value)
    if data_type=="date":
        text=unicodedata.normalize("NFKC",str(value)).strip()
        text=re.sub(r'\b([A-Za-z]{3})\.\s*',r'\1 ',text)
        if any(c in text for c in "年月日"):
            text=re.sub(r"\s+","",text)
            # Filled form rules may surround components, never split digits.
            filled=re.fullmatch(r'_*([0-9]{4})_*年_*([0-9]{1,2})_*月_*([0-9]{1,2})_*日_*',text)
            if filled:text='{}年{}月{}日'.format(*filled.groups())
        for fmt in ("%Y-%m-%d","%Y/%m/%d","%Y.%m.%d","%Y年%m月%d日","%Y%m%d"):
            try: return datetime.strptime(text,fmt).date().isoformat()
            except ValueError: pass
        # 10/11/2026 is deliberately unresolved, rather than guessing DMY or MDY.
        return _named_month_date(text)
    if data_type=="currency_code":
        text=compact(value).upper()
        if text.startswith('(') and text.endswith(')'):text=text[1:-1]
        mapping={"人民币":"CNY","RMB":"CNY","CNY":"CNY","美元":"USD","USD":"USD","欧元":"EUR","EUR":"EUR","港币":"HKD","HKD":"HKD","英镑":"GBP","GBP":"GBP","日元":"JPY","JPY":"JPY"}
        mapping["CNY-RENMINBI"]="CNY"
        mapping["CNY人民币"]="CNY"
        if text not in mapping: raise ValueError("unknown currency")
        return mapping[text]
    if data_type=="account":
        text=re.sub(r"[\s-]","",unicodedata.normalize("NFKC",str(value)))
        if not text or not re.fullmatch(r"[A-Za-z0-9]+",text): raise ValueError("invalid account")
        return text
    if data_type=='unit':
        return normalize_unit(value)
    if data_type=="list":
        if not isinstance(value,list) or not all(isinstance(x,str) for x in value): raise ValueError("invalid list")
        return value
    if data_type=="rows":
        if not isinstance(value,list) or not all(isinstance(x,dict) for x in value): raise ValueError("invalid rows")
        # Preserve row identities, units and source IDs. No invented scalar aggregation.
        json.dumps(value,allow_nan=False)
        return value
    if not isinstance(value,str): raise ValueError("invalid text")
    return unicodedata.normalize("NFKC",value).strip()


def equivalent(a,b):
    if isinstance(a,list) and isinstance(b,list):
        return len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
    if isinstance(a,dict) and isinstance(b,dict):
        keys=set(a)-{"block_ids","raw_values"}
        return keys==set(b)-{"block_ids","raw_values"} and all(equivalent(a[k],b[k]) for k in keys)
    try:
        if not isinstance(a,(list,dict)) and not isinstance(b,(list,dict)):
            return Decimal(str(a))==Decimal(str(b))
    except (InvalidOperation,ValueError):
        pass
    return compact(a)==compact(b)


def field_equivalent(a, b, spec):
    """Numeric equality must not erase zeros in normalized account/text IDs."""
    if spec['data_type'] in {'account', 'text'}:
        if a is None or b is None:
            return a is None and b is None
        return isinstance(a, str) and isinstance(b, str) and compact(a) == compact(b)
    return equivalent(a, b)


def _source_without_label(raw, spec):
    text=unicodedata.normalize('NFKC',raw).strip()
    source_labels={'invoice_no':['Rechnungsnummer'],'contract_no':['Contract No.'],
                   'payee_account':['Account No','Account No.','Account Number'],
                   'seller':['Verkäufer'],'buyer':['Käufer'],
                   'currency':['Währung'],'date':['Datum'],'payment_terms':['Zahlungsbedingungen']}
    for label in sorted({spec['label'],*spec.get('aliases',[]),*source_labels.get(spec.get('key'),[])},key=len,reverse=True):
        text=re.sub(r'^'+re.escape(label)+r'\s*[:：]\s*','',text,flags=re.I)
    return text


_IDENTIFIER_KEYS = {'contract_no', 'invoice_no', 'order_no', 'bill_of_lading_no', 'proforma_invoice_no'}


def identifier_source_check(raw, spec, texts):
    """A Latin/numeric identifier must occur whole in one actual source block.

    Keep a map to whitespace-preserving text: compacting the whole line would
    make a following Date label look like an identifier suffix. Separate OCR
    blocks cannot be joined to invent a complete identifier, though its printed
    label may be in a different block from the complete value.
    """
    account = spec['data_type'] == 'account'
    if not account and spec['key'] not in _IDENTIFIER_KEYS:
        return dict(complete=True)
    token = compact(_source_without_label(raw, spec))
    if not token:
        return dict(complete=False)

    def following_field(tail):
        # This is only eligibility for an independent pixel read, not a trusted
        # delimiter. Unknown labels or untyped following values stay unresolved.
        for label, kind in (('Währung', 'currency_code'), ('Currency', 'currency_code'),
                            ('币种', 'currency_code'), ('Date', 'date'), ('Datum', 'date'), ('日期', 'date')):
            match = re.fullmatch(re.escape(label.casefold()) + r'\s*[:：]\s*(.+)', tail.strip())
            if match:
                try:
                    value = normalize(match[1], kind)
                    if value is not None:
                        return dict(kind='possible_following_field_merge', following_label=label,
                                    following_type=kind, following_value=value)
                except (TypeError, ValueError):
                    pass
        return None

    def alphanumeric(char):
        return char.isascii() and char.isalnum()

    def continues(text, edge, direction, token_edge):
        pos = edge - 1 if direction < 0 else edge
        adjacent = pos
        while 0 <= pos < len(text) and text[pos].isspace():
            pos += direction
        if not 0 <= pos < len(text):
            return False
        char = text[pos]
        if pos == adjacent and alphanumeric(char):
            return True
        if char in '-/._':
            other = pos + direction
            # A sentence period followed by whitespace is punctuation, not a
            # connector to the next field label. Hyphens/slashes may be spaced.
            if char == '.' and pos != adjacent:
                return False
            if char != '.':
                while 0 <= other < len(text) and text[other].isspace():
                    other += direction
            if 0 <= other < len(text) and alphanumeric(text[other]):
                return True
        # An account can contain groups of digits separated by printed spaces.
        # A quote of only one group is not complete evidence of that account.
        return account and pos != adjacent and char in '0123456789' and token_edge in '0123456789'

    possible_merge = None
    for original in texts:
        text = unicodedata.normalize('NFKC', original).casefold()
        positions = [i for i, char in enumerate(text) if not char.isspace()]
        joined = ''.join(text[i] for i in positions)
        start = joined.find(token)
        while start >= 0:
            left, right = positions[start], positions[start + len(token) - 1] + 1
            left_continues = continues(text, left, -1, token[0])
            right_continues = continues(text, right, 1, token[-1])
            if not left_continues and not right_continues:
                return dict(complete=True)
            if not left_continues and right_continues:
                possible_merge = possible_merge or following_field(text[right:])
            start = joined.find(token, start + 1)
    result = dict(complete=False)
    if possible_merge:
        result['boundary'] = possible_merge
    return result


def normalize_source(raw,spec):
    """Remove an explicit field label, never arbitrary digits or business words."""
    text = _source_without_label(raw, spec)
    if spec['data_type']=='date':
        # A prose reference such as 于2026年10月12日订立的授信函 contains one date.
        matches=re.findall(r'(?<![\d_])_*[0-9]{4}[\s_]*年[\s_]*[0-9]{1,2}[\s_]*月[\s_]*[0-9]{1,2}[\s_]*日_*(?![\d_])|(?<!\d)[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}(?!\d)',text)
        if len(matches)==1:return normalize(matches[0],'date')
    if spec['data_type']=='text':
        text=selection_label(text)
        if spec.get('choices'):return normalize_choice(text,spec)
    if spec.get('measurement') and spec['data_type']=='decimal':
        match=re.fullmatch(r'([+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*([^\d]+)',text)
        if match:
            normalize_unit(match[2])  # Only an explicit registered unit may be separated.
            return decimal_value(match[1])
    return normalize(text,spec['data_type'])


def selection_label(text):
    """Remove printed mark tokens only; this never decides what the mark means."""
    return re.sub(r'^\s*(?:[☑☒✓✔×✗□]|\[[ xX✓✔]*\])\s*','',text)


def normalize_choice(value,spec):
    for canonical,aliases in spec.get('choices',{}).items():
        if any(compact(value)==compact(a) for a in [canonical,*aliases]):return canonical
    raise ValueError('unknown choice')


def normalize_unit(value):
    text=compact(value)
    if text.startswith('(') and text.endswith(')'):text=text[1:-1]
    text=re.sub(r'^(?:(?:cny|rmb|usd|eur|元|人民币|美元)\s*)?[/／]','',text)
    aliases={'MT':['mt','metricton','metrictons','metrictonne','metrictonnes','tonne','tonnes','t','吨','公吨'],
             'kg':['kg','kgs','kilogram','kilograms','千克','公斤'],
             'COILS':['coil','coils','卷'],'PCS':['pc','pcs','piece','pieces','件','个','stk','stk.','stück','stücke']}
    for canonical,labels in aliases.items():
        if text in labels:return canonical
    # "ton" alone may mean a short/long ton; no implicit metric assumption.
    raise ValueError('unknown or ambiguous unit')
