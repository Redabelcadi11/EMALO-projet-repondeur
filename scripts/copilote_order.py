#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

PROJECT_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_BOOTSTRAP_ROOT))

from src.runtime_paths import (
    bootstrap_runtime_environment,
    get_project_root,
)
from src.erp_safety import assert_erp_write_allowed

bootstrap_runtime_environment()
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


PROJECT_ROOT = get_project_root()
DEBUG_DIR = PROJECT_ROOT / "resultats" / "copilote-debug"

KNOWN_INPUTS = {
    "Date commande": "#w_6772_i",
    "Date depart": "#w_6768_i",
    "Date livraison": "#w_6780_i",
    "Heure depart": "#w_6843_i",
}

LABEL_VARIANTS = {
    "Date depart": ["Date depart", "Date départ"],
    "Heure depart": ["Heure depart", "Heure départ"],
    "Date livraison": ["Date livraison", "Date livraison "],
}


class AutomationError(RuntimeError):
    pass


def slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", text).strip("_") or "step"


def normalize_search_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def ensure_debug_dir() -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        print(message.encode("ascii", errors="replace").decode("ascii"), flush=True)


def resolve_browser_executable(explicit_path: str = "") -> str | None:
    candidates = [
        explicit_path,
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def save_debug(page: Page, name: str) -> None:
    ensure_debug_dir()
    slug = slugify(name)
    png_path = DEBUG_DIR / f"{slug}.png"
    html_path = DEBUG_DIR / f"{slug}.html"
    txt_path = DEBUG_DIR / f"{slug}.txt"
    page.screenshot(path=str(png_path), full_page=True)
    html_path.write_text(page.content(), encoding="utf-8")
    txt_path.write_text(page.locator("body").inner_text(), encoding="utf-8")
    log(f"debug saved: {png_path}")


def close_popup(page: Page) -> None:
    candidates = [
        ("legacy popup", page.locator("#w_214")),
        ("obsolete modules ok", page.locator("#w_2271")),
        ("visible ok button", page.get_by_role("button", name="OK")),
        ("obsolete modules close", page.locator("#w_2261")),
    ]
    for label, locator in candidates:
        try:
            if locator.count() and locator.first.is_visible():
                log(f"close popup: {label}")
                locator.first.click()
                page.wait_for_timeout(1000)
        except PlaywrightTimeoutError:
            continue


def accept_confirmation_dialog(page: Page) -> bool:
    candidates = [
        page.get_by_role("button", name="Oui"),
        page.get_by_text("Oui", exact=True),
    ]
    for locator in candidates:
        try:
            if locator.count() and locator.first.is_visible():
                log("accept confirmation dialog")
                locator.first.click()
                page.wait_for_timeout(1200)
                wait_for_idle(page)
                return True
        except PlaywrightTimeoutError:
            continue
    return False


def wait_for_idle(page: Page, timeout_ms: int = 30000) -> None:
    page.wait_for_function(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };

          for (const el of document.querySelectorAll('.inf-loader, .inf-w-loader-spinner, .inf-w-text')) {
            if (!visible(el)) continue;
            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (text === 'Exécution en cours') return false;
            if (el.classList.contains('inf-loader') || el.classList.contains('inf-w-loader-spinner')) {
              return false;
            }
          }
          return true;
        }
        """,
        timeout=timeout_ms,
    )
    page.wait_for_timeout(500)


def login(page: Page, app_url: str, user: str, password: str, dossier: str) -> None:
    log("open login page")
    page.goto(app_url, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_selector("#form-login", timeout=120000)
    page.fill("#form-login", user)
    page.fill("#form-pass", password)
    page.click("#button")
    page.wait_for_timeout(1200)

    dossier_select = page.locator("#form-dossier")
    if dossier_select.count():
        log(f"select dossier {dossier}")
        dossier_select.select_option(dossier)
        page.click("#button")
        page.wait_for_timeout(1200)

    page.wait_for_timeout(2500)
    if page.locator("#form-login").count() and page.locator("#form-login").is_visible():
        save_debug(page, "login_failed")
        raise AutomationError("login form still visible after authentication")


def open_commande_search(page: Page, base_url: str) -> None:
    log("open VT/Commande")
    page.goto(base_url + "app/#!/VT/Commande", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(5000)
    close_popup(page)
    save_debug(page, "vt_commande_loaded")


def open_vtrcom(page: Page, base_url: str) -> None:
    log("open VTRCOM")
    page.goto(base_url + "app/#!/vtrcom", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(5000)
    close_popup(page)
    wait_for_idle(page)
    save_debug(page, "vtrcom_loaded")


def launch_vtrcom_search(page: Page) -> None:
    candidates = [
        page.get_by_role("button", name="Lancer"),
        page.get_by_text("Lancer", exact=True),
    ]
    for locator in candidates:
        try:
            if locator.count() and locator.first.is_visible():
                log("launch VTRCOM search")
                locator.first.click()
                deadline = time.time() + 90
                while time.time() < deadline:
                    page.wait_for_timeout(2000)
                    body_text = page.locator("body").inner_text()
                    body_normalized = normalize_search_text(body_text)
                    if "en cours" not in body_normalized and "extraction des donnees" not in body_normalized:
                        break
                wait_for_idle(page)
                save_debug(page, "vtrcom_results")
                return
        except PlaywrightTimeoutError:
            continue
    save_debug(page, "missing_vtrcom_lancer")
    raise AutomationError("VTRCOM launch button not found")


def inspect_page_for_terms(page: Page, terms: list[str]) -> bool:
    body_text = page.locator("body").inner_text()
    normalized_body = normalize_search_text(body_text)
    matched = True
    for term in terms:
        term_normalized = normalize_search_text(term)
        present = term_normalized in normalized_body
        log(f"term {'found' if present else 'missing'}: {term}")
        matched = matched and present
    log(body_text[:4000])
    return matched


def set_vtrcom_filters(page: Page, client_livre: str, date_depart: str) -> None:
    if client_livre:
        if not set_reference_by_label(page, "Client livré", client_livre):
            save_debug(page, "missing_vtrcom_client_livre")
            raise AutomationError("could not set VTRCOM Client livré filter")
        log(f"set Client livré: {client_livre}")
    if date_depart:
        fill_input_by_label(page, "Date départ", date_depart)
        log(f"set Date départ: {date_depart}")
    page.wait_for_timeout(1000)
    save_debug(page, "vtrcom_filters_filled")


def create_order_for_client(page: Page, client: str) -> None:
    assert_erp_write_allowed("Playwright: ouverture d'une nouvelle commande client")
    log(f"search client {client}")
    page.wait_for_timeout(2000)
    close_popup(page)
    save_debug(page, "client_home_loaded")

    client_input = page.locator(".custom-id-client input.form-control").first
    client_editor = page.locator(".custom-id-client .inf-select-selected[contenteditable='true']").first
    if not client_input.count():
        save_debug(page, "missing_client_input")
        raise AutomationError("client input not found on home screen")

    if client_editor.count() and client_editor.is_visible():
        client_editor.click()
    client_input.fill(client, force=True)
    page.wait_for_timeout(1200)
    save_debug(page, "client_typed")
    client_input.press("ArrowDown")
    client_input.press("Enter")
    page.wait_for_timeout(2500)
    save_debug(page, "client_selected")

    create_candidates = [
        page.locator("#w_153"),
        page.get_by_text("Créer une commande pour le client", exact=False),
        page.get_by_text("Creer une commande pour le client", exact=False),
        page.get_by_text("Créer une commande", exact=False),
        page.get_by_text("Creer une commande", exact=False),
        page.get_by_role("button", name=re.compile("cr[eé]er une commande", re.I)),
    ]
    create_button = None
    for locator in create_candidates:
        if locator.count() and locator.first.is_visible():
            create_button = locator.first
            break
    if create_button is None:
        save_debug(page, "missing_create_order_button")
        raise AutomationError("create order button not found after client search")

    create_button.click()
    page.wait_for_timeout(6000)


def fill_input(page: Page, selector: str, value: str) -> bool:
    locator = page.locator(selector)
    if not locator.count():
        return False
    if not locator.first.is_visible():
        return False
    locator.first.click()
    locator.first.fill(value)
    page.wait_for_timeout(150)
    return True


def label_variants(label: str) -> list[str]:
    key = label.replace("é", "e").replace("è", "e")
    return LABEL_VARIANTS.get(key, [label])


def exact_form_group_xpath(label: str, target_xpath: str) -> str:
    normalized = label.strip()
    return (
        "xpath=//div[contains(@class,'form-group')]"
        f"[.//label[normalize-space()='{normalized}']]"
        f"//{target_xpath}"
    )


def get_reference_text_by_label(page: Page, label: str) -> str:
    for variant in label_variants(label):
        locator = page.locator(
            exact_form_group_xpath(variant, "*[contains(@class,'inf-select-selected-elts')]")
        )
        if locator.count() and locator.first.is_visible():
            return locator.first.inner_text().strip()
    return ""


def set_reference_by_label(page: Page, label: str, value: str) -> bool:
    for variant in label_variants(label):
        input_box = page.locator(exact_form_group_xpath(variant, "input[contains(@class,'form-control')]"))
        if not input_box.count():
            continue
        input_box.first.fill(value, force=True)
        page.wait_for_timeout(1200)
        input_box.first.press("ArrowDown")
        input_box.first.press("Enter")
        page.wait_for_timeout(1500)
        if get_reference_text_by_label(page, label):
            return True
    return False


def fill_input_by_label(page: Page, label: str, value: str) -> None:
    key = label.replace("é", "e").replace("è", "e")
    variants = label_variants(label)
    selector = KNOWN_INPUTS.get(key)
    if selector and fill_input(page, selector, value):
        log(f"set {label}: {value}")
        return

    for variant in variants:
        candidates = [
            exact_form_group_xpath(variant, "input"),
        ]
        for candidate in candidates:
            if fill_input(page, candidate, value):
                log(f"set {label}: {value}")
                return

    save_debug(page, f"missing_{label}")
    raise AutomationError(f"could not find input for label {label}")


def fill_general_information(page: Page, date_commande: str, date_depart: str, date_livraison: str, heure_depart: str) -> str:
    assert_erp_write_allowed("Playwright: modification de l'entete d'une commande")
    transport_before = get_reference_text_by_label(page, "Transport")
    fill_input_by_label(page, "Date commande", date_commande)
    fill_input_by_label(page, "Date depart", date_depart)
    fill_input_by_label(page, "Date livraison", date_livraison)
    page.wait_for_timeout(1200)
    fill_input_by_label(page, "Heure depart", heure_depart)
    if transport_before and not get_reference_text_by_label(page, "Transport"):
        if set_reference_by_label(page, "Transport", transport_before):
            log(f"set Transport: {transport_before}")
    page.wait_for_timeout(1000)
    return get_reference_text_by_label(page, "Transport") or transport_before


def open_articles_step(page: Page, heure_depart: str, transport_value: str) -> None:
    assert_erp_write_allowed("Playwright: passage a la saisie des articles")
    for attempt in range(3):
        click_toolbar_next(page, f"to_articles_{attempt + 1}")
        if accept_confirmation_dialog(page):
            body_text = page.locator("body").inner_text()
            if "Qté cdée" in body_text or "Qte cdée" in body_text or "\nArticle\n" in body_text:
                wait_for_idle(page)
                return
        body_text = page.locator("body").inner_text()
        if "Qté cdée" in body_text or "Qte cdée" in body_text or "\nArticle\n" in body_text:
            wait_for_idle(page)
            return

        repaired = False
        if "Heure départ est obligatoire" in body_text:
            fill_input_by_label(page, "Heure depart", heure_depart)
            repaired = True
        if "Transport est obligatoire" in body_text and transport_value:
            if set_reference_by_label(page, "Transport", transport_value):
                log(f"set Transport: {transport_value}")
                repaired = True
        if not repaired:
            break

    save_debug(page, "articles_step_unavailable")
    raise AutomationError("could not reach article step")


def get_toolbar_snapshot(page: Page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };
          const isClickable = (el) => {
            if (el.matches('button,[role="button"],a')) return true;
            const cls = (el.className || '').toString();
            if (cls.includes('inf-button') || cls.includes('inf-w-button')) return true;
            if (cls.includes('inf-widget') && el.tagName === 'IMG') return true;
            if (getComputedStyle(el).cursor === 'pointer') return true;
            return false;
          };
          const out = [];
          for (const el of document.querySelectorAll('body *')) {
            if (!visible(el) || !isClickable(el)) continue;
            const r = el.getBoundingClientRect();
            if (r.y < 70 || r.y > 190) continue;
            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
            out.push({
              tag: el.tagName,
              id: el.id || '',
              cls: (el.className || '').toString(),
              text,
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
            });
          }
          out.sort((a, b) => a.x - b.x || a.y - b.y);
          return out;
        }
        """
    )


