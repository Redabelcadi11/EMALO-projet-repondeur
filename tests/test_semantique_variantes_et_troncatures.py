from src.normalisation import normaliser_texte
from src import produits as produits_module
from src.produits import (
    _incompatibilites_semantiques,
    _preuve_positive_noyau_produit,
    _score_correspondance_produit,
    chercher_produits,
    extraire_mentions_produits,
)
from transcrire_audios import (
    extraire_pont_fenetre_asr,
    fin_liste_avec_fragment_suspect,
    fin_transcription_suspecte,
    fusionner_transcription_avec_fin,
    recuperer_suffixe_liste_fragmentaire,
    reprise_transcription_preferee,
    transcription_fenetres_preferee,
    transcription_liste_longue_a_controler,
)


def _article(code: str, libelle: str, ventes: int = 1) -> dict:
    return {
        "code_article": code,
        "libelle_article": libelle,
        "libelle_normalise": normaliser_texte(libelle),
        "unite_vente": "COL",
        "prix": 10.0,
        "ratio_net_par_unite": 0.0,
        "quantite_habituelle_commande": 1.0,
        "nb_ventes_article_total": ventes,
        "nb_ventes_article_recentes": ventes,
        "derniere_vente_article_ordinal": 739786,
        "source_article": "historique_client_pretest",
    }


def test_les_variantes_de_recherche_ne_creent_pas_de_contradiction() -> None:
    article = _article("A", "LAIT ENTIER UHT 6X1L")
    mentions = extraire_mentions_produits("un pack de lait entier")

    resultats = chercher_produits(
        mentions,
        [article],
        [article],
        {"lait": ["lait entier", "lait demi ecreme"]},
    )

    assert resultats[0]["selection"]["code_article"] == "A"
    assert resultats[0]["selection"]["semantiquement_compatible"] is True
    assert "incompatibilite=type_lait_contradictoire" not in resultats[0]["selection"]["raisons"]


def test_une_contradiction_effectivement_prononcee_reste_bloquante() -> None:
    assert _incompatibilites_semantiques(
        "lait entier", "lait demi ecreme uht 6x1l"
    ) == ["type_lait_contradictoire"]


def test_troncature_lexicale_distinctive_devient_un_candidat_fort() -> None:
    assert _score_correspondance_produit(
        "mozza", "MOZZARELLA FIORDILATTE 2.5KG", None
    ) >= 85.0


def test_racine_de_conditionnement_ne_devient_pas_un_produit() -> None:
    assert _score_correspondance_produit(
        "cart", "GOBELET CARTON 10CL X50P", None
    ) < 50.0


def test_historique_ne_depasse_pas_un_candidat_lexicalement_fort() -> None:
    produit_cible = _article("A", "MOZZARELLA FIORDILATTE 2.5KG", ventes=1)
    produit_historique_sans_rapport = _article("B", "ORIGAN PIZZA 90GR", ventes=100)

    resultats = chercher_produits(
        extraire_mentions_produits("quatre paquets de mozza"),
        [produit_cible, produit_historique_sans_rapport],
        [produit_cible, produit_historique_sans_rapport],
        {},
    )

    assert resultats[0]["selection"]["code_article"] == "A"
    mauvais = next(
        candidat
        for candidat in resultats[0]["candidats"]
        if candidat["code_article"] == "B"
    )
    assert "plausibilite_lexicale_insuffisante_pour_departage" in mauvais["raisons"]


def test_lait_qualificatif_accepte_la_famille_et_la_variante_prononcees() -> None:
    assert _incompatibilites_semantiques(
        "burrata au lait de vache",
        "burrata vache 125g x6p",
    ) == []
    assert _incompatibilites_semantiques(
        "lait de coco",
        "lait de coco 85 pourcent 1l",
    ) == []


def test_sans_sucre_exclut_le_sucre_sans_rejeter_la_puree() -> None:
    assert _incompatibilites_semantiques(
        "puree de mangue 100 pourcent sans sucre",
        "puree mangue 100 pourcent 1kg",
    ) == []
    assert "sucre_explicitement_exclu" in _incompatibilites_semantiques(
        "puree de mangue 100 pourcent sans sucre",
        "sucre semoule 1kg",
    )


def test_attribut_prononce_bloque_un_cadencier_incompatible() -> None:
    cerise_cadencier = _article(
        "CERISE", "PUREE CERISE NOIRE 100% BOIRON 1K", ventes=100
    )
    cassis_catalogue = _article(
        "CASSIS", "PUREE CASSIS 100% BOIRON 1K", ventes=1
    )

    resultat = chercher_produits(
        extraire_mentions_produits("un kilo de puree de cassis boiron"),
        [cerise_cadencier],
        [cerise_cadencier, cassis_catalogue],
        {},
    )[0]

    assert resultat["selection"]["code_article"] == "CASSIS"
    cerise = next(
        candidat
        for candidat in resultat["candidats"]
        if candidat["code_article"] == "CERISE"
    )
    assert cerise["semantiquement_compatible"] is False
    assert (
        "incompatibilite=attribut_explicite_contradictoire:fruit"
        in cerise["raisons"]
    )


