from __future__ import annotations

from src.normalisation import normaliser_texte
from src.clients import identifier_client
from extraire_informations import construire_lignes_commande
from src.produits import (
    _resoudre_quantite_commande_candidat,
    _score_selection_ponderee,
    chercher_produits,
    extraire_mentions_produits,
)


def _article(code: str, libelle: str, *, client: bool = False) -> dict:
    return {
        "code_article": code,
        "libelle_article": libelle,
        "libelle_normalise": normaliser_texte(libelle),
        "unite_vente": "PACK",
        "prix": 5.0,
        "ratio_net_par_unite": 6.0,
        "quantite_habituelle_commande": 2.0,
        "nb_ventes_article_total": 40 if client else 2,
        "nb_ventes_article_recentes": 20 if client else 1,
        "derniere_vente_article_ordinal": 739700,
        "source_article": "historique_client" if client else "referentiel_articles",
    }


def test_presentation_date_et_verbes_ne_deviennent_pas_articles() -> None:
    texte = (
        "Bonjour, ici Horizon Brunch a Saint Jean de Luz. "
        "J'appelle pour la commande demain matin. Il faudra deux packs "
        "de lait entier et un carton de croque monsieur. Merci."
    )

    assert [
        mention["produit_normalise"]
        for mention in extraire_mentions_produits(texte)
    ] == ["lait entier", "croque monsieur"]


def test_fragments_numeriques_de_conversation_sont_rejetes() -> None:
    texte = (
        "Pour le restaurant Alpha a Bayonne, le 12 aout. "
        "Il me faudrait un carton de ca serait demain matin, "
        "une petite, dix groupes et deux boites ici le restaurant Alpha."
    )

    assert extraire_mentions_produits(texte) == []


def test_pourcentage_complete_le_produit_precedent() -> None:
    mentions = extraire_mentions_produits(
        "deux kilos de chocolat noir, 78 pourcent"
    )

    assert len(mentions) == 1
    assert mentions[0]["produit_normalise"] == "chocolat noir 78 pour cent"


def test_historique_ne_peut_pas_inventer_une_quantite_absente() -> None:
    resultat = _resoudre_quantite_commande_candidat(
        {
            "quantite_principale": None,
            "unite_principale": None,
            "conditionnement_multiple": None,
        },
        _article("X", "PRODUIT TEST", client=True),
    )

    assert resultat["quantite_resolue"] is None
    assert resultat["raisons_resolution"] == ["quantite_absente_non_resolue"]


def test_quantite_absente_ne_rentre_pas_dans_les_lignes_commande() -> None:
    lignes, raisons = construire_lignes_commande([
        {
            "selection": {
                "code_article": "X",
                "libelle_article": "PRODUIT TEST",
                "prix": 2.0,
                "score_global": 90.0,
                "source_recherche": "cadencier_client",
            },
            "quantite_resolue": None,
            "quantite_principale": None,
            "unite_resolue": "PI",
            "produit_fiable": False,
            "ambigu": True,
        }
    ])

    assert lignes == []
    assert "quantite_absente_ligne_1" in raisons


def test_identite_nette_globale_bat_ressemblance_cadencier() -> None:
    cadencier = _article("LAIT", "LAIT DEMI ECREME UHT 6X1L", client=True)
    coco = _article("COCO", "LAIT DE COCO 6X1L")
    resultat = chercher_produits(
        extraire_mentions_produits("deux cartons de lait de coco"),
        [cadencier],
        [cadencier, coco],
        {},
    )[0]

    assert resultat["selection"]["code_article"] == "COCO"


def test_cadencier_reste_prioritaire_a_ecart_textuel_modere() -> None:
    client = {
        "score_texte": 65.0,
        "score_conditionnement": 25.0,
        "dans_cadencier_client": True,
        "nb_ventes_article_total": 8,
        "nb_ventes_article_recentes": 3,
    }
    global_net = {
        **client,
        "score_texte": 82.0,
        "dans_cadencier_client": False,
    }

    assert _score_selection_ponderee(client) > _score_selection_ponderee(global_net)


