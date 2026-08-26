import json
from pathlib import Path

preds_dir = Path("/opt/emalo-repondeur-worker/evaluation/predictions")
for p in sorted(preds_dir.glob("*.json")):
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        schema = d.get("schema", "no-schema")
        rows = len(d.get("rows", []))
        print(f"{p.name:50s} | schema={schema} | rows={rows}")
    except Exception as e:
        print(f"{p.name:50s} | error={e}")
