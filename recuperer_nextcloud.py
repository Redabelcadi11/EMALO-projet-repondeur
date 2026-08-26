from __future__ import annotations

import argparse
import base64
import getpass
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from src.runtime_paths import bootstrap_runtime_environment, get_project_root


bootstrap_runtime_environment()


AUDIO_EXTENSIONS = {
    ".ogg",
    ".mp3",
    ".wav",
    ".m4a",
    ".webm",
    ".flac",
    ".mp4",
    ".mpeg",
    ".mpga",
}

DEFAULT_TARGET_DIR = (
    get_project_root() / "ressources-originales" / "audio-nextcloud"
)
DEFAULT_MANIFEST_PATH = (
    get_project_root() / "cache" / "nextcloud-sync-manifest.json"
)
DEFAULT_SETTINGS_PATH = get_project_root() / "config" / "nextcloud.json"


@dataclass(frozen=True)
class RemoteItem:
    href: str
    relative_path: str
    is_collection: bool
    etag: str
    last_modified: str
    size: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recupere les commandes vocales depuis Nextcloud via WebDAV."
    )
    parser.add_argument(
        "--url",
        default="https://openvoice-new.basco-restauration.fr:4443",
        help="URL racine Nextcloud.",
    )
    parser.add_argument(
        "--username",
        default="",
        help="Utilisateur Nextcloud. Peut aussi venir de NEXTCLOUD_USERNAME.",
    )
    parser.add_argument(
        "--password",
        default="",
        help="Mot de passe ou app-password. Peut aussi venir de NEXTCLOUD_PASSWORD.",
    )
    parser.add_argument(
        "--remote-path",
        default="",
        help="Dossier distant a synchroniser, relatif a l'utilisateur WebDAV.",
    )
    parser.add_argument(
        "--target-dir",
        default=str(DEFAULT_TARGET_DIR),
        help="Dossier local de depot des audios.",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Fichier local de suivi des fichiers deja telecharges.",
    )
    parser.add_argument(
        "--settings",
        default=str(DEFAULT_SETTINGS_PATH),
        help="Fichier JSON de configuration Nextcloud.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Accepte un certificat TLS non valide.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Liste les fichiers a recuperer sans les telecharger.",
    )
    return parser.parse_args(argv)


def getenv_default(name: str, current_value: str) -> str:
    if current_value:
        return current_value
    import os

    return os.environ.get(name, "")


