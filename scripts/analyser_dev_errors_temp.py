import json
from pathlib import Path

data = json.load(open('/opt/emalo-autotune/private/development-v3-postpackaging-score.json'))
results = data.get('results', [])

target_audios = [
    '2026-08-12_00-26-32_De-0621028163.wav',
    '2026-08-12_00-48-47_De-0614640948.wav',
    '2026-08-12_00-59-38_De-0663651399.wav',
    '2026-08-12_18-13-33_De-Inconnu.wav',
    '2026-08-12_22-49-10_De-0638233470.wav',
    '2026-08-12_23-15-15_De-0784126145.wav',
    '2026-08-13_01-15-05_De-0686306294.wav',
    '2026-08-13_02-20-48_De-0663651399.wav',
]

for r in results:
    if r['audio'] in target_audios:
        print(f"\n==========================================")
        print(f"AUDIO: {r['audio']}")
        print(f"CLIENT: truth={r['truth_client']}, pred={r['predicted_client']}")
        print(f"TRANSCRIPTION: {r['transcription']}")
        print(f"TRUTH LINES ({len(r.get('truth', []))}): {r.get('truth')}")
        print(f"PREDICTED LINES ({len(r.get('predicted', []))}): {r.get('predicted')}")
        print(f"MISSING: {r.get('missing')}")
        print(f"EXTRA: {r.get('extra')}")
        print(f"EXPECTED CANDIDATE RANKS: {r.get('expected_candidate_ranks')}")
