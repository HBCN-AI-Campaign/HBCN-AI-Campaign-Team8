"""Run from code/backend. Review the generated diff before updating the baseline."""
import json
from pathlib import Path

from app.routers.assistant import public_openapi

destination = Path(__file__).resolve().parents[3] / 'docs/ai-assistant/contracts/assistant-v1.openapi.json'
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(public_openapi(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(destination)
