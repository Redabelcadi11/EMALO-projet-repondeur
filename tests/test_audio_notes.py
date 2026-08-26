from __future__ import annotations

import json

import pytest

from src.audio_notes import load_audio_notes, save_audio_note


def test_audio_note_is_saved_and_updated_atomically(tmp_path):
    path = tmp_path / "remarques_audios.json"
    audio = {
        "name": "2026-08-21_00-00-38_De-0686843096.wav",
        "path": r"L:\Public\audio.wav",
        "phone": "0686843096",
        "date": "2026-08-21",
        "time": "00:00",
    }

    first = save_audio_note("audio-1", "Client incorrect", audio=audio, path=path)
    second = save_audio_note("audio-1", "Client et creme incorrects", audio=audio, path=path)

    assert first is not None
    assert second is not None
    assert second["note"] == "Client et creme incorrects"
    assert second["created_at"] == first["created_at"]
    assert json.loads(path.read_text(encoding="utf-8"))["notes"]["audio-1"] == second
    assert load_audio_notes(path)["notes"]["audio-1"] == second


def test_empty_note_removes_only_the_selected_audio(tmp_path):
    path = tmp_path / "remarques_audios.json"
    save_audio_note("audio-1", "A corriger", path=path)
    save_audio_note("audio-2", "A conserver", path=path)

    result = save_audio_note("audio-1", "   ", path=path)

    assert result is None
    notes = load_audio_notes(path)["notes"]
    assert "audio-1" not in notes
    assert notes["audio-2"]["note"] == "A conserver"


def test_invalid_key_and_corrupt_file_are_never_overwritten(tmp_path):
    path = tmp_path / "remarques_audios.json"
    with pytest.raises(ValueError):
        save_audio_note("", "texte", path=path)

    path.write_text("{invalide", encoding="utf-8")
    with pytest.raises(RuntimeError):
        save_audio_note("audio-1", "texte", path=path)
    assert path.read_text(encoding="utf-8") == "{invalide"