def test_pistache_prononcee_ne_devient_pas_un_autre_parfum_cadencier() -> None:
    coco_cadencier = _article(
        "COCO", "PUREE COCO SUCREE BOIRON 1K", ventes=100
    )
    pistache_catalogue = _article(
        "PISTACHE", "PISTACHE HACHEE / KG", ventes=1
    )

    resultat = chercher_produits(
        extraire_mentions_produits("un kilo de pistache hachee"),
        [coco_cadencier],
        [coco_cadencier, pistache_catalogue],
        {},
    )[0]

    assert resultat["selection"]["code_article"] == "PISTACHE"
    coco = next(
        candidat
        for candidat in resultat["candidats"]
        if candidat["code_article"] == "COCO"
    )
    assert coco["semantiquement_compatible"] is False


def test_referentiel_officiel_secours_requiert_deux_ancrages_explicites(
    monkeypatch,
) -> None:
    sauce_cadencier = _article("SOJA", "SAUCE SOJA 1L", ventes=100)
    pistache_referentiel = _article("PISTACHE", "PISTACHE HACHEE / KG")
    pistache_referentiel["source_article"] = "referentiel_articles"

    monkeypatch.setattr(
        produits_module,
        "_catalogue_references_controle_produits",
        lambda: [pistache_referentiel],
    )

    resultat = chercher_produits(
        extraire_mentions_produits(
            "un kilo de p filo de pistache hachee"
        ),
        [sauce_cadencier],
        [sauce_cadencier],
        {},
    )[0]

    assert resultat["selection"]["code_article"] == "PISTACHE"
    assert resultat["selection"]["source_recherche"] == "referentiel_articles"
    assert "selection_deux_ancrages_produit_explicites" in (
        resultat["selection"]["raisons"]
    )


def test_referentiel_officiel_ne_cree_pas_un_candidat_sur_un_seul_mot(
    monkeypatch,
) -> None:
    sauce_cadencier = _article("SOJA", "SAUCE SOJA 1L", ventes=100)
    pistache_referentiel = _article("PISTACHE", "PISTACHE HACHEE / KG")
    pistache_referentiel["source_article"] = "referentiel_articles"

    monkeypatch.setattr(
        produits_module,
        "_catalogue_references_controle_produits",
        lambda: [pistache_referentiel],
    )

    resultat = chercher_produits(
        extraire_mentions_produits("un kilo de pistache"),
        [sauce_cadencier],
        [sauce_cadencier],
        {},
    )[0]

    assert all(
        candidat["source_recherche"] != "referentiel_articles"
        for candidat in resultat["candidats"]
    )


def test_un_ingredient_partage_ne_remplace_pas_le_noyau_principal() -> None:
    assert "noyau_produit_principal_contradictoire" in (
        _incompatibilites_semantiques(
            "deux litres d huile de tournesol",
            "THON EN MORCEAUX A L HUILE DE TOURNESOL 1KG",
        )
    )
    assert "noyau_produit_principal_contradictoire" in (
        _incompatibilites_semantiques(
            "deux litres de jus de boeuf",
            "FILET DE BOEUF FRAIS 3KG",
        )
    )


def test_un_produit_compose_ne_gagne_pas_sur_son_seul_parfum() -> None:
    assert "noyau_produit_compose_contradictoire" in (
        _incompatibilites_semantiques(
            "deux kilos de noix",
            "2.5L NOIX DE COCO SORBET ARTISANAL",
        )
    )
    assert not _incompatibilites_semantiques(
        "deux bacs de sorbet noix de coco",
        "2.5L NOIX DE COCO SORBET ARTISANAL",
    )


