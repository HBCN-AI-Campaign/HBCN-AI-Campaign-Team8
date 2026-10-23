"""Serial live baseline/replay. Source PDFs and raw outputs stay outside Git."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.parsing.config import ParserSettings
from app.parsing.contracts import Block
from app.parsing.contracts import ParseError
from app.parsing.pipeline import ParsingPipeline
from app.parsing.providers import HSBCSemanticProvider, PaddleHttpProvider, SYSTEM_PROMPT, REGION_TRANSCRIPTION_PROMPT, RECORDS_PROMPT, TERMS_PROMPT, INVOICE_ITEMS_PROMPT
from app.parsing.registry import TYPE_LABELS
from parser_tunnel import OcrTunnel, SshModelClient


def env_file(path):
    return {s.split("=",1)[0].strip():s.split("=",1)[1].strip().strip("\"'")
            for s in Path(path).read_text(encoding="utf-8-sig").splitlines()
            if "=" in s and not s.lstrip().startswith("#")}


class CachedOcr:
    def __init__(self,provider,root,offline=False): self.provider=provider;self.root=root;self.live=0;self.live_attempts=0;self.replay=0;self.offline=offline
    def analyze(self,page):
        key=hashlib.sha256(page.image).hexdigest()
        dest=self.root/(key+".json")
        if dest.exists():
            self.replay+=1
            blocks=[Block(**b) for b in json.loads(dest.read_text(encoding="utf-8"))]
            for i,b in enumerate(blocks): b.id=f"p{page.number}b{i}"
            return blocks
        if self.offline: raise ParseError("OFFLINE_OCR_CACHE_MISS")
        self.live_attempts+=1
        result=self.provider.analyze(page);self.live+=1
        dest.write_text(json.dumps([asdict(b) for b in result],ensure_ascii=False,indent=2),encoding="utf-8")
        return result

    def close(self):self.provider.close()


class CachedSemantic:
    def __init__(self,provider,root,offline=False): self.provider=provider;self.root=root;self.live=0;self.live_attempts=0;self.replay=0;self.offline=offline
    def extract(self,pages,type_code,specs,*,visual):
        payload=[SYSTEM_PROMPT,self.provider.cfg.vision_model,type_code,specs,visual,
            [[p.number,hashlib.sha256(p.image).hexdigest(),[asdict(b) for b in p.blocks]] for p in pages]]
        key=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        dest=self.root/(key+".json")
        if dest.exists(): self.replay+=1;return json.loads(dest.read_text(encoding="utf-8"))
        if self.offline: raise ParseError("OFFLINE_SEMANTIC_CACHE_MISS")
        self.live_attempts+=1
        result=self.provider.extract(pages,type_code,specs,visual=visual);self.live+=1
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        return result

    def transcribe_region(self,page,spec):
        payload=[REGION_TRANSCRIPTION_PROMPT,self.provider.cfg.vision_model,
                 {k:spec[k] for k in ('key','label','data_type')},hashlib.sha256(page.image).hexdigest()]
        key=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        dest=self.root/(key+'.json')
        if dest.exists():self.replay+=1;return json.loads(dest.read_text(encoding='utf-8'))
        if self.offline:raise ParseError('OFFLINE_TRANSCRIPTION_CACHE_MISS')
        self.live_attempts+=1
        result=self.provider.transcribe_region(page,spec);self.live+=1
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result

    def extract_records(self,pages,spec,*,focus_page):
        prompt=TERMS_PROMPT if spec['key']=='facility_terms' else (INVOICE_ITEMS_PROMPT if spec['key']=='line_items' else RECORDS_PROMPT)
        payload=[prompt,self.provider.cfg.vision_model,spec,focus_page,
            [[p.number,hashlib.sha256(p.image).hexdigest(),[asdict(b) for b in p.blocks]] for p in pages]]
        key=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        dest=self.root/(key+'.json')
        if dest.exists():self.replay+=1;return json.loads(dest.read_text(encoding='utf-8'))
        if self.offline:raise ParseError('OFFLINE_RECORDS_CACHE_MISS')
        self.live_attempts+=1
        result=self.provider.extract_records(pages,spec,focus_page=focus_page);self.live+=1
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result

    def close(self):self.provider.close()


def implementation_hash():
    return hashlib.sha256(b''.join(p.name.encode()+p.read_bytes() for p in sorted((Path(__file__).resolve().parents[1]/'app'/'parsing').glob('*.py')))).hexdigest()


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-root",required=True)
    p.add_argument("--output",default="parser_data/evaluation/set8")
    p.add_argument("--ai-env",default=".env")
    p.add_argument("--ssh-config-env",help="Only reads resource-file path and pinned host-key from this dotenv")
    p.add_argument("--ocr-url",default="http://127.0.0.1:7888")
    p.add_argument("--filename",help="Limit iteration to one filename")
    p.add_argument("--type-code",choices=sorted(TYPE_LABELS),help="Explicit routing for one --filename; does not rename the original or measure classification accuracy")
    p.add_argument("--offline",action="store_true",help="Replay only; never connect to SSH/OCR/model")
    args=p.parse_args()
    if args.type_code and not args.filename:p.error('--type-code requires --filename')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    for name in ("ocr","semantic"): (out/name).mkdir(exist_ok=True)
    ai=env_file(args.ai_env)
    cfg=ParserSettings(ocr_base_url=args.ocr_url,vision_base_url=ai.get("PARSER_VISION_BASE_URL") or ai.get("AI_BASE_URL",""),
        vision_api_key=ai.get("PARSER_VISION_API_KEY") or ai.get("AI_API_KEY",""),
        vision_model=ai.get("PARSER_VISION_MODEL") or ai.get("AI_MODEL",""))
    tunnel=None
    if args.ssh_config_env and not args.offline:
        ssh=env_file(args.ssh_config_env)
        tunnel=OcrTunnel(ssh["RAG_SSH_RESOURCE_FILE"],ssh["RAG_SSH_HOST_KEY_SHA256"])
        cfg.ocr_base_url=tunnel.url
    ocr_provider=PaddleHttpProvider(cfg)
    semantic_provider=HSBCSemanticProvider(cfg,client=SshModelClient(tunnel) if tunnel else None)
    ocr=CachedOcr(ocr_provider,out/"ocr",args.offline);semantic=CachedSemantic(semantic_provider,out/"semantic",args.offline)
    pipeline=ParsingPipeline(cfg,ocr=ocr,semantic=semantic,progress=lambda **e: print(json.dumps(e,ensure_ascii=False),flush=True))
    docs=[];start=time.monotonic();implementation_start=implementation_hash()
    try:
        files=sorted(Path(args.source_root).glob("*.pdf"))
        if args.filename: files=[f for f in files if f.name==args.filename]
        for path in files:
            doc=pipeline.parse_document(path,path.name,type_code=args.type_code)
            docs.append(doc)
            (out/(path.stem+".result.json")).write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
            summary=dict(filename=path.name,pages=doc["page_count"],status=doc["status"],
                accepted=sum(f["status"]=="accepted" for f in doc["fields"]),fields=len(doc["fields"]),
                errors=doc["issues"],seconds=doc["seconds"])
            print(json.dumps(summary,ensure_ascii=False),flush=True)
        report=json.dumps(dict(documents=docs,seconds=round(time.monotonic()-start,3),
            ocr_live=ocr.live,ocr_replay=ocr.replay,semantic_live=semantic.live,semantic_replay=semantic.replay,
            ocr_live_attempts=ocr.live_attempts,semantic_live_attempts=semantic.live_attempts,
            ocr_failed_attempts=ocr.live_attempts-ocr.live,semantic_failed_attempts=semantic.live_attempts-semantic.live,
            model=cfg.vision_model,offline=args.offline,operator_type_code=args.type_code,
            implementation_sha256=implementation_start,implementation_end_sha256=implementation_hash(),
            implementation_changed_during_run=implementation_start!=implementation_hash()),ensure_ascii=False,indent=2)
        if not args.filename:(out/'run.json').write_text(report,encoding='utf-8')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        (out/f"run-{stamp}-{'offline' if args.offline else 'live'}.json").write_text(report,encoding='utf-8')
    finally:
        ocr_provider.close();semantic_provider.close()
        if tunnel: tunnel.close()


if __name__=="__main__": main()
