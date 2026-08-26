from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROD_HTML = PROJECT_ROOT / "app-desktop" / "renderer" / "prod.html"


def test_prod_ui_is_self_contained_and_limits_initial_dom_size():
    html = PROD_HTML.read_text(encoding="utf-8")

    assert "cdn.tailwindcss.com" not in html
    assert "fonts.googleapis.com" not in html
    assert "const PAGE_SIZE = 40;" in html
    assert "audios.slice(0, state.visibleCount)" in html
    assert 'data-action="load-more"' in html


def test_prod_ui_exposes_one_persistent_note_editor_per_rendered_audio():
    html = PROD_HTML.read_text(encoding="utf-8")

    assert 'textarea class="note-input"' in html
    assert 'data-action="save-note"' in html
    assert '["load-audio-notes"]' in html
    assert '["save-audio-note", payload({' in html
    assert "state.noteDrafts" in html


def test_packaged_prod_ui_includes_its_preload_bridge():
    package = json.loads(
        (PROJECT_ROOT / "app-desktop" / "package.json").read_text(encoding="utf-8")
    )

    assert "preload-prod.js" in package["build"]["files"]
