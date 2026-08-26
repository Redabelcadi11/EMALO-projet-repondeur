from __future__ import annotations

import json
from pathlib import Path

import src.clients as clients_module
from src.clients import (
    charger_aliases_telephoniques_confirmes,
    enrichir_clients_avec_aliases_telephoniques_confirmes,
    identifier_client,
)
from src.product_hierarchy import (
    eligible_secondary_codes,
    explicit_attribute_conflicts,
    reappro_fallback_bonuses,
    extract_label_measures,
    extract_spoken_physical_constraint,
    safe_physical_score,
    semantic_variant_score,
)
from src.produits import (
    _score_token_produit,
    _tokens_produit,
    normaliser_transcription_produits,
)
from src.produits import extraire_mentions_produits
from src.produits import chercher_produits


def _candidate(code: str, label: str, score: float) -> dict:
    return {
        "code_article": code,
        "libelle_article": label,
        "libelle_normalise": label.casefold(),
        "score_texte": score,
        "prix": 10.0,
        "source_article": "referentiel_articles",
        "unite_vente": "PI",
        "nb_ventes_article_total": 0,
        "nb_ventes_article_recentes": 0,
        "derniere_vente_article_ordinal": -1,
        "quantite_habituelle_commande": 0.0,
        "volume_historique_total": 0.0,
        "ratio_net_par_unite": 0.0,
    }


def _eligible(mention: str, candidates: list[dict]) -> set[str]:
    return eligible_secondary_codes(
        candidates,
        _tokens_produit(mention),
        _tokens_produit,
        _score_token_produit,
    )


def test_conditionnement_ne_rend_jamais_une_autre_famille_eligible() -> None:
    cases = (
        (
            "4 kg huile pour friteuse",
            _candidate("H", "HUILE FRITURE 10L", 70),
            _candidate("V", "BAVETTE ENTIERE 4K", 65),
        ),
        (
            "24 pieces camembert",
            _candidate("C", "CAMEMBERT 150G", 70),
            _candidate("P", "PAPIER HYGIENIQUE X24P", 65),
        ),
        (
            "3 kg beurre",
            _candidate("B", "BEURRE DOUX 1KG", 70),
            _candidate("V", "VIANDE BRAISEE 3K", 65),
        ),
    )
    for mention, wanted, unrelated in cases:
        eligible = _eligible(mention, [wanted, unrelated])
        assert wanted["code_article"] in eligible
        assert unrelated["code_article"] not in eligible
        score, _ = safe_physical_score(
            mention,
            unrelated["libelle_article"],
            eligible=unrelated["code_article"] in eligible,
        )
        assert score == 0.0


def test_quantite_totale_ne_devient_pas_taille_unitaire() -> None:
    constraint = extract_spoken_physical_constraint("3 kg de beurre")
    assert constraint is not None
    assert constraint.dimension == "mass"
    assert constraint.unit_size is None
    score, _ = safe_physical_score(
        "3 kg de beurre", "BEURRE DOUX 1KG", eligible=True
    )
    assert score == 0.0


def test_pack_piece_est_parse_sans_confondre_quantite_totale() -> None:
    labels = extract_label_measures("CAMEMBERT 150G X24P")
    assert any(
        item.dimension == "count" and item.unit_value == 24.0
        for item in labels
    )
    total = extract_spoken_physical_constraint("24 pieces de camembert")
    assert total is not None
    assert total.dimension == "count"
    assert total.unit_size is None
    pack = extract_spoken_physical_constraint(
        "un carton de 24 pieces de camembert"
    )
    assert pack is not None
    assert pack.dimension == "count"
    assert pack.unit_size == 24.0


def test_taille_unitaire_explicitement_decrite_est_utilisee() -> None:
    constraint = extract_spoken_physical_constraint(
        "3 pots de beurre de 1 kg"
    )
    assert constraint is not None
    assert constraint.unit_size == 1.0
    compatible, _ = safe_physical_score(
        "3 pots de beurre de 1 kg", "BEURRE POT 1K", eligible=True
    )
    different, _ = safe_physical_score(
        "3 pots de beurre de 1 kg", "BEURRE POT 500G", eligible=True
    )
    assert compatible > different


