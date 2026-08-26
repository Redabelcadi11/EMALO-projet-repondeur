import json
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_error_analysis.py <score_json>")
        return 1
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = json.load(f)
    results = data.get("results", [])
    print(f"Total dev audios: {len(results)}")
    causes_count = {}
    for r in results:
        for c in r.get("causes", []):
            causes_count[c] = causes_count.get(c, 0) + 1
    print("Causes counts:\n", json.dumps(causes_count, indent=2))

    print("\n=== CLIENT ERRORS ===")
    for r in results:
        if not r.get("client_correct"):
            print(f"Audio: {r['audio']}, truth: {r.get('truth_client')}, pred: {r.get('predicted_client')}, text: {r.get('transcription', '')[:100]}")

    print("\n=== DATE ERRORS ===")
    for r in results:
        if not r.get("date_correct"):
            print(f"Audio: {r['audio']}, truth: {r.get('truth_delivery_date')}, pred: {r.get('predicted_delivery_date')}, text: {r.get('transcription', '')[:100]}")

    print("\n=== PERFECT CONTENT BUT REJECTED ===")
    for r in results:
        if r.get("content_exact") and not r.get("accepted"):
            print(f"Audio: {r['audio']}, accepted: {r.get('accepted')}, causes: {r.get('causes')}")

    print("\n=== SUMMARY OF MISSING / EXTRA PRODUCTS ===")
    missing_rank_dist = {}
    for r in results:
        for code, rank in r.get("expected_candidate_ranks", {}).items():
            rkey = str(rank)
            missing_rank_dist[rkey] = missing_rank_dist.get(rkey, 0) + 1
    print("Expected candidate rank distribution for missing codes:", json.dumps(missing_rank_dist, indent=2))

if __name__ == "__main__":
    main()
