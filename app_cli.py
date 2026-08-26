from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from src.runtime_paths import (
    bootstrap_runtime_environment,
    get_project_root,
)


def _print_help() -> None:
    print(
        "Usage: ProjetRepondeur.exe <commande> [options]\n"
        "\n"
        "Commandes:\n"
        "  ui                Lance l'interface du repondeur\n"
        "  ui-prod           Lance l'interface production Nextcloud\n"
        "  ui-python         Lance l'ancienne interface Python de secours\n"
        "  nextcloud-sync    Recupere les audios du repondeur depuis Nextcloud\n"
        "  pipeline          Lance le pipeline vocal principal\n"
        "  copilote-order    Lance l'automatisation Copilote\n"
        "  install-runtime   Installe le runtime navigateur Playwright\n"
        "  doctor            Vérifie l'installation locale\n"
    )


def _has_bundled_playwright_runtime(project_root: Path) -> bool:
    runtime_root = project_root / "ms-playwright"
    return runtime_root.exists() and any(runtime_root.iterdir())


def _run_playwright_install(*browser_names: str) -> int:
    import playwright.__main__

    original_argv = sys.argv[:]
    try:
        sys.argv = ["playwright", "install", *browser_names]
        try:
            playwright.__main__.main()
        except SystemExit as exc:
            return int(exc.code or 0)
        return 0
    finally:
        sys.argv = original_argv


def _cmd_install_runtime(argv: list[str]) -> int:
    _ = argv
    bootstrap_runtime_environment()
    print("Installation runtime Playwright : chromium")
    exit_code = _run_playwright_install("chromium")
    if exit_code != 0:
        return exit_code
    print("Runtime Playwright installé.")
    return 0


def _cmd_doctor(argv: list[str]) -> int:
    _ = argv
    project_root = bootstrap_runtime_environment()
    ffmpeg_path = shutil.which("ffmpeg")
    playwright_path = Path(project_root / "ms-playwright")
    print(f"Project root: {project_root}")
    print(f"ffmpeg: {ffmpeg_path or 'NOT_FOUND'}")
    print(f"playwright cache: {playwright_path}")
    print(f"playwright cache exists: {playwright_path.exists()}")
    print(
        "playwright bundled runtime: "
        f"{_has_bundled_playwright_runtime(project_root)}"
    )
    print(f"config exists: {(project_root / 'config').exists()}")
    print(
        "ressources-originales exists: "
        f"{(project_root / 'ressources-originales').exists()}"
    )
    return 0


def _run_interactive_menu() -> int:
    actions = {
        "1": ("Verifier l'installation", lambda: _cmd_doctor([])),
        "2": ("Lancer l'interface", lambda: _cmd_ui([])),
        "3": ("Installer / reparer le runtime navigateur", lambda: _cmd_install_runtime([])),
        "4": ("Afficher l'aide Nextcloud", lambda: _cmd_nextcloud_sync(["--help"])),
        "5": ("Afficher l'aide du pipeline", lambda: _cmd_pipeline(["--help"])),
        "6": ("Afficher l'aide Copilote", lambda: _cmd_copilote_order(["--help"])),
        "7": ("Quitter", lambda: 0),
    }
    while True:
        print("")
        print("Projet Repondeur")
        print("================")
        for key, (label, _) in actions.items():
            print(f"{key}. {label}")
        choice = input("\nChoix : ").strip()
        action = actions.get(choice)
        if action is None:
            print("Choix invalide.")
            continue
        label, handler = action
        print("")
        print(f"> {label}")
        result = handler()
        if choice == "7":
            return result
        print("")
        input("Appuyez sur Entrée pour revenir au menu...")


def _cmd_pipeline(argv: list[str]) -> int:
    bootstrap_runtime_environment()
    from lancer_pipeline import main as pipeline_main

    try:
        return int(pipeline_main(argv) or 0)
    except SystemExit as exc:
        return int(exc.code or 0)


def _cmd_nextcloud_sync(argv: list[str]) -> int:
    bootstrap_runtime_environment()
    from recuperer_nextcloud import main as nextcloud_main

    try:
        return int(nextcloud_main(argv) or 0)
    except SystemExit as exc:
        return int(exc.code or 0)


def _cmd_ui_python(argv: list[str]) -> int:
    _ = argv
    bootstrap_runtime_environment()
    from ui_repondeur import main as ui_main

    ui_main()
    return 0


def _cmd_ui(argv: list[str]) -> int:
    _ = argv
    import os

    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    node_dir = Path(r"C:\Program Files\nodejs")
    if node_dir.exists() and str(node_dir) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(node_dir) + os.pathsep + os.environ.get("PATH", "")
    project_root = bootstrap_runtime_environment()
    from generer_ui_data import main as generate_ui_data

    generate_ui_data()
    app_dir = project_root / "app-desktop"
    if not (app_dir / "node_modules" / "electron").exists():
        print("Dependances Electron absentes. Lancez: cd app-desktop ; npm install")
        return 1
    npm_cmd = shutil.which("npm") or str(node_dir / "npm.cmd")
    return subprocess.call([npm_cmd, "start"], cwd=str(app_dir))


def _cmd_ui_prod(argv: list[str]) -> int:
    _ = argv
    import os

    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    os.environ["REPONDEUR_UI_MODE"] = "prod"
    node_dir = Path(r"C:\Program Files\nodejs")
    if node_dir.exists() and str(node_dir) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(node_dir) + os.pathsep + os.environ.get("PATH", "")
    project_root = bootstrap_runtime_environment()
    os.environ["REPONDEUR_UI_DATA_PATH"] = str(
        project_root / "cache" / "ui" / "repondeur-data-prod.json"
    )
    from generer_ui_data_prod import main as generate_prod_ui_data

    generate_prod_ui_data()
    app_dir = project_root / "app-desktop"
    if not (app_dir / "node_modules" / "electron").exists():
        print("Dependances Electron absentes. Lancez: cd app-desktop ; npm install")
        return 1
    npm_cmd = shutil.which("npm") or str(node_dir / "npm.cmd")
    return subprocess.call([npm_cmd, "start"], cwd=str(app_dir))


def _cmd_copilote_order(argv: list[str]) -> int:
    bootstrap_runtime_environment()
    from scripts.copilote_order import main as copilote_main

    try:
        return int(copilote_main(argv) or 0)
    except SystemExit as exc:
        return int(exc.code or 0)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        if sys.stdin.isatty() and sys.stdout.isatty():
            return _run_interactive_menu()
        _print_help()
        return 0
    if argv[0] in {"-h", "--help", "help"}:
        _print_help()
        return 0

    command = argv[0]
    command_argv = argv[1:]
    handlers = {
        "ui": _cmd_ui,
        "ui-electron": _cmd_ui,
        "ui-prod": _cmd_ui_prod,
        "ui-python": _cmd_ui_python,
        "nextcloud-sync": _cmd_nextcloud_sync,
        "pipeline": _cmd_pipeline,
        "copilote-order": _cmd_copilote_order,
        "install-runtime": _cmd_install_runtime,
        "doctor": _cmd_doctor,
    }
    handler = handlers.get(command)
    if handler is None:
        print(f"Commande inconnue: {command}", file=sys.stderr)
        _print_help()
        return 2
    return handler(command_argv)


if __name__ == "__main__":
    raise SystemExit(main())

