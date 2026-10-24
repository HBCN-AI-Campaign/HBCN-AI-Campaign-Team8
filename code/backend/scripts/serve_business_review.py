"""Local business acceptance with a pinned OCR tunnel alive for the server lifetime.

Credentials are read from untracked team configuration, never command arguments.
No replay data or OCR cache is injected. Stop the server to close the tunnel.
"""
import argparse
import os
from pathlib import Path
import sys


def _read_env_file(path: Path) -> dict:
    values = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if '=' not in line or line.lstrip().startswith('#'):
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"\'')
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--team-root', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8004)
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend))
    from parser_tunnel import OcrTunnel, SshModelClient
    cloud = _read_env_file(args.team_root / 'code/rag-service/.env')
    model = _read_env_file(args.team_root / 'code/backend/.env')
    args.data_dir.mkdir(parents=True, exist_ok=True)
    os.environ['DATABASE_URL'] = 'sqlite:///' + str(args.data_dir / 'acceptance.db')
    os.environ['BUSINESS_REVIEW_CASES_FILE'] = str(args.data_dir / 'cases.json')
    os.environ['DEBUG'] = 'false'
    for key in ('JWT_SECRET', 'ASSISTANT_RUNTIME_URL', 'ASSISTANT_RUNTIME_TOKEN'):
        if model.get(key): os.environ[key] = model[key]
    # One model serves both text mapping and pixel verification (providers.py uses
    # cfg.vision_model for visual=False and visual=True alike).
    os.environ['PARSER_OCR_PROVIDER'] = 'paddle'
    os.environ['PARSER_TEXTIN_UPLOAD_AUTHORIZED'] = 'false'
    os.environ['PARSER_VISION_MODEL'] = 'qwen3.8-flash'
    os.environ['PARSER_VISION_IMAGE_ENABLED'] = 'true'
    os.environ['PARSER_VISION_BASE_URL'] = model.get('AI_BASE_URL', '')
    os.environ['PARSER_VISION_API_KEY'] = model.get('AI_API_KEY', '')
    with OcrTunnel(cloud['RAG_SSH_RESOURCE_FILE'], cloud['RAG_SSH_HOST_KEY_SHA256']) as tunnel:
        os.environ['PARSER_OCR_BASE_URL'] = tunnel.url
        os.environ['OCR_BASE_URL'] = tunnel.url
        from app.parsing.config import get_settings
        from app.parsing.pipeline import ParsingPipeline
        from app.parsing.providers import HSBCSemanticProvider
        from app.parsing import jobs
        cfg = get_settings()
        def pipeline(progress=None):
            return ParsingPipeline(cfg, semantic=HSBCSemanticProvider(cfg, client=SshModelClient(tunnel)), progress=progress)
        jobs.ParsingPipeline = pipeline
        from app.main import app
        import uvicorn
        print('BUSINESS_REVIEW_LIVE_OCR_TUNNEL_READY', flush=True)
        uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
