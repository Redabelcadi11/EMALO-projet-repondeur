from __future__ import annotations

import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PORTAL_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PORTAL_ROOT / "portal_config.json"


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_html(handler: BaseHTTPRequestHandler) -> None:
    html = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EMALO</title>
  <style>
    :root{color-scheme:light;--night:#1f2329;--ink:#111827;--stone:#f6f3ee;--line:#e7e2da;--theme:#059669;--soft:rgba(5,150,105,.12)}
    *{box-sizing:border-box} body{margin:0;min-height:100vh;background:var(--stone);font-family:Inter,"Segoe UI",system-ui,sans-serif;color:var(--ink)}
    .page{min-height:100vh;display:grid;grid-template-columns:1.08fr .92fr}
    .hero{position:relative;overflow:hidden;background:#fff;padding:4rem;display:flex;align-items:center}
    .hero:before{content:"";position:absolute;width:20rem;height:20rem;left:-8rem;top:-8rem;border-radius:999px;background:rgba(209,250,229,.72);filter:blur(22px)}
    .hero:after{content:"";position:absolute;width:18rem;height:18rem;right:1.5rem;bottom:3rem;border-radius:999px;background:rgba(246,243,238,.95);filter:blur(18px)}
    .content{position:relative;max-width:31rem}.mark{display:grid;place-items:center;width:4rem;height:4rem;border-radius:1.15rem;background:var(--theme);color:#fff;font-size:1.35rem;font-weight:950}
    h1,p{margin:0} h1{margin-top:1.45rem;font-size:2.5rem;line-height:1.04;font-weight:950;letter-spacing:0}.muted{margin-top:1rem;line-height:1.7;color:rgba(17,24,39,.56);font-weight:650}
    .side{display:grid;place-items:center;padding:2rem}.card{width:min(100%,440px);background:#fff;border:1px solid var(--line);border-radius:1.5rem;padding:2rem;box-shadow:0 18px 50px rgba(31,35,41,.08)}
    .eyebrow{font-size:.82rem;font-weight:950;color:var(--theme);text-transform:uppercase;letter-spacing:.12em}.title{margin-top:.75rem;font-size:2rem;font-weight:950}
    button{width:100%;height:5.75rem;border:0;border-radius:1rem;color:#fff;font:inherit;font-weight:950;cursor:pointer;margin-top:1rem;transition:.16s ease}
    button small{display:block;font-size:.78rem;font-weight:750;opacity:.76;margin-top:.3rem}.achats{background:var(--night)}.repondeur{background:var(--theme)}button:hover{filter:brightness(.94)}
    .msg{margin-top:1rem;padding:.75rem;border-radius:1rem;background:#fff1f2;color:#b42318;font-weight:800;display:none}
    @media(max-width:900px){.page{grid-template-columns:1fr}.hero{min-height:42vh;padding:2rem}}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero"><div class="content"><div class="mark">EM</div><h1>Portail EMALO</h1><p class="muted">Choisis l'espace de travail a ouvrir. Chaque application reste lancee par son propre moteur.</p></div></section>
    <section class="side"><div class="card"><div class="eyebrow">Ouvrir</div><div class="title">Selection de l'application</div>
      <button class="achats" data-app="achats">Achats<small>Application achats actuelle</small></button>
      <button class="repondeur" data-app="repondeur">Repondeur<small>Commandes vocales clients</small></button>
      <div id="msg" class="msg"></div>
    </div></section>
  </main>
  <script>
    const msg=document.getElementById('msg');
    document.addEventListener('click', async (event)=>{
      const button=event.target.closest('button[data-app]');
      if(!button) return;
      msg.style.display='none';
      try{
        const res=await fetch('/api/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({app:button.dataset.app})});
        const payload=await res.json();
        if(!payload.ok){throw new Error(payload.message || 'Ouverture impossible');}
      }catch(error){
        msg.textContent=error.message || String(error);
        msg.style.display='block';
      }
    });
  </script>
</body>
</html>"""
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def launch_app(app_name: str) -> None:
    config = load_config()
    powershell = str(config.get("powershell") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    if app_name == "achats":
        script = str(config.get("achats_script") or "")
        root = str(config.get("achats_project_root") or "")
        if not script or not Path(script).exists():
            raise FileNotFoundError(f"Script Achats introuvable: {script}")
        subprocess.Popen(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-ProjectRoot", root],
            cwd=root or None,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return
    if app_name == "repondeur":
        script = str(config.get("repondeur_script") or "")
        root = str(config.get("repondeur_project_root") or "")
        if not script or not Path(script).exists():
            raise FileNotFoundError(f"Script Repondeur introuvable: {script}")
        subprocess.Popen(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-ProjectRoot", root],
            cwd=root or None,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return
    raise ValueError("Application inconnue")


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "EMALOPortal/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if urlparse(self.path).path in {"", "/", "/index.html"}:
            send_html(self)
            return
        send_json(self, 404, {"ok": False, "message": "Endpoint inconnu"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/open":
            send_json(self, 404, {"ok": False, "message": "Endpoint inconnu"})
            return
        try:
            payload = read_body(self)
            launch_app(str(payload.get("app") or ""))
            send_json(self, 200, {"ok": True})
        except Exception as exc:
            send_json(self, 500, {"ok": False, "message": str(exc)})


def main() -> int:
    port = int((load_config().get("port") if load_config() else None) or 8764)
    server = ThreadingHTTPServer(("127.0.0.1", port), PortalHandler)
    print(f"Portail EMALO ecoute sur http://127.0.0.1:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