def click_toolbar_next(page: Page, debug_name: str) -> None:
    direct_next = page.locator("button.custom-id-multipage_tabs_button-next").first
    if direct_next.count() and direct_next.is_visible() and direct_next.is_enabled():
        log("click toolbar next button")
        direct_next.click()
        page.wait_for_timeout(2000)
        body_text = page.locator("body").inner_text()
        if "Qté cdée" in body_text or "Qte cdée" in body_text or "Article" in body_text:
            return

    snapshot = get_toolbar_snapshot(page)
    actions = next((item for item in snapshot if item["text"] == "Actions"), None)
    if not actions:
        save_debug(page, f"{debug_name}_no_actions")
        raise AutomationError("could not locate Actions button in toolbar")

    candidates = [
        item
        for item in snapshot
        if item["x"] < actions["x"]
        and item["x"] >= actions["x"] - 220
        and item["w"] <= 80
        and item["h"] <= 80
        and item["text"] in ("", "0 article", "Precad.")
    ]
    candidates.sort(key=lambda item: item["x"], reverse=True)

    if not candidates:
        (DEBUG_DIR / f"{slugify(debug_name)}_toolbar.json").write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        save_debug(page, f"{debug_name}_toolbar")
        raise AutomationError("no toolbar candidate found before Actions")

    for candidate in candidates:
        x = candidate["x"] + candidate["w"] / 2
        y = candidate["y"] + candidate["h"] / 2
        log(f"click toolbar candidate {candidate}")
        page.mouse.click(x, y)
        page.wait_for_timeout(2000)
        body_text = page.locator("body").inner_text()
        if "Qté cdée" in body_text or "Qte cdée" in body_text or "Article" in body_text:
            return

    save_debug(page, f"{debug_name}_after_toolbar")
    raise AutomationError("toolbar navigation click did not open article step")


def dispatch_click_by_text(page: Page, tag_name: str, text: str) -> bool:
    return bool(
        page.evaluate(
            """
            ({ tagName, text }) => {
              const needle = text.toLowerCase();
              const els = [...document.querySelectorAll(tagName)];
              const target = els.find((el) => ((el.innerText || el.textContent || '').toLowerCase().includes(needle)));
              if (!target) return false;
              target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
              return true;
            }
            """,
            {"tagName": tag_name, "text": text},
        )
    )


