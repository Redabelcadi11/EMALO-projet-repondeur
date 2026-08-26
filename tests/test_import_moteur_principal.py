from __future__ import annotations


def test_moteur_principal_est_importable() -> None:
    import extraire_informations

    assert callable(extraire_informations.traiter_transcriptions)
    assert callable(extraire_informations.chercher_produits)
