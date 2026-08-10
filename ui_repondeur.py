from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import threading
import time
import tkinter as tk
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from src.runtime_paths import bootstrap_runtime_environment, get_project_root

import copilote_integration as copilote


bootstrap_runtime_environment()

PROJECT_ROOT = get_project_root()
CONFIG_DIR = PROJECT_ROOT / "config"
USERS_PATH = CONFIG_DIR / "users-ui.json"
NEXTCLOUD_AUDIO_DIR = PROJECT_ROOT / "ressources-originales" / "audio-nextcloud"
VALIDATED_CSV = PROJECT_ROOT / "resultats" / "commandes-validees" / "commandes_validees.csv"
PROBLEM_CSV = PROJECT_ROOT / "resultats" / "commandes-problematiques" / "commandes_problematiques.csv"

BG = "#F6F3EE"
PANEL = "#FFFCF8"
NIGHT = "#1F2329"
NIGHT_SOFT = "#2A3038"
INK = "#111827"
LINE = "#E7E2DA"
EMERALD = "#059669"
DANGER = "#B91C1C"
WARN = "#D97706"


def password_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def ensure_users() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if USERS_PATH.exists():
        return
    bootstrap_password = os.environ.get("REPONDEUR_BOOTSTRAP_PASSWORD", "").strip()
    if not bootstrap_password:
        raise RuntimeError("REPONDEUR_BOOTSTRAP_PASSWORD doit etre defini pour initialiser les comptes.")
    USERS_PATH.write_text(
        json.dumps(
            {
                "admin": {
                    "password_hash": password_hash(bootstrap_password),
                    "role": "ADMIN",
                    "active": True,
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def load_users() -> dict:
    ensure_users()
    return json.loads(USERS_PATH.read_text(encoding="utf-8"))


def save_users(users: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    USERS_PATH.write_text(json.dumps(users, indent=2), encoding="utf-8")


def normalize_status(value: str) -> str:
    return (value or "").strip().upper()


def read_semicolon_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def group_csv_orders(rows: list[dict[str, str]]) -> dict[str, list[tuple[int, dict[str, str]]]]:
    grouped: dict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for index, row in enumerate(rows):
        ref = (row.get("order_ref") or "").strip()
        if ref:
            grouped[ref].append((index, row))
    return dict(grouped)


def order_summary(order_ref: str, indexed_rows: list[tuple[int, dict[str, str]]]) -> dict[str, str]:
    rows = [row for _, row in indexed_rows]
    statuses = sorted({normalize_status(row.get("statut", "")) for row in rows})
    client_codes = sorted({(row.get("client_code") or "").strip() for row in rows if row.get("client_code")})
    clients = sorted({(row.get("client") or "").strip() for row in rows if row.get("client")})
    dates = sorted({(row.get("date_livraison") or "").strip() for row in rows if row.get("date_livraison")})
    products = len(rows)
    qty = 0.0
    for row in rows:
        try:
            qty += float((row.get("quantity") or "0").replace(",", "."))
        except ValueError:
            pass
    return {
        "order_ref": order_ref,
        "client": clients[0] if clients else "",
        "client_code": client_codes[0] if client_codes else "",
        "date_livraison": dates[0] if dates else "",
        "products": str(products),
        "quantity": f"{qty:g}",
        "statut": ", ".join(statuses),
        "numero": ", ".join(sorted({row.get("copilote_numero", "") for row in rows if row.get("copilote_numero")})),
        "message": next((row.get("message", "") for row in rows if row.get("message")), ""),
    }


class OrderEditor(tk.Toplevel):
    def __init__(self, parent: "RepondeurApp", order_ref: str, rows: list[dict[str, str]]):
        super().__init__(parent)
        self.parent = parent
        self.order_ref = order_ref
        self.rows = [dict(row) for row in rows]
        self.title(f"Detail commande {order_ref}")
        self.geometry("980x620")
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        container = ttk.Frame(self, style="Panel.TFrame", padding=18)
        container.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)
        first = self.rows[0] if self.rows else {}

        header = ttk.Frame(container, style="Panel.TFrame")
        header.pack(fill=tk.X)
        ttk.Label(header, text=f"Commande {self.order_ref}", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(header, text="Enregistrer", command=self.save).pack(side=tk.RIGHT)

        form = ttk.Frame(container, style="Panel.TFrame")
        form.pack(fill=tk.X, pady=(18, 12))
        self.client_var = tk.StringVar(value=first.get("client", ""))
        self.client_code_var = tk.StringVar(value=first.get("client_code", ""))
        self.date_var = tk.StringVar(value=first.get("date_livraison", ""))
        fields = [
            ("Client", self.client_var),
            ("Code client", self.client_code_var),
            ("Date livraison", self.date_var),
        ]
        for col, (label, var) in enumerate(fields):
            box = ttk.Frame(form, style="Panel.TFrame")
            box.grid(row=0, column=col, sticky="ew", padx=(0, 10))
            ttk.Label(box, text=label, style="Small.TLabel").pack(anchor=tk.W)
            ttk.Entry(box, textvariable=var).pack(fill=tk.X, pady=(4, 0))
            form.columnconfigure(col, weight=1)

        columns = ("product_code", "product_label", "quantity", "unit", "statut")
        self.product_tree = ttk.Treeview(container, columns=columns, show="headings", height=14)
        headings = {
            "product_code": "Code produit",
            "product_label": "Produit",
            "quantity": "Quantite",
            "unit": "Unite",
            "statut": "Statut",
        }
        for col in columns:
            self.product_tree.heading(col, text=headings[col])
            self.product_tree.column(col, width=120 if col != "product_label" else 420, anchor=tk.W)
        self.product_tree.pack(fill=tk.BOTH, expand=True)
        self.product_tree.bind("<Double-1>", self.edit_selected_product)
        self.refresh_products()

        actions = ttk.Frame(container, style="Panel.TFrame")
        actions.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(actions, text="Modifier ligne selectionnee", command=self.edit_selected_product).pack(side=tk.LEFT)
        ttk.Button(actions, text="Ajouter une ligne produit", command=self.add_product).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Supprimer ligne", command=self.delete_product).pack(side=tk.LEFT, padx=(8, 0))

    def refresh_products(self) -> None:
        self.product_tree.delete(*self.product_tree.get_children())
        for i, row in enumerate(self.rows):
            self.product_tree.insert(
                "",
                tk.END,
                iid=str(i),
                values=(
                    row.get("product_code", ""),
                    row.get("product_label", ""),
                    row.get("quantity", ""),
                    row.get("unit", ""),
                    row.get("statut", ""),
                ),
            )

    def selected_index(self) -> int | None:
        selected = self.product_tree.selection()
        if not selected:
            return None
        return int(selected[0])

    def edit_selected_product(self, _event=None) -> None:
        index = self.selected_index()
        if index is None:
            return
        self._product_form(index)

    def add_product(self) -> None:
        self.rows.append({
            "order_ref": self.order_ref,
            "dossier": "BASCO",
            "client": self.client_var.get(),
            "client_code": self.client_code_var.get(),
            "date_livraison": self.date_var.get(),
            "transport": "HENDAYE",
            "transport_code": "HENDAYE",
            "product_code": "",
            "product_label": "",
            "quantity": "1",
            "unit": "UB",
            "statut": "A_ENVOYE",
        })
        self.refresh_products()

    def delete_product(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        del self.rows[index]
        self.refresh_products()

    def _product_form(self, index: int) -> None:
        row = self.rows[index]
        dialog = tk.Toplevel(self)
        dialog.title("Modifier produit")
        dialog.geometry("560x360")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, style="Panel.TFrame", padding=16)
        frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        vars_by_key = {}
        for key, label in [
            ("product_code", "Code produit"),
            ("product_label", "Libelle"),
            ("quantity", "Quantite"),
            ("unit", "Unite"),
            ("statut", "Statut"),
        ]:
            ttk.Label(frame, text=label, style="Small.TLabel").pack(anchor=tk.W)
            var = tk.StringVar(value=row.get(key, ""))
            ttk.Entry(frame, textvariable=var).pack(fill=tk.X, pady=(3, 8))
            vars_by_key[key] = var

        def apply() -> None:
            for key, var in vars_by_key.items():
                row[key] = var.get()
            self.refresh_products()
            dialog.destroy()

        ttk.Button(frame, text="Valider", command=apply).pack(anchor=tk.E, pady=(8, 0))

    def save(self) -> None:
        existing_rows = copilote.load_csv()
        kept = [row for row in existing_rows if (row.get("order_ref") or "").strip() != self.order_ref]
        for row in self.rows:
            for col in copilote.ALL_COLUMNS:
                row.setdefault(col, "")
            row["order_ref"] = self.order_ref
            row["client"] = self.client_var.get()
            row["client_code"] = self.client_code_var.get()
            row["date_livraison"] = self.date_var.get()
            row["dossier"] = row.get("dossier") or "BASCO"
            row["transport"] = row.get("transport") or "HENDAYE"
            row["transport_code"] = row.get("transport_code") or "HENDAYE"
            row["statut"] = row.get("statut") or "A_ENVOYE"
            kept.append(row)
        copilote.save_csv(kept)
        self.parent.refresh_all()
        self.destroy()


class RepondeurApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Projet Repondeur - BASCO")
        self.geometry("1360x820")
        self.minsize(1120, 720)
        self.configure(bg=BG)
        self.current_user = ""
        self.current_menu = "dashboard"
        self.selected_orders: set[str] = set()
        self.rows: list[dict[str, str]] = []
        self._setup_style()
        self.show_login()

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Root.TFrame", background=BG)
        style.configure("Sidebar.TFrame", background=NIGHT)
        style.configure("Title.TLabel", background=PANEL, foreground=INK, font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", background=PANEL, foreground="#6B7280", font=("Segoe UI", 10))
        style.configure("Small.TLabel", background=PANEL, foreground="#6B7280", font=("Segoe UI", 8, "bold"))
        style.configure("Sidebar.TLabel", background=NIGHT, foreground="white", font=("Segoe UI", 13, "bold"))
        style.configure("SidebarSmall.TLabel", background=NIGHT, foreground="#B8C0CC", font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(12, 8))
        style.configure("Primary.TButton", background=NIGHT, foreground="white")
        style.configure("Treeview", rowheight=34, font=("Segoe UI", 9), background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background=NIGHT, foreground="white")

    def clear(self) -> None:
        for child in self.winfo_children():
            child.destroy()

    def show_login(self) -> None:
        self.clear()
        root = ttk.Frame(self, style="Root.TFrame")
        root.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(root, bg="white")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = ttk.Frame(root, style="Panel.TFrame", padding=36)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, ipadx=30)

        tk.Label(left, text="Projet Repondeur", bg="white", fg=INK, font=("Segoe UI", 34, "bold")).pack(anchor=tk.W, padx=70, pady=(90, 8))
        tk.Label(left, text="Nextcloud -> voix -> commande -> Copilote", bg="white", fg="#6B7280", font=("Segoe UI", 14)).pack(anchor=tk.W, padx=72)
        tk.Label(left, text="BASCO", bg=NIGHT, fg="white", font=("Segoe UI", 12, "bold"), padx=18, pady=8).pack(anchor=tk.W, padx=72, pady=38)

        ttk.Label(right, text="Connexion", style="Title.TLabel").pack(anchor=tk.W, pady=(90, 4))
        ttk.Label(right, text="Acces interne. Identifiant initial admin / admin.", style="Subtitle.TLabel").pack(anchor=tk.W, pady=(0, 24))
        self.login_user = tk.StringVar(value="admin")
        self.login_password = tk.StringVar(value="")
        ttk.Label(right, text="Utilisateur", style="Small.TLabel").pack(anchor=tk.W)
        ttk.Entry(right, textvariable=self.login_user).pack(fill=tk.X, pady=(4, 14))
        ttk.Label(right, text="Mot de passe", style="Small.TLabel").pack(anchor=tk.W)
        ttk.Entry(right, textvariable=self.login_password, show="*").pack(fill=tk.X, pady=(4, 18))
        self.login_error = ttk.Label(right, text="", style="Subtitle.TLabel")
        self.login_error.pack(anchor=tk.W, pady=(0, 10))
        ttk.Button(right, text="Se connecter", style="Primary.TButton", command=self.login).pack(fill=tk.X)
        self.bind("<Return>", lambda _e: self.login())

    def login(self) -> None:
        users = load_users()
        username = self.login_user.get().strip()
        password = self.login_password.get()
        user = users.get(username)
        if not user or not user.get("active") or user.get("password_hash") != password_hash(password):
            self.login_error.configure(text="Identifiants incorrects.")
            return
        self.current_user = username
        self.show_app()

    def show_app(self) -> None:
        self.clear()
        shell = ttk.Frame(self, style="Root.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)
        sidebar = ttk.Frame(shell, style="Sidebar.TFrame", width=260, padding=18)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        content = ttk.Frame(shell, style="Root.TFrame", padding=18)
        content.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self.content = content

        ttk.Label(sidebar, text="Projet Repondeur", style="Sidebar.TLabel").pack(anchor=tk.W, pady=(4, 2))
        ttk.Label(sidebar, text=f"Connecte: {self.current_user}", style="SidebarSmall.TLabel").pack(anchor=tk.W, pady=(0, 18))
        self.menu_buttons = {}
        for key, label in [
            ("dashboard", "Tableau de bord"),
            ("problematic", "Commandes problematiques"),
            ("password", "Mon mot de passe"),
            ("guide", "Guide utilisateur"),
            ("support", "Support"),
        ]:
            btn = tk.Button(
                sidebar,
                text=label,
                anchor="w",
                bg="white" if key == self.current_menu else NIGHT,
                fg=NIGHT if key == self.current_menu else "#D1D5DB",
                activebackground="white",
                activeforeground=NIGHT,
                relief="flat",
                padx=14,
                pady=12,
                font=("Segoe UI", 10, "bold"),
                command=lambda k=key: self.switch_menu(k),
            )
            btn.pack(fill=tk.X, pady=3)
            self.menu_buttons[key] = btn
        tk.Button(
            sidebar,
            text="Deconnexion",
            anchor="w",
            bg=NIGHT_SOFT,
            fg="white",
            relief="flat",
            padx=14,
            pady=12,
            font=("Segoe UI", 10, "bold"),
            command=self.show_login,
        ).pack(side=tk.BOTTOM, fill=tk.X, pady=(18, 0))

        self.render_current()

    def switch_menu(self, key: str) -> None:
        self.current_menu = key
        for menu_key, btn in self.menu_buttons.items():
            btn.configure(bg="white" if menu_key == key else NIGHT, fg=NIGHT if menu_key == key else "#D1D5DB")
        self.render_current()

    def clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def render_current(self) -> None:
        self.clear_content()
        if self.current_menu == "dashboard":
            self.render_dashboard()
        elif self.current_menu == "problematic":
            self.render_problematic()
        elif self.current_menu == "password":
            self.render_password()
        elif self.current_menu == "guide":
            self.render_guide()
        elif self.current_menu == "support":
            self.render_support()

    def card(self, parent, title: str, value: str, tone: str = INK) -> tk.Frame:
        frame = tk.Frame(parent, bg="white", highlightbackground=LINE, highlightthickness=1)
        tk.Label(frame, text=title.upper(), bg="white", fg="#6B7280", font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, padx=14, pady=(12, 0))
        tk.Label(frame, text=value, bg="white", fg=tone, font=("Segoe UI", 22, "bold")).pack(anchor=tk.W, padx=14, pady=(0, 12))
        return frame

    def refresh_all(self) -> None:
        self.rows = copilote.load_csv()
        self.render_current()

    def render_dashboard(self) -> None:
        self.rows = copilote.load_csv()
        grouped = group_csv_orders(self.rows)
        summaries = [order_summary(ref, rows) for ref, rows in grouped.items()]
        pending = [s for s in summaries if all(st in copilote.PENDING_STATUSES for st in {x.strip() for x in s["statut"].split(",")})]
        sent = [s for s in summaries if "ENVOYE" in s["statut"]]
        errors = [s for s in summaries if "ERREUR" in s["statut"]]

        header = ttk.Frame(self.content, style="Root.TFrame")
        header.pack(fill=tk.X)
        ttk.Label(header, text="Tableau de bord", style="Title.TLabel", background=BG).pack(side=tk.LEFT)
        ttk.Button(header, text="Rafraichir", command=self.refresh_all).pack(side=tk.RIGHT)

        kpis = ttk.Frame(self.content, style="Root.TFrame")
        kpis.pack(fill=tk.X, pady=16)
        for i, (title, value, tone) in enumerate([
            ("Commandes", str(len(summaries)), INK),
            ("A envoyer", str(len(pending)), EMERALD),
            ("Envoyees", str(len(sent)), INK),
            ("Erreurs", str(len(errors)), DANGER),
        ]):
            c = self.card(kpis, title, value, tone)
            c.grid(row=0, column=i, sticky="ew", padx=(0, 10))
            kpis.columnconfigure(i, weight=1)

        actions = ttk.Frame(self.content, style="Root.TFrame")
        actions.pack(fill=tk.X, pady=(0, 12))
        ttk.Button(actions, text="Synchroniser Nextcloud", command=self.run_nextcloud_sync).pack(side=tk.LEFT)
        ttk.Button(actions, text="Lancer traitement vocal", command=self.run_pipeline).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Importer CSV validees", command=self.import_validated_csv).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Envoyer selection", style="Primary.TButton", command=self.send_selected).pack(side=tk.RIGHT)
        ttk.Button(actions, text="Tout envoyer", command=self.send_all_pending).pack(side=tk.RIGHT, padx=(0, 8))

        table_frame = ttk.Frame(self.content, style="Panel.TFrame", padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("selected", "order_ref", "client", "date", "products", "qty", "statut", "numero", "message")
        self.dashboard_tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        headings = {
            "selected": "Sel.",
            "order_ref": "Commande",
            "client": "Client",
            "date": "Livraison",
            "products": "Produits",
            "qty": "Qte",
            "statut": "Statut",
            "numero": "Copilote",
            "message": "Message",
        }
        widths = {"selected": 55, "order_ref": 140, "client": 220, "date": 100, "products": 75, "qty": 70, "statut": 110, "numero": 90, "message": 320}
        for col in columns:
            self.dashboard_tree.heading(col, text=headings[col])
            self.dashboard_tree.column(col, width=widths[col], anchor=tk.W)
        self.dashboard_tree.pack(fill=tk.BOTH, expand=True)
        self.dashboard_tree.bind("<Button-1>", self.on_dashboard_click)
        self.dashboard_tree.bind("<Double-1>", self.open_order_details)
        for summary in summaries:
            ref = summary["order_ref"]
            self.dashboard_tree.insert(
                "",
                tk.END,
                iid=ref,
                values=(
                    "[x]" if ref in self.selected_orders else "[ ]",
                    ref,
                    f"{summary['client_code']} - {summary['client']}",
                    summary["date_livraison"],
                    summary["products"],
                    summary["quantity"],
                    summary["statut"],
                    summary["numero"],
                    summary["message"],
                ),
            )

        self.log_box = tk.Text(self.content, height=7, bg="#111827", fg="#E5E7EB", insertbackground="white")
        self.log_box.pack(fill=tk.X, pady=(12, 0))
        self.log("Pret.")

    def on_dashboard_click(self, event) -> None:
        region = self.dashboard_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.dashboard_tree.identify_column(event.x)
        if col != "#1":
            return
        item = self.dashboard_tree.identify_row(event.y)
        if not item:
            return
        if item in self.selected_orders:
            self.selected_orders.remove(item)
        else:
            self.selected_orders.add(item)
        self.render_dashboard()

    def open_order_details(self, _event=None) -> None:
        selected = self.dashboard_tree.selection()
        if not selected:
            return
        ref = selected[0]
        grouped = group_csv_orders(copilote.load_csv())
        rows = [row for _, row in grouped.get(ref, [])]
        if rows:
            OrderEditor(self, ref, rows)

    def log(self, message: str) -> None:
        if hasattr(self, "log_box") and self.log_box.winfo_exists():
            stamp = datetime.now().strftime("%H:%M:%S")
            self.log_box.insert(tk.END, f"[{stamp}] {message}\n")
            self.log_box.see(tk.END)

    def send_refs(self, refs: list[str]) -> None:
        if not refs:
            messagebox.showinfo("Envoi", "Aucune commande selectionnee.")
            return
        threading.Thread(target=self._send_refs_worker, args=(refs,), daemon=True).start()

    def send_selected(self) -> None:
        self.send_refs(sorted(self.selected_orders))

    def send_all_pending(self) -> None:
        grouped = group_csv_orders(copilote.load_csv())
        refs = []
        for ref, indexed in grouped.items():
            statuses = {normalize_status(row.get("statut", "")) for _, row in indexed}
            if statuses and all(status in copilote.PENDING_STATUSES for status in statuses):
                refs.append(ref)
        self.send_refs(sorted(refs))

    def _send_refs_worker(self, refs: list[str]) -> None:
        rows = copilote.load_csv()
        grouped = group_csv_orders(rows)
        lock_fd = None
        try:
            lock_fd = copilote.acquire_send_lock()
            for ref in refs:
                indexed = grouped.get(ref, [])
                if not indexed:
                    continue
                statuses = {normalize_status(row.get("statut", "")) for _, row in indexed}
                if not statuses or not all(status in copilote.PENDING_STATUSES for status in statuses):
                    self.after(0, lambda r=ref: self.log(f"{r}: ignore, statut non envoyable"))
                    continue
                order_rows = [row for _, row in indexed]
                errors = copilote.validate_template(order_rows)
                if errors:
                    msg = " | ".join(errors[:3])
                    for index, _ in indexed:
                        rows[index]["statut"] = "ERREUR"
                        rows[index]["message"] = msg
                    copilote.save_csv(rows)
                    self.after(0, lambda r=ref, m=msg: self.log(f"{r}: ERREUR {m}"))
                    continue
                self.after(0, lambda r=ref: self.log(f"{r}: envoi Copilote..."))
                status = None
                try:
                    status, reason, candidates, out_dir, error = copilote.send_service_request(ref, order_rows)
                    number = candidates[-1] if candidates else ""
                    final_status = "ENVOYE" if 200 <= status < 300 and not error else "ERREUR"
                    message = f"HTTP {status} {reason}; logs={out_dir}"
                    if error:
                        message = f"{error}; {message}"
                except Exception as exc:
                    number = ""
                    final_status = "ERREUR"
                    message = str(exc)
                sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for index, _ in indexed:
                    rows[index]["statut"] = final_status
                    rows[index]["http_status"] = str(status) if status is not None else ""
                    rows[index]["copilote_numero"] = number
                    rows[index]["sent_at"] = sent_at
                    rows[index]["message"] = message
                copilote.save_csv(rows)
                self.after(0, lambda r=ref, st=final_status, n=number: self.log(f"{r}: {st} {n}"))
                time.sleep(0.2)
        finally:
            if lock_fd is not None:
                copilote.release_send_lock(lock_fd)
            self.after(0, self.refresh_all)

    def run_nextcloud_sync(self) -> None:
        env_extra = {"NEXTCLOUD_USERNAME": os.environ.get("NEXTCLOUD_USERNAME", "")}
        if "NEXTCLOUD_PASSWORD" in os.environ:
            env_extra["NEXTCLOUD_PASSWORD"] = os.environ["NEXTCLOUD_PASSWORD"]
        else:
            password = simpledialog.askstring("Nextcloud", "Mot de passe Nextcloud", show="*", parent=self)
            if not password:
                self.log("Sync Nextcloud annulee: mot de passe manquant.")
                return
            env_extra["NEXTCLOUD_PASSWORD"] = password
        self.run_command(
            ["python", str(PROJECT_ROOT / "app_cli.py"), "nextcloud-sync", "--insecure"],
            "Sync Nextcloud",
            env_extra=env_extra,
        )

    def run_pipeline(self) -> None:
        self.run_command(["python", str(PROJECT_ROOT / "app_cli.py"), "pipeline", "--tous-les-audios"], "Pipeline vocal")

    def run_command(self, cmd: list[str], label: str, env_extra: dict[str, str] | None = None) -> None:
        def worker() -> None:
            self.after(0, lambda: self.log(f"{label}: demarrage"))
            env = os.environ.copy()
            if env_extra:
                env.update(env_extra)
            proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, env=env, timeout=7200)
            tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-8:])
            self.after(0, lambda: self.log(f"{label}: termine rc={proc.returncode}\n{tail}"))
        threading.Thread(target=worker, daemon=True).start()

    def import_validated_csv(self) -> None:
        rows = read_semicolon_csv(VALIDATED_CSV)
        if not rows:
            messagebox.showinfo("Import", "Aucune commande validee a importer.")
            return
        existing = copilote.load_csv()
        existing_refs = {(row.get("order_ref") or "").strip() for row in existing}
        added = 0
        for row in rows:
            audio = Path(row.get("audio_source", "audio")).stem
            run_id = row.get("run_id") or datetime.now().strftime("%Y%m%d_%H%M%S")
            ref = f"VOC-{run_id}-{audio}".replace(" ", "_")[:80]
            if ref in existing_refs:
                continue
            full = {name: "" for name in copilote.ALL_COLUMNS}
            full.update({
                "order_ref": ref,
                "dossier": "BASCO",
                "client": row.get("client_nom", ""),
                "client_code": row.get("client_code", ""),
                "date_livraison": row.get("date_livraison", ""),
                "transport": "HENDAYE",
                "transport_code": "HENDAYE",
                "product_code": row.get("code_article", ""),
                "product_label": row.get("libelle_article", ""),
                "quantity": row.get("quantite", ""),
                "unit": row.get("unite", ""),
                "statut": "A_ENVOYE",
                "message": f"Import vocal {row.get('audio_source', '')}",
            })
            existing.append(full)
            added += 1
        copilote.save_csv(existing)
        messagebox.showinfo("Import", f"{added} ligne(s) importee(s).")
        self.refresh_all()

    def render_problematic(self) -> None:
        ttk.Label(self.content, text="Commandes problematiques", style="Title.TLabel", background=BG).pack(anchor=tk.W)
        ttk.Label(self.content, text="Commandes a corriger avant integration Copilote.", style="Subtitle.TLabel", background=BG).pack(anchor=tk.W, pady=(0, 14))
        rows = []
        for row in read_semicolon_csv(PROBLEM_CSV):
            rows.append(row)
        for row in copilote.load_csv():
            if normalize_status(row.get("statut")) == "ERREUR":
                rows.append({
                    "audio_source": row.get("order_ref", ""),
                    "client_code": row.get("client_code", ""),
                    "client_nom": row.get("client", ""),
                    "date_livraison": row.get("date_livraison", ""),
                    "raisons_problematiques": row.get("message", ""),
                    "transcription": "",
                })
        frame = ttk.Frame(self.content, style="Panel.TFrame", padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        columns = ("source", "client", "date", "raison", "transcription")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col, title, width in [
            ("source", "Source", 210),
            ("client", "Client", 220),
            ("date", "Livraison", 100),
            ("raison", "Probleme", 300),
            ("transcription", "Transcription", 420),
        ]:
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor=tk.W)
        tree.pack(fill=tk.BOTH, expand=True)
        for i, row in enumerate(rows):
            tree.insert("", tk.END, iid=str(i), values=(
                row.get("audio_source", ""),
                f"{row.get('client_code', '')} - {row.get('client_nom', '')}",
                row.get("date_livraison", ""),
                row.get("raisons_problematiques", ""),
                row.get("transcription", ""),
            ))
        ttk.Label(self.content, text="Astuce: corriger ou creer la commande dans le tableau de bord via Detail commande.", style="Subtitle.TLabel", background=BG).pack(anchor=tk.W, pady=8)

    def render_password(self) -> None:
        box = ttk.Frame(self.content, style="Panel.TFrame", padding=24)
        box.pack(fill=tk.X)
        ttk.Label(box, text="Mon mot de passe", style="Title.TLabel").pack(anchor=tk.W)
        current = tk.StringVar()
        new = tk.StringVar()
        confirm = tk.StringVar()
        for label, var, show in [
            ("Mot de passe actuel", current, "*"),
            ("Nouveau mot de passe", new, "*"),
            ("Confirmation", confirm, "*"),
        ]:
            ttk.Label(box, text=label, style="Small.TLabel").pack(anchor=tk.W, pady=(14, 0))
            ttk.Entry(box, textvariable=var, show=show).pack(fill=tk.X, pady=(4, 0))

        def change() -> None:
            users = load_users()
            user = users.get(self.current_user)
            if not user or user.get("password_hash") != password_hash(current.get()):
                messagebox.showerror("Mot de passe", "Mot de passe actuel incorrect.")
                return
            if len(new.get()) < 4 or new.get() != confirm.get():
                messagebox.showerror("Mot de passe", "Confirmation incorrecte ou mot de passe trop court.")
                return
            user["password_hash"] = password_hash(new.get())
            save_users(users)
            messagebox.showinfo("Mot de passe", "Mot de passe modifie.")

        ttk.Button(box, text="Changer le mot de passe", command=change).pack(anchor=tk.E, pady=(18, 0))

    def render_guide(self) -> None:
        text = (
            "Guide utilisateur\n\n"
            "1. Synchroniser Nextcloud pour recuperer les nouveaux messages vocaux.\n"
            "2. Lancer le traitement vocal pour transcrire et extraire les commandes.\n"
            "3. Importer les commandes validees dans le tableau de bord.\n"
            "4. Ouvrir Detail pour verifier les produits d'une commande.\n"
            "5. Selectionner les commandes a envoyer ou utiliser Tout envoyer.\n\n"
            "Les commandes problematiques doivent etre corrigees avant envoi."
        )
        self.text_page("Guide utilisateur", text)

    def render_support(self) -> None:
        text = (
            "Support\n\n"
            "Chemins utiles:\n"
            f"- Projet: {PROJECT_ROOT}\n"
            f"- Audios Nextcloud: {NEXTCLOUD_AUDIO_DIR}\n"
            f"- CSV Copilote: {copilote.CSV_PATH}\n"
            f"- Logs Copilote: {copilote.RUNS_DIR}\n\n"
            "En cas d'erreur Copilote, verifier que Copilote BASCO est ouvert et connecte."
        )
        self.text_page("Support", text)

    def text_page(self, title: str, text: str) -> None:
        ttk.Label(self.content, text=title, style="Title.TLabel", background=BG).pack(anchor=tk.W, pady=(0, 12))
        box = tk.Text(self.content, bg="white", fg=INK, wrap=tk.WORD, font=("Segoe UI", 11), relief="flat", padx=18, pady=18)
        box.pack(fill=tk.BOTH, expand=True)
        box.insert(tk.END, text)
        box.configure(state=tk.DISABLED)


def main() -> None:
    app = RepondeurApp()
    app.mainloop()


if __name__ == "__main__":
    main()