def click_visible_tab_link(page: Page, text: str) -> bool:
    return bool(
        page.evaluate(
            """
            (label) => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width >= 10 && r.height >= 10 &&
                  s.display !== 'none' && s.visibility !== 'hidden' &&
                  !el.classList.contains('inf-hide') &&
                  r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
              };
              const normalized = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const needle = normalized(label);
              const candidates = [
                ...document.querySelectorAll('a.inf-w-tabs-nav-link'),
                ...document.querySelectorAll('a[role=\"button\"]'),
              ];
              for (const candidate of candidates) {
                if (!visible(candidate)) continue;
                const textValue = normalized(candidate.innerText || candidate.textContent || '');
                if (textValue !== needle && !textValue.includes(needle)) continue;
                candidate.click();
                return true;
              }
              return false;
            }
            """,
            text,
        )
    )


def get_visible_tab_links(page: Page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };
          const out = [];
          for (const link of document.querySelectorAll('a.inf-w-tabs-nav-link')) {
            if (!visible(link)) continue;
            const r = link.getBoundingClientRect();
            out.push({
              text: (link.innerText || link.textContent || '').replace(/\\s+/g, ' ').trim(),
              id: link.id || '',
              cls: (link.className || '').toString(),
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
            });
          }
          return out;
        }
        """
    )


def is_visible_tab_selectable(page: Page, text: str) -> bool:
    normalized = normalize_search_text(text)
    for tab in get_visible_tab_links(page):
        if normalize_search_text(tab["text"]) != normalized:
            continue
        return "inf-w-inactive" not in tab["cls"]
    return False


def get_visible_selected_cells(page: Page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };
          const out = [];
          for (const cell of document.querySelectorAll('.inf-cell.row-selected, .inf-cell.row-anchored')) {
            if (!visible(cell)) continue;
            const r = cell.getBoundingClientRect();
            const text = (cell.innerText || cell.textContent || '').replace(/\\s+/g, ' ').trim();
            out.push({
              text,
              cls: (cell.className || '').toString(),
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
            });
          }
          out.sort((a, b) => a.y - b.y || a.x - b.x);
          return out;
        }
        """
    )


def get_visible_headers(page: Page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };
          const out = [];
          for (const cell of document.querySelectorAll('.inf-header')) {
            if (!visible(cell)) continue;
            const r = cell.getBoundingClientRect();
            const text = (cell.innerText || cell.textContent || '').replace(/\\s+/g, ' ').trim();
            out.push({
              text,
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
            });
          }
          out.sort((a, b) => a.y - b.y || a.x - b.x);
          return out;
        }
        """
    )


def get_selected_current_row(page: Page) -> dict[str, str]:
    headers = [
        header
        for header in get_visible_headers(page)
        if header["y"] < 300 and header["x"] >= 250
    ]
    cells = [
        cell
        for cell in get_visible_selected_cells(page)
        if 350 <= cell["y"] <= 950 and cell["x"] >= 250
    ]
    if not headers or not cells:
        return {}

    row_y = min(cell["y"] for cell in cells)
    row_cells = [cell for cell in cells if cell["y"] == row_y]
    values: dict[str, str] = {}
    for header in headers:
        matching = next((cell for cell in row_cells if cell["x"] == header["x"]), None)
        values[header["text"]] = matching["text"] if matching else ""
    return values


def get_selected_current_row_y(page: Page) -> int | None:
    cells = [
        cell
        for cell in get_visible_selected_cells(page)
        if 350 <= cell["y"] <= 950 and cell["x"] >= 250
    ]
    if not cells:
        return None
    return min(cell["y"] for cell in cells)


def get_selected_article_row(page: Page) -> dict | None:
    row = get_selected_current_row(page)
    article = (row.get("Article *") or row.get("Article") or "").strip()
    row_y = get_selected_current_row_y(page)
    if not article or row_y is None:
        return None
    return {
        "text": article,
        "y": row_y,
        "h": 21,
    }


def get_principal_visible_rows(page: Page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const root = document.querySelector('.custom-id-principalSource');
          if (!root) return [];

          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };

          const headers = [...root.querySelectorAll('.inf-header')]
            .filter(visible)
            .map((header) => {
              const r = header.getBoundingClientRect();
              return {
                text: (header.innerText || header.textContent || '').replace(/\\s+/g, ' ').trim(),
                x: Math.round(r.x),
                y: Math.round(r.y),
              };
            })
            .filter((header) => header.text && header.y < 400)
            .sort((a, b) => a.x - b.x);

          const cells = [...root.querySelectorAll('.inf-cell')]
            .filter(visible)
            .map((cell) => {
              const r = cell.getBoundingClientRect();
              return {
                text: (cell.innerText || cell.textContent || '').replace(/\\s+/g, ' ').trim(),
                x: Math.round(r.x),
                y: Math.round(r.y),
                h: Math.round(r.height),
                cls: (cell.className || '').toString(),
              };
            })
            .filter((cell) => cell.y >= 200 && cell.y <= 950 && cell.x >= 200);

          const rows = new Map();
          for (const cell of cells) {
            const key = `${cell.y}`;
            if (!rows.has(key)) rows.set(key, { y: cell.y, h: cell.h, cells: [] });
            rows.get(key).cells.push(cell);
          }

          const out = [];
          for (const row of rows.values()) {
            row.cells.sort((a, b) => a.x - b.x);
            const values = {};
            for (const header of headers) {
              const matching = row.cells.find((cell) => cell.x === header.x);
              if (matching) values[header.text] = matching.text;
            }
            out.push({
              y: row.y,
              h: row.h,
              values,
            });
          }
          out.sort((a, b) => a.y - b.y);
          return out;
        }
        """
    )


def find_principal_row_by_article(page: Page, article_code: str) -> dict | None:
    normalized_code = normalize_search_text(article_code)
    for row in get_principal_visible_rows(page):
        article = normalize_search_text(row["values"].get("Article *") or row["values"].get("Article") or "")
        if article == normalized_code:
            return row
    return None


def wait_for_article_row_ready(page: Page, article_code: str, timeout_ms: int = 12000) -> dict | None:
    deadline = time.time() + timeout_ms / 1000
    last_row = None
    while time.time() < deadline:
        row = find_principal_row_by_article(page, article_code)
        if row:
            last_row = row
            values = row["values"]
            semi_net = (values.get("Prix semi-net") or "").strip()
            qty = (values.get("Qté cdée") or "").strip()
            remises = (values.get("Remises") or "").strip()
            if qty and (semi_net or remises):
                log(f"article row ready for {article_code}: {json.dumps(values, ensure_ascii=False)}")
                return row
        if is_next_enabled(page):
            return row
        page.wait_for_timeout(500)
    if last_row:
        log(f"article row last observed for {article_code}: {json.dumps(last_row['values'], ensure_ascii=False)}")
    return last_row


