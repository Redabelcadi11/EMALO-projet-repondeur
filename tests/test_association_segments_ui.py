from __future__ import annotations

import json
from pathlib import Path

import generer_ui_data_prod as ui_data
from extraire_informations import construire_lignes_commande
from prod_pipeline import summarize_command


def _produit(
    segment_index: int,
    texte_source: str,
    code: str | None,
    libelle: str = "",
    fiable: bool = True,
) -> dict:
    selection = (
        {
            "code_article": code,
            "libelle_article": libelle,
            "score_global": 90.0,
            "source_recherche": "cadencier_client",
            "prix": 1.0,
        }
        if code
        else None
    )
    return {
        "segment_id": f"segment-{segment_index}",
        "segment_index": segment_index,
        "texte_source": texte_source,
        "quantite_principale": 1.0,
        "quantite_resolue": 1.0 if code else None,
        "unite_principale": "PCE",
        "unite_resolue": "PCE" if code else None,
        "produit_fiable": fiable,
        "produit_reconnu": bool(code and fiable),
        "ambigu": not fiable,
        "selection": selection,
    }


def _commande_decalee() -> dict:
    produits = [
        _produit(1, "1 lait non retenu", None, fiable=False),
        _produit(2, "3 stracciatella", "STRAC", "STRACCIATELLA", fiable=True),
        _produit(3, "1 jambon italien", "JAMB", "JAMBON ITALIEN", fiable=True),
    ]
    lignes, _ = construire_lignes_commande(produits)
    return {
        "fichier_audio": "audio.ogg",
        "client_retenu": "CLIENT",
        "clients_candidats": [],
        "date_livraison": {},
        "produits": produits,
        "lignes_commande": lignes,
        "statut": "PROBLEMATIQUE",
        "raisons_problematiques": [],
    }


def test_lignes_conservent_l_identifiant_du_segment_apres_filtrage() -> None:
    commande = _commande_decalee()

    assert [ligne["ordre_ligne"] for ligne in commande["lignes_commande"]] == [1, 2]
    assert [ligne["segment_id"] for ligne in commande["lignes_commande"]] == [
        "segment-2",
        "segment-3",
    ]


def test_preview_ui_associe_la_ligne_a_son_segment_et_non_a_sa_position() -> None:
    preview = summarize_command(_commande_decalee(), Path("audio.ogg"))
    produits = preview["product_recognition"]

    assert len(produits) == 2
    assert produits[0]["segment_id"] == "segment-2"
    assert produits[0]["product_code"] == "STRAC"
    assert produits[0]["product_label"] == "STRACCIATELLA"
    assert produits[1]["segment_id"] == "segment-3"
    assert produits[1]["product_code"] == "JAMB"


def test_generation_ui_associe_la_ligne_a_son_segment_et_non_a_sa_position(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commande = _commande_decalee()
    extraction = tmp_path / "audio__extraction.json"
    extraction.write_text(json.dumps(commande), encoding="utf-8")
    monkeypatch.setattr(ui_data, "EXTRACTIONS_DIR", tmp_path)

    details = ui_data.problem_recognition_details("audio.ogg")
    produits = details["product_recognition"]

    assert len(produits) == 2
    assert produits[0]["segment_id"] == "segment-2"
    assert produits[0]["product_label"] == "STRACCIATELLA"
    assert produits[1]["segment_id"] == "segment-3"
    assert produits[1]["product_label"] == "JAMBON ITALIEN"


def test_ui_n_affiche_pas_un_span_explicitement_non_reconnu(
    tmp_path: Path,
    monkeypatch,
) -> None:
    produit = _produit(9, "sinon n importe", "FAUX", "FAUX PRODUIT", fiable=False)
    produit["produit_reconnu"] = False
    commande = {
        "fichier_audio": "audio.ogg",
        "client_retenu": "CLIENT",
        "client_nom_retenu": "CLIENT TEST",
        "clients_candidats": [],
        "date_livraison": {},
        "produits": [produit],
        "lignes_commande": [],
        "statut": "PROBLEMATIQUE",
        "raisons_problematiques": [],
    }

    assert summarize_command(commande, Path("audio.ogg"))["product_recognition"] == []

    extraction = tmp_path / "audio__extraction.json"
    extraction.write_text(json.dumps(commande), encoding="utf-8")
    monkeypatch.setattr(ui_data, "EXTRACTIONS_DIR", tmp_path)
    assert ui_data.problem_recognition_details("audio.ogg")["product_recognition"] == []


def test_details_ambiguite_ne_montrent_que_la_meme_famille() -> None:
    produit = _produit(
        1,
        "du gros sel de guerande",
        "SEL_MER",
        "SEL MER GROS 5K",
        fiable=True,
    )
    produit["ambigu"] = True
    produit["raisons_ambiguite"] = ["selection_article_non_nette"]
    produit["candidats"] = [
        produit["selection"],
        {
            "code_article": "SEL_GUERANDE",
            "libelle_article": "SEL DE GUERANDE GROS 800G",
            "score_texte": 80.0,
            "semantiquement_compatible": True,
        },
        {
            "code_article": "FROMAGE",
            "libelle_article": "FROMAGE FOUETTE SEL DE GUERANDE 4K",
            "score_texte": 75.0,
            "semantiquement_compatible": True,
        },
    ]
    commande = {
        "fichier_audio": "audio.ogg",
        "client_retenu": "CLIENT",
        "clients_candidats": [],
        "date_livraison": {},
        "produits": [produit],
        "lignes_commande": construire_lignes_commande([produit])[0],
        "statut": "VALIDEE",
        "raisons_problematiques": ["produit_ambigu_ligne_1"],
    }

    details = summarize_command(commande, Path("audio.ogg"))[
        "product_recognition"
    ][0]

    assert [item["product_code"] for item in details["alternatives"]] == [
        "SEL_GUERANDE"
    ]


def test_ui_affiche_un_code_reconnu_sans_inventer_de_ligne_commande(
    tmp_path: Path,
    monkeypatch,
) -> None:
    produit = _produit(
        1,
        "fromage affine",
        "FROM",
        "FROMAGE AFFINE",
        fiable=False,
    )
    produit["produit_reconnu"] = True
    produit["quantite_principale"] = None
    produit["quantite_resolue"] = None
    commande = {
        "fichier_audio": "audio.ogg",
        "client_retenu": "CLIENT",
        "client_nom_retenu": "CLIENT TEST",
        "clients_candidats": [],
        "date_livraison": {},
        "produits": [produit],
        "lignes_commande": [],
        "statut": "PROBLEMATIQUE",
        "raisons_problematiques": [],
    }

    preview = summarize_command(commande, Path("audio.ogg"))
    assert preview["product_recognition"][0]["recognized"] is True
    assert preview["product_recognition"][0]["product_code"] == "FROM"
    assert preview["product_recognition"][0]["quantity"] is None

    extraction = tmp_path / "audio__extraction.json"
    extraction.write_text(json.dumps(commande), encoding="utf-8")
    monkeypatch.setattr(ui_data, "EXTRACTIONS_DIR", tmp_path)
    details = ui_data.problem_recognition_details("audio.ogg")
    assert details["product_recognition"][0]["recognized"] is True
    assert details["product_recognition"][0]["product_code"] == "FROM"
    assert details["product_recognition"][0]["quantity"] is None
