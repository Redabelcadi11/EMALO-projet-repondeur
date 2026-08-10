# EMALO Repondeur

Sources Windows/TSE de la version de production du 10 aout 2026. Les audios, transcriptions, donnees clients, catalogues, commandes Copilote et secrets locaux ne sont pas inclus.

## Composants

- `src/` et les scripts Python racine : transcription, reconnaissance client/produits et pipeline de commande.
- `app-desktop/` : interface Electron et interface navigateur de production.
- `scripts/` et `copilote/` : integration et outils Copilote sans captures ni commandes reelles.
- `worker_transcription_server.py` et `worker_client.py` : delegation des traitements vers la VM/VPS.

## Configuration locale

1. Copier les fichiers `config/*.example` vers leur nom sans `.example` et renseigner les valeurs locales.
2. Copier `app-desktop/renderer/auth-config.example.js` vers `auth-config.js`.
3. Definir `OPENAI_API_KEY`, `NEXTCLOUD_USERNAME`, `NEXTCLOUD_PASSWORD`, `COPILOTE_USER`, `COPILOTE_PASSWORD` et `REPONDEUR_BOOTSTRAP_PASSWORD` dans l environnement du service concerne.
4. Copier `portal_config.json.example` vers `portal_config.json` si le portail est utilise.

Le raccourci public de production lance `DEMARRER_REPONDEUR_BROWSER.ps1`. Les donnees runtime doivent etre restaurees separement depuis un stockage securise.

## Tests

Installer les dependances de `requirements.txt`, puis executer les tests dans un environnement isole :

```powershell
python -m pytest -q
```

Ne jamais lancer les tests avec des chemins pointant vers les dossiers runtime de production.