def wait_for_article_commit_settle(page: Page, article_code: str, timeout_ms: int = 20000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    saw_one_article = False
    while time.time() < deadline:
        if has_visible_table_editor(page):
            close_visible_table_editor(page)
        accept_confirmation_dialog(page)

        count = get_visible_article_count(page)
        if count == "1 article":
            saw_one_article = True

        if is_next_enabled(page) or is_visible_tab_selectable(page, "Récapitulatif") or is_save_enabled(page):
            log(
                "article commit settled "
                + json.dumps(
                    {
                        "count": count,
                        "next": is_next_enabled(page),
                        "recap": is_visible_tab_selectable(page, "Récapitulatif"),
                        "save": is_save_enabled(page),
                    },
                    ensure_ascii=False,
                )
            )
            return True

        page.wait_for_timeout(1200)
        try:
            wait_for_idle(page, timeout_ms=4000)
        except PlaywrightTimeoutError:
            pass

    row = find_principal_row_by_article(page, article_code)
    if row:
        log(f"article commit timeout row {article_code}: {json.dumps(row['values'], ensure_ascii=False)}")
    log(
        "article commit timeout "
        + json.dumps(
            {
                "count": get_visible_article_count(page),
                "next": is_next_enabled(page),
                "recap": is_visible_tab_selectable(page, "Récapitulatif"),
                "save": is_save_enabled(page),
            },
            ensure_ascii=False,
        )
    )
    return False


def select_principal_row_by_article(page: Page, article_code: str) -> bool:
    row = find_principal_row_by_article(page, article_code)
    if not row:
        return False
    headers = {header["text"]: header for header in get_visible_headers(page)}
    article_header = headers.get("Article *") or headers.get("Article")
    if not article_header:
        return False
    click_grid_cell_at_row(page, article_header, row["y"], row["h"])
    page.wait_for_timeout(400)
    log(f"reselected article row {article_code}")
    return True


def get_selected_row_from_table(page: Page, root_selector: str) -> dict[str, str]:
    return page.evaluate(
        """
        (rootSelector) => {
          const root = document.querySelector(rootSelector);
          if (!root) return {};

          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };

          const headers = [...root.querySelectorAll('.inf-header')]
            .filter(visible)
            .map((header) => {
              const r = header.getBoundingClientRect();
              return {
                text: (header.innerText || header.textContent || '').replace(/\\s+/g, ' ').trim(),
                x: Math.round(r.x),
                y: Math.round(r.y),
              };
            })
            .filter((header) => header.text);

          const cells = [...root.querySelectorAll('.inf-cell.row-selected, .inf-cell.row-anchored')]
            .filter(visible)
            .map((cell) => {
              const r = cell.getBoundingClientRect();
              return {
                text: (cell.innerText || cell.textContent || '').replace(/\\s+/g, ' ').trim(),
                x: Math.round(r.x),
                y: Math.round(r.y),
              };
            });

          if (!headers.length || !cells.length) return {};

          const rowY = Math.min(...cells.map((cell) => cell.y));
          const rowCells = cells.filter((cell) => cell.y === rowY);
          const out = {};
          for (const header of headers) {
            const matching = rowCells.find((cell) => cell.x === header.x);
            if (matching) out[header.text] = matching.text;
          }
          return out;
        }
        """,
        root_selector,
    )


def get_last_order_row(page: Page) -> dict[str, str]:
    return get_selected_row_from_table(page, ".custom-id-dernCdeTable")


def parse_numeric_value(text: str) -> str:
    match = re.search(r"([0-9]+(?:[.,][0-9]+)?)", text or "")
    if not match:
        return ""
    return match.group(1).replace(",", ".")


def click_table_shortcut(page: Page, root_selector: str, label: str) -> bool:
    return bool(
        page.evaluate(
            """
            ({ rootSelector, label }) => {
              const root = document.querySelector(rootSelector);
              if (!root) return false;

              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width >= 10 && r.height >= 10 &&
                  s.display !== 'none' && s.visibility !== 'hidden' &&
                  !el.classList.contains('inf-hide') &&
                  r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
              };
              const normalized = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const needle = normalized(label);
              for (const button of root.querySelectorAll('.inf-table-shortcuts-row button')) {
                if (!visible(button)) continue;
                const textValue = normalized(button.innerText || button.textContent || '');
                if (textValue !== needle) continue;
                button.click();
                return true;
              }
              return false;
            }
            """,
            {"rootSelector": root_selector, "label": label},
        )
    )


def click_principal_shortcut(page: Page, label: str) -> bool:
    if click_table_shortcut(page, ".custom-id-principalSource", label):
        log(f"click main table shortcut {label}")
        page.wait_for_timeout(700)
        wait_for_idle(page)
        return True
    log(f"main table shortcut not found: {label}")
    return False


def nudge_main_header_into_view(page: Page, header_text: str, target_right: int = 1450) -> bool:
    result = page.evaluate(
        """
        ({ headerText, targetRight }) => {
          const root = document.querySelector('.custom-id-principalSource');
          if (!root) return null;
          const normalized = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
          const needle = normalized(headerText);
          const header = [...root.querySelectorAll('.inf-header')].find((el) => {
            const s = getComputedStyle(el);
            if (s.display === 'none' || s.visibility === 'hidden' || el.classList.contains('inf-hide')) return false;
            return normalized(el.innerText || el.textContent || '') === needle;
          });
          if (!header) return { found: false };
          const r = header.getBoundingClientRect();
          const overflow = Math.round(r.x + r.width - targetRight);
          if (overflow <= 0) {
            return { found: true, overflow, scrollLeft: 0 };
          }
          const container = root.querySelector('.scroll') || root.querySelector('.scroll-horizontal');
          if (!container) return { found: true, overflow, noContainer: true };
          container.scrollLeft = (container.scrollLeft || 0) + overflow + 40;
          return {
            found: true,
            overflow,
            scrollLeft: Math.round(container.scrollLeft || 0),
            scrollWidth: Math.round(container.scrollWidth || 0),
            clientWidth: Math.round(container.clientWidth || 0),
          };
        }
        """,
        {"headerText": header_text, "targetRight": target_right},
    )
    if not result:
        log("main grid horizontal nudge evaluation failed")
        return False
    if not result.get("found"):
        log(f"main grid header not found for horizontal nudge: {header_text}")
        return False
    if result.get("noContainer"):
        log("main grid horizontal scroll container not found")
        return False
    page.wait_for_timeout(500)
    log(f"nudge main grid for {header_text}: {json.dumps(result, ensure_ascii=False)}")
    return True


def fill_visible_table_editor_with_navigation(page: Page, value: str, arrow_down: bool = False) -> bool:
    locator = page.locator(".inf-table-widget-container input.form-control")
    try:
        count = locator.count()
    except PlaywrightTimeoutError:
        return False
    if not count:
        return False

    for index in range(count - 1, -1, -1):
        candidate = locator.nth(index)
        if not candidate.is_visible():
            continue
        try:
            candidate.click()
            candidate.fill(value)
            page.wait_for_timeout(250)
            if arrow_down:
                candidate.press("ArrowDown")
                page.wait_for_timeout(250)
            candidate.press("Enter")
            page.wait_for_timeout(1000)
            return True
        except PlaywrightTimeoutError:
            continue
    return False


def fill_selected_main_row_cell(page: Page, header_text: str, value: str, arrow_down: bool = False) -> bool:
    row_y = get_selected_current_row_y(page)
    if row_y is None:
        return False

    headers = {header["text"]: header for header in get_visible_headers(page)}
    header = headers.get(header_text)
    if not header:
        return False

    target_x = header["x"] + min(max(header["w"] * 0.5, 30), max(header["w"] - 8, 30))
    target_y = row_y + 10

    def current_value() -> str:
        return get_selected_current_row(page).get(header_text, "").strip()

    def value_applied() -> bool:
        applied = current_value()
        if not applied:
            return False
        if header_text.startswith("Prix"):
            return parse_numeric_value(applied) == parse_numeric_value(value)
        return normalize_search_text(applied) == normalize_search_text(value)

    attempts = [
        ("click", lambda: page.mouse.click(target_x, target_y)),
        ("double_click", lambda: page.mouse.dblclick(target_x, target_y)),
        ("f2", lambda: page.keyboard.press("F2")),
    ]
    for label, action in attempts:
        action()
        page.wait_for_timeout(350)
        if fill_visible_table_editor_with_navigation(page, value, arrow_down=arrow_down):
            blur_grid_focus(page)
            page.wait_for_timeout(400)
            if value_applied():
                log(f"filled {header_text} using {label}")
                return True

    page.mouse.click(target_x, target_y)
    page.wait_for_timeout(250)
    page.keyboard.press("Control+A")
    page.keyboard.type(value, delay=40)
    if arrow_down:
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(250)
    page.keyboard.press("Enter")
    page.wait_for_timeout(800)
    blur_grid_focus(page)
    page.wait_for_timeout(400)
    if value_applied():
        log(f"filled {header_text} using direct keyboard typing")
        return True

    save_debug(page, f"failed_fill_{header_text}")
    return False


def try_fill_type_prix_from_history(page: Page, article_code: str) -> bool:
    history = get_last_order_row(page)
    type_prix = (history.get("Type prix") or history.get("Type prix *") or "").strip()
    if not type_prix:
        return False

    if not select_principal_row_by_article(page, article_code):
        return False

    main_headers = [
        header["text"]
        for header in get_visible_headers(page)
        if header["y"] < 400 and header["x"] >= 250
    ]
    if not any(text.startswith("Type prix") for text in main_headers):
        if click_principal_shortcut(page, "TP"):
            select_principal_row_by_article(page, article_code)

    row = get_selected_current_row(page)
    header_name = next(
        (
            header["text"]
            for header in get_visible_headers(page)
            if header["y"] < 400 and header["x"] >= 250 and header["text"].startswith("Type prix")
        ),
        "",
    )
    if not header_name:
        return False
    if row.get(header_name, "").strip():
        return False

    log(f"fill missing Type prix with history value {type_prix}")
    if fill_selected_main_row_cell(page, header_name, type_prix, arrow_down=True):
        save_debug(page, "filled_type_prix")
        return True
    return False


def try_fill_missing_price_semi_net(page: Page, article_code: str) -> bool:
    target_row = find_principal_row_by_article(page, article_code)
    if not target_row:
        return False

    row = target_row["values"]
    history = get_last_order_row(page)
    history_price = parse_numeric_value(history.get("Prix net pied") or history.get("Prix") or "")
    tarif = parse_numeric_value(row.get("Prix tarif", ""))
    semi_net = row.get("Prix semi-net", "").strip()
    if not tarif or semi_net:
        return False

    if not nudge_main_header_into_view(page, "Prix semi-net"):
        if click_principal_shortcut(page, "PRIX"):
            select_principal_row_by_article(page, article_code)
            nudge_main_header_into_view(page, "Prix semi-net")
    log(f"visible headers after price nudge: {json.dumps(get_visible_headers(page), ensure_ascii=False)}")
    if not any(header["text"] == "Prix semi-net" for header in get_visible_headers(page)):
        return False
    if not select_principal_row_by_article(page, article_code):
        return False
    value = history_price or tarif
    if not value:
        return False

    log(f"fill missing Prix semi-net with {'history price' if history_price else 'Prix tarif'} {value}")
    if fill_selected_main_row_cell(page, "Prix semi-net", value):
        save_debug(page, "filled_prix_semi_net")
        return True
    return False


def dispatch_click_selector(page: Page, selector: str) -> bool:
    return bool(
        page.evaluate(
            """
            (selector) => {
              const target = document.querySelector(selector);
              if (!target) return false;
              target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
              return true;
            }
            """,
            selector,
        )
    )


def get_grid_headers(page: Page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const out = [];
          for (const el of document.querySelectorAll('body *')) {
            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (!text) continue;
            if (!['Article', 'Qté cdée', 'Qte cdée'].includes(text)) continue;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            if (s.display === 'none' || s.visibility === 'hidden') continue;
            out.push({
              text,
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
            });
          }
          return out;
        }
        """
    )


def click_grid_cell(page: Page, header: dict, row_offset: int = 26) -> None:
    x = header["x"] + min(max(header["w"] * 0.5, 30), max(header["w"] - 8, 30))
    y = header["y"] + header["h"] + row_offset
    page.mouse.click(x, y)
    page.wait_for_timeout(500)


def click_grid_cell_at_row(page: Page, header: dict, row_y: int, row_h: int = 21) -> None:
    x = header["x"] + min(max(header["w"] * 0.5, 30), max(header["w"] - 8, 30))
    y = row_y + max(row_h / 2, 10)
    page.mouse.click(x, y)
    page.wait_for_timeout(500)


def get_visible_dropdown_rows(page: Page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };

          const rows = new Map();
          for (const cell of document.querySelectorAll('.inf-select-dropdown:not(.inf-hide) .inf-cell')) {
            if (!visible(cell)) continue;
            const text = (cell.innerText || cell.textContent || '').replace(/\\s+/g, ' ').trim();
            if (!text) continue;
            const r = cell.getBoundingClientRect();
            const key = Math.round(r.y);
            if (!rows.has(key)) {
              rows.set(key, { y: Math.round(r.y), cells: [] });
            }
            rows.get(key).cells.push({
              text,
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
            });
          }

          return [...rows.values()]
            .map((row) => {
              row.cells.sort((a, b) => a.x - b.x);
              return {
                y: row.y,
                text: row.cells.map((cell) => cell.text).join(' | '),
                x: row.cells[0].x,
                h: row.cells[0].h,
              };
            })
            .sort((a, b) => a.y - b.y);
        }
        """
    )


