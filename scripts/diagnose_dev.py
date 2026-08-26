import json
import sys
from collections import Counter
from pathlib import Path

score_file = Path("/opt/emalo-autotune/private/development-reprise-score.json")
if not score_file.exists():
    score_file = Path("/opt/emalo-autotune/private/development-v3-balanced-score.json")

data = json.loads(score_file.read_text(encoding="utf-8"))
results = data.get("results", [])

print(f"=== Total Results: {len(results)} ===")

print("\n--- Client Errors ---")
for r in results:
    if not r.get("client_correct"):
        print(f"Audio: {r.get('audio')}")
        print(f"  Truth client: {r.get('truth_client')}")
        print(f"  Pred client:  {r.get('predicted_client')}")
        t = str(r.get("transcription") or "")
        print(f"  Transcript:   {t[:120]}...")

print("\n--- Date Errors ---")
for r in results:
    if not r.get("date_correct"):
        print(f"Audio: {r.get('audio')}")
        print(f"  Truth date: {r.get('truth_delivery_date')}")
        print(f"  Pred date:  {r.get('predicted_delivery_date')}")
        t = str(r.get("transcription") or "")
        print(f"  Transcript:   {t[:120]}...")

print("\n--- Candidate Ranks for Missing Lines ---")
ranks = Counter()
for r in results:
    for code, rank in r.get("expected_candidate_ranks", {}).items():
        ranks[str(rank)] += 1
for k, v in sorted(ranks.items()):
    print(f"  rank {k}: {v}")

print("\n--- Missing lines details (first 15) ---")
count = 0
for r in results:
    for m in r.get("missing", []):
        code = m.get("code")
        rank = r.get("expected_candidate_ranks", {}).get(code)
        pred_codes = [p.get("code") for p in r.get("predicted", [])]
        print(f"Audio: {r.get('audio')} | Missing code: {code} qte={m.get('quantity')} {m.get('unit')} | rank={rank} | Predicted: {pred_codes}")
        count += 1
        if count >= 15:
            break
    if count >= 15:
        break

print("\n--- Extra lines details (first 15) ---")
count = 0
for r in results:
    for e in r.get("extra", []):
        print(f"Audio: {r.get('audio')} | Extra code: {e.get('code')} qte={e.get('quantity')} {e.get('unit')}")
        count += 1
        if count >= 15:
            break
    if count >= 15:
        break