def load_settings(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def resolve_setting(
    current_value: str,
    env_name: str,
    settings: dict[str, object],
    settings_key: str,
) -> str:
    if current_value:
        return current_value
    import os

    env_value = os.environ.get(env_name, "")
    if env_value:
        return env_value
    value = settings.get(settings_key, "")
    return str(value or "")


def make_ssl_context(insecure: bool) -> ssl.SSLContext | None:
    if not insecure:
        return None
    return ssl._create_unverified_context()


def auth_header(username: str, password: str) -> str:
    token = f"{username}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(token).decode("ascii")


def quote_path(path: str) -> str:
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    return "/".join(urllib.parse.quote(part) for part in parts)


def webdav_root(base_url: str, username: str, remote_path: str) -> str:
    base = base_url.rstrip("/")
    user = urllib.parse.quote(username)
    remote = quote_path(remote_path)
    url = f"{base}/remote.php/dav/files/{user}/"
    if remote:
        url += remote + "/"
    return url


def request_bytes(
    method: str,
    url: str,
    username: str,
    password: str,
    ssl_context: ssl.SSLContext | None,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> bytes:
    request_headers = {
        "Authorization": auth_header(username, password),
        "User-Agent": "ProjetRepondeur-NextcloudSync/1.0",
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=60,
            context=ssl_context,
        ) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(
            f"Nextcloud HTTP {exc.code} sur {method} {url}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Connexion Nextcloud impossible: {exc.reason}") from exc


def propfind(
    url: str,
    username: str,
    password: str,
    ssl_context: ssl.SSLContext | None,
) -> list[RemoteItem]:
    body = b"""<?xml version="1.0" encoding="utf-8" ?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:resourcetype/>
    <d:getetag/>
    <d:getlastmodified/>
    <d:getcontentlength/>
  </d:prop>
</d:propfind>
"""
    raw = request_bytes(
        "PROPFIND",
        url,
        username,
        password,
        ssl_context,
        body=body,
        headers={
            "Depth": "1",
            "Content-Type": "application/xml; charset=utf-8",
        },
    )
    root = ET.fromstring(raw)
    ns = {"d": "DAV:"}
    base_path = urllib.parse.urlparse(url).path.rstrip("/") + "/"
    items: list[RemoteItem] = []
    for response in root.findall("d:response", ns):
        href = response.findtext("d:href", default="", namespaces=ns)
        if not href:
            continue
        href_path = urllib.parse.unquote(urllib.parse.urlparse(href).path)
        if href_path.rstrip("/") == base_path.rstrip("/"):
            continue

        propstat = response.find("d:propstat", ns)
        prop = propstat.find("d:prop", ns) if propstat is not None else None
        if prop is None:
            continue

        resourcetype = prop.find("d:resourcetype", ns)
        is_collection = (
            resourcetype is not None
            and resourcetype.find("d:collection", ns) is not None
        )
        etag = prop.findtext("d:getetag", default="", namespaces=ns).strip('"')
        last_modified = prop.findtext(
            "d:getlastmodified", default="", namespaces=ns
        )
        size_text = prop.findtext("d:getcontentlength", default="0", namespaces=ns)
        try:
            size = int(size_text or "0")
        except ValueError:
            size = 0

        relative = href_path
        if relative.startswith(base_path):
            relative = relative[len(base_path) :]
        relative = relative.strip("/")
        items.append(
            RemoteItem(
                href=urllib.parse.urljoin(url, urllib.parse.quote(relative)),
                relative_path=relative,
                is_collection=is_collection,
                etag=etag,
                last_modified=last_modified,
                size=size,
            )
        )
    return items


def iter_remote_files(
    root_url: str,
    username: str,
    password: str,
    ssl_context: ssl.SSLContext | None,
) -> list[RemoteItem]:
    result: list[RemoteItem] = []
    stack = [root_url]
    seen_dirs = set()
    while stack:
        current_url = stack.pop()
        if current_url in seen_dirs:
            continue
        seen_dirs.add(current_url)
        for item in propfind(current_url, username, password, ssl_context):
            if item.is_collection:
                stack.append(current_url.rstrip("/") + "/" + quote_path(item.relative_path) + "/")
                continue
            if Path(item.relative_path).suffix.lower() in AUDIO_EXTENSIONS:
                result.append(item)
    return sorted(result, key=lambda item: item.relative_path.lower())


def load_manifest(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_manifest(path: Path, manifest: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def local_path_for(target_dir: Path, remote_path: str) -> Path:
    clean = Path(remote_path.replace("\\", "/"))
    parts = [part for part in clean.parts if part not in {"", ".", ".."}]
    return target_dir.joinpath(*parts)


def should_download(item: RemoteItem, manifest: dict[str, dict[str, object]]) -> bool:
    previous = manifest.get(item.relative_path)
    if previous is None:
        return True
    return (
        previous.get("etag") != item.etag
        or previous.get("size") != item.size
        or previous.get("last_modified") != item.last_modified
    )


def download_item(
    item: RemoteItem,
    target_dir: Path,
    username: str,
    password: str,
    ssl_context: ssl.SSLContext | None,
) -> Path:
    target = local_path_for(target_dir, item.relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = request_bytes("GET", item.href, username, password, ssl_context)
    target.write_bytes(content)
    return target


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = load_settings(Path(args.settings))
    args.url = resolve_setting(args.url, "NEXTCLOUD_URL", settings, "url")
    args.username = resolve_setting(
        args.username, "NEXTCLOUD_USERNAME", settings, "username"
    )
    args.password = resolve_setting(
        args.password, "NEXTCLOUD_PASSWORD", settings, "password"
    )
    args.remote_path = resolve_setting(
        args.remote_path, "NEXTCLOUD_REMOTE_PATH", settings, "remote_path"
    )
    if not args.insecure and bool(settings.get("insecure")):
        args.insecure = True
    if not args.username:
        print("Utilisateur Nextcloud manquant.", file=sys.stderr)
        print(
            "Utilise --username, NEXTCLOUD_USERNAME ou config/nextcloud.json.",
            file=sys.stderr,
        )
        return 2
    if not args.password:
        args.password = getpass.getpass("Mot de passe Nextcloud: ")

    target_dir = Path(args.target_dir)
    manifest_path = Path(args.manifest)
    ssl_context = make_ssl_context(args.insecure)
    root_url = webdav_root(args.url, args.username, args.remote_path)

    print(f"Nextcloud: {args.url.rstrip('/')}")
    print(f"Dossier distant: /{args.remote_path.strip('/')}")
    print(f"Dossier local: {target_dir}")
    print("Inventaire distant...")

    manifest = load_manifest(manifest_path)
    remote_files = iter_remote_files(root_url, args.username, args.password, ssl_context)
    candidates = [
        item for item in remote_files if should_download(item, manifest)
    ]

    print(f"Audios distants: {len(remote_files)}")
    print(f"Nouveaux/modifies: {len(candidates)}")
    if args.dry_run:
        for item in candidates:
            print(f"DRY-RUN {item.relative_path} ({item.size} octets)")
        return 0

    downloaded = 0
    for item in candidates:
        target = download_item(
            item,
            target_dir,
            args.username,
            args.password,
            ssl_context,
        )
        manifest[item.relative_path] = {
            "etag": item.etag,
            "last_modified": item.last_modified,
            "size": item.size,
            "local_path": str(target),
        }
        downloaded += 1
        print(f"OK {item.relative_path} -> {target}")

    save_manifest(manifest_path, manifest)
    print(f"Telechargements termines: {downloaded}")
    print(f"Manifeste: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
