#!/usr/bin/env python3
import sys, os, time
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from src.runtime_paths import bootstrap_runtime_environment
bootstrap_runtime_environment()

from scripts.generer_comparaison_locale import read_truth, select_pairs, prediction_lines, unique_phone_clients
from extraire_informations import traiter_transcriptions

csv_path = ROOT / "resultats" / "copilote-replay" / "commandes_ES_200_dernieres_au_2026-08-11.csv"
truth = read_truth(csv_path)

audios_dir = ROOT / "resultats" / "transcriptions"
wav_paths = list(audios_dir.glob("*__transcription.json"))
wav_paths = [Path(str(p).replace("__transcription.json", ".wav")) for p in wav_paths]

phones = unique_phone_clients()
pairs, coverage = select_pairs(truth, date(2026, 8, 1), date(2026, 8, 12))

# Get the JSON paths for these pairs
json_paths = []
for p in pairs:
    stem = p['audio'].stem
    json_path = ROOT / "resultats" / "transcriptions" / f"{stem}__transcription.json"
    json_paths.append(json_path)

print(f"Running local extraction on {len(json_paths)} files...")
start = time.perf_counter()
results = traiter_transcriptions(chemins_transcriptions=json_paths)
print(f"Extraction done in {time.perf_counter() - start:.1f}s")

res_map = {r['fichier_transcription']: r for r in results}

correct_dates = 0
correct_clients = 0
perfect_orders = 0
total_es_lines = 0
found_es_lines = 0
software_correct_lines = 0
software_total_lines = 0

for p in pairs:
    stem = p['audio'].stem
    json_name = f"{stem}__transcription.json"
    predicted = res_map.get(json_name, {})
    
    # Check client
    pred_client = str(predicted.get("client_retenu") or "")
    truth_client = str(p['truth'].get("client_code") or "")
    client_ok = (pred_client == truth_client)
    if client_ok: correct_clients += 1
        
    # Check date
    date_iso = predicted.get("date_livraison", {}).get("date_iso")
    date_ok = False
    if date_iso:
        try:
            date_ok = (date.fromisoformat(date_iso) == p['truth'].get("order_date"))
        except:
            pass
    if date_ok: correct_dates += 1
        
    # Check products
    t_lines = prediction_lines(p['truth'])
    p_lines = prediction_lines(predicted)
    
    total_es_lines += len(t_lines)
    software_total_lines += len(p_lines)
    
    t_codes = [l['code'] for l in t_lines]
    p_codes = [l['code'] for l in p_lines]
    
    found = 0
    for code in t_codes:
        if code in p_codes:
            found += 1
            found_es_lines += 1
            
    for code in p_codes:
        if code in t_codes:
            software_correct_lines += 1
            
    if client_ok and date_ok and len(t_lines) == len(p_lines) and found == len(t_lines):
        perfect_orders += 1

print("\n=== NOUVEAUX RESULTATS APRES CORRECTIONS ===")
print(f"Total Paires : {len(pairs)}")
print(f"Client correct : {correct_clients}/{len(pairs)} ({correct_clients/len(pairs)*100:.1f}%)")
print(f"Date correcte : {correct_dates}/{len(pairs)} ({correct_dates/len(pairs)*100:.1f}%)")
print(f"Lignes ES trouvées (Rappel) : {found_es_lines}/{total_es_lines} ({found_es_lines/total_es_lines*100:.1f}%)")
print(f"Lignes Logiciel correctes (Précision) : {software_correct_lines}/{software_total_lines} ({software_correct_lines/software_total_lines*100:.1f}%)")
