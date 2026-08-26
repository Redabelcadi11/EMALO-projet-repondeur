from __future__ import annotations

import pytest

from src.produits import extraire_mentions_produits


def _produits_quantites(texte: str) -> list[tuple[str, float]]:
    return [
        (
            mention["produit_normalise"],
            mention["quantite_principale"],
        )
        for mention in extraire_mentions_produits(texte)
    ]


@pytest.mark.parametrize(
    ("transcription", "attendus"),
    [
        (
            "faites moi quatre kilos de puree de peche "
            "et une poche de filet de poulet sous vide",
            [
                ("puree de peche", 4.0),
                ("filet de poulet sous vide", 1.0),
            ],
        ),
        (
            "je vais vous prendre quatre vingt dix oeufs "
            "et un bac de glace vanille",
            [("oeufs", 90.0), ("glace vanille", 1.0)],
        ),
        (
            "c est pour passer une commande pour un sachet "
            "de noix decortiquees et deux petits pains blancs",
            [
                ("noix decortiquees", 1.0),
                ("petits pains blancs", 2.0),
            ],
        ),
        (
            "un paquet de chapelure panko et avec ca "
            "je vous donnerai deux bouteilles d huile d olive",
            [
                ("chapelure panko", 1.0),
                ("huile d olive", 2.0),
            ],
        ),
        (
            "un carton de sauce anglaise ainsi qu une "
            "caisse de biscuits cuiller",
            [
                ("sauce anglaise", 1.0),
                ("biscuits cuiller", 1.0),
            ],
        ),
    ],
)
def test_formulations_reelles_du_corpus_sont_segmentees(
    transcription: str,
    attendus: list[tuple[str, float]],
) -> None:
    assert _produits_quantites(transcription) == attendus


def test_ignore_le_recapitulatif_explicitement_annonce() -> None:
    transcription = (
        "dix kilos de chapelure panko, vingt pieces de camembert "
        "et un carton de steak hache. Donc je repete la commande "
        "au cas ou : dix kilos de chapelure panko, vingt pieces "
        "de camembert et un carton de steak hache."
    )

    assert _produits_quantites(transcription) == [
        ("chapelure panko", 10.0),
        ("camembert", 20.0),
        ("steak hache", 1.0),
    ]


def test_ignore_les_explications_et_mots_de_liaison() -> None:
    transcription = (
        "deux poches de mutti aromatisata. Donc, deux poches, "
        "ca fait un carton. Ensuite dix-huit buchettes de chevre, "
        "donc trois fois six, dix-huit buchettes de chevre."
    )

    produits = [
        produit
        for produit, _ in _produits_quantites(transcription)
    ]
    assert "donc" not in produits
    assert "ensuite" not in produits
    assert "ca fait 1 carton" not in produits
    assert "fois 6" not in produits


def test_intro_composite_conserve_le_premier_article() -> None:
    transcription = (
        "ce sera pour passer une commande pour un sachet "
        "de noix decortiquees et deux petits pains blancs"
    )

    assert _produits_quantites(transcription) == [
        ("noix decortiquees", 1.0),
        ("petits pains blancs", 2.0),
    ]


def test_article_sans_quantite_est_complete_par_la_clause_suivante() -> None:
    transcription = (
        "il me faudrait des tagliatelle al nuevo. "
        "Je vais vous en prendre deux paquets."
    )

    assert _produits_quantites(transcription) == [
        ("tagliatelle al nuevo", 2.0),
    ]


def test_pourcentage_est_rattache_a_la_creme_precedente() -> None:
    mentions = extraire_mentions_produits(
        "un lot de creme a, vingt pour cent, deux litres de madere cuisine"
    )

    assert mentions[0]["produit_normalise"] == "creme a 20 pour cent"
    assert mentions[1]["produit_normalise"] == "madere cuisine"


def test_message_reel_complexe_rattache_quantites_et_ignore_metadonnees() -> None:
    transcription = (
        "Bonjour, c est Fabien de chez Matin Traiteur a Saint Jean de Luz. "
        "Il me faudrait pour demain mardi un sac de riz etuve, "
        "je crois que c est cinq kilos, du parmesan en copeaux, "
        "il m en faudrait deux, deux parmesan en copeaux, "
        "mozzarella rapee, il m en faudrait une, une poche, "
        "blanc de volaille, soixante filets, "
        "soixante filets de blanc de volaille, de la creme cheese, "
        "il m en faudrait deux, donc ca fait trois kilos, "
        "deux unites en pot, roti de porc en echine, "
        "roti de porc en echine, il m en faudrait deux, "
        "chevre buche, deux fois un kilo, cinq kilos de champignons "
        "de Paris eminces en surge, une bouteille de jus de citron, "
        "pas de pulqueau si possible. Merci, au revoir."
    )

    mentions = extraire_mentions_produits(transcription)
    assert [item["produit_normalise"] for item in mentions] == [
        "riz etuve",
        "parmesan en copeaux",
        "mozzarella rapee",
        "filets de blanc de volaille",
        "creme cheese",
        "roti de porc en echine",
        "chevre buche",
        "champignons de paris eminces en surge",
        "jus de citron",
    ]
    assert [item["quantite_principale"] for item in mentions] == [
        1.0, 2.0, 1.0, 60.0, 2.0, 2.0, 2.0, 5.0, 1.0
    ]
    assert mentions[0]["precisions_quantite"][0]["quantite"] == 5.0
    assert mentions[4]["precisions_quantite"][0]["quantite"] == 3.0
    assert mentions[-1]["exclusions_produit"] == ["pulqueau"]
