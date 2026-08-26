from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

import extraire_informations as extraction


def _ecrire_xlsx(chemin: Path, en_tetes: list[str], lignes: list[list[object]]) -> None:
    classeur = Workbook()
    feuille = classeur.active
    feuille.append(en_tetes)
    for ligne in lignes:
        feuille.append(ligne)
    classeur.save(chemin)
    classeur.close()


@pytest.mark.parametrize(
    ("en_tete", "aliases", "attendu"),
    [
        ("Clients_Code", extraction.ALIASES_COLONNES_CLIENTS["code_client"], "Clients_Code"),
        ("CLIENTS-LIVRES-CODE", extraction.ALIASES_COLONNES_CLIENTS["code_client"], "CLIENTS-LIVRES-CODE"),
        ("Téléphone du contact", extraction.ALIASES_COLONNES_CLIENTS["telephone"], "Téléphone du contact"),
        ("Code_Postal", extraction.ALIASES_COLONNES_CLIENTS["code_postal"], "Code_Postal"),
        ("Client Livre Code", extraction.ALIASES_COLONNES_CADENCIER["code_client"], "Client Livre Code"),
        ("Article-Code", extraction.ALIASES_COLONNES_CADENCIER["code_article"], "Article-Code"),
        (
            "Mtt Net Pied Livré 10/05/26 - 18/08/26",
            extraction.ALIASES_COLONNES_CADENCIER["prix_net"],
            "Mtt Net Pied Livré 10/05/26 - 18/08/26",
        ),
    ],
)
def test_resolution_colonnes_ignore_casse_accents_et_separateurs(
    en_tete: str,
    aliases: list[str],
    attendu: str,
) -> None:
    assert extraction.choisir_colonne([en_tete], aliases) == attendu


def test_loaders_acceptent_les_schemas_actuels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dossier_clients = tmp_path / "clients"
    dossier_cadencier = tmp_path / "cadencier"
    dossier_clients.mkdir()
    dossier_cadencier.mkdir()

    _ecrire_xlsx(
        dossier_clients / "info-clients.xlsx",
        ["Clients_Code", "Clients-Lib", "Code Postal", "Ville", "Téléphone"],
        [["CLIENT42", "LE CLIENT 42", "64200", "BIARRITZ", "06 12 34 56 78"]],
    )
    _ecrire_xlsx(
        dossier_cadencier / "cadencier-clientsBASCO.xlsx",
        [
            "Article code",
            "Article lib",
            "Client-Code",
            "Client lib",
            "Mtt Net Pied Livré 10/05/26 - 18/08/26",
            "Poids Net Livré 10/05/26 - 18/08/26",
        ],
        [["ART01", "ARTICLE TEST 1K", "CLIENT42", "LE CLIENT 42", 12.5, 2.0]],
    )

    monkeypatch.setattr(extraction, "DOSSIER_CLIENTS", dossier_clients)
    monkeypatch.setattr(extraction, "DOSSIER_CADENCIER", dossier_cadencier)

    clients = extraction.charger_clients()
    cadencier = extraction.charger_cadencier()

    assert clients[0]["code_client"] == "CLIENT42"
    assert clients[0]["nom_client"] == "LE CLIENT 42"
    assert clients[0]["telephones"] == ["0612345678"]
    assert cadencier["CLIENT42"][0]["code_article"] == "ART01"


def test_loader_clients_ignore_le_fichier_temporaire_excel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dossier_clients = tmp_path / "clients"
    dossier_clients.mkdir()
    _ecrire_xlsx(
        dossier_clients / "info-clients.xlsx",
        ["Clients_Code", "Clients-Lib", "Code Postal", "Ville", "Telephone"],
        [["CLIENT42", "LE CLIENT 42", "64200", "BIARRITZ", "06 12 34 56 78"]],
    )
    # Excel cree ce verrou pendant que le vrai classeur est ouvert. Son
    # contenu n'est pas un classeur lisible et ne doit jamais etre charge.
    (dossier_clients / "~$info-clients.xlsx").write_bytes(b"verrou Excel")

    monkeypatch.setattr(extraction, "DOSSIER_CLIENTS", dossier_clients)

    assert extraction.trouver_fichiers_xlsx(dossier_clients) == [
        dossier_clients / "info-clients.xlsx"
    ]
    assert extraction.charger_clients()[0]["code_client"] == "CLIENT42"


def test_erreur_colonne_obligatoire_decrit_le_schema_et_le_fichier() -> None:
    chemin = Path("info-clients.xlsx")

    with pytest.raises(KeyError) as erreur:
        extraction.choisir_colonne(
            ["Clients lib", "Ville", "Téléphone"],
            extraction.ALIASES_COLONNES_CLIENTS["code_client"],
            champ_metier="code_client",
            chemin=chemin,
        )

    message = str(erreur.value)
    assert "Champ metier recherche : code_client" in message
    assert "Aliases essayes" in message
    assert "Colonnes reellement disponibles" in message
    assert "Clients lib" in message
    assert "Fichier concerne : info-clients.xlsx" in message


def test_resolution_ne_confond_pas_un_alias_court_avec_une_autre_colonne() -> None:
    assert extraction.choisir_colonne(
        ["Plafond compte autorise"],
        extraction.ALIASES_COLONNES_CLIENTS["code_client"],
        obligatoire=False,
    ) is None