def test_le_ranking_respecte_expression_entiere_avant_historique(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        produits_module, "_catalogue_references_controle_produits", lambda: []
    )
    cas = [
        (
            "deux litres d huile de tournesol",
            _article("BON", "HUILE DE TOURNESOL 1L", ventes=1),
            _article(
                "MAUVAIS", "THON A L HUILE DE TOURNESOL 1KG", ventes=100
            ),
        ),
        (
            "deux litres de jus de boeuf",
            _article("BON", "JUS DE BOEUF 1L", ventes=1),
            _article("MAUVAIS", "FILET DE BOEUF FRAIS 3KG", ventes=100),
        ),
        (
            "deux kilos de noix",
            _article("BON", "CERNEAUX DE NOIX 1KG", ventes=1),
            _article(
                "MAUVAIS", "2.5L NOIX DE COCO SORBET ARTISANAL", ventes=100
            ),
        ),
        (
            "un carton de muffins au chocolat",
            _article("BON", "MUFFIN CHOCOLAT X24P", ventes=1),
            _article(
                "MAUVAIS", "5L CHOCOLAT CREME GLACEE ARTISANALE", ventes=100
            ),
        ),
        (
            "un sac de chocolat noir en pistoles de 5 kilos",
            _article("BON", "CHOCOLAT NOIR PISTOLES 5KG", ventes=1),
            _article(
                "MAUVAIS", "5L CHOCOLAT CREME GLACEE ARTISANALE", ventes=100
            ),
        ),
    ]

    for transcription, bon, mauvais in cas:
        resultat = chercher_produits(
            extraire_mentions_produits(transcription),
            [mauvais],
            [bon, mauvais],
            {},
        )[0]
        assert resultat["selection"]["code_article"] == "BON"
        candidat_mauvais = next(
            candidat
            for candidat in resultat["candidats"]
            if candidat["code_article"] == "MAUVAIS"
        )
        assert candidat_mauvais["semantiquement_compatible"] is False


def test_un_noyau_court_au_pluriel_reste_un_vrai_produit() -> None:
    miel = _article("MIEL", "MIEL TOUTES FLEURS 500G", ventes=1)
    sauce = _article("SAUCE", "SAUCE MIEL MOUTARDE 1L", ventes=100)
    glace = _article("GLACE", "2.5L MIEL AMANDE CREME GLACEE", ventes=100)

    resultat = chercher_produits(
        extraire_mentions_produits("deux miels"),
        [sauce, glace],
        [miel, sauce, glace],
        {},
    )[0]

    assert resultat["selection"]["code_article"] == "MIEL"
    assert resultat["produit_reconnu"] is True


def test_les_attributs_forts_prononces_sont_obligatoires_dans_le_libelle() -> None:
    cas = [
        ("parmesan en poudre", "PARMIGIANO REGGIANO 1KG"),
        ("piquillos en lanieres", "PIQUILLOS ENTIERS 3/1"),
        ("farine napolitaine", "FARINE DE BLE T55 25KG"),
        ("olives noires en rondelles", "OLIVES NOIRES DENOYAUTEES 5/1"),
    ]
    for mention, libelle in cas:
        assert any(
            raison.startswith("attribut_explicite_")
            for raison in _incompatibilites_semantiques(mention, libelle)
        )


def test_oeuf_entier_liquide_refuse_les_parties_et_la_coquille() -> None:
    assert _incompatibilites_semantiques(
        "un litre d oeuf entier liquide", "BLANC OEUF LIQUIDE 2L"
    )
    assert _incompatibilites_semantiques(
        "un litre d oeuf entier liquide", "OEUF MOYEN X90P"
    )
    assert not _incompatibilites_semantiques(
        "un litre d oeuf entier liquide", "OEUF ENTIER LIQUIDE 2L"
    )


def test_quantite_et_cadencier_ne_prouvent_pas_un_fragment_incomprehensible() -> None:
    candidat = _article("A", "TOMATE CONFITE 1KG", ventes=100)
    candidat.update({
        "dans_cadencier_client": True,
        "score_texte": 27.0,
        "semantiquement_compatible": True,
    })
    prouve, _ = _preuve_positive_noyau_produit(
        "deux microbeurres et convietes",
        candidat,
        [],
        {"quantite_principale": 2.0, "unite_principale": "PCE"},
    )
    assert prouve is False


def test_reformulation_oeuf_entier_liquide_reste_une_seule_mention() -> None:
    mentions = extraire_mentions_produits(
        "un litre d oeuf liquide, d oeuf entier, "
        "un litre d oeuf entier liquide"
    )
    oeufs = [
        mention for mention in mentions
        if "oeuf" in mention.get("produit_normalise", "")
    ]
    assert len(oeufs) == 1
    assert "entier" in oeufs[0]["produit_normalise"]
    assert "liquide" in oeufs[0]["produit_normalise"]


def test_preference_historique_avec_variante_modifie_la_ligne_precedente() -> None:
    mentions = extraire_mentions_produits(
        "un jambon iberique, celui que je prends d habitude paleta"
    )
    assert len(mentions) == 1
    assert "jambon iberique" in mentions[0]["produit_normalise"]
    assert "paleta" in mentions[0]["produit_normalise"]
    assert mentions[0]["preference_historique_compatible"] is True