def test_chocolat_reste_dans_son_noyau_avant_conditionnement() -> None:
    chocolate = _candidate("C", "CHOCOLAT NOIR PISTOLES 5K", 62)
    ice = _candidate("G", "5L CHOCOLAT CREME GLACEE", 48)
    meat = _candidate("V", "VIANDE 5K", 90)
    eligible = _eligible("5 kg chocolat noir", [chocolate, ice, meat])
    assert chocolate["code_article"] in eligible
    assert ice["code_article"] in eligible
    assert meat["code_article"] not in eligible
    assert safe_physical_score(
        "5 kg chocolat noir", ice["libelle_article"], eligible=True
    )[0] < 0


def test_formats_de_libelles_sont_parses_generiquement() -> None:
    measures = extract_label_measures("SAC 500G PACK 6X1L POCHE 2.5K X5P")
    assert any(item.dimension == "mass" and item.unit_value == 0.5 for item in measures)
    assert any(
        item.dimension == "volume" and item.unit_value == 1 and item.multiplier == 6
        for item in measures
    )
    assert any(
        item.dimension == "mass" and item.unit_value == 2.5 and item.multiplier == 5
        for item in measures
    )


def test_relation_semantique_reste_bornee_au_noyau_coulis() -> None:
    mention = "coulis de fruits exotiques"
    mango = _candidate("M", "COULIS MANGUE PASSION 500G", 40)
    red = _candidate("R", "COULIS FRUITS ROUGES 500G", 64)
    unrelated = _candidate("A", "ANANAS EN TRANCHES 500G", 90)
    eligible = _eligible(mention, [mango, red, unrelated])
    assert {"M", "R"}.issubset(eligible)
    assert "A" not in eligible
    assert semantic_variant_score(mention, mango["libelle_article"], eligible=True)[0] > 0
    assert semantic_variant_score(mention, red["libelle_article"], eligible=True)[0] < 0
    assert semantic_variant_score(mention, unrelated["libelle_article"], eligible=False)[0] == 0


def test_attribut_fruit_explicite_contredit_un_autre_fruit() -> None:
    assert explicit_attribute_conflicts(
        "puree de cassis boiron", "PUREE CERISE NOIRE BOIRON"
    ) == ["attribut_explicite_contradictoire:fruit"]
    assert not explicit_attribute_conflicts(
        "puree de cassis boiron", "PUREE CASSIS BOIRON"
    )


def test_forme_en_des_est_normalisee_en_cube_sans_modifier_l_article_des() -> None:
    assert normaliser_transcription_produits("mangue en des") == "mangue en cube"
    assert normaliser_transcription_produits("des mangues surgelees") == (
        "des mangues surgelees"
    )


def test_decoupes_cube_et_rape_explicites_bloquent_les_candidats_sans_cette_forme() -> None:
    assert "attribut_explicite_absent:forme_decoupe" in explicit_attribute_conflicts(
        "mangue en cube", "COULIS MANGUE PASSION 500G"
    )
    assert "attribut_explicite_absent:forme_decoupe" in explicit_attribute_conflicts(
        "emmental rape", "GRAINE SESAME NOIR 1K"
    )


def test_un_mot_de_forme_grain_ne_force_pas_un_article_non_prouve() -> None:
    sesame = _candidate("S", "GRAINE SESAME NOIR 1K", 100)
    resultat = chercher_produits(
        extraire_mentions_produits("deux kilos de grain rape"),
        [sesame],
        [sesame],
        {},
    )[0]
    assert resultat["produit_reconnu"] is False


def test_parfum_glace_ne_supprime_aucun_candidat() -> None:
    assert not explicit_attribute_conflicts(
        "glace vanille", "CREME GLACEE MENTHE CHOCOLAT"
    )
    assert not explicit_attribute_conflicts(
        "glace vanille", "CREME GLACEE RHUM RAISINS"
    )


def test_parfum_glace_ne_filtre_aucune_autre_famille() -> None:
    assert not explicit_attribute_conflicts(
        "deux sauces chocolat", "SAUCE MENTHE 1L"
    )
    assert not explicit_attribute_conflicts(
        "deux litres de vin et du chocolat", "VIN ROUGE 10L"
    )


def test_saveur_explicite_bat_historique_cadencier_incompatible() -> None:
    menthe = _candidate(
        "MENTHE", "2.5L MENTHE CHOCOLAT CREME GLACEE ARTISANALE", 100
    )
    menthe["nb_ventes_article_total"] = 500
    menthe["nb_ventes_article_recentes"] = 500
    vanille = _candidate(
        "VANILLE", "2.5L VANILLE DELICE CREME GLACEE ARTISANALE", 100
    )

    resultat = chercher_produits(
        extraire_mentions_produits("deux boites de glace vanille"),
        [menthe],
        [menthe, vanille],
        {},
    )[0]

    assert resultat["selection"]["code_article"] == "VANILLE"
    assert resultat["selection"]["dans_cadencier_client"] is False


