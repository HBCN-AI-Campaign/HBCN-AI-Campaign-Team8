"""Auditable pixel transcription when OCR and the full-page reading disagree.

Two views of the same model are a consistency gate, not independent accuracy
estimates. Never overwrite the OCR block or reinterpret its confidence.
"""
from copy import deepcopy
import hashlib
import re

from .normalization import field_equivalent, normalize_source
from .regional import crop_page

CORRECTABLE = {'RAW_VALUE_NOT_GROUNDED','VALUE_SOURCE_MISMATCH','LOW_OCR_SCORE','IDENTIFIER_SOURCE_INCOMPLETE'}


def correction_crop(candidate,spec,pages,max_pixels):
    if candidate.get('method')!='vision' or candidate.get('verification'):
        return None
    if candidate.get('visual_state')!='clear' or candidate.get('normalized_value') is None:
        return None
    issues=set(candidate.get('issues',[]))
    if not issues or not issues.issubset(CORRECTABLE):return None
    if 'IDENTIFIER_SOURCE_INCOMPLETE' in issues and candidate.get('identifier_boundary', {}).get('kind') != 'possible_following_field_merge':
        return None
    anchors=[(p,b) for p in pages for b in p.blocks if b.id in candidate.get('block_ids',[]) and not b.method.endswith('_region')]
    # One line containing the actual numeric token is the anchor. Other prose
    # (especially an amount in words) must not influence the blind local read.
    numeric=[(p,b) for p,b in anchors if re.search(r'\d{2,}',b.text)]
    if numeric:anchors=numeric
    if len(anchors)!=1:return None
    page,block=anchors[0]
    box=block.bbox
    if (box[2]-box[0])*(box[3]-box[1])>.1:return None
    prepared=crop_page(page,box,max_pixels)
    if prepared is None:return None
    crop,pixels=prepared
    return crop,dict(page=page.number,bbox=[pixels[0]/page.width,pixels[1]/page.height,pixels[2]/page.width,pixels[3]/page.height],
        anchor_block_id=block.id,anchor_text=block.text,anchor_bbox=block.bbox,
        page_image_sha256=hashlib.sha256(page.image).hexdigest(),page_width=page.width,page_height=page.height,
        crop_width=crop.width,crop_height=crop.height,image_sha256=hashlib.sha256(crop.image).hexdigest())


def validate_transcription(original,spec,transcription,source):
    result=deepcopy(original)
    result.update(verification='blind_region_pixels',raw_value=transcription.get('raw_text'),issues=[],
        pixel_evidence=dict(source,transcription=transcription,full_page_value=original['normalized_value'],
                            full_page_raw_value=original.get('raw_value'),same_model=True))
    result.pop('superseded',None)
    if 'IDENTIFIER_SOURCE_INCOMPLETE' in original.get('issues',[]) and original.get('identifier_boundary', {}).get('kind') != 'possible_following_field_merge':
        result['issues'].append('IDENTIFIER_CORRECTION_NOT_ELIGIBLE')
    if transcription.get('visual_state')!='clear':result['issues'].append('REGION_NOT_CLEAR')
    try:
        value=normalize_source(transcription.get('raw_text'),spec)
    except (ValueError,TypeError):value=None
    result['normalized_value']=value
    if value is None:result['issues'].append('REGION_VALUE_INVALID')
    elif not field_equivalent(value,original['normalized_value'],spec):result['issues'].append('VISUAL_READS_DISAGREE')
    # Source OCR evidence remains verbatim; the different raw_value is explicitly
    # a model transcription of this hashed image, not an OCR-supported quote.
    result['source']={'page':source['page'],'bbox':source['bbox']}
    result['reason']='整页读取与不含OCR文本/候选值的局部图像转录一致；保留原OCR及图像哈希，仍属同模型核对。'
    return result
