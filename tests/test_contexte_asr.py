from src.contexte_asr import (
    construire_hotwords_par_telephone,
    telephone_depuis_nom_audio,
)
from transcrire_audios import transcrire_audio


def test_telephone_depuis_nom_audio_normalise_indicatif_francais() -> None:
    assert telephone_depuis_nom_audio("2026-08-04_01-55_De-+33781619619.wav") == "0781619619"


def test_hotwords_combinent_identite_et_vocabulaire_distinctif_cadencier() -> None:
    clients = [{
        "code_client": "IBAIA",
        "nom_client": "IBAIA LA MAISON DU BONHEUR",
        "ville": "BAYONNE",
        "aliases": ["Hibaya"],
        "telephones": ["0781619619"],
    }]
    cadencier = {"IBAIA": [{
        "code_article": "RABAS",
        "libelle_article": "RABAS PANE PREMIUM 1K",
        "nb_ventes_article_recentes": 2,
        "nb_ventes_article_total": 4,
    }]}
    hotwords = construire_hotwords_par_telephone(
        clients,
        cadencier,
        synonymes_produits={"txistorra": ["shistora"]},
        limite_termes=10,
    )
    assert "IBAIA LA MAISON DU BONHEUR" in hotwords["0781619619"]
    assert "Hibaya" in hotwords["0781619619"]
    assert "RABAS" in hotwords["0781619619"]
    assert "txistorra" in hotwords["0781619619"]


def test_hotwords_utilisent_aussi_un_alias_telephone_confirme() -> None:
    clients = [{
        "code_client": "BELHABARSOCO",
        "nom_client": "BELHABAR - MAIKA SARL",
        "ville": "",
        "aliases": [],
        "telephones": [],
        "telephones_confirmes": ["0644910746"],
    }]
    cadencier = {"BELHABARSOCO": [{
        "code_article": "00010922",
        "libelle_article": "CHIPIRON FARINE PCS 2K",
    }]}

    hotwords = construire_hotwords_par_telephone(clients, cadencier)

    assert "0644910746" in hotwords
    assert "CHIPIRON" in hotwords["0644910746"]


def test_hotwords_cadencier_prioritaire_sur_synonymes_globaux() -> None:
    clients = [{
        "code_client": "BELHABARSOCO",
        "nom_client": "BELHABAR",
        "ville": "",
        "aliases": [],
        "telephones_confirmes": ["0644910746"],
    }]
    cadencier = {"BELHABARSOCO": [{
        "code_article": "00010922",
        "libelle_article": "CHIPIRON FARINE PCS 2K",
    }]}

    hotwords = construire_hotwords_par_telephone(
        clients,
        cadencier,
        synonymes_produits={
            "txistorra": ["shistora"],
            "sriracha": ["shiritaï"],
            "fregola": ["frigo la sarda"],
        },
        limite_termes=3,
    )

    termes = [term.strip() for term in hotwords["0644910746"].split(",")]
    assert "CHIPIRON" in termes
    assert "txistorra" not in termes


def test_hotwords_conservent_des_phrases_produits_du_cadencier() -> None:
    clients = [{
        "code_client": "BAHIA",
        "nom_client": "BAHIA BEACH",
        "ville": "BIDART",
        "telephones_confirmes": ["0763003079"],
    }]
    cadencier = {"BAHIA": [
        {"code_article": "M", "libelle_article": "MANGUE CUBE 10X10 1K"},
        {"code_article": "E", "libelle_article": "EMMENTAL RAPE BRIN MOYEN 1K"},
        {"code_article": "C", "libelle_article": "CAILLE DE BREBIS MAMIA ULTZAMA 140MLX6P"},
        {"code_article": "B", "libelle_article": "BOBINE ESSUIE MAINS GM X6P"},
    ]}

    hotwords = construire_hotwords_par_telephone(
        clients, cadencier, limite_termes=24
    )["0763003079"]

    assert "MANGUE CUBE" in hotwords
    assert "EMMENTAL RAPE BRIN MOYEN" in hotwords
    assert "CAILLE BREBIS MAMIA ULTZAMA" in hotwords
    assert "BOBINE ESSUIE MAINS" in hotwords


def test_transcription_transmet_les_hotwords_au_modele(tmp_path) -> None:
    class Informations:
        language = "fr"
        language_probability = 1.0

    class Modele:
        parametres = None

        def transcribe(self, _audio, **parametres):
            self.parametres = parametres
            return iter(()), Informations()

    modele = Modele()
    resultat = transcrire_audio(
        modele,
        tmp_path / "audio.wav",
        hotwords="IBAIA, txistorra, rabas",
    )
    assert modele.parametres["hotwords"] == "IBAIA, txistorra, rabas"
    assert resultat["contexte_asr_actif"] is True
    assert resultat["contexte_asr_nb_termes"] == 3

