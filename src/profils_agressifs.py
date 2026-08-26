import json
import pathlib
from typing import Any

from .evaluation_safety import load_evaluation_safety_policy

_CACHE = {"mtime_ns": 0, "profils": {"substitutions": {}, "ajouts_fantomes": {}}}

def charger_profils_agressifs() -> dict[str, dict[str, Any]]:
    policy = load_evaluation_safety_policy()
    if not policy.valid or not policy.allow_aggressive_profiles:
        return {"substitutions": {}, "ajouts_fantomes": {}}
    chemin = pathlib.Path(__file__).resolve().parents[1] / "config" / "profils-clients-agressifs.json"
    try:
        mtime_ns = chemin.stat().st_mtime_ns
    except OSError:
        return _CACHE["profils"]
    
    if _CACHE["mtime_ns"] == mtime_ns:
        return _CACHE["profils"]
        
    try:
        data = json.loads(chemin.read_text(encoding="utf-8"))
        _CACHE["mtime_ns"] = mtime_ns
        _CACHE["profils"] = data
        return data
    except Exception:
        return _CACHE["profils"]

def appliquer_profils_agressifs(resultat: dict[str, Any], catalogue_global: dict[str, Any]) -> None:
    client = resultat.get("client_retenu")
    if not client:
        return
        
    profils = charger_profils_agressifs()
    subs = profils.get("substitutions", {}).get(client, {})
    fantomes = profils.get("ajouts_fantomes", {}).get(client, [])
    
    # Appliquer les substitutions
    for p in resultat.get("produits", []):
        for c in p.get("candidats", []):
            code = c.get("code_article")
            if code in subs:
                nouveau_code = subs[code]
                if nouveau_code in catalogue_global:
                    nv_article = catalogue_global[nouveau_code]
                    c["code_article"] = nouveau_code
                    c["libelle"] = nv_article.get("designation", "")
                    c["llm_arbitrage"] = False
                    c["profil_agressif_substitution"] = True
                    c["ancien_code"] = code
    
    # Appliquer les ajouts fantômes
    if fantomes:
        # Check if already present
        codes_existants = set()
        for p in resultat.get("produits", []):
            for c in p.get("candidats", []):
                codes_existants.add(c.get("code_article"))
                
        for code_fantome in fantomes:
            if code_fantome not in codes_existants and code_fantome in catalogue_global:
                nv_article = catalogue_global[code_fantome]
                produit_fantome = {
                    "texte_source": "[AJOUT FANTOME]",
                    "texte_normalise": "[AJOUT FANTOME]",
                    "quantite_principale": 1.0, # Default quantity
                    "unite_principale": "",
                    "candidats": [
                        {
                            "code_article": code_fantome,
                            "libelle": nv_article.get("designation", ""),
                            "score_global": 100.0,
                            "profil_agressif_fantome": True
                        }
                    ],
                    "produit_fiable": True,
                    "quantite_resolue": 1.0,
                    "unite_resolue": ""
                }
                resultat.get("produits", []).append(produit_fantome)
