from src.business_rules import business_rule_enabled


def test_evaluation_ab_peut_desactiver_une_regle_sans_modifier_config(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "EMALO_DISABLED_BUSINESS_RULES",
        "fallback_phonetique_intra_famille",
    )
    assert business_rule_enabled("fallback_phonetique_intra_famille") is False
    assert business_rule_enabled("telephone_exact_verrouille") is True