def get_visible_table_toolbar_buttons(page: Page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };

          const out = [];
          for (const button of document.querySelectorAll('.inf-table-toolbar-btn')) {
            if (!visible(button)) continue;
            const r = button.getBoundingClientRect();
            if (r.x < 980 || r.y < 100 || r.y > 700) continue;
            out.push({
              id: button.id || '',
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
              cls: (button.className || '').toString(),
            });
          }
          return out.sort((a, b) => a.y - b.y || a.x - b.x);
        }
        """
    )


def get_visible_tooltip_label(page: Page) -> str:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };
          const headers = [...document.querySelectorAll('.inf-tooltip:not(.inf-hide) .inf-tooltip-header-left')]
            .filter(visible)
            .map((el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim())
            .filter(Boolean);
          return headers[0] || '';
        }
        """
    )


def describe_visible_table_toolbar_buttons(page: Page) -> list[dict]:
    described = []
    for button in get_visible_table_toolbar_buttons(page):
        page.mouse.move(button["x"] + button["w"] / 2, button["y"] + button["h"] / 2)
        page.wait_for_timeout(450)
        described.append(
            {
                **button,
                "tooltip": get_visible_tooltip_label(page),
            }
        )
    page.mouse.move(40, 40)
    page.wait_for_timeout(200)
    return described


def has_visible_reference_rows(page: Page) -> bool:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };
          return [...document.querySelectorAll('span.reference')].some(visible);
        }
        """
    )


def count_visible_reference_rows(page: Page) -> int:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };
          return [...document.querySelectorAll('span.reference')].filter(visible).length;
        }
        """
    )


