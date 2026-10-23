"""Local browser acceptance: isolated DB/uploads, real-response replay, no inference.

Run Vite separately with HBCN_API_TARGET=http://127.0.0.1:18108.
Test accounts: parser-operator / parser-reviewer, password ParserTest-Local-2026.
Only loopback is supported. Never use this replay server for production.
"""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=18108)
    parser.add_argument('--data-dir',help='Dedicated directory under backend/parser_data; defaults to the existing local acceptance directory')
    parser.add_argument('--cache-root',default='parser_data/evaluation/set8',help='Frozen OCR/model cache, read only; no inference is permitted')
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('port must be 1024..65535')
    backend=Path(__file__).resolve().parents[1]
    private=(backend/(args.data_dir or 'parser_data/browser-acceptance')).resolve()
    if not private.is_relative_to((backend/'parser_data').resolve()):
        parser.error('--data-dir must stay inside backend/parser_data')
    private.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(backend))
    # These must precede app/config/database imports; no default DB lifespan.
    os.environ['DATABASE_URL']='sqlite:///'+str(private/'acceptance.db')
    os.environ['DEBUG']='false'
    from app import config
    config.UPLOAD_DIR=private/'uploads'
    from app.main import app
    from app.database import Base,engine,SessionLocal
    from app.models import User,Role,Customer
    from app.security import hash_password
    from app.parsing import jobs
    from app.parsing.pipeline import ParsingPipeline
    from app.parsing.config import ParserSettings
    from app.parsing.providers import PaddleHttpProvider,HSBCSemanticProvider
    from evaluate_parser import CachedOcr,CachedSemantic,env_file
    jobs.DATA_DIR=private/'runs'
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for name,role in [('parser-operator',Role.OPERATOR),('parser-reviewer',Role.REVIEWER)]:
            if not db.query(User).filter_by(username=name).first():
                db.add(User(username=name,display_name='文件解析隔离验收',
                            hashed_password=hash_password('ParserTest-Local-2026'),role=role))
        if not db.query(Customer).filter_by(customer_no='PARSER-TEST-8').first():
            db.add(Customer(customer_no='PARSER-TEST-8',name='ABCD有限公司'))
        db.commit()
    ai=env_file(backend/'.env')
    cfg=ParserSettings(vision_base_url=ai.get('PARSER_VISION_BASE_URL') or ai.get('AI_BASE_URL',''),
        vision_api_key=ai.get('PARSER_VISION_API_KEY') or ai.get('AI_API_KEY',''),
        vision_model=ai.get('PARSER_VISION_MODEL') or ai.get('AI_MODEL',''))
    cache=(backend/args.cache_root).resolve()
    if not all((cache/d).is_dir() for d in ('ocr','semantic')):
        parser.error('run evaluate_parser.py first to populate the private real-response cache')
    def factory(progress=None):
        return ParsingPipeline(cfg,ocr=CachedOcr(PaddleHttpProvider(cfg),cache/'ocr',True),
            semantic=CachedSemantic(HSBCSemanticProvider(cfg),cache/'semantic',True),progress=progress)
    jobs.ParsingPipeline=factory
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)


if __name__=='__main__':main()