def test_historique_reste_prioritaire_si_aucune_saveur_n_est_prononcee() -> None:
    menthe = _candidate(
        "MENTHE", "2.5L MENTHE CHOCOLAT CREME GLACEE ARTISANALE", 100
    )
    menthe["nb_ventes_article_total"] = 10
    menthe["nb_ventes_article_recentes"] = 10
    vanille = _candidate(
        "VANILLE", "2.5L VANILLE DELICE CREME GLACEE ARTISANALE", 100
    )

    resultat = chercher_produits(
        extraire_mentions_produits("deux boites de glace"),
        [menthe],
        [menthe, vanille],
        {},
    )[0]

    assert resultat["selection"]["code_article"] == "MENTHE"
    assert resultat["selection"]["dans_cadencier_client"] is True


def test_priorite_parfum_ne_deconsolide_pas_une_enumeration_ambigue() -> None:
    menthe = _candidate(
        "MENTHE", "2.5L MENTHE CHOCOLAT CREME GLACEE ARTISANALE", 100
    )
    menthe["nb_ventes_article_total"] = 500
    menthe["nb_ventes_article_recentes"] = 500
    vanille = _candidate(
        "VANILLE", "2.5L VANILLE DELICE CREME GLACEE ARTISANALE", 100
    )
    caramel = _candidate(
        "CARAMEL", "2.5L CARAMEL BEURRE SALE CREME GLACEE ARTISANALE", 100
    )

    resultats = chercher_produits(
        extraire_mentions_produits(
            "une boite de glace vanille et une boite de glace caramel"
        ),
        [menthe],
        [menthe, vanille, caramel],
        {},
    )

    assert len(resultats) == 2
    assert [
        resultat["selection"]["code_article"] for resultat in resultats
    ] == ["MENTHE", "MENTHE"]
    assert all(
        "priorite_parfum_non_appliquee_sur_enumeration_fusionnee"
        in resultat["selection"]["raisons"]
        for resultat in resultats
    )


def test_fallback_phonetique_reste_dans_la_famille() -> None:
    candidates = [
        {
            "code_article": "CAD",
            "libelle_normalise": "vinaigre de cidre 1l",
            "dans_cadencier_client": True,
            "source_recherche": "cadencier_client",
        },
        {
            "code_article": "XERES",
            "libelle_normalise": "vinaigre de xeres 1l",
            "dans_cadencier_client": False,
            "source_recherche": "catalogue_global",
        },
        {
            "code_article": "AUTRE",
            "libelle_normalise": "viande xrf 1kg",
            "dans_cadencier_client": False,
            "source_recherche": "catalogue_reappro",
        },
    ]
    bonuses = reappro_fallback_bonuses(
        candidates,
        _tokens_produit("vinaigre de xrf"),
        _tokens_produit,
        _score_token_produit,
        allow_asr_variant=True,
        allow_explicit_attribute=False,
    )
    assert "XERES" in bonuses
    assert "AUTRE" not in bonuses


def test_phonetique_catalogue_intra_famille_peut_departager_xrf() -> None:
    cadencier = [_candidate("CIDRE", "VINAIGRE DE CIDRE 1L", 100)]
    catalogue = [
        _candidate("CIDRE", "VINAIGRE DE CIDRE 1L", 100),
        _candidate("XERES", "VINAIGRE DE XERES 1L", 1),
        _candidate("HORS_FAMILLE", "VIANDE XRF 1KG", 100),
    ]

    resultat = chercher_produits(
        extraire_mentions_produits("une bouteille de vinaigre de xrf"),
        cadencier,
        catalogue,
        {},
    )[0]

    assert resultat["selection"]["code_article"] == "XERES"
    assert (
        "fallback_catalogue_variante_phonetique_intra_famille"
        in resultat["selection"]["raisons"]
    )


