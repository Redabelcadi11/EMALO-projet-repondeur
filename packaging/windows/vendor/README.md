# Vendor Windows

## Optionnel

Tu peux déposer ici des binaires Windows à embarquer automatiquement dans le package.

### FFmpeg

Structure attendue :

```text
packaging/windows/vendor/ffmpeg/bin/ffmpeg.exe
packaging/windows/vendor/ffmpeg/bin/ffprobe.exe
packaging/windows/vendor/ffmpeg/bin/*.dll
```

Si ce dossier est présent, le build Windows le copiera dans :

```text
ProjetRepondeur/ffmpeg/
```

Sinon, le script de build essaiera de récupérer `ffmpeg.exe` depuis le système Windows de build.
