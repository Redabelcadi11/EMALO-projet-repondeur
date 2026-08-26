import json
import sys
from pathlib import Path

score_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/emalo-autotune/private/development-v3-balanced-score.json")
data = json.loads(score_file.read_text(encoding="utf-8"))

print(f"=== File: {score_file.name} ===")
if "metrics" in data:
    for k, v in data["metrics"].items():
        if k != "cause_counts":
            print(f"  {k}: {v}")
    print("  cause_counts:", json.dumps(data["metrics"].get("cause_counts", {}), ensure_ascii=False))

results = data.get("results", [])
print(f"\nTotal audios in results: {len(results)}")

for r in results:
    if len(sys.argv) > 2 and sys.argv[2] not in r.get("audio", ""):
        continue
    # If filtered to only predicted
    if not r.get("predicted") and len(sys.argv) > 2:
        continue
    missing = r.get("missing", [])
    extra = r.get("extra", [])
    truth = r.get("truth", [])
    pred = r.get("predicted", [])
    causes = r.get("causes", [])
    print(f"\n--- Audio: {r.get('audio')} ---")
    print(f"  Client: truth={r.get('truth_client')} pred={r.get('predicted_client')} (ok={r.get('client_correct')})")
    print(f"  Date: truth={r.get('truth_date')} pred={r.get('predicted_date')} (ok={r.get('date_correct')})")
    print(f"  Status: pred_status={r.get('predicted_status')} accepted={r.get('accepted')} exact_content={r.get('content_exact')}")
    print(f"  Causes: {causes}")
    print(f"  Text: {r.get('transcription')}")
    print(f"  Truth ({len(truth)} lines):")
    for t in truth:
        print(f"    - {t.get('code')} {t.get('label')} | qte={t.get('quantity')} {t.get('unit')}")
    print(f"  Predicted ({len(pred)} lines):")
    for p in pred:
        print(f"    - {p.get('code')} {p.get('label')} | qte={p.get('quantity')} {p.get('unit')} (source: '{p.get('source_text')}')")
    if missing:
        print(f"  Missing ({len(missing)} lines):")
        for m in missing:
            print(f"    - {m.get('code')} qte={m.get('quantity')} {m.get('unit')}")
    if extra:
        print(f"  Extra ({len(extra)} lines):")
        for e in extra:
            print(f"    - {e.get('code')} qte={e.get('quantity')} {e.get('unit')}")