def _client(
    code: str,
    nom: str,
    ville: str,
    aliases: list[str],
    telephones: list[str] | None = None,
) -> dict:
    return {
        "code_client": code,
        "nom_client": nom,
        "ville": ville,
        "adresse_1": "",
        "adresse_2": "",
        "code_postal": "",
        "aliases": aliases,
        "telephones": telephones or [],
    }


def test_nom_et_ville_explicites_peuvent_corriger_un_telephone_obsolete() -> None:
    clients = [
        _client("ANCIEN", "ANCIEN RESTAURANT", "BIARRITZ", ["ancien"], ["0612345678"]),
        _client("NOUVEAU", "MAISON NOUVELLE", "BAYONNE", ["maison nouvelle"]),
    ]
    resultat = identifier_client(
        "Bonjour, c'est la Maison Nouvelle a Bayonne. Il me faudrait deux cartons de frites.",
        clients,
        {},
        extraire_mentions_produits("deux cartons de frites"),
        telephone_appel="06 12 34 56 78",
    )

    assert resultat["client_retenu"] == "NOUVEAU"
    assert "nom_etablissement_contredit_telephone" in resultat["raisons_decision"]


def test_telephone_reste_prioritaire_si_son_nom_correspond_aussi() -> None:
    clients = [
        _client("ACTIF", "SNACK DU FORT SOCOA", "URRUGNE", ["fortsocoa"], ["0612345678"]),
        _client("ANCIEN", "SNACK DU FORT", "SOCOA", ["snack fort"]),
    ]
    resultat = identifier_client(
        "Bonsoir, c'est le snack du fort a Socoa. Il me faudrait deux cartons de frites.",
        clients,
        {},
        extraire_mentions_produits("deux cartons de frites"),
        telephone_appel="06 12 34 56 78",
    )

    assert resultat["client_retenu"] == "ACTIF"
    assert "client_identifie_par_telephone" in resultat["raisons_decision"]


def test_nom_compose_phonetique_bat_alias_court_trouve_dans_la_ville() -> None:
    clients = [
        _client("CIBLE", "BI UR ARTE", "HENDAYE", ["bi ur arte"]),
        _client("DISTRACTEUR", "BAR JEAN", "BIARRITZ", ["jean"]),
    ]
    resultat = identifier_client(
        "Commande pour le biourarte a Hendaye, puis livraison a Saint Jean de Luz.",
        clients,
        {},
        [],
    )

    assert resultat["client_retenu"] == "CIBLE"
    assert resultat["raisons_decision"] == ["client_identifie_par_nom_distinctif"]


def test_nom_long_asr_decoupe_bat_son_prefixe_court_dans_la_meme_ville() -> None:
    clients = [
        _client("BIBAM", "SAS BIBAM", "SAINT JEAN DE LUZ", ["bibam"]),
        _client("BIBAMPIZZ", "BIBAMPIZZ", "SAINT JEAN DE LUZ", ["bibampizz"]),
    ]
    resultat = identifier_client(
        "Bonjour, c'est la Bibim Pits a Saint-Jean-de-Luz. "
        "Il me faudrait un carton d'oeufs.",
        clients,
        {},
        extraire_mentions_produits("un carton d'oeufs"),
    )

    assert resultat["client_retenu"] == "BIBAMPIZZ"
    candidat = next(
        item for item in resultat["candidats"]
        if item["code_client"] == "BIBAMPIZZ"
    )
    assert candidat["score_enseigne_contextuel"] == 96.0
    assert resultat["raisons_decision"] == [
        "client_identifie_par_enseigne_phonetique_ville"
    ]


def test_client_apres_formule_commande_reste_dans_la_zone_client() -> None:
    clients = [
        _client("ROYAL", "LE ROYALTY", "BIARRITZ", ["royalty"]),
        _client("AUTRE", "LE ROYAL", "PAU", ["royal"]),
    ]
    resultat = identifier_client(
        "Bonjour, ce serait pour une commande pour le Royalty pour demain matin. "
        "Il me faudrait deux cartons de frites.",
        clients,
        {},
        extraire_mentions_produits("deux cartons de frites"),
    )

    assert resultat["client_retenu"] == "ROYAL"
    assert "royalty" in resultat["zone_client"]
