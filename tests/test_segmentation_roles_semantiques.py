from __future__ import annotations

from extraire_informations import detecter_type_action_commande
from src.produits import (
    analyser_role_semantique_clause,
    extraire_mentions_produits,
)


def _produits(texte: str) -> list[str]:
    return [
        mention["produit_normalise"]
        for mention in extraire_mentions_produits(texte)
    ]


def test_discours_de_commande_sans_noyau_produit_est_ignore() -> None:
    clauses_conversationnelles = (
        "je vais faire une demande",
        "on va proceder a un ajout",
        "je dois apporter une modification",
        "je voudrais faire un complement",
        "ensuite on change de sujet",
        "je vais faire un rajout",
    )

    for clause in clauses_conversationnelles:
        assert _produits(clause) == [], clause


def test_verbe_de_discours_avec_noyau_produit_reste_une_mention() -> None:
    cas = (
        ("je vais ajouter 90 oeufs", "oeuf"),
        ("je vais faire un complement, deux sacs de farine", "farine"),
        (
            "je voudrais passer une commande de deux cartons de tomates",
            "tomate",
        ),
        ("on passe a la suite, trois tartes aux pommes", "tarte"),
    )

    for transcription, noyau_attendu in cas:
        produits = _produits(transcription)
        assert any(noyau_attendu in produit for produit in produits), (
            transcription,
            produits,
        )
        assert len(produits) == 1, (transcription, produits)


def test_roles_structurels_n_eliminent_pas_les_produits_hors_bloc() -> None:
    cas = (
        "pour demain, deux sacs de farine",
        "informations de livraison au quai arriere, deux sacs de farine",
        "merci beaucoup, deux sacs de farine",
        "deux sacs de farine, client maison du port",
    )

    for transcription in cas:
        assert any("farine" in produit for produit in _produits(transcription))


def test_qualificatif_complete_toujours_le_produit_precedent() -> None:
    produits = _produits("deux bacs de glace vanille, bourbon")

    assert produits == ["glace vanille bourbon"]


def test_roles_non_produit_ne_partent_pas_au_matching() -> None:
    cas = (
        ("rebonjour", "POLITENESS"),
        ("est ce que ce serait possible d avoir", "ORDER_DISCOURSE"),
        ("je passerai vers 10h", "DELIVERY"),
        ("en complement de ma precedente commande", "ORDER_DISCOURSE"),
        ("si vous n avez plus de poires", "CONDITION"),
        ("je viens de retrouver des pommes", "INFORMATION_ONLY"),
    )

    for clause, role in cas:
        assert analyser_role_semantique_clause(clause) == role
        assert _produits(clause) == []


def test_discours_final_est_retire_sans_perdre_le_produit() -> None:
    produits = _produits(
        "un carton de legumes en lanieres surgeles et je vais continuer"
    )

    assert produits == ["legumes en lanieres surgeles"]


def test_etat_isole_complete_la_mention_precedente() -> None:
    assert _produits("fonds d artichauts, surgeles pareil") == [
        "fonds d artichauts surgeles"
    ]
    assert _produits("tomates, les confites") == ["tomates confites"]


def test_negation_et_substitution_deviennent_des_modifications_a_rappeler() -> None:
    cas = (
        "dans ma commande pas de pommes, je viens d en retrouver",
        "ne mettez pas les poires",
        "remplacez les pommes par des poires",
        "si vous n avez pas de pommes prenez des poires a la place",
    )

    for transcription in cas:
        action = detecter_type_action_commande(transcription)
        assert action["type_action"] == "modification"


def test_condition_seule_ne_cree_aucun_article() -> None:
    assert _produits("si vous n avez pas de fruits rouges") == []


def test_virgule_apres_reference_alphanumerique_separe_deux_mentions() -> None:
    produits = _produits("un sac de farine t00, trois sauces tomates")

    assert produits == ["farine t00", "sauces tomates"]


def test_introduction_avant_conditionnement_multiple_ne_mange_pas_le_produit() -> None:
    mentions = extraire_mentions_produits(
        "est ce que vous pourriez apporter demain 6x1kg de puree de fruit sans sucre"
    )

    assert len(mentions) == 1
    assert mentions[0]["quantite_principale"] == 6.0
    assert mentions[0]["conditionnement_multiple"] == 1.0
    assert mentions[0]["produit_normalise"] == "puree de fruit"


def test_discours_livraison_et_politesse_isoles_ne_creent_pas_de_segments() -> None:
    for clause in (
        "me faudrait",
        "je suis desole",
        "j ai ete coupe",
        "une livraison pour demain matin",
        "9 heures",
        "on est parti",
        "tu as toutes les references",
    ):
        assert _produits(clause) == [], clause


def test_grammaire_horaire_livraison_ne_cree_jamais_un_produit() -> None:
    expressions = (
        "9 heures du matin",
        "a partir de 9 heures du matin",
        "vers 9h30",
        "avant 10 h",
        "entre 8 heures et 10 heures",
    )

    for expression in expressions:
        assert analyser_role_semantique_clause(expression) == "DELIVERY"
        assert _produits(expression) == [], expression


def test_horaire_livraison_en_fin_de_phrase_ne_pollue_pas_le_produit() -> None:
    produits = _produits(
        "50 kilos de glacons et de les livrer a partir de 9 heures du matin"
    )

    assert produits == ["glacons"]


def test_disponibilite_positive_separe_deux_noyaux_produit() -> None:
    assert _produits(
        "un carton de panini et si vous avez de la glace cookie"
    ) == ["panini", "glace cookie"]
    assert _produits(
        "360 oeufs et si tu avais du soja sale"
    ) == ["oeufs", "soja sale"]


def test_conjonction_asr_avant_quantite_separe_deux_produits() -> None:
    assert _produits(
        "deux cartons de croquettes 1 quatre litres de creme liquide"
    ) == ["croquettes", "creme liquide"]
