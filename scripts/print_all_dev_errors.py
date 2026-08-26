import json
from pathlib import Path

score_path = Path("/opt/emalo-autotune/private/development-v3-postpackaging-score.json")
data = json.loads(score_path.read_text(encoding="utf-8"))
results = data.get("results", [])

print(f"Total dev audios: {len(results)}\n")
for i, r in enumerate(results, 1):
    audio = r["audio"]
    text = r.get("transcription", "").replace("\n", " ")
    truth = r.get("truth", [])
    pred = r.get("predicted", [])
    missing = r.get("missing", [])
    extra = r.get("extra", [])
    causes = r.get("causes", [])
    print(f"[{i:02d}] {audio}")
    print(f"     Client: {r.get('truth_client')} (truth) vs {r.get('predicted_client')} (pred)")
    print(f"     Date: {r.get('truth_delivery_date')} (truth) vs {r.get('predicted_delivery_date')} (pred)")
    print(f"     Status: accepted={r.get('accepted')} | content_exact={r.get('content_exact')} | auto_exact={r.get('automation_exact')}")
    print(f"     Causes: {causes}")
    print(f"     Text: {text}")
    if missing:
        print(f"     Missing ({len(missing)}): {missing}")
    if extra:
        print(f"     Extra ({len(extra)}): {extra}")
    if r.get("expected_candidate_ranks"):
        print(f"     Candidate ranks: {r.get('expected_candidate_ranks')}")
    print("-" * 80)
