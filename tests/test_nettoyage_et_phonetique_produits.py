from __future__ import annotations

from pathlib import Path

from src.normalisation import normaliser_texte
from src.produits import (
    _score_correspondance_produit,
    charger_synonymes_produits,
    chercher_produits,
    extraire_mentions_produits,
)


def _article(code: str, libelle: str, unite: str) -> dict:
    return {
        "code_article": code,
        "libelle_article": libelle,
        "libelle_normalise": normaliser_texte(libelle),
        "unite_vente": unite,
        "prix": 10.0,
        "ratio_net_par_unite": 0.0,
        "quantite_habituelle_commande": 1.0,
        "nb_ventes_article_total": 5,
        "nb_ventes_article_recentes": 2,
        "derniere_vente_article_ordinal": 739786,
        "source_article": "historique_client_pretest",
    }


def test_politesse_commentaire_et_exclusion_ne_polluent_pas_les_produits() -> None:
    transcription = (
        "Bonjour le restaurant Le Basta. Il me faudrait 6 litres de creme "
        "contre 5% s'il vous plait. Il me faudrait un sac d'un kilo de "
        "piment d'Espelette et pas le pauvre Saipo que vous m'avez mis ce "
        "matin parce que je ne peux rien en faire. Il me faudrait 15 "
        "burrata aussi s'il vous plait. Merci pour demain."
    )
    mentions = extraire_mentions_produits(transcription)
    assert [mention["produit_normalise"] for mention in mentions] == [
        "creme 35", "piment d espelette", "burrata",
    ]


def test_variantes_phonetiques_produit_restent_exigeantes() -> None:
    assert _score_correspondance_produit(
        "cafe mocha",
        normaliser_texte("2.5L CAFE MOKA CREME GLACEE ARTISANALE"),
        None,
    ) >= 75.0
    assert _score_correspondance_produit(
        "piment espelette",
        normaliser_texte("PIMENT ESPELETTE AOP POUDRE 1KG"),
        "KG",
    ) >= 80.0


def test_basta_resout_articles_et_conditionnements_sans_ambiguite_residuelle() -> None:
    transcription = (
        "Bonjour le restaurant Le Basta. Il me faudrait 6 litres de creme "
        "contre 5%. Il me faudrait un sac d'un kilo de piment d'Espelette "
        "et pas le pauvre Saipo que vous m'avez mis ce matin. Il me faudrait "
        "15 burrata aussi s'il vous plait. Merci."
    )
    creme = _article("00401203", "CREME UHT 35% HELIOR 6X1L", "PACK")
    piment = _article("03051467", "PIMENT ESPELETTE AOP 250G", "POC")
    burrata = _article("00444832", "BURRATA DI BUFALA GAROFALO 125G X8P", "COL")
    synonymes = charger_synonymes_produits(
        Path(__file__).resolve().parents[1] / "config" / "synonymes-produits.json"
    )
    produits = chercher_produits(
        extraire_mentions_produits(transcription), [burrata],
        [creme, piment, burrata], synonymes,
    )
    assert [p["selection"]["code_article"] for p in produits] == [
        "00401203", "03051467", "00444832",
    ]
    assert [(p["quantite_resolue"], p["unite_resolue"]) for p in produits] == [
        (1.0, "PACK"), (4.0, "POC"), (2.0, "COL"),
    ]
    assert all(p["produit_fiable"] and not p["ambigu"] for p in produits)


def test_jolies_glaces_priorise_correspondance_nette_et_variantes() -> None:
    chocolat_cadencier = _article(
        "00020240", "2.5L MENTHE CHOCOLAT CREME GLACEE ARTISANALE", "BOITE"
    )
    moka = _article("00021621", "2.5L CAFE MOKA CREME GLACEE ARTISANALE", "BOITE")
    fraise = _article("00020152", "5L FRAISE ESSENTIELLE CREME GLACEE ARTISANALE", "BOITE")
    chocolat_lait = _article("00020233", "2.5L CHOCOLAT LAIT CREME GLACEE ARTISANALE", "BOITE")
    cadencier = [chocolat_cadencier, moka, fraise]
    synonymes = charger_synonymes_produits(
        Path(__file__).resolve().parents[1] / "config" / "synonymes-produits.json"
    )
    transcription = (
        "Les Jolies Glaces. Je voudrais un chocolat au lait, un cafe mocha "
        "et deux fraises d'excellence. Merci."
    )
    produits = chercher_produits(
        extraire_mentions_produits(transcription), cadencier,
        [*cadencier, chocolat_lait], synonymes,
    )
    assert [p["selection"]["code_article"] for p in produits] == [
        "00020233", "00021621", "00020152",
    ]
    assert all(p["produit_fiable"] and not p["ambigu"] for p in produits)


def test_fruit_surgele_ne_devient_ni_sorbet_ni_autre_famille() -> None:
    framboise = _article(
        "00016307", "FRAMBOISE WILLAMETTE ENTIERE 2.5KG", "POC"
    )
    sorbet = _article(
        "00020264", "2.5L FRAMBOISE SORBET ARTISANAL", "BOITE"
    )
    champignon = _article(
        "P0000256", "CHAMPIGNONS COUPES SURGELES 2.5KG", "POC"
    )
    mentions = extraire_mentions_produits(
        "Il me faudrait dix kilos de framboises surgelees."
    )
    produits = chercher_produits(
        mentions, [], [sorbet, champignon, framboise], {}
    )
    assert produits[0]["selection"]["code_article"] == "00016307"
    assert produits[0]["produit_fiable"] is True


def test_variante_cadencier_incompatible_ne_bloque_pas_catalogue_global() -> None:
    aiguillette = _article(
        "000S0801", "AIGUILLETTE POULET PANEE CORN FLAKES 35/55G X5K", "COL"
    )
    nuggets = _article(
        "00010824", "NUGGETS DE FILET DE POULET CUIT 22G 2.5K", "BOITE"
    )
    nuggets_concurrent = _article(
        "00010864", "NUGGETS 100% FILET POULET 1.25K", "COL"
    )
    synonymes = charger_synonymes_produits(
        Path(__file__).resolve().parents[1] / "config" / "synonymes-produits.json"
    )
    produits = chercher_produits(
        extraire_mentions_produits("Un carton de nuggets de poulet."),
        [aiguillette],
        [aiguillette, nuggets, nuggets_concurrent],
        synonymes,
    )
    assert produits[0]["selection"]["code_article"] == "00010824"
    assert produits[0]["produit_fiable"] is True
