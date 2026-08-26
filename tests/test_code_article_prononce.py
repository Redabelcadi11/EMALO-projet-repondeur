from __future__ import annotations

from src.produits import extraire_mentions_produits, chercher_produits


def _article(code: str, label: str, sales: int = 0) -> dict:
    return {
        "code_article": code,
        "libelle_article": label,
        "libelle_normalise": label.lower(),
        "prix": 10.0,
        "nb_ventes_article_total": sales,
        "nb_ventes_article_recentes": sales,
        "derniere_vente_article_ordinal": 1,
        "unite_vente": "CAR",
    }


def _selection(text: str, client: list[dict], catalog: list[dict]) -> dict:
    mentions = extraire_mentions_produits(text)
    results = chercher_produits(
        mentions=mentions,
        produits_client=client,
        catalogue_global=catalog,
        synonymes={},
        limite=5,
    )
    assert len(results) == 1
    return results[0]


def test_reference_complete_prioritaire_sur_libelle_et_historique() -> None:
    pancake = _article("00017333", "PANCAKE 30G X80P", sales=100)
    reference = _article(
        "00003002",
        "CREPE SUCREE VANILLE TAPAS 14CM 30GX80P",
    )
    result = _selection(
        "2 cartons de pancakes par 80 pieces avec la reference 00003002",
        [pancake],
        [pancake, reference],
    )

    assert result["selection"]["code_article"] == "00003002"
    assert result["selection"]["regle_selection"] == "code_article_prononce_exact"
    assert result["produit_reconnu"] is True
    assert result["quantite_resolue"] == 2.0


def test_reference_sans_zeros_initiaux_est_resolue_si_unique() -> None:
    ancien = _article("00005033", "BEIGNET CALAMAR ROMAINE 1KG", sales=100)
    reference = _article(
        "00121155",
        'BEIGNET DE CALAMAR ROMAINE "EXCELLENT" 1K',
    )
    result = _selection(
        "4 sachets de calamars a la romaine, reference 12-11-55",
        [ancien],
        [ancien, reference],
    )

    assert result["selection"]["code_article"] == "00121155"
    assert result["produit_reconnu"] is True
    assert result["quantite_resolue"] == 4.0


def test_reference_orale_whisper_est_recomposee() -> None:
    ancien = _article("00404103", "BREBIS BRIQUE LE CAUSSENARD", sales=100)
    reference = _article(
        "00404212",
        "BREBIS BRIQUE TRANCHEE ERLITA 40P 1K",
    )
    result = _selection(
        "3 pieces de brebis briques tranchees avec la reference "
        "zero zero quarante quarante-deux douze",
        [ancien],
        [ancien, reference],
    )

    assert result["selection"]["code_article"] == "00404212"
    assert result["produit_reconnu"] is True


def test_reference_isolee_modifie_le_produit_precedent_sans_nouvelle_ligne() -> None:
    mentions = extraire_mentions_produits(
        "4 sachets de calamars a la romaine, reference 12-11-55, "
        "4 cartons d anchois surgeles"
    )

    assert len(mentions) == 2
    assert mentions[0]["quantite"] == 4.0
    assert "reference 12x11x55" in mentions[0]["texte_source"]
    assert mentions[1]["produit_normalise"] == "anchois surgeles"


def test_dimension_sans_marqueur_ne_devient_pas_un_code_article() -> None:
    magret = _article("00060415", "MAGRET CANARD 350 400G")
    collision = _article("00350400", "PAPIER FORMAT SPECIAL")
    result = _selection(
        "2 pieces de magret 350-400 grammes",
        [magret],
        [magret, collision],
    )

    assert result["selection"]["code_article"] == "00060415"
    assert not result["selection"].get("code_article_prononce_exact")


def test_suffixe_ambigu_ne_force_aucune_reference() -> None:
    premier = _article("00003002", "CREPE SUCREE VANILLE")
    second = _article("000003002", "AUTRE ARTICLE")
    result = _selection(
        "2 cartons de pancakes reference 3002",
        [premier],
        [premier, second],
    )

    assert not result["selection"].get("code_article_prononce_exact")