def test_paleta_explicite_ecarte_un_jambon_generique() -> None:
    assert _incompatibilites_semantiques(
        "jambon iberique paleta", "JAMBON IBERICO 24 MOIS"
    )
    assert not _incompatibilites_semantiques(
        "jambon iberique paleta", "PALETA IBERICA 24 MOIS"
    )


def test_les_fins_asr_coupees_declenchent_une_reprise() -> None:
    assert fin_transcription_suspecte("un carton de fiordilatte et deux pa")
    assert fin_transcription_suspecte("un jambon iberique et 15 bur")
    assert fin_transcription_suspecte("trois cartons de gaufres s")
    assert fin_transcription_suspecte(
        "une longe de thon, deux kilos de moutarde, vingt litres de vin blanc cuisine,"
    )
    assert not fin_transcription_suspecte(
        "trois cartons de gaufres sucrees. Merci beaucoup."
    )


def test_une_reprise_ne_remplace_que_si_la_prefixe_reste_stable() -> None:
    initial = "deux cartons de burrata et deux pa"
    assert reprise_transcription_preferee(
        initial, "deux cartons de burrata et deux paquets de penne"
    )
    assert not reprise_transcription_preferee(
        initial, "bonjour ceci est une hallucination totalement differente"
    )


def test_fenetre_finale_est_fusionnee_sans_dupliquer_le_chevauchement() -> None:
    assert fusionner_transcription_avec_fin(
        "une longe de thon et vingt litres de vin blanc cuisine,",
        "vingt litres de vin blanc cuisine. Merci, bonne soiree, au revoir.",
    ) == (
        "une longe de thon et vingt litres de vin blanc cuisine, "
        "Merci, bonne soiree, au revoir."
    )
    assert fusionner_transcription_avec_fin(
        "vingt litres de vin blanc cuisine,",
        "Merci, bonne soiree, au revoir.",
    ).endswith("Merci, bonne soiree, au revoir.")


def test_fenetre_interieure_ajoute_seulement_un_pont_ancre_sur_les_deux_segments() -> None:
    pont = extraire_pont_fenetre_asr(
        "six kilos de mangue en des, six pots",
        "mangue en des, six pots de sopalin et huile d olive, 90 oeufs frais",
        "90 oeufs frais et cinq kilos de chocolat",
    )
    assert pont == "de sopalin et huile d olive,"
    assert not extraire_pont_fenetre_asr(
        "six kilos de mangue en des, six pots",
        "un produit qui ne provient pas de cette frontiere",
        "90 oeufs frais et cinq kilos de chocolat",
    )


def test_pont_audio_accepte_les_variantes_asr_ordinaires_d_un_meme_ancrage() -> None:
    assert extraire_pont_fenetre_asr(
        "six pots",
        "six pots de mamia et quatre bidons d huile, quatre vingt dix oeufs",
        "90 oeux et cinq kilos de chocolat",
    ) == "de mamia et quatre bidons d huile,"


def test_verification_interieure_reservee_aux_longues_listes() -> None:
    texte = (
        "deux cartons de pain, trois litres de creme, quatre boites de feta, "
        "cinq kilos de riz"
    )
    assert transcription_liste_longue_a_controler(
        texte, duree_audio=51.0, nb_segments=2
    )
    assert not transcription_liste_longue_a_controler(
        "un carton de pain", duree_audio=51.0, nb_segments=2
    )
    assert not transcription_liste_longue_a_controler(
        texte, duree_audio=20.0, nb_segments=2
    )


def test_mosaique_fenetres_exige_un_gain_de_couverture_du_cadencier() -> None:
    hotwords = "MANGUE CUBE, CAILLE BREBIS MAMIA, EMMENTAL RAPE, BOBINE ESSUIE MAINS"
    initial = "six kilos de mangue en des et quatre bouteilles d huile"
    enrichi = (
        "six kilos de mangue cube, une caille brebis mamia, emmental rape, "
        "une bobine essuie mains et quatre bouteilles d huile"
    )
    assert transcription_fenetres_preferee(initial, enrichi, hotwords)
    assert not transcription_fenetres_preferee(
        enrichi, initial, hotwords
    )


def test_suffixe_liste_fragmentaire_est_recupere_apres_un_ancrage_audio() -> None:
    initial = (
        "quatre litres de creme fraiche et deux kilos de glaire ap. Merci."
    )
    fenetre = "un litre de canne fraiche et deux kilos de grele rapee. Merci."
    assert fin_liste_avec_fragment_suspect(initial)
    assert recuperer_suffixe_liste_fragmentaire(initial, fenetre) == (
        "quatre litres de creme fraiche et deux kilos de grele rapee. Merci."
    )