def test_phonetique_n_interprete_pas_une_variante_deja_lisible() -> None:
    candidates = [
        {
            "code_article": "CAD",
            "libelle_normalise": "creme liquide 35 pourcent 1l",
            "dans_cadencier_client": True,
            "source_recherche": "cadencier_client",
        },
        {
            "code_article": "BALSAMIQUE",
            "libelle_normalise": "creme balsamique 50cl",
            "dans_cadencier_client": False,
            "source_recherche": "catalogue_global",
        },
    ]
    bonuses = reappro_fallback_bonuses(
        candidates,
        _tokens_produit("creme liquide 35 pourcent"),
        _tokens_produit,
        _score_token_produit,
        allow_asr_variant=True,
        allow_explicit_attribute=False,
    )

    assert "BALSAMIQUE" not in bonuses


def test_fallback_reappro_attribut_explicite_ecarte_cadencier_contradictoire() -> None:
    candidates = [
        {
            "code_article": "CERISE",
            "libelle_normalise": "puree cerise noire boiron",
            "dans_cadencier_client": True,
            "source_recherche": "cadencier_client",
        },
        {
            "code_article": "CASSIS",
            "libelle_normalise": "puree cassis boiron",
            "dans_cadencier_client": False,
            "source_recherche": "catalogue_reappro",
        },
    ]
    bonuses = reappro_fallback_bonuses(
        candidates,
        _tokens_produit("puree de cassis boiron"),
        _tokens_produit,
        _score_token_produit,
        allow_asr_variant=False,
        allow_explicit_attribute=True,
    )
    assert bonuses["CASSIS"][0] > 0
    assert "CERISE" not in bonuses


def _client(
    code: str,
    name: str,
    city: str,
    *,
    phones: list[str] | None = None,
    info_phones: list[str] | None = None,
) -> dict:
    return {
        "code_client": code,
        "nom_client": name,
        "ville": city,
        "adresse_1": "",
        "adresse_2": "",
        "code_postal": "",
        "aliases": [name.casefold()],
        "telephones": phones or [],
        "telephones_info": info_phones or [],
        "telephones_confirmes": [],
    }


def test_alias_telephone_confirme_est_persistant_et_verrouille_client(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "aliases.json"
    path.write_text(json.dumps({
        "0609549702": {
            "code_client": "PLANBID",
            "nom_client": "LA PLANCHA D'ILBARRITZ",
            "confirme": True,
        }
    }), encoding="utf-8")
    clients = [
        _client("PLANBID", "LA PLANCHA D ILBARRITZ", "BIDART"),
        _client("AUTRE", "MAISON AUTRE", "BAYONNE"),
    ]
    aliases = charger_aliases_telephoniques_confirmes(path)
    enrichir_clients_avec_aliases_telephoniques_confirmes(clients, aliases)
    monkeypatch.setattr(
        clients_module,
        "business_rule_enabled",
        lambda name: name == "telephone_exact_verrouille",
    )
    result = identifier_client(
        "Bonjour, c'est la maison autre a Bayonne.",
        clients,
        {},
        [],
        telephone_appel="06 09 54 97 02",
    )
    assert result["client_retenu"] == "PLANBID"
    assert result["raisons_decision"] == [
        "client_verrouille_par_alias_telephone_confirme"
    ]


def test_alias_confirme_ruisseau_est_persistant() -> None:
    chemin = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "aliases-telephoniques-confirmes.json"
    )
    aliases = charger_aliases_telephoniques_confirmes(chemin)
    assert aliases["0678649622"] == {
        "code_client": "RUISSBIDART",
        "nom_client": "LE RUISSEAU MS EXPLOITATION",
    }


def test_alias_confirme_xistera_est_persistant() -> None:
    chemin = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "aliases-telephoniques-confirmes.json"
    )
    aliases = charger_aliases_telephoniques_confirmes(chemin)
    assert aliases["0786564042"] == {
        "code_client": "XISTERA",
        "nom_client": "CHISTERA ET COQUILLAGES",
    }


def test_alias_confirme_bibampizz_est_persistant() -> None:
    chemin = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "aliases-telephoniques-confirmes.json"
    )
    aliases = charger_aliases_telephoniques_confirmes(chemin)
    assert aliases["0686843096"] == {
        "code_client": "BIBAMPIZZ",
        "nom_client": "BIBAMPIZZ",
    }


