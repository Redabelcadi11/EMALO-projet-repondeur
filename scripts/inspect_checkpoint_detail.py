import json
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("evaluation/predictions/test-llama-1audio.checkpoint.json")
data = json.loads(path.read_text(encoding="utf-8"))
for r in data.get("rows", []):
    diag = r.get("diagnostics", {})
    llama_res = diag.get("llama_resolution", {})
    print("Error:", llama_res.get("error"))