def get_loader_snapshot(page: Page) -> dict[str, str | bool]:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };
          for (const el of document.querySelectorAll('.inf-loader, .inf-w-loader-spinner, .inf-w-text')) {
            if (!visible(el)) continue;
            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (!text) continue;
            if (text === 'Exécution en cours') {
              return { visible: true, text };
            }
          }
          return { visible: false, text: '' };
        }
        """
    )


def click_main_table_add(page: Page) -> bool:
    buttons = get_visible_table_toolbar_buttons(page)
    if not buttons:
        return False
    button = buttons[0]
    log(f"click main table toolbar button {button}")
    page.mouse.click(button["x"] + button["w"] / 2, button["y"] + button["h"] / 2)
    page.wait_for_timeout(1200)
    return True


def is_next_enabled(page: Page) -> bool:
    next_button = page.locator("button.custom-id-multipage_tabs_button-next").first
    return bool(next_button.count() and next_button.is_enabled())


def is_save_enabled(page: Page) -> bool:
    save_button = page.get_by_role("button", name="Enregistrer")
    return bool(save_button.count() and save_button.first.is_enabled())


def has_article_count(page, expected: str = "1 article") -> bool:
    return expected in page.locator("body").inner_text()


def get_visible_article_count(page: Page) -> str:
    for item in get_toolbar_snapshot(page):
        text = (item.get("text") or "").strip()
        if re.fullmatch(r"\d+\s+article[s]?", text):
            return text
    return ""


def blur_grid_focus(page: Page) -> None:
    page.mouse.click(300, 95)
    page.wait_for_timeout(600)


def try_post_line_commit_gestures(page: Page, product_query: str) -> bool:
    gestures = [
        ("enter", lambda: page.keyboard.press("Enter")),
        ("tab", lambda: page.keyboard.press("Tab")),
        ("shift_tab", lambda: page.keyboard.press("Shift+Tab")),
        ("blur", lambda: blur_grid_focus(page)),
    ]
    for label, action in gestures:
        if not select_principal_row_by_article(page, product_query):
            return False
        log(f"try post-line gesture {label}")
        action()
        page.wait_for_timeout(800)
        if has_visible_table_editor(page):
            close_visible_table_editor(page)
        try:
            wait_for_idle(page, timeout_ms=8000)
        except PlaywrightTimeoutError:
            pass
        log(
            "post-line gesture state "
            + json.dumps(
                {
                    "gesture": label,
                    "loader": get_loader_snapshot(page),
                    "count": get_visible_article_count(page),
                    "next": is_next_enabled(page),
                    "recap": is_visible_tab_selectable(page, "Récapitulatif"),
                    "save": is_save_enabled(page),
                },
                ensure_ascii=False,
            )
        )
        if wait_for_article_commit_settle(page, product_query, timeout_ms=6000):
            return True
    return False


def fill_visible_table_editor(page: Page, value: str) -> bool:
    locator = page.locator(".inf-table-widget-container input.form-control")
    try:
        count = locator.count()
    except PlaywrightTimeoutError:
        return False
    if not count:
        return False

    for index in range(count - 1, -1, -1):
        candidate = locator.nth(index)
        if not candidate.is_visible():
            continue
        try:
            candidate.click()
            candidate.fill(value)
            page.wait_for_timeout(150)
            candidate.press("Enter")
            page.wait_for_timeout(800)
            return True
        except PlaywrightTimeoutError:
            continue
    return False


def has_visible_table_editor(page: Page) -> bool:
    locator = page.locator(".inf-table-widget-container input.form-control")
    try:
        count = locator.count()
    except PlaywrightTimeoutError:
        return False
    for index in range(count):
        if locator.nth(index).is_visible():
            return True
    return False


def close_visible_table_editor(page: Page) -> bool:
    if not has_visible_table_editor(page):
        return True

    for key in ("Enter", "Tab", "Escape"):
        page.keyboard.press(key)
        page.wait_for_timeout(500)
        if not has_visible_table_editor(page):
            log(f"closed visible table editor with {key}")
            return True

    blur_grid_focus(page)
    page.wait_for_timeout(500)
    if not has_visible_table_editor(page):
        log("closed visible table editor with blur")
        return True
    return False


def find_visible_reference_row(page: Page, product_query: str) -> dict | None:
    return page.evaluate(
        """
        (productQuery) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };

          const normalized = (text) => (text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
          const query = normalized(productQuery);
          for (const ref of document.querySelectorAll('span.reference')) {
            if (!visible(ref)) continue;
            const text = normalized(ref.innerText || ref.textContent || '');
            if (text !== query) continue;
            const cell = ref.closest('.inf-cell');
            if (!cell || !visible(cell)) continue;
            const r = cell.getBoundingClientRect();
            return {
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
              text,
            };
          }
          return null;
        }
        """,
        product_query,
    )


def get_first_visible_reference_row(page: Page) -> dict | None:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 10 && r.height >= 10 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };

          for (const ref of document.querySelectorAll('span.reference')) {
            if (!visible(ref)) continue;
            const cell = ref.closest('.inf-cell');
            if (!cell || !visible(cell)) continue;
            const r = cell.getBoundingClientRect();
            return {
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
              text: (ref.innerText || ref.textContent || '').replace(/\\s+/g, ' ').trim(),
            };
          }
          return null;
        }
        """
    )


def click_reference_row_button(page: Page, product_query: str) -> bool:
    button = page.evaluate(
        """
        (productQuery) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 8 && r.height >= 8 &&
              s.display !== 'none' && s.visibility !== 'hidden' &&
              !el.classList.contains('inf-hide') &&
              r.bottom >= 0 && r.right >= 0 && r.top <= innerHeight && r.left <= innerWidth;
          };

          const normalized = (text) => (text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
          const query = normalized(productQuery);
          for (const ref of document.querySelectorAll('span.reference')) {
            if (!visible(ref)) continue;
            const text = normalized(ref.innerText || ref.textContent || '');
            if (text !== query) continue;
            const cell = ref.closest('.inf-cell');
            const button = cell ? cell.querySelector('button') : null;
            if (!button || !visible(button)) continue;
            const r = button.getBoundingClientRect();
            return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
          }
          return null;
        }
        """,
        product_query,
    )
    if not button:
        return False
    log(f"click row button for {product_query}")
    page.mouse.click(button["x"] + button["w"] / 2, button["y"] + button["h"] / 2)
    page.wait_for_timeout(800)
    return True