def test_telephone_info_exact_unique_ne_peut_pas_etre_renverse(
    monkeypatch,
) -> None:
    clients = [
        _client(
            "ACTIF", "CLIENT ACTIF", "BIARRITZ",
            phones=["0612345678"], info_phones=["0612345678"],
        ),
        _client("NOMME", "MAISON NOMMEE", "BAYONNE"),
    ]
    monkeypatch.setattr(
        clients_module,
        "business_rule_enabled",
        lambda name: name == "telephone_exact_verrouille",
    )
    result = identifier_client(
        "Bonjour, c'est la meson nolee.",
        clients,
        {},
        [],
        telephone_appel="0612345678",
    )
    assert result["client_retenu"] == "ACTIF"
    assert result["raisons_decision"] == [
        "client_verrouille_par_telephone_info_clients"
    ]


def test_telephone_info_exact_unique_est_prioritaire_sur_nom_et_ville(
    monkeypatch,
) -> None:
    clients = [
        _client(
            "ANCIEN", "CLIENT ANCIEN", "BIARRITZ",
            phones=["0612345678"], info_phones=["0612345678"],
        ),
        _client("ACTUEL", "BAHIA BEACH", "BIDART"),
    ]
    monkeypatch.setattr(
        clients_module,
        "business_rule_enabled",
        lambda name: name == "telephone_exact_verrouille",
    )
    result = identifier_client(
        "Bonjour, c'est Bahia Beach a Bidart.",
        clients,
        {},
        [],
        telephone_appel="0612345678",
    )
    assert result["client_retenu"] == "ANCIEN"
    assert result["raisons_decision"] == [
        "client_verrouille_par_telephone_info_clients"
    ]


def test_telephone_exact_configure_unique_est_prioritaire(
    monkeypatch,
) -> None:
    clients = [
        _client(
            "CONFIG", "CLIENT CONFIGURE", "BIARRITZ",
            phones=["0612345678"],
        ),
        _client("NOMME", "MAISON NOMMEE", "BAYONNE"),
    ]
    monkeypatch.setattr(
        clients_module,
        "business_rule_enabled",
        lambda name: name == "telephone_exact_verrouille",
    )
    result = identifier_client(
        "Bonjour, c'est la maison nommee a Bayonne.",
        clients,
        {},
        [],
        telephone_appel="0612345678",
    )
    assert result["client_retenu"] == "CONFIG"
    assert result["raisons_decision"] == [
        "client_verrouille_par_telephone_exact"
    ]


def test_telephone_info_partage_n_est_pas_verrouille(monkeypatch) -> None:
    clients = [
        _client(
            "A", "CLIENT ALPHA", "BIARRITZ",
            phones=["0612345678"], info_phones=["0612345678"],
        ),
        _client(
            "B", "CLIENT BETA", "BAYONNE",
            phones=["0612345678"], info_phones=["0612345678"],
        ),
    ]
    monkeypatch.setattr(
        clients_module,
        "business_rule_enabled",
        lambda name: name == "telephone_exact_verrouille",
    )
    result = identifier_client(
        "Bonjour, c'est Client Beta a Bayonne.",
        clients,
        {},
        [],
        telephone_appel="0612345678",
    )
    assert "client_verrouille_par_telephone_info_clients" not in result[
        "raisons_decision"
    ]


def test_contexte_glace_necrase_pas_un_noyau_explicite(monkeypatch) -> None:
    import src.produits as products_module

    monkeypatch.setattr(
        products_module,
        "business_rule_enabled",
        lambda name: name == "contexte_enumeration_ambigu",
    )
    mentions = extraire_mentions_produits(
        "Pour les glaces: framboise, pistache, caramel, "
        "puis une sauce caramel et des poivrons caramelises."
    )
    products = [item["produit_normalise"] for item in mentions]
    assert any(item == "glace caramel" for item in products)
    assert any("sauce caramel" in item and "glace" not in item for item in products)
    assert any("poivrons caramelises" in item and "glace" not in item for item in products)


def test_reference_historique_reste_un_modificateur(monkeypatch) -> None:
    import src.produits as products_module

    monkeypatch.setattr(
        products_module,
        "business_rule_enabled",
        lambda name: name == "historique_modificateur",
    )
    mentions = extraire_mentions_produits(
        "12 litres de creme liquide 35%, la derniere marque que j ai achetee."
    )
    assert len(mentions) == 1
    assert mentions[0]["preference_historique_compatible"] is True
    assert "creme liquide" in mentions[0]["produit_normalise"]


