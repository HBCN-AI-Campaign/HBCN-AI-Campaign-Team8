"""Deterministic synthetic mark cases, real providers, separate raw and gated results.

Gold is an instruction-defined engineering test, not a claim about real bank forms.
Images and provider responses stay in the ignored parser_data directory.
"""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw,ImageFont
from app.parsing.config import ParserSettings
from app.parsing.pipeline import ParsingPipeline
from app.parsing.preprocess import prepare
from app.parsing.providers import HSBCSemanticProvider,PaddleHttpProvider
from app.parsing.registry import FIELDS
from evaluate_parser import CachedOcr,CachedSemantic,env_file
from parser_tunnel import OcrTunnel,SshModelClient


CASES=[
    ('check_a','A check mark means selected. Choose exactly one option.',('check','empty'),'银行受托支付'),
    ('cross_selected_a','An X means selected. Choose exactly one option.',('cross','empty'),'银行受托支付'),
    ('cross_deleted_a','An X deletes an option. A check mark means selected.',('cross','check'),'借款人自主支付'),
    ('strike_deleted_a','A line through text deletes it. A check means selected.',('strike','check'),'借款人自主支付'),
    ('none','A check mark means selected. Choose exactly one option.',('empty','empty'),None),
    ('both','A check mark means selected. Choose exactly one option.',('check','check'),None),
    ('dash_unknown','Choose exactly one option. Unclear marks need review.',('dash','empty'),None),
]


def render(path,case):
    name,instruction,marks,_=case
    im=Image.new('RGB',(1200,650),'white');d=ImageDraw.Draw(im)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',29)
    title=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',38)
    d.text((45,40),'DRAWDOWN INSTRUCTION',font=title,fill='black')
    d.text((45,120),'Disbursement method',font=font,fill='black')
    d.text((45,180),instruction,font=font,fill='black')
    for i,(label,mark) in enumerate(zip(('Bank entrusted payment','Borrower autonomous payment'),marks)):
        x,y=65,290+i*115
        d.rectangle((x,y,x+40,y+40),outline='black',width=2)
        d.text((x+65,y),label,font=font,fill='black')
        if mark=='check': d.line([(x+5,y+22),(x+17,y+34),(x+35,y+5)],fill='black',width=5)
        if mark=='cross':
            d.line([(x+5,y+5),(x+35,y+35)],fill='black',width=4)
            d.line([(x+35,y+5),(x+5,y+35)],fill='black',width=4)
        if mark=='dash':d.line([(x+5,y+20),(x+35,y+20)],fill='black',width=4)
        if mark=='strike':d.line([(x+60,y+19),(x+65+d.textlength(label,font=font),y+19)],fill='black',width=4)
    im.save(path)


def raw_prediction(candidates):
    values=[]
    for c in candidates:
        if c.get('visual_state') in {'ambiguous','deleted','unselected'}:continue
        value=c.get('value')
        if value is None:continue
        choice=next(s for s in FIELDS['DRAWDOWN_INSTRUCTION'] if s['key']=='disbursement_method')
        from app.parsing.normalization import normalize_choice
        try:value=normalize_choice(value,choice)
        except ValueError:continue
        if value not in values:values.append(value)
    return values[0] if len(values)==1 else None


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',default='parser_data/evaluation/choices')
    p.add_argument('--ai-env',default='.env')
    p.add_argument('--ssh-config-env',default='../rag-service/.env')
    p.add_argument('--offline',action='store_true')
    args=p.parse_args();out=Path(args.output)
    for name in ('images','ocr','semantic'):(out/name).mkdir(parents=True,exist_ok=True)
    ai=env_file(args.ai_env);tunnel=None
    cfg=ParserSettings(ocr_base_url='http://127.0.0.1:7888',vision_base_url=ai.get('AI_BASE_URL',''),
        vision_api_key=ai.get('AI_API_KEY',''),vision_model=ai.get('AI_MODEL',''))
    if not args.offline:
        ssh=env_file(args.ssh_config_env)
        tunnel=OcrTunnel(ssh['RAG_SSH_RESOURCE_FILE'],ssh['RAG_SSH_HOST_KEY_SHA256'])
        cfg.ocr_base_url=tunnel.url
    op=PaddleHttpProvider(cfg);sp=HSBCSemanticProvider(cfg,client=SshModelClient(tunnel) if tunnel else None)
    ocr=CachedOcr(op,out/'ocr',args.offline);semantic=CachedSemantic(sp,out/'semantic',args.offline)
    pipeline=ParsingPipeline(cfg,ocr=ocr,semantic=semantic)
    original=FIELDS['DRAWDOWN_INSTRUCTION']
    choice=next(s for s in original if s['key']=='disbursement_method')
    FIELDS['DRAWDOWN_INSTRUCTION']=[choice]  # Test a registered submodule; no fake model responses.
    rows=[];start=time.monotonic()
    try:
        for case in CASES:
            name,_,_,expected=case;path=out/'images'/(name+'.png');render(path,case)
            doc=pipeline.parse_document(path,path.name,type_code='DRAWDOWN_INSTRUCTION')
            f=doc['fields'][0]
            # Image-only gets no OCR tokens. It is diagnostic output, never trusted source evidence.
            pages=prepare(path,cfg)
            image_raw=semantic.extract(pages,'DRAWDOWN_INSTRUCTION',[choice],visual=True)
            text_raw=[c for c in f['candidates'] if c['method']=='ocr_semantic']
            row=dict(case=name,expected=expected,image_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                ocr_text_guess=raw_prediction(text_raw),image_only_guess=raw_prediction(image_raw),
                hybrid_value=f['value'],hybrid_status=f['status'],correct=f['value']==expected,
                false_accept=f['value'] is not None and f['value']!=expected,
                errors=doc['issues'],field=f,image_only_candidates=image_raw)
            rows.append(row)
            (out/(name+'.result.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in row.items() if k not in {'field','image_only_candidates'}},ensure_ascii=False),flush=True)
        report=dict(cases=rows,count=len(rows),hybrid_correct=sum(r['correct'] for r in rows),
            false_accepts=sum(r['false_accept'] for r in rows),
            ocr_text_raw_correct=sum(r['ocr_text_guess']==r['expected'] for r in rows),
            image_only_raw_correct=sum(r['image_only_guess']==r['expected'] for r in rows),
            offline=args.offline,seconds=round(time.monotonic()-start,3),model=cfg.vision_model,
            ocr_live=ocr.live,ocr_replay=ocr.replay,semantic_live=semantic.live,semantic_replay=semantic.replay,
            note='Synthetic instruction-defined cases. Raw single-channel guesses are not evidence-validated acceptance.')
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False),flush=True)
    finally:
        FIELDS['DRAWDOWN_INSTRUCTION']=original
        op.close();sp.close()
        if tunnel:tunnel.close()


if __name__=='__main__':main()
