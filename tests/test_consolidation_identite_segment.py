from __future__ import annotations

from extraire_informations import construire_lignes_commande
from src.segment_association import indexer_lignes_par_segment


def _produit(
    segment_index: int,
    produit_normalise: str,
    *,
    code: str = "CODE",
    libelle: str = "ARTICLE GENERIQUE",
    score_texte: float = 72.0,
    score_global: float = 72.0,
    quantite: float = 1.0,
) -> dict:
    return {
        "segment_id": f"segment-{segment_index}",
        "segment_index": segment_index,
        "texte_source": f"{quantite:g} {produit_normalise}",
        "produit_normalise": produit_normalise,
        "quantite_principale": quantite,
        "quantite_resolue": quantite,
        "unite_principale": "PCE",
        "unite_resolue": "PCE",
        "produit_fiable": True,
        "ambigu": False,
        "selection": {
            "code_article": code,
            "libelle_article": libelle,
            "score_texte": score_texte,
            "score_global": score_global,
            "score_selection": score_global,
            "source_recherche": "cadencier_client",
            "prix": 1.0,
        },
    }


def test_variantes_distinctes_forcees_sur_un_code_generique_restent_separees() -> None:
    lignes, _ = construire_lignes_commande([
        _produit(1, "boisson cereale avoine"),
        _produit(2, "boisson cereale amande"),
    ])

    assert [ligne["segment_id"] for ligne in lignes] == [
        "segment-1", "segment-2",
    ]
    assert [ligne["code_article"] for ligne in lignes] == ["CODE", "CODE"]


def test_designations_incompatibles_au_meme_code_ne_sont_pas_fusionnees() -> None:
    lignes, _ = construire_lignes_commande([
        _produit(1, "herbe aromatique fraiche", score_global=61.0),
        _produit(2, "legume racine frais", score_global=97.0),
    ])

    assert [ligne["segment_id"] for ligne in lignes] == [
        "segment-1", "segment-2",
    ]


def test_repetition_du_meme_article_conserve_la_lignee_des_deux_segments() -> None:
    lignes, raisons = construire_lignes_commande([
        _produit(1, "huile olive", quantite=2.0, score_global=70.0),
        _produit(2, "huile olive", quantite=3.0, score_global=90.0),
    ])

    assert len(lignes) == 1
    assert lignes[0]["segment_ids"] == ["segment-2", "segment-1"]
    assert lignes[0]["quantite"] == 3.0
    assert "article_duplique_consolide_CODE" in raisons

    par_segment, _ = indexer_lignes_par_segment(lignes)
    assert par_segment["segment-1"] is lignes[0]
    assert par_segment["segment-2"] is lignes[0]


def test_remplacement_d_un_candidat_ne_reutilise_pas_l_identite_obsolete() -> None:
    lignes, _ = construire_lignes_commande([
        _produit(1, "sauce tomate", score_texte=50.0, score_global=50.0),
        _produit(2, "sauce pesto", score_texte=80.0, score_global=80.0),
        _produit(3, "sauce tomate", score_texte=90.0, score_global=90.0),
    ])

    assert len(lignes) == 1
    assert lignes[0]["segment_id"] == "segment-3"
    assert lignes[0]["segment_ids"] == ["segment-3"]
