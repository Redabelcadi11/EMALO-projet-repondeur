from __future__ import annotations

from pathlib import Path

from src.produits import chercher_produits, charger_synonymes_produits


def _mention(text: str) -> dict[str, object]:
    return {
        "texte_source": text,
        "texte_normalise": text,
        "produit_normalise": text,
        "texte_produit": text,
        "quantite_principale": 2.0,
        "quantite": 2.0,
        "unite_principale": "CAR",
        "unite_detectee": "CAR",
        "precisions_quantite": [],
        "ambigu": False,
        "raisons_ambiguite": [],
    }


def _article(code: str, label: str) -> dict[str, object]:
    return {
        "code_article": code,
        "libelle_article": label,
        "libelle_normalise": label.casefold(),
        "prix": 10.0,
        "nb_ventes_article_total": 2,
        "nb_ventes_article_recentes": 1,
    }


def _synonymes() -> dict[str, list[str]]:
    return charger_synonymes_produits(
        Path("config/synonymes-produits.json")
    )


def test_alias_asr_gidolive_reste_dans_le_cadencier_client() -> None:
    gidolive = _article("GIDOLIVE_1L", "HUILE GIDOLIVE SPECIAL PLANCHA 1L")
    autre_huile = _article("ARBEQUINA", "HUILE OLIVE EXTRA VIERGE 1L")

    resultat = chercher_produits(
        [_mention("jus d olive")], [gidolive], [autre_huile], _synonymes(), limite=5
    )[0]

    assert resultat["selection"]["code_article"] == "GIDOLIVE_1L"
    assert resultat["selection"]["dans_cadencier_client"] is True


def test_alias_asr_chili_thai_ne_derive_pas_vers_teriyaki() -> None:
    chili = _article("CHILI", "SAUCE SWEET CHILI THAI ROUGE 725ML")
    teriyaki = _article("TERIYAKI", "SAUCE TERIYAKI 250ML")

    resultat = chercher_produits(
        [_mention("sauces shiritai")], [chili, teriyaki], [chili, teriyaki], _synonymes(), limite=5
    )[0]

    assert resultat["selection"]["code_article"] == "CHILI"


def test_mignonnette_resout_vers_poivre_concasse_et_pas_moulu() -> None:
    concasse = _article("00051428", "POIVRE NOIR CONCASSE 1K")
    moulu = _article("00051427", "POIVRE GRIS MOULU 470G")

    resultat = chercher_produits(
        [_mention("1 sachet de poivre mignonnette")],
        [concasse, moulu],
        [concasse, moulu],
        _synonymes(),
        limite=5,
    )[0]

    assert resultat["selection"]["code_article"] == "00051428"
    assert resultat["produit_fiable"] is True


def test_pipette_de_miel_resout_vers_format_squeez() -> None:
    miel_squeez = _article("00050461", "MIEL SQUEEZ FLEURS LIQUIDE 500G")
    autre_produit = _article("GAZ", "CARTOUCHE GAZ POUR CHALUMEAU")

    resultat = chercher_produits(
        [_mention("3 pipettes de miel pour la belloteka")],
        [miel_squeez, autre_produit],
        [miel_squeez, autre_produit],
        _synonymes(),
        limite=5,
    )[0]

    assert resultat["selection"]["code_article"] == "00050461"
    assert resultat["produit_fiable"] is True


def test_pain_burger_reste_sur_le_pain_buns_du_cadencier() -> None:
    pain_client = _article(
        "00017370",
        "PAIN BUNS BRIOCHE NATURE AMBIANT 77G 11CM X36P",
    )
    pain_secours = _article(
        "00011219",
        "PAIN BUNS GEANT 12CM X30P",
    )

    resultat = chercher_produits(
        [_mention("2 pains burgers")],
        [pain_client],
        [pain_secours],
        _synonymes(),
        catalogue_reappro=[pain_secours],
        limite=5,
    )[0]

    assert resultat["selection"]["code_article"] == "00017370"
    assert resultat["selection"]["dans_cadencier_client"] is True
