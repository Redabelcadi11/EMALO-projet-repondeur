# Installation sur TSE

## 1. Hypothèse

Ce document part de l'hypothèse que le **TSE** est un **serveur Windows / Remote Desktop / Terminal Server** sur lequel l'application devra etre installee et executee.

Etat actuel du projet :

- le projet est d'abord un **projet Python local** ;
- un **packaging Windows** est maintenant prepare dans le depot, mais doit etre genere et valide depuis une machine Windows ;
- c'est un **projet Python local** avec :
  - un pipeline de transcription / extraction ;
  - un script d'automatisation web Copilote ;
- il n'y a **pas de base de donnees locale** ;
- il n'y a **pas de service Windows obligatoire** dans l'etat actuel.

## 2. Objectif du logiciel

Le logiciel a pour but d'automatiser la prise de commande a partir de messages vocaux clients, puis de preparer ou saisir une commande dans l'ERP Copilote.

Fonctions actuelles :

1. transcription locale des messages vocaux ;
2. identification du client ;
3. extraction de la date de livraison ;
4. extraction des produits / quantites / unites ;
5. production de fichiers CSV de commandes valides et problematiques ;
6. automatisation de la saisie dans **Copilote web** via navigateur automatise.

## 3. Schema fonctionnel

```text
Messages vocaux
    |
    v
Transcription locale Whisper
    |
    v
Extraction metier
- client
- date
- produits
- quantites
    |
    +----------------------------+
    |                            |
    v                            v
CSV commandes valides       CSV commandes problematiques
    |
    v
Automatisation Copilote web (Playwright)
    |
    v
Saisie de commande dans l'ERP
```

## 4. Architecture technique actuelle

### Composants principaux

- [lancer_pipeline.py](/home/reda/Documents/projet-repondeur/lancer_pipeline.py:1)
  Point d'entree principal du pipeline.
- [transcrire_audios.py](/home/reda/Documents/projet-repondeur/transcrire_audios.py:1)
  Transcription locale via `faster-whisper`.
- [extraire_informations.py](/home/reda/Documents/projet-repondeur/extraire_informations.py:1)
  Extraction metier et export CSV.
- [scripts/copilote_order.py](/home/reda/Documents/projet-repondeur/scripts/copilote_order.py:1)
  Automatisation de la saisie dans Copilote web via Playwright.

### Donnees lues

- fichiers audio ;
- fichiers Excel / donnees clients ;
- fichiers Excel / donnees cadencier ;
- fichiers JSON de configuration :
  - [config/variantes-clients.json](/home/reda/Documents/projet-repondeur/config/variantes-clients.json:1)
  - [config/synonymes-produits.json](/home/reda/Documents/projet-repondeur/config/synonymes-produits.json:1)

### Donnees produites

- transcriptions JSON / TXT ;
- extractions JSON / TXT ;
- CSV :
  - `commandes_validees.csv`
  - `commandes_problematiques.csv`
- captures/debug HTML/TXT/PNG pour l'automatisation Copilote.

## 5. Dependances logicielles

### Runtime principal

- en **mode packagé Windows** :
  - **Python n'a pas besoin d'être installé sur le TSE**
  - il est embarqué dans l'application construite avec PyInstaller
- en **mode source** :
  - **Python 3.11 ou 3.12 64 bits** reste nécessaire

### Dependances Python

Fichier actuel :
- [requirements.txt](/home/reda/Documents/projet-repondeur/requirements.txt:1)

Liste :

- `faster-whisper>=1.2.0`
- `openpyxl>=3.1.0`
- `rapidfuzz>=3.0.0`
- `dateparser>=1.2.0`
- `pytest>=7.0.0`
- `playwright>=1.59.0`

### Dependances systeme / binaires

- **Navigateur Chromium** pour Playwright
  - en mode packagé, il peut être **embarqué dans l'installateur**
  - sinon, installation via `playwright install chromium`
- **FFmpeg**
  - requis pour le decodage audio par la chaine Whisper dans la plupart des cas
  - peut être embarqué dans le package Windows si fourni au moment du build
- acces disque en lecture/ecriture sur le repertoire projet

### Modele IA local

- modele Whisper : `large-v3`
- execution actuelle :
  - `device = cpu`
  - `compute_type = int8`

Implication :

- **pas de GPU obligatoire**
- mais consommation CPU / RAM non negligeable

## 6. Prerequis machine TSE

### Minimum recommande

- Windows Server / TSE 64 bits
- si installation via **Setup Windows packagé** :
  - pas de Python à installer sur le TSE
- si installation en **mode source** :
  - Python 3.11+ installe pour tous les utilisateurs concernes ou pour le compte de service choisi
- droits d'execution navigateur
- acces au stockage local ou partage reseau pour :
  - le projet ;
  - les ressources d'entree ;
  - les resultats ;
  - le cache du modele Whisper ;
  - le cache navigateur Playwright

### Ressources recommandees

- CPU multi-coeurs
- 8 Go RAM minimum
- 16 Go RAM recommande si transcription locale et navigateur automatise sur la meme machine
- espace disque :
  - projet + resultats
  - modele Whisper
  - navigateur Playwright

