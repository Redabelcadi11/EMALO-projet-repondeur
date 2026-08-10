# Packaging Windows

## Objectif

Générer un livrable Windows simple à installer sur un TSE :

- une application packagée `ProjetRepondeur.exe`
- un dossier applicatif complet
- un zip de distribution
- un installateur Windows si Inno Setup est disponible

Avec ce mode de packaging :

- **Python n'a pas besoin d'être installé sur le TSE**
- l'interpréteur Python est embarqué dans l'exécutable packagé

## Entrée packagée

Le point d'entrée packagé est :

- [app_cli.py](/home/reda/Documents/projet-repondeur/app_cli.py:1)

Commandes disponibles :

- `pipeline`
- `copilote-order`
- `install-runtime`
- `doctor`

## Build Windows

Scripts fournis :

- [build_windows.ps1](/home/reda/Documents/projet-repondeur/packaging/windows/build_windows.ps1:1)
- [build_windows.bat](/home/reda/Documents/projet-repondeur/packaging/windows/build_windows.bat:1)
- [ProjetRepondeur.spec](/home/reda/Documents/projet-repondeur/packaging/windows/ProjetRepondeur.spec:1)
- [ProjetRepondeur.iss](/home/reda/Documents/projet-repondeur/packaging/windows/ProjetRepondeur.iss:1)

### Depuis une machine Windows

```powershell
cd C:\chemin\vers\projet-repondeur
packaging\windows\build_windows.ps1
```

## Sorties attendues

- `dist\windows\ProjetRepondeur\`
- `dist\windows\ProjetRepondeur-windows.zip`
- `dist\installer\ProjetRepondeur-Setup.exe` si Inno Setup est installé

## Remarques

- le build embarque automatiquement **Chromium Playwright**
- le build embarque **FFmpeg** si :
  - il est disponible sur la machine Windows de build
  - ou s'il est placé dans `packaging/windows/vendor/ffmpeg`
- l'installateur propose maintenant :
  - une case `raccourci bureau`
  - une case `raccourci barre des tâches` en mode best effort
  - une case `réparer / réinstaller le runtime navigateur`

Après installation, tu peux lancer :

```text
ProjetRepondeur.exe install-runtime
```

ou le raccourci :

```text
Projet Repondeur - Installer runtime
```

## Préconisation TSE

Sur le TSE, la séquence recommandée est :

1. installer l'application
2. lancer `doctor`
3. vérifier que le runtime Playwright est bien embarqué
4. vérifier que `ffmpeg` est bien présent
5. tester `pipeline`
6. tester `copilote-order`