def attempt_article_commit(page: Page, product_query: str) -> bool:
    if has_visible_table_editor(page):
        log("visible table editor detected before article commit")
        close_visible_table_editor(page)
        wait_for_idle(page)
        if wait_for_article_commit_settle(page, product_query, timeout_ms=6000):
            return True

    if is_next_enabled(page):
        return True

    row = find_principal_row_by_article(page, product_query)
    if row:
        values = row["values"]
        semi_net = (values.get("Prix semi-net") or "").strip()
        remises = (values.get("Remises") or "").strip()
        qty = (values.get("Qté cdée") or "").strip()
        if qty and (semi_net or remises):
            log(f"target row already complete: {json.dumps(values, ensure_ascii=False)}")
            select_principal_row_by_article(page, product_query)
            blur_grid_focus(page)
            if wait_for_article_commit_settle(page, product_query, timeout_ms=12000):
                return True
            if try_post_line_commit_gestures(page, product_query):
                return True

    if try_fill_type_prix_from_history(page, product_query):
        wait_for_idle(page)
        if wait_for_article_commit_settle(page, product_query, timeout_ms=6000):
            return True

    if try_fill_missing_price_semi_net(page, product_query):
        wait_for_idle(page)
        if wait_for_article_commit_settle(page, product_query, timeout_ms=6000):
            return True

    if select_principal_row_by_article(page, product_query):
        page.keyboard.press("Enter")
        page.wait_for_timeout(600)
        blur_grid_focus(page)
        if wait_for_article_commit_settle(page, product_query, timeout_ms=8000):
            return True
        if try_post_line_commit_gestures(page, product_query):
            return True

    buttons = describe_visible_table_toolbar_buttons(page)
    log(f"visible table toolbar buttons: {json.dumps(buttons, ensure_ascii=False)}")
    if len(buttons) <= 1:
        return False

    def toolbar_priority(button: dict) -> tuple[int, int]:
        tooltip = button.get("tooltip", "").strip().lower()
        if tooltip.startswith("ajouter"):
            return (0, button["y"])
        if tooltip.startswith("coller"):
            return (1, button["y"])
        if tooltip.startswith("déplacer") or tooltip.startswith("deplacer"):
            return (2, button["y"])
        return (3, button["y"])

    likely_commit_buttons = [
        button
        for button in buttons
        if "inf-w-inactive" not in button.get("cls", "")
        and not button.get("tooltip", "").strip().lower().startswith("supprimer")
    ]
    likely_commit_buttons.sort(key=toolbar_priority)
    for button in likely_commit_buttons:
        log(f"try article commit button {button}")
        page.mouse.click(button["x"] + button["w"] / 2, button["y"] + button["h"] / 2)
        page.wait_for_timeout(1000)
        wait_for_idle(page)
        save_debug(page, f"article_commit_{button['id'] or button['y']}")
        if is_next_enabled(page):
            return True
        if has_article_count(page):
            if has_visible_table_editor(page):
                log(f"visible table editor detected after commit button {button['id'] or button['y']}")
                close_visible_table_editor(page)
                wait_for_idle(page)
            blur_grid_focus(page)
            try:
                wait_for_idle(page, timeout_ms=8000)
            except PlaywrightTimeoutError:
                pass
            save_debug(page, f"article_commit_blur_{button['id'] or button['y']}")
            log(f"visible tabs after commit button {button['id'] or button['y']}: {json.dumps(get_visible_tab_links(page), ensure_ascii=False)}")
            log(f"visible headers after commit button {button['id'] or button['y']}: {json.dumps(get_visible_headers(page), ensure_ascii=False)}")
            log(f"selected cells after commit button {button['id'] or button['y']}: {json.dumps(get_visible_selected_cells(page), ensure_ascii=False)}")
            if try_fill_type_prix_from_history(page, product_query):
                wait_for_idle(page)
                log(f"visible tabs after type prix fill {button['id'] or button['y']}: {json.dumps(get_visible_tab_links(page), ensure_ascii=False)}")
            if try_fill_missing_price_semi_net(page, product_query):
                wait_for_idle(page)
                log(f"visible tabs after price fill {button['id'] or button['y']}: {json.dumps(get_visible_tab_links(page), ensure_ascii=False)}")
            row = find_principal_row_by_article(page, product_query)
            if row:
                values = row["values"]
                semi_net = (values.get("Prix semi-net") or "").strip()
                remises = (values.get("Remises") or "").strip()
                qty = (values.get("Qté cdée") or "").strip()
                if qty and (semi_net or remises):
                    log(f"target row complete after commit button {button['id'] or button['y']}: {json.dumps(values, ensure_ascii=False)}")
                    select_principal_row_by_article(page, product_query)
                    blur_grid_focus(page)
                    if wait_for_article_commit_settle(page, product_query):
                        return True
            if wait_for_article_commit_settle(page, product_query, timeout_ms=6000):
                return True

    if len(buttons) > 1:
        button = likely_commit_buttons[0] if likely_commit_buttons else buttons[1]
        log(f"try primary secondary button {button}")
        page.mouse.click(button["x"] + button["w"] / 2, button["y"] + button["h"] / 2)
        page.wait_for_timeout(1000)
        wait_for_idle(page)
        save_debug(page, f"article_commit_{button['id'] or button['y']}")
        if is_next_enabled(page):
            return True
        if has_article_count(page):
            if has_visible_table_editor(page):
                log(f"visible table editor detected after commit button {button['id'] or button['y']}")
                close_visible_table_editor(page)
                wait_for_idle(page)
            blur_grid_focus(page)
            try:
                wait_for_idle(page, timeout_ms=8000)
            except PlaywrightTimeoutError:
                pass
            save_debug(page, f"article_commit_blur_{button['id'] or button['y']}")
            log(f"visible tabs after commit button {button['id'] or button['y']}: {json.dumps(get_visible_tab_links(page), ensure_ascii=False)}")
            log(f"visible headers after commit button {button['id'] or button['y']}: {json.dumps(get_visible_headers(page), ensure_ascii=False)}")
            log(f"selected cells after commit button {button['id'] or button['y']}: {json.dumps(get_visible_selected_cells(page), ensure_ascii=False)}")
            if try_fill_type_prix_from_history(page, product_query):
                wait_for_idle(page)
                log(f"visible tabs after type prix fill {button['id'] or button['y']}: {json.dumps(get_visible_tab_links(page), ensure_ascii=False)}")
            if try_fill_missing_price_semi_net(page, product_query):
                wait_for_idle(page)
                log(f"visible tabs after price fill {button['id'] or button['y']}: {json.dumps(get_visible_tab_links(page), ensure_ascii=False)}")
            row = find_principal_row_by_article(page, product_query)
            if row:
                values = row["values"]
                semi_net = (values.get("Prix semi-net") or "").strip()
                remises = (values.get("Remises") or "").strip()
                qty = (values.get("Qté cdée") or "").strip()
                if qty and (semi_net or remises):
                    log(f"target row complete after commit button {button['id'] or button['y']}: {json.dumps(values, ensure_ascii=False)}")
                    select_principal_row_by_article(page, product_query)
                    blur_grid_focus(page)
                    if wait_for_article_commit_settle(page, product_query):
                        return True
            if wait_for_article_commit_settle(page, product_query, timeout_ms=6000):
                return True

    return False


def select_dropdown_entry(page: Page, product_query: str) -> bool:
    rows = get_visible_dropdown_rows(page)
    if not rows:
        return False

    query_normalized = normalize_search_text(product_query)
    query_tokens = [token for token in re.split(r"[^0-9a-zA-Z]+", query_normalized) if token]

    def match_score(row: dict) -> tuple[int, int]:
        row_text = normalize_search_text(row["text"])
        if row_text == query_normalized:
            return (4, 0)
        if query_normalized and f"| {query_normalized} |" in f"| {row_text} |":
            return (3, 0)
        token_hits = sum(1 for token in query_tokens if token and token in row_text)
        if token_hits and token_hits == len(query_tokens):
            return (2, -token_hits)
        if query_normalized and query_normalized in row_text:
            return (1, 0)
        return (0, 0)

    matched_rows = []
    for row in rows:
        score = match_score(row)
        if score[0] > 0:
            matched_rows.append((score, row))

    if not matched_rows:
        return False

    matched_rows.sort(key=lambda item: (-item[0][0], item[0][1], item[1]["y"]))
    row = matched_rows[0][1]
    page.mouse.click(row["x"] + 12, row["y"] + row["h"] / 2)
    page.wait_for_timeout(800)
    return True


