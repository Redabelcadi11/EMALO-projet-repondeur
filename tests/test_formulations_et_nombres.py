from src.produits import extraire_mentions_produits, remplacer_nombres_en_chiffres


def test_nombres_francais_composes() -> None:
    cas = {
        "dix huit pieces": "18 pieces",
        "soixante dix sept pieces": "77 pieces",
        "quatre vingt dix oeufs": "90 oeufs",
        "quatre vingt dix neuf pieces": "99 pieces",
        "vingt et un sacs": "21 sacs",
    }
    for source, attendu in cas.items():
        assert remplacer_nombres_en_chiffres(source) == attendu


def test_formulations_futures_et_prise_de_commande() -> None:
    cas = {
        "il me faudra 6 litres de lait": (6.0, "lait"),
        "j ai besoin d une brique de fromage bleu": (1.0, "fromage bleu"),
        "il nous faudrait deux cartons de frites": (2.0, "frites"),
        "je prendrai trois poches de poulet": (3.0, "poulet"),
    }
    for transcription, attendu in cas.items():
        mentions = extraire_mentions_produits(transcription)
        assert len(mentions) == 1
        assert mentions[0]["quantite_principale"] == attendu[0]
        assert mentions[0]["texte_produit"] == attendu[1]


def test_on_va_vous_prendre_garde_toutes_les_lignes() -> None:
    mentions = extraire_mentions_produits(
        "Pour la pizzeria rond, on va vous prendre une tomme de brebis briques, "
        "un pot de creme fraiche et un kilo de pistache decortiquee."
    )
    assert [item["texte_produit"] for item in mentions] == [
        "tomme de brebis briques",
        "creme fraiche",
        "pistache decortiquee",
    ]