## 7. Prerequis reseau

### Flux necessaires

- acces HTTP/HTTPS vers l'instance Copilote web
- resolution DNS / acces IP vers l'ERP si utilise via URL interne

### A verifier avec l'equipe TSE

- le TSE peut-il atteindre :
  - le serveur Copilote web ;
  - les partages/fichiers sources clients et cadencier ;
- le TSE autorise-t-il l'execution d'un navigateur automatise ;
- le TSE autorise-t-il l'installation des composants Playwright/Chromium ;
- le TSE autorise-t-il l'installation de FFmpeg ;
- le TSE autorise-t-il le telechargement initial du modele Whisper et du navigateur ?

## 8. Installation type

### Option recommandée : installation packagée

1. générer le livrable Windows depuis une machine Windows :
   - [build_windows.ps1](/home/reda/Documents/projet-repondeur/packaging/windows/build_windows.ps1:1)
2. fournir au TSE :
   - `ProjetRepondeur-Setup.exe`
   - ou à défaut `ProjetRepondeur-windows.zip`
3. installer l'application sur le TSE
4. cocher si besoin :
   - raccourci bureau
   - raccourci barre des tâches
   - réparation / réinstallation runtime navigateur
5. après installation, lancer :

```text
ProjetRepondeur.exe doctor
```

### Option de secours : installation source

### Etape 1

Installer :

- Python 3.11 ou 3.12
- FFmpeg

### Etape 2

Copier le projet sur le TSE, par exemple :

```text
C:\Applications\projet-repondeur
```

### Etape 3

Creer un environnement virtuel Python :

```bash
python -m venv .venv
```

### Etape 4

Installer les dependances Python :

```bash
.venv\Scripts\pip install -r requirements.txt
```

### Etape 5

Installer le navigateur Playwright :

```bash
.venv\Scripts\playwright install chromium
```

### Etape 6

Verifier la presence des ressources metier :

- base clients
- cadencier
- fichiers config
- repertoire de resultats

### Etape 7

Executer un test :

```bash
.venv\Scripts\python lancer_pipeline.py --sans-transcription
```

Puis, pour la partie ERP :

```bash
.venv\Scripts\python scripts\copilote_order.py
```

## 9. Permissions a prevoir

- droit de lecture/ecriture sur le repertoire projet ;
- droit de creation/modification des fichiers de resultats ;
- droit d'execution Python ;
- droit d'execution d'un navigateur automatise ;
- si capture reseau/proxy de debug : droits supplementaires potentiels pour certificat local ou proxy local.

## 10. Point important sur la "capture des requetes"

Si l'objectif est de **recuperer les requetes du logiciel bureau / de Copilote**, c'est **possible dans certains cas**, mais ce n'est pas garanti dans tous.

### Cas favorable

Si l'application bureau utilise :

- HTTP / HTTPS classique ;
- un navigateur embarque ou un client web standard ;
- sans certificate pinning ;

alors on peut souvent intercepter les requetes avec un outil type :

- HTTP Toolkit
- Fiddler
- mitmproxy

### Cas defavorable

Si l'application bureau utilise :

- un protocole proprietaire ;
- du chiffrement non interceptable ;
- du certificate pinning ;

alors la capture sera plus complexe, voire impossible sans adaptation plus lourde.

### Conclusion pratique

Oui, **une application bureau ou un proxy desktop peut aider a recuperer les requetes**, mais il faut prevoir en plus :

- l'installation du logiciel de capture ;
- parfois l'installation d'un certificat racine local ;
- l'autorisation reseau et securite de l'environnement TSE ;
- des tests de compatibilite avec le client logiciel reel.

## 11. Limites de la version actuelle

- un packaging Windows est prepare, mais non valide en execution Windows depuis cette session Linux ;
- pas de service Windows ;
- pas d'interface graphique utilisateur final dediee ;
- pas d'interface installee "clic unique" deja produite dans ce depot tant que le build Windows n'a pas ete lance ;
- l'automatisation ERP repose sur l'interface web Copilote, pas sur une API officielle.

## 12. Recommandation a transmettre a l'equipe TSE

Le plus juste a leur dire aujourd'hui est :

1. le depot contient maintenant un **packaging Windows prepare** ;
2. le build doit etre realise depuis Windows pour produire l'application TSE ;
3. sur le **TSE cible**, Python n'est **pas requis** si on installe la version packagée ;
4. le logiciel a besoin de **Python + dependances Python + Playwright/Chromium + FFmpeg** pendant la phase de build ou de mode source ;
5. l'application cible doit avoir acces au **reseau interne Copilote** et aux **fichiers metier** ;
6. si l'objectif inclut la **capture des requetes** du logiciel bureau, il faut prevoir un **outil proxy de debug** en plus, avec validation securite.

## 13. Suite conseillee

Avant installation definitive sur le TSE, il est recommande de valider sur une machine de test :

1. l'installation Python + dependances ;
2. l'execution du pipeline ;
3. l'ouverture Copilote depuis Playwright ;
4. la possibilite ou non de capturer les requetes du client bureau si c'est bien un objectif.