def enter_article_line(page: Page, product_query: str, quantity: str) -> str:
    assert_erp_write_allowed("Playwright: ajout ou modification d'une ligne article")
    wait_for_idle(page)
    headers = get_grid_headers(page)
    article = next((item for item in headers if item["text"] == "Article"), None)
    qty = next((item for item in headers if item["text"] in ("Qté cdée", "Qte cdée")), None)
    if not article or not qty:
        (DEBUG_DIR / "grid_headers.json").write_text(
            json.dumps(headers, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        save_debug(page, "missing_grid_headers")
        raise AutomationError("could not locate Article and quantity headers")

    selected_row = None
    if product_query == "AUTO_FIRST":
        selected_row = get_first_visible_reference_row(page)
        if selected_row:
            product_query = selected_row["text"]
            log(f"auto-selected first visible product {product_query}")
    else:
        selected_row = find_visible_reference_row(page, product_query)
    if not selected_row and has_visible_reference_rows(page):
        if click_main_table_add(page):
            wait_for_idle(page)
            save_debug(page, "article_add_clicked")
            if product_query == "AUTO_FIRST":
                selected_row = get_first_visible_reference_row(page)
                if selected_row:
                    product_query = selected_row["text"]
                    log(f"auto-selected first visible product {product_query}")
            else:
                selected_row = find_visible_reference_row(page, product_query)
    if selected_row:
        log(f"selected visible row {selected_row['text']}")
        page.mouse.click(selected_row["x"] + 12, selected_row["y"] + selected_row["h"] / 2)
        page.wait_for_timeout(500)
    else:
        log(f"enter product query {product_query}")
        selected_row_y = get_selected_current_row_y(page)
        if selected_row_y is not None:
            click_grid_cell_at_row(page, article, selected_row_y)
        else:
            click_grid_cell(page, article)
        if has_visible_table_editor(page):
            if not fill_visible_table_editor(page, product_query):
                page.keyboard.type(product_query, delay=50)
        else:
            page.keyboard.type(product_query, delay=50)
        page.wait_for_timeout(1200)
        save_debug(page, "article_query_typed")
        inserted_row = find_visible_reference_row(page, product_query)
        if inserted_row:
            log("article code applied directly in grid")
            selected_row = inserted_row
        elif select_dropdown_entry(page, product_query):
            log("selected product from dropdown")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1200)
            inserted_row = find_visible_reference_row(page, product_query)
            if inserted_row:
                selected_row = inserted_row
        else:
            page.keyboard.press("Enter")
            page.wait_for_timeout(1200)
            inserted_row = find_visible_reference_row(page, product_query)
            if inserted_row:
                log("article code accepted after Enter")
                selected_row = inserted_row

        if not selected_row:
            selected_row = get_selected_article_row(page)
            if selected_row:
                log(f"resolved article from selected row: {selected_row['text']}")

        if not selected_row:
            save_debug(page, "article_query_not_applied")
            raise AutomationError(f"could not apply product query {product_query}")

    resolved_article_code = selected_row["text"]
    log(f"enter quantity {quantity}")
    if selected_row:
        click_grid_cell_at_row(page, qty, selected_row["y"], selected_row["h"])
    else:
        click_grid_cell(page, qty)
    page.wait_for_timeout(400)
    if fill_visible_table_editor(page, quantity):
        log("filled quantity through visible table editor")
    else:
        page.keyboard.type(quantity, delay=50)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1200)
    if has_visible_table_editor(page):
        if selected_row and article:
            click_grid_cell_at_row(page, article, selected_row["y"], selected_row["h"])
            page.wait_for_timeout(400)
        close_visible_table_editor(page)
        page.wait_for_timeout(400)

    wait_for_idle(page)
    ready_row = wait_for_article_row_ready(page, resolved_article_code)
    if ready_row:
        select_principal_row_by_article(page, resolved_article_code)
        blur_grid_focus(page)
        page.wait_for_timeout(400)

    next_button = page.locator("button.custom-id-multipage_tabs_button-next").first
    if next_button.count() and not next_button.is_enabled():
        attempt_article_commit(page, resolved_article_code)
    return resolved_article_code


def save_order(page: Page, article_code: str) -> None:
    assert_erp_write_allowed("Playwright: clic Enregistrer sur une commande")
    visible_tabs = get_visible_tab_links(page)
    log(f"visible tabs before save: {json.dumps(visible_tabs, ensure_ascii=False)}")

    if has_article_count(page, "1 article"):
        wait_for_article_commit_settle(page, article_code, timeout_ms=15000)
        if select_principal_row_by_article(page, article_code):
            blur_grid_focus(page)
            wait_for_article_commit_settle(page, article_code, timeout_ms=6000)

    if is_visible_tab_selectable(page, "Récapitulatif") and click_visible_tab_link(page, "Récapitulatif"):
        page.wait_for_timeout(2000)
        wait_for_idle(page)
        save_debug(page, "recap_tab_clicked")

    save_button = page.get_by_role("button", name="Enregistrer")
    if not save_button.count():
        save_debug(page, "missing_save_button")
        raise AutomationError("Enregistrer button not found")
    if not save_button.first.is_enabled() and not has_article_count(page, "1 article"):
        click_toolbar_next(page, "before_save")
        page.wait_for_timeout(2000)
        accept_confirmation_dialog(page)
    if not save_button.first.is_enabled():
        body_text = page.locator("body").inner_text()
        if "1 article" in body_text:
            wait_for_article_commit_settle(page, article_code, timeout_ms=12000)
            if is_visible_tab_selectable(page, "Récapitulatif"):
                click_visible_tab_link(page, "Récapitulatif")
                page.wait_for_timeout(1500)
                wait_for_idle(page)
            accept_confirmation_dialog(page)
            refreshed_save_button = page.get_by_role("button", name="Enregistrer")
            if refreshed_save_button.count() and refreshed_save_button.first.is_enabled():
                refreshed_save_button.first.click()
            else:
                save_debug(page, "disabled_save_button")
                raise AutomationError("Enregistrer button is disabled even with 1 article")
            page.wait_for_timeout(3000)
            accept_confirmation_dialog(page)
            save_debug(page, "forced_save_attempt")
            updated_text = page.locator("body").inner_text()
            if "valeur non autorisée" in updated_text.lower() or "valeur invalide" in updated_text.lower():
                raise AutomationError("Copilote reported invalid / unauthorized value")
            return
        save_debug(page, "disabled_save_button")
        raise AutomationError("Enregistrer button is disabled")
    save_button.first.click()
    page.wait_for_timeout(4000)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a sales order in Copilote.")
    parser.add_argument("--mode", choices=["create-order", "inspect-vtrcom"], default="create-order")
    parser.add_argument("--base-url", default="http://172.16.213.101:8080/ventes/")
    parser.add_argument("--app-url", default="http://172.16.213.101:8080/ventes/app/")
    parser.add_argument("--user", default="ET")
    parser.add_argument("--password", default="j48y2p")
    parser.add_argument("--dossier", default="04")
    parser.add_argument("--client", default="AFFRANCHILAB")
    parser.add_argument("--date-commande", default="30/09/2026")
    parser.add_argument("--date-depart", default="30/09/2026")
    parser.add_argument("--date-livraison", default="30/09/2026")
    parser.add_argument("--heure-depart", default="0800")
    parser.add_argument("--product-query", default="00210820")
    parser.add_argument("--quantity", default="10")
    parser.add_argument("--verify-term", action="append", default=[])
    parser.add_argument("--filter-client-livre", default="")
    parser.add_argument("--filter-date-depart", default="")
    parser.add_argument("--browser-executable", default="")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--show-browser", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "create-order":
        assert_erp_write_allowed("automatisation Playwright: creation de commande")
    ensure_debug_dir()
    started = time.time()
    headless = not args.show_browser

    try:
        with sync_playwright() as playwright:
            browser_executable = resolve_browser_executable(args.browser_executable)
            launch_options = {"headless": headless}
            if browser_executable:
                launch_options["executable_path"] = browser_executable
            browser = playwright.chromium.launch(**launch_options)
            page = browser.new_page(viewport={"width": 1600, "height": 1200})
            page.set_default_timeout(60000)

            login(page, args.app_url, args.user, args.password, args.dossier)
            if args.mode == "inspect-vtrcom":
                open_vtrcom(page, args.base_url)
                if args.filter_client_livre or args.filter_date_depart:
                    set_vtrcom_filters(page, args.filter_client_livre, args.filter_date_depart)
                launch_vtrcom_search(page)
                matched = inspect_page_for_terms(page, args.verify_term)
                log(f"inspect result: {'MATCH' if matched else 'NO_MATCH'}")
            else:
                open_commande_search(page, args.base_url)
                create_order_for_client(page, args.client)
                save_debug(page, "order_form_loaded")

                transport_value = fill_general_information(
                    page,
                    date_commande=args.date_commande,
                    date_depart=args.date_depart,
                    date_livraison=args.date_livraison,
                    heure_depart=args.heure_depart,
                )
                save_debug(page, "general_information_filled")

                open_articles_step(page, args.heure_depart, transport_value)
                save_debug(page, "article_step_loaded")

                article_code = enter_article_line(page, args.product_query, args.quantity)
                save_debug(page, "article_line_entered")

                save_order(page, article_code)
                save_debug(page, "order_after_save")

                final_text = page.locator("body").inner_text()
                log("save completed")
                log(final_text[:1200])
            browser.close()
    except PlaywrightTimeoutError as exc:
        log(f"timeout: {exc}")
        return 1
    except AutomationError as exc:
        log(f"automation error: {exc}")
        return 1
    except Exception as exc:  # pragma: no cover - defensive for first runs
        log(f"unexpected error: {exc}")
        return 1

    log(f"done in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