def test_reference_historique_ne_departage_que_des_produits_compatibles(
    monkeypatch,
) -> None:
    import src.produits as products_module

    monkeypatch.setattr(
        products_module,
        "business_rule_enabled",
        lambda name: name == "historique_modificateur",
    )
    mentions = extraire_mentions_produits(
        "12 litres de creme liquide 35%, la derniere marque que j ai achetee."
    )
    catalogue = [
        {
            "code_article": "ANCIENNE",
            "libelle_article": "CREME LIQUIDE UHT 35% MARQUE A 1L",
            "libelle_normalise": "creme liquide uht 35 marque a 1l",
            "prix": 10.0,
            "derniere_vente_article_ordinal": 100,
        },
        {
            "code_article": "DERNIERE",
            "libelle_article": "CREME LIQUIDE UHT 35% MARQUE B 1L",
            "libelle_normalise": "creme liquide uht 35 marque b 1l",
            "prix": 10.0,
            "derniere_vente_article_ordinal": 200,
        },
        {
            "code_article": "RECENTE_HORS_FAMILLE",
            "libelle_article": "HUILE OLIVE 1L",
            "libelle_normalise": "huile olive 1l",
            "prix": 10.0,
            "derniere_vente_article_ordinal": 300,
        },
    ]
    resultat = chercher_produits(
        mentions, catalogue, catalogue, {}, limite=5
    )[0]
    assert resultat["selection"]["code_article"] == "DERNIERE"
    assert "derniere_reference_compatible_achetee" in resultat[
        "selection"
    ]["raisons"]


def test_product_gate_refuse_une_clause_sans_noyau_catalogue(monkeypatch) -> None:
    import src.produits as products_module

    monkeypatch.setattr(
        products_module,
        "business_rule_enabled",
        lambda name: name == "product_gate_noyau",
    )
    mention = {
        "texte_source": "avec",
        "texte_normalise": "avec",
        "produit_normalise": "avec",
        "texte_produit": "avec",
        "quantite_principale": 1.0,
        "quantite": 1.0,
        "unite_principale": "PCE",
        "unite_detectee": "PCE",
        "precisions_quantite": [],
        "ambigu": False,
        "raisons_ambiguite": [],
    }
    catalogue = [{
        "code_article": "H1",
        "libelle_article": "HUILE OLIVE 1L",
        "libelle_normalise": "huile olive 1l",
        "prix": 10.0,
    }]
    resultat = chercher_produits(
        [mention], catalogue, catalogue, {}, limite=3
    )[0]
    assert resultat["selection"] is None
    assert resultat["produit_fiable"] is False


def test_product_gate_accepte_un_noyau_autonome(monkeypatch) -> None:
    import src.produits as products_module

    monkeypatch.setattr(
        products_module,
        "business_rule_enabled",
        lambda name: name == "product_gate_noyau",
    )
    mention = {
        "texte_source": "une feta",
        "texte_normalise": "une feta",
        "produit_normalise": "feta",
        "texte_produit": "feta",
        "quantite_principale": 1.0,
        "quantite": 1.0,
        "unite_principale": "PCE",
        "unite_detectee": "PCE",
        "precisions_quantite": [],
        "ambigu": False,
        "raisons_ambiguite": [],
    }
    catalogue = [{
        "code_article": "F1",
        "libelle_article": "FETA AOP 1KG",
        "libelle_normalise": "feta aop 1kg",
        "prix": 10.0,
    }]
    resultat = chercher_produits(
        [mention], catalogue, catalogue, {}, limite=3
    )[0]
    assert resultat["selection"]["code_article"] == "F1"


def test_product_gate_ne_rejette_pas_une_forme_asr_substantielle(monkeypatch) -> None:
    import src.produits as products_module

    monkeypatch.setattr(
        products_module,
        "business_rule_enabled",
        lambda name: name == "product_gate_noyau",
    )
    mention = {
        "texte_source": "un carton de pinza",
        "texte_normalise": "un carton de pinza",
        "produit_normalise": "pinza",
        "texte_produit": "pinza",
        "quantite_principale": 1.0,
        "quantite": 1.0,
        "unite_principale": "CAR",
        "unite_detectee": "CAR",
        "precisions_quantite": [],
        "ambigu": False,
        "raisons_ambiguite": [],
    }
    catalogue = [{
        "code_article": "P1",
        "libelle_article": "PINSA DI MARCO 230G X16P",
        "libelle_normalise": "pinsa di marco 230g x16p",
        "prix": 10.0,
    }]
    resultat = chercher_produits(
        [mention], catalogue, catalogue, {}, limite=3
    )[0]
    assert resultat["selection"]["code_article"] == "P1"
