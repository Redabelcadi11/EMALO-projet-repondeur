import json
import glob
from pathlib import Path

for p in sorted(glob.glob('/opt/emalo-autotune/private/*score*.json')):
    try:
        data = json.loads(Path(p).read_text(encoding='utf-8'))
        print(f"=== {Path(p).name} ===")
        print(f"Keys: {list(data.keys())}")
        if 'summary' in data:
            print("Summary:", json.dumps(data['summary'], indent=2, ensure_ascii=False))
        if 'metrics' in data:
            print("Metrics:", json.dumps(data['metrics'], indent=2, ensure_ascii=False))
        if 'global' in data:
            print("Global:", json.dumps(data['global'], indent=2, ensure_ascii=False))
        # check first 5 keys if no summary/metrics
        for k in list(data.keys())[:8]:
            if k not in ('results', 'predictions', 'truth', 'summary', 'metrics', 'global'):
                print(f"  {k}: {data[k]}")
    except Exception as e:
        print(f"Error {p}: {e}")
