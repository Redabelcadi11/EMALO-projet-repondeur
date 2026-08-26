import json
import sys
from pathlib import Path

score_file = Path("/opt/emalo-autotune/private/development-reprise-score.json")
if not score_file.exists():
    score_file = Path("/opt/emalo-autotune/private/development-v3-balanced-score.json")

data = json.loads(score_file.read_text(encoding="utf-8"))
results = data.get("results", [])

print("=== Detailed Inspection of rank=None missing lines ===")
total_none = 0
for r in results:
    audio = r.get("audio")
    ranks = r.get("expected_candidate_ranks", {})
    none_codes = [code for code, rank in ranks.items() if rank is None]
    if not none_codes:
        continue
    
    truth_by_code = {t.get("code"): t for t in r.get("truth", [])}
    print(f"\n--- Audio: {audio} ---")
    print(f"Transcript: {r.get('transcription')}")
    for code in none_codes:
        total_none += 1
        t = truth_by_code.get(code, {})
        print(f"  Missed True Product: [{code}] {t.get('label')} (qte={t.get('quantity')} {t.get('unit')})")
        diag = r.get("diagnostics", {})
        # List candidate products extracted
        for p in diag.get("products", []):
            seg_text = p.get("texte_segment") or p.get("mention")
            cands = p.get("candidats", [])
            cand_codes = [c.get("code_article") for c in cands[:3]]
            # print(f"    Segment: '{seg_text}' -> Top cands: {cand_codes}")

print(f"\nTotal rank=None missed lines: {total_none}")
