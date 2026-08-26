import json
import re
import string
from pathlib import Path
from datetime import date
from typing import Any, Dict, List

try:
    from rapidfuzz import fuzz
except ImportError:
    import sys
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rapidfuzz"])
    from rapidfuzz import fuzz

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.generer_comparaison_locale import read_truth, select_pairs

REPLAY_DIR = Path(__file__).resolve().parents[1] / "resultats" / "copilote-replay"
TRANSCRIPTIONS_DIR = Path(__file__).resolve().parents[1] / "resultats" / "transcriptions"
REGLES_PATH = Path(__file__).resolve().parents[1] / "config" / "regles-apprentissage.json"

STOPWORDS = {"et", "le", "la", "les", "un", "une", "des", "du", "de", "pour", "demain", "bonjour", "au", "aux", "il", "faut", "je", "voudrais", "svp", "merci", "kilo", "kilos", "litre", "litres", "carton", "cartons", "colis", "boite", "boites", "sachet", "sachets", "ca", "c", "est", "pas"}

def normalize(text):
    text = str(text).lower()
    text = text.translate(str.maketrans('', '', string.punctuation))
    return " ".join(text.split())

def main():
    print("Loading all historical truth CSVs...")
    all_truth = {}
    csv_files = list(REPLAY_DIR.glob("historique_es_pretest_*.csv")) + list(REPLAY_DIR.glob("commandes_ES_*.csv"))
    
    for csv_path in csv_files:
        try:
            truth = read_truth(csv_path)
            for k, v in truth.items():
                all_truth[k] = v
        except Exception as e:
            pass
            
    print(f"Total unique ES orders in history: {len(all_truth)}")
    
    print("Pairing audios...")
    pairs, coverage = select_pairs(all_truth, date(2026, 4, 1), date(2026, 8, 30))
    print(f"Total Paired Orders: {len(pairs)}")
    
    try:
        with open(REGLES_PATH, "r", encoding="utf-8") as f:
            regles_data = json.load(f)
    except Exception:
        regles_data = {"version": 1, "rules": []}
    
    # Remove old auto_apprentissage rules
    regles_data["rules"] = [r for r in regles_data.get("rules", []) if r.get("origin") != "auto_apprentissage"]
    existing_rules = regles_data["rules"]
    new_rules = []
    
    for pair in pairs:
        audio_path = Path(pair["audio"])
        json_name = audio_path.name.replace(".wav", "__transcription.json")
        json_path = TRANSCRIPTIONS_DIR / json_name
        
        if not json_path.exists():
            continue
            
        with open(json_path, "r", encoding="utf-8") as f:
            tdata = json.load(f)
            transcription_text = normalize(tdata.get("texte", ""))
            
        words = [w for w in transcription_text.split() if w not in STOPWORDS and len(w) > 2]
        if not words:
            continue
            
        es_order = pair["truth"]
        client = str(es_order.get("client_code", "")).strip()
        
        for article in es_order.get("lignes", []):
            designation = normalize(article.get("designation", ""))
            code_article = str(article.get("code", "")).strip()
            if not designation or not code_article:
                continue
                
            best_phrase = ""
            best_score = 0
            
            for i in range(len(words)):
                for j in range(i+1, min(i+4, len(words)+1)):
                    phrase = " ".join(words[i:j])
                    score_token = fuzz.token_set_ratio(designation, phrase)
                    if score_token > best_score:
                        best_score = score_token
                        best_phrase = phrase
            
            # If the best score is between 75 and 99, it means the client used a variant!
            if 75 <= best_score <= 99 and len(best_phrase) > 4:
                rule_id = f"auto_{client}_{code_article}_{best_phrase.replace(' ', '_')}"
                if not any(r.get("id") == rule_id for r in existing_rules + new_rules):
                    new_rules.append({
                        "id": rule_id,
                        "client_all": [client],
                        "mention_any": [best_phrase],
                        "label_all": [article.get("designation", "")],
                        "bonus": 90,
                        "enabled": True,
                        "origin": "auto_apprentissage"
                    })
    
    regles_data["rules"].extend(new_rules)
    
    with open(REGLES_PATH, "w", encoding="utf-8") as f:
        json.dump(regles_data, f, indent=2, ensure_ascii=False)
        
    print(f"Mined {len(new_rules)} new rules from {len(pairs)} pairs!")

if __name__ == "__main__":
    main()
