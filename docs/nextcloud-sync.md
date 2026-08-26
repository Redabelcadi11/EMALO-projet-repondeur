# Synchronisation Nextcloud

Cette brique recupere les messages vocaux du repondeur depuis Nextcloud via
WebDAV, puis les depose dans :

```text
ressources-originales/audio-nextcloud
```

Le pipeline vocal lit maintenant ce dossier en plus de `audio-exemples`.

## Configuration

Variables d'environnement recommandees :

```powershell
$env:NEXTCLOUD_USERNAME="utilisateur-nextcloud"
$env:NEXTCLOUD_PASSWORD="mot-de-passe-ou-app-password"
$env:NEXTCLOUD_REMOTE_PATH="chemin/du/dossier/commandes"
```

Le mot de passe peut aussi etre saisi interactivement si
`NEXTCLOUD_PASSWORD` n'est pas defini.

## Tester sans telecharger

```powershell
python app_cli.py nextcloud-sync --insecure --dry-run
```

## Telecharger les nouveaux audios

```powershell
python app_cli.py nextcloud-sync --insecure
```

Un manifeste local est conserve dans :

```text
cache/nextcloud-sync-manifest.json
```

Il evite de retelecharger les memes fichiers et sert de garde-fou contre les
doublons.
