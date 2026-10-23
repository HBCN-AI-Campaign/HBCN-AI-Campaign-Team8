"""Optional native-PDF scope for numbered goods tables in commercial contracts.

pdfplumber supplies geometry and literal row numbers, never accepted business
values. Scanned/unrecognised layouts retain the existing semantic/manual path.
"""
from dataclasses import replace
import re


def _compact(value):
    return re.sub(r'\s+','',value).lower()


def _header(table):
    values=table.extract()
    text=_compact(' '.join(str(c) for r in values[:6] for c in r if c))
    english=all(t in text for t in ('descriptionofgoods','quantity','unitprice','totalamount'))
    german=all(t in text for t in ('warenbeschreibung','menge','einzelpreis','gesamtbetrag'))
    if not (english or german):return None
    for index,row in enumerate(values[:6]):
        if row and _compact(str(row[0])) in {'no.','no','nr.','nr'}:
            cell=table.rows[index].cells[0]
            descriptions=[table.rows[index].cells[j] for j,c in enumerate(row)
                          if c and _compact(str(c)) in {'descriptionofgoods','warenbeschreibung'}]
            if cell and len(descriptions)==1 and descriptions[0]:return cell,descriptions[0]
    return None


def native_goods_scope(path,pages):
    scope=dict(method='pdfplumber_native_table',status='not_detected',regions=[],rows=[],description_sources=[],issues=[])
    if path.suffix.lower()!='.pdf':return scope
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages)!=len(pages):raise ValueError('page count mismatch')
            for number,native in enumerate(pdf.pages,1):
                recognised=0
                for table in native.find_tables():
                    headers=_header(table)
                    if headers is None:continue
                    header,description=headers
                    x0,y0,x1,y1=table.bbox
                    if not (0<=x0<x1<=native.width and 0<=y0<y1<=native.height):
                        scope['issues'].append('NATIVE_TABLE_GEOMETRY_INVALID');continue
                    # Table row reconstruction can miss a split last row. Read
                    # every original word in the actual number column instead.
                    anchors=[w for w in native.extract_words()
                             if re.fullmatch(r'[1-9][0-9]{0,3}',w['text'])
                             and header[0]<=((w['x0']+w['x1'])/2)<=header[2]
                             and header[3]<w['top'] and w['bottom']<=y1+.1]
                    if not anchors:continue
                    recognised+=1
                    scope['regions'].append(dict(page=number,bbox=[x0/native.width,y0/native.height,x1/native.width,y1/native.height]))
                    # Track all original OCR/native blocks in the description
                    # column, including a continuation above the next row's
                    # number. Their values are never copied into a business row.
                    for block in pages[number-1].blocks:
                        cx=(block.bbox[0]+block.bbox[2])*native.width/2
                        cy=(block.bbox[1]+block.bbox[3])*native.height/2
                        if description[0]<=cx<=description[2] and description[3]<cy<=y1:
                            scope['description_sources'].append(dict(block_id=block.id,page=number,bbox=block.bbox,text=block.text))
                    for w in anchors:
                        scope['rows'].append(dict(line_no=w['text'],page=number,
                            bbox=[w['x0']/native.width,w['top']/native.height,w['x1']/native.width,w['bottom']/native.height]))
                if recognised>1:scope['issues'].append('MULTIPLE_NUMBERED_GOODS_TABLES')
        if scope['rows']:
            scope['status']='detected'
            numbers=[int(r['line_no']) for r in scope['rows']]
            if numbers!=list(range(1,max(numbers)+1)):
                scope['issues'].append('NATIVE_TABLE_ROW_SEQUENCE_UNPROVEN')
            if len(numbers)>200:scope['issues'].append('NATIVE_TABLE_ROW_LIMIT')
    except Exception:
        # Optional routing cannot make the original parse fail or provide a
        # partly trusted scope after the native reader failed.
        scope.update(status='unavailable',regions=[],rows=[],description_sources=[],issues=['NATIVE_TABLE_SCOPE_UNAVAILABLE'])
    scope['issues']=list(dict.fromkeys(scope['issues']))
    return scope


def scope_pages(pages,scope):
    result=[]
    for page in pages:
        boxes=[r['bbox'] for r in scope['regions'] if r['page']==page.number]
        if not boxes:continue
        blocks=[b for b in page.blocks if any(
            box[0]-.003 <= (b.bbox[0]+b.bbox[2])/2 <= box[2]+.003 and
            box[1]-.003 <= (b.bbox[1]+b.bbox[3])/2 <= box[3]+.003 for box in boxes)]
        result.append(replace(page,blocks=blocks))
    return result
