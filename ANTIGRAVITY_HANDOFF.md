# Handoff Antigravity — EMALO Répondeur

État figé le 13 août 2026. Ce document doit permettre de reprendre le travail
sans refaire l'audit ni ouvrir prématurément le jeu final.

## À respecter avant toute action

1. Ne jamais créer, modifier, importer ou envoyer une commande dans Copilote.
2. Conserver `config/erp-safety.json` avec `evaluation_lock=true` et
   `allow_erp_writes=false`.
3. Ne jamais fournir au prédicteur, à Whisper ou à Llama une commande ERP
   cible, même indirectement par un profil, une règle apprise ou un cadencier
   enrichi après le message.
4. Ne pas ouvrir, afficher, scorer ni diagnostiquer le holdout final de
   20 audios avant le gel définitif du moteur.
5. Ne pas utiliser Qwen pour l'arbitrage produit. Le modèle autorisé à tester
   est le Llama local existant `llama3.1:70b`.

Le projet local est
`L:\Public\EMALO-Achats\EMALO-Repondeur`. Il n'est pas un dépôt Git : faire
une sauvegarde explicite avant une future série de modifications. La copie de
calcul est `/opt/emalo-repondeur-worker` sur `ubuntu@51.210.2.253`.

## État opérationnel laissé en place

- `emalo-repondeur-worker.service` est actif et écoute localement sur
  `127.0.0.1:8787`.
- Le worker utilise le GPU L4 pour faster-whisper `large-v3`.
- Ollama reste installé et actif sur `127.0.0.1:11434`, mais le modèle Llama
  a été déchargé de la VRAM après l'expérience (`/api/ps` vide).
- Le modèle présent est `llama3.1:70b`, 70,6 milliards de paramètres,
  Q4_K_M, digest
  `711a9e8463afd8edd580debd3b5c521521ebe55ba95bb80d576f4149969e07c6`.
- Qwen n'a pas été utilisé pour cette passe.
- Aucun appel OpenAI n'est nécessaire dans le chemin d'évaluation.
- Aucune écriture ERP n'a été tentée pendant cette passe.

Pour une expérience Llama, arrêter temporairement le worker afin de libérer la
VRAM. Après l'expérience, exécuter :

```bash
ollama stop llama3.1:70b
sudo systemctl start emalo-repondeur-worker.service
systemctl is-active emalo-repondeur-worker.service
```

## Audit ERP terminé

La politique centrale fail-closed est implémentée par :

- `config/erp-safety.json` ;
- `src/erp_safety.py` ;
- `copilote/erp_write_guard.groovy`.

Une politique absente, invalide ou incomplète bloque aussi les écritures. Son
chemin n'est pas remplaçable par une variable d'environnement. Pour autoriser
une écriture, il faudrait simultanément modifier la politique, retirer le
verrou, passer en production et fournir une confirmation d'environnement :
aucune de ces conditions n'est présente.

Tous les chemins mutants trouvés par inspection statique sont gardés :

| Chemin | Mutation potentielle | Garde |
| --- | --- | --- |
| `copilote_integration.send_service_request` | service Groovy | Python avant session/réseau |
| `copilote/send_order_service.groovy` | `CommandeService.create`, lignes, `saveCdeBatch` | Groovy avant service distant |
| `copilote_integration.send_direct_request` | rejeu binaire vers `ProxyServlet` | Python avant fichier/réseau |
| `electron_bridge._send_orders` | envoi depuis Electron/web | Python |
| `electron_bridge._send_audio_order` | analyse puis envoi audio | Python |
| `ui_repondeur.send_refs` | bouton d'envoi UI Python | Python |
| `scripts/copilote_order.py` | Playwright : création, lignes, Enregistrer | garde au mode et à chaque étape mutante |
| `copilote/probe_line_quantities.groovy` | appelle `CommandeService.create` | bloqué comme écriture potentielle |

Les lectures restent autorisées : extraction Infocentre
`execute2`, `CommandeService.loadNumCde`, recherche client et recherche de
commande. Voir `docs/audit-securite-erp.md`.

## Pipeline compris

1. `recuperer_nextcloud.py` fait uniquement `PROPFIND` puis `GET` et copie
   les nouveaux audios. Il ne fait ni `DELETE`, ni `MOVE`, ni `PUT`.
2. La tâche Windows `EMALO-Repondeur-Nextcloud-Sync`, exécutée comme SYSTEM,
   synchronise à 03:00 et 23:00 sans session `adminemalo`.
3. L'UI appelle `prod_pipeline.run_selected_audios_pipeline`.
4. `worker_client.py` ouvre le tunnel SSH défini dans `config/worker.json`.
5. `worker_transcription_server.py` transcrit avec faster-whisper
   `large-v3`, CUDA FP16, beam 5.
6. `extraire_informations.traiter_transcriptions` identifie client, date,
   segments produits, références, quantités, unités et statut.
7. La recherche utilise d'abord le cadencier client, puis le catalogue global
   autorisé et le référentiel de contrôle des conditionnements.
8. Les résultats sont des fichiers locaux. Aucun envoi automatique n'est
   nécessaire pour prédire ou évaluer.

La vérité ERP est lue séparément par
`scripts/extract_copilote_repondeur_orders.py` et
`copilote/extract_repondeur_orders.groovy`. L'extraction utilisée est :

`resultats/copilote-replay/commandes_ES_2026-08-12_au_2026-08-13.csv`.

## Corpus et séparation sans fuite

- 208/208 audios ont été transcrits sur GPU.
- Temps total Whisper : 416,941 s ; moyenne : 1,994 s/audio ; médiane :
  1,607 s/audio.
- 275 commandes ES ont été récupérées en lecture seule.
- L'apparieur indépendant a retenu 63 paires robustes sans lire les
  prédictions du programme.
- Développement : 43 audios, 359 lignes ERP.
- Holdout temporel final : 20 audios, les plus récents parmi les paires
  `metadata_exact`.
- Corpus privé :
  `/opt/emalo-autotune/private/corpus-temporal-2026-08-12-13-v2.json`.
- Manifeste développement sans cible :
  `/opt/emalo-repondeur-worker/evaluation/manifests/development-2026-08-12-13.json`.

Le holdout de 20 audios n'a pas été ouvert ni scoré pendant cette passe.

`config/evaluation-safety.json` interdit les profils agressifs, les règles
client apprises et l'enrichissement depuis les commandes ES évaluées.
`config/profils-clients-agressifs.json` et
`config/regles-apprentissage.json` sont conservés pour audit mais ne doivent
pas alimenter le moteur.

L'évaluation se fait en trois processus :

1. le processus privé fabrique un manifeste sans cible ;
2. le prédicteur, lancé comme `ubuntu`, ne peut pas lire le dossier privé ;
3. seulement après sauvegarde de la prédiction, un autre processus lit la
   vérité et calcule les métriques.

## Métrique de production

`automation_order_accuracy` exige simultanément :

- bon client ;
- bonne date de livraison ;
- multiensemble exact des triplets
  `(code article, quantité, unité)` ;
- statut `VALIDEE`.

Le seuil est 90 % sur au moins 20 nouveaux audios. Sur le holdout actuel, cela
signifie au moins 18 commandes automatiques entièrement exactes sur 20.

## Résultats développement

| Version | Rappel code | Précision code | Rappel ligne exacte | Précision ligne exacte | Client | Date | Contenu exact | Automatisation exacte |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| V1 baseline, 43 audios | 57,94 % | 60,47 % | 48,47 % | 50,58 % | 88,37 % | 81,40 % | 2,33 % | 0 % |
| V2 règles générales | 54,60 % | 61,44 % | 45,68 % | 51,41 % | 88,37 % | 97,67 % | 2,33 % | 0 % |
| V3 balanced, meilleur état évalué complet | 57,10 % | 71,68 % | 48,47 % | 60,84 % | 93,02 % | 97,67 % | 4,65 % | 2,33 % |

V3 a prédit 286 lignes pour 359 lignes réelles. Deux commandes ont un contenu
exact ; une seule est une commande automatique entièrement exacte.
`line_set_accuracy` vaut 6,98 %, le taux d'acceptation automatique 2,33 %.
Le seuil de production est donc très loin d'être atteint.

Artefacts :

- prédiction V1 :
  `evaluation/predictions/baseline-development-v1.json` ;
- prédiction V2 :
  `evaluation/predictions/development-v2-general-rules.json` ;
- prédiction V3 :
  `evaluation/predictions/development-v3-balanced.json` ;
- scores privés V2/V3 :
  `/opt/emalo-autotune/private/development-v2-general-rules-score.json` et
  `development-v3-balanced-score.json`.

Causes V3 agrégées :

- classement produit : 34 commandes ;
- faux produits : 34 ;
- quantité/conditionnement : 19 ;
- client : 3 ;
- rejet interne d'une commande autrement correcte : 2 ;
- candidat attendu absent de la recherche : 2 ;
- date : 1.

Les améliorations déterministes générales déjà intégrées comprennent :

- dates de livraison ;
- frontières d'intention et suppression des salutations, lieux, jours,
  remerciements et fins d'appel comme produits ;
- fusion des répétitions Whisper sans sommer artificiellement ;
- quantités placées avant ou après le produit ;
- non-invention d'une quantité habituelle quand le vocal ne la justifie pas ;
- contradictions sémantiques et marge réelle entre candidats ;
- identification client par téléphone, nom, variantes phonétiques et ville ;
- priorité au cadencier client sans empêcher une référence autorisée hors de
  ce cadencier ;
- conditionnements du référentiel de contrôle.

## Architecture Llama 70B ajoutée

Fichiers :

- `src/llama_product_resolver.py` ;
- `scripts/arbitrer_predictions_llama_local.py` ;
- `tests/test_llama_product_resolver.py`.

Le chemin est volontairement séparé du pipeline principal tant qu'il n'a pas
été validé sur un échantillon représentatif. Il n'est pas le défaut production.

Architecture :

1. appel local fixe à `http://127.0.0.1:11434/api/generate` ;
2. vérification qu'un Llama d'au moins 60B est réellement installé ;
3. premier passage compact pour normaliser/extraire les mentions produit ;
4. récupération indépendante dans les données autorisées ;
5. arbitrage par petits lots ;
6. validation déterministe finale des codes, unités, quantités, preuve
   textuelle, confiance et conditionnements ;
7. sauvegarde/checkpoint avant toute évaluation privée.

Données autorisées transmises ou utilisées :

- transcription Whisper ;
- client identifié ;
- cadencier/historique antérieur disponible en production ;
- catalogue de production ;
- référentiel officiel de contrôle, environ 59 000 références ;
- libellés, unités et conditionnements ;
- candidats déterministes et contexte disponible au moment de l'appel.

La commande ERP cible est refusée récursivement par nom de champ
(`truth`, `ground_truth`, `commande_reelle`, etc.). Le script exige
`truth_received_by_predictor=false`, refuse le chemin privé et certifie
`erp_write_attempted=false`.

### Expériences Llama réalisées

Les grands prompts monolithiques ne conviennent pas à cette machine :

- le modèle pèse environ 42 Go pour 24 Go de VRAM ; environ 21–22 Go sont
  chargés en VRAM et une partie reste en RAM/CPU ;
- normalisation d'un audio extrême de 30 lignes : environ 115 s ;
- prompt monolithique final : timeout à 900 s ;
- premier essai par lots : un lot réussi, lot suivant timeout à 300 s.

Le script a donc été rendu incrémental : petits lots, checkpoint, conservation
des lots déjà réussis et erreurs par lot.

Mini-échantillon fixé avant consultation de la vérité : les cinq audios les
plus courts/difficiles selon la sortie baseline. Il contient 8 lignes réelles.

| Moteur sur ces 5 audios | Codes exacts | Lignes exactes | Commandes parfaites |
| --- | ---: | ---: | ---: |
| V3 déterministe | 1/8 (12,5 %) | 1/8 (12,5 %) | 0/5 |
| Llama 70B | 6/8 (75 %) | 4/8 (50 %) | 2/5 (40 %) |

Llama a produit 8 lignes contre 4 pour V3. Le premier audio a pris 50,198 s ;
les quatre suivants 266,489 s, soit environ 63,3 s/audio sur les cinq. Ce
signal est encourageant mais non représentatif et ne justifie pas encore une
activation en production.

Artefacts publics :

- `development-v3-llama70b-short-smoke1-v2.json` ;
- `development-v3-llama70b-short-smoke-next4.json` ;
- checkpoints homonymes.

Score privé des quatre derniers :
`development-v3-llama70b-short-smoke-next4-score.json`.

### Dernière correction courte, non rescorrée

Le mini-test a révélé deux erreurs générales de quantité :

- `20 kg` de `GLACON 2K X5P` doit donner 2 colis de 10 kg ;
- l'énoncé `6x1L` correspondant exactement à un pack officiel doit donner
  1 pack, et `deux packs de 6x1L` doit donner 2 packs.

Le validateur calcule maintenant la capacité depuis les formats explicites
`6X1L`, `2K X5P`, avec gestion KG/G/L/ML, avant le calcul générique.
Cette correction n'utilise aucune vérité ERP et est couverte par des tests.
Conformément à la consigne de ne plus lancer d'expérience longue, le
mini-échantillon n'a pas été réinterrogé auprès de Llama après ce changement :
ne pas présenter les métriques ci-dessus comme métriques post-correction.

## Tests et audits finaux

- Suite complète locale après le dernier changement :
  **183 tests passés sur 183** en 104,17 s.
- Audit ciblé ERP/séparation/appariement : **21/21**.
- Tests Llama sur l'instance : **17/17**.
- Le scan statique retrouve les implémentations mutantes listées plus haut et
  chacune possède une garde centrale ou Groovy.
- Les politiques constatées sont :
  `mode=evaluation`, `evaluation_lock=true`,
  `allow_erp_reads=true`, `allow_erp_writes=false`.

Commande de test locale :

```powershell
Set-Location -LiteralPath 'L:\Public\EMALO-Achats\EMALO-Repondeur'
& '.\.venv\Scripts\python.exe' -m pytest -q tests
```

Sur l'instance, lancer `pytest -q tests`, pas `pytest -q` à la racine :
un ancien dossier de sauvegarde root-only
`backups/pre-general-rules-20260813` provoque sinon une erreur de collecte
`PermissionError` sans rapport avec le code.

## Commandes d'évaluation à conserver

Préparer un manifeste sans cible depuis un processus privé :

```bash
cd /opt/emalo-repondeur-worker
sudo -n .venv/bin/python scripts/preparer_manifest_evaluation.py \
  --corpus /opt/emalo-autotune/private/corpus-temporal-2026-08-12-13-v2.json \
  --transcriptions resultats/transcriptions \
  --output evaluation/manifests/development-reprise.json \
  --splits development
```

Produire la prédiction déterministe comme `ubuntu`, sans accès au privé :

```bash
cd /opt/emalo-repondeur-worker
.venv/bin/python scripts/generer_predictions_evaluation.py \
  --manifest evaluation/manifests/development-reprise.json \
  --transcriptions resultats/transcriptions \
  --output evaluation/predictions/development-reprise.json \
  --work-dir evaluation/work/development-reprise \
  --workers 1 \
  --forbidden-path /opt/emalo-autotune/private
```

Lancer Llama sur une prédiction déjà figée, toujours sans privé :

```bash
sudo systemctl stop emalo-repondeur-worker.service
cd /opt/emalo-repondeur-worker
.venv/bin/python scripts/arbitrer_predictions_llama_local.py \
  --predictions evaluation/predictions/development-v3-balanced.json \
  --output evaluation/predictions/development-v3-llama70b-reprise.json \
  --checkpoint evaluation/predictions/development-v3-llama70b-reprise.checkpoint.json \
  --forbidden-path /opt/emalo-autotune/private \
  --batch-size 4 \
  --batch-catalogue-items 64 \
  --minimum-line-confidence 0.35 \
  --validation-confidence 0.80 \
  --timeout-seconds 240
```

Évaluer seulement après fermeture et sauvegarde de la prédiction :

```bash
cd /opt/emalo-repondeur-worker
sudo -n .venv/bin/python scripts/evaluer_predictions_sans_fuite.py \
  --corpus /opt/emalo-autotune/private/corpus-temporal-2026-08-12-13-v2.json \
  --predictions evaluation/predictions/development-v3-llama70b-reprise.json \
  --output /opt/emalo-autotune/private/development-v3-llama70b-reprise-score.json \
  --splits development
```

Après toute passe Llama, décharger le modèle et redémarrer le worker avec les
commandes de la section « État opérationnel ».

## Prochaines priorités

1. Ne pas toucher au holdout.
2. Régénérer une prédiction développement avec le code actuel afin de changer
   proprement l'empreinte applicative après la correction de conditionnement.
3. Si du temps de calcul est disponible, figer à l'avance un échantillon
   développement représentatif, ou utiliser les 43 audios, puis exécuter
   Llama une seule fois avec checkpoints. Ne choisir aucun audio à partir de
   sa vérité.
4. Comparer objectivement V3 et Llama sur
   `automation_order_accuracy`, contenu exact, lignes exactes, rappel et
   précision. Conserver Llama seulement si la généralisation progresse sans
   dégrader fortement la précision ni la latence opérationnelle.
5. Traiter ensuite, dans cet ordre, les familles encore dominantes :
   classement/récupération produit, faux segments, quantité/conditionnement,
   rejets internes, puis clients. N'ajouter que des règles générales ou des
   données réellement disponibles au moment de la commande.
6. Refaire tous les tests et l'audit statique, figer code/configuration/hash.
7. Une fois seulement le moteur définitivement gelé, exécuter une unique
   évaluation du holdout. Ne diagnostiquer ni corriger sur ce holdout.

## Fichiers importants créés ou modifiés pendant la passe

- sécurité : `src/erp_safety.py`, `config/erp-safety.json`,
  `copilote/erp_write_guard.groovy`, gardes dans
  `copilote_integration.py`, `electron_bridge.py`, `ui_repondeur.py`,
  `scripts/copilote_order.py`, scripts Groovy mutants ;
- anti-fuite : `src/evaluation_safety.py`,
  `config/evaluation-safety.json`, désactivation des profils/règles ES ;
- évaluation : `src/evaluation_metrics.py`,
  `scripts/preparer_manifest_evaluation.py`,
  `scripts/generer_predictions_evaluation.py`,
  `scripts/evaluer_predictions_sans_fuite.py`,
  `scripts/comparer_versions_evaluation.py`,
  `scripts/apparier_audio_commandes_independant.py` ;
- moteur général : `extraire_informations.py`, `src/clients.py`,
  `src/produits.py` ;
- Llama : `src/llama_product_resolver.py`,
  `scripts/arbitrer_predictions_llama_local.py` ;
- documentation : `docs/audit-securite-erp.md`,
  `docs/architecture-et-evaluation-sans-fuite.md` ;
- tests : `test_erp_safety.py`, `test_evaluation_sans_fuite.py`,
  `test_evaluateur_isole.py`, `test_appariement_independant.py`,
  `test_regles_generales_evaluation.py`,
  `test_llama_product_resolver.py` et la suite existante.

## Conclusion honnête

La passe a sécurisé l'ERP, isolé correctement la vérité, construit une
évaluation exigeante et amélioré nettement la précision des lignes du moteur
déterministe. Le Llama 70B local montre un gain très net sur cinq petits cas,
mais il n'existe pas encore de preuve représentative qu'il porte la commande
complète à 90 %. Le meilleur état complet et défendable reste V3 à 2,33 %
d'automatisation exacte ; le projet n'est donc pas au niveau production.
La prochaine reprise doit valider Llama sur le développement sans ouvrir les
20 audios finaux, puis n'utiliser le holdout qu'une seule fois après gel.

## Reprise Codex du 14 août 2026 (section la plus récente)

Cette section remplace l'état final ancien ci-dessus pour toute reprise.

- ANTIGRAVITY_NIGHT_STATE.json a été lu comme source de vérité des
  expériences Gemini.
- Exp 11 n'apportait aucun gain; Exp 12 régressait de 4 à 3 commandes
  strictement exactes. Leurs changements ont été intégralement annulés.
- La suite complète passe: **183/183** (145,42 s).
- Une prédiction neuve a été produite sur les **43 audios développement
  uniquement**, comme utilisateur ubuntu, avec le chemin privé interdit.
- Prédiction publique:
  evaluation/predictions/development-codex-exp10-restored.json
  (SHA-256
  1b76b2217aed8c53a71c1bdea9ca287ddb2af148ac3b339027a3a172ed035a67).
- Score privé:
  /opt/emalo-autotune/private/development-codex-exp10-restored-score.json.
- La reproduction est strictement identique à Exp 10:
  précision/rappel référence **73,05 % / 57,38 %**,
  précision/rappel ligne exacte **62,77 % / 49,30 %**,
  client **100 %**, date **97,67 %**, contenu et automatisation stricts
  **9,30 % (4/43)**, acceptation automatique **37,21 %**, aucun rejet interne
  d'une commande correcte.
- Causes restantes: faux produit 32, classement produit 31, quantité 18,
  recherche candidat 3, segmentation/ASR 1, date 1.
- Le holdout final de 20 audios n'a pas été ouvert.
- Le verrou ERP reste inchangé:
  mode=evaluation, evaluation_lock=true, lectures autorisées,
  écritures interdites.

Travail en cours: analyse agrégée des rangs candidats, faux segments et
conditionnements afin de tester une amélioration généralisable. Ne réintroduire
ni stemming final en s, ni bonus générique de contenant, ni suppression de
l'expression exacte en plus sans nouvelle preuve mesurée.

### Exp 13 conservée — conditionnements décimaux

- Fichiers moteur: src/produits.py et tests/test_quantites_classement.py.
- Correction générale: lecture du libellé brut pour préserver 2.5L/2,5L,
  prise en charge de 6X1L et 2K X5P, puis application de l'unité officielle.
- Tests: **186/186**.
- Prédiction:
  evaluation/predictions/development-codex-exp13-packaging-decimals.json
  (SHA-256
  5bf8854ecf90f8fbe704d219a8bc730d333345c75726f0565f4c76541d780c8c).
- Score:
  /opt/emalo-autotune/private/development-codex-exp13-packaging-decimals-score.json.
- Nouveau meilleur état: strict **9,30 % (4/43)** inchangé,
  précision/rappel référence **73,05 % / 57,38 %** inchangés,
  précision/rappel ligne exacte **64,54 % / 50,70 %**,
  divergences même-code quantité/unité **24 au lieu de 29**,
  erreurs de quantité par audio **17 au lieu de 18**.
- Aucun accès au holdout; aucune cible fournie au prédicteur; aucune écriture
  ERP.

Prochaine piste mesurée: la couverture/résolution produit. Sur les 177 lignes
encore manquantes, 97 n'exposent pas la bonne référence dans les candidats
publics et 44 l'exposent déjà aux rangs 1 à 3. Le Llama 70,6B existant doit
être évalué sur les 43 audios avec catalogue autorisé, sans vérité cible, puis
ses quantités doivent rester validées/recalculées par les règles officielles.

### Préflight Exp 14b — bug cadencier Llama corrigé

La première tentative Exp 14a a été arrêtée avant le premier audio complet et
avant toute évaluation. Le script utilisait directement le code client public
en minuscules pour lire un dictionnaire de cadenciers indexé en majuscules:
le Llama recevait donc **zéro historique client**.

Correction dans scripts/arbitrer_predictions_llama_local.py:

- normalisation casefold des clés client;
- fusion dédupliquée des entrées;
- lookup casefold du client prédit;
- test de non-régression ajouté.

Validation:

- **187/187 tests**;
- xipironanglet récupère 24 produits et 00010900 est bien marqué
  in_client_history avec ses statistiques de ventes;
- couverture catalogue autorisé: **359/359 références cibles**;
- historique client réellement disponible: **191/359 (53,20 %)**;
- parmi les lignes manquantes Exp 13: **68/177 (38,42 %)** sont dans
  l'historique client.

Artifacts Exp 14a conservés comme essai rejeté:
evaluation/development-codex-exp14-llama70b-full.log. Ne pas réutiliser son
checkpoint éventuel. La prochaine passe valide doit porter le nom Exp 14b.

## Résultat Exp 14b — Llama 70,6B avec historique client

La passe complète des 43 audios de développement est terminée. Elle part de
la prédiction Exp 13 figée, tourne sous l'utilisateur `ubuntu` avec
`/opt/emalo-autotune/private` déclaré interdit, et n'a reçu aucune vérité
ERP. Aucun chemin d'écriture ERP n'a été appelé.

Résultat mesuré après production de toutes les prédictions:

- durée: **10 870,983 s (3 h 01 min)**;
- 260 lignes prédites pour 359 lignes réelles;
- précision/rappel référence: **72,31 % / 52,37 %**;
- précision/rappel ligne exacte: **57,69 % / 41,78 %**;
- contenu exact: **6/43 (13,95 %)**;
- exact automatique: **3/43 (6,98 %)**;
- taux d'acceptation automatique: **25,58 %**;
- 7 réponses JSON de lots invalides, 57 lignes rejetées par validation;
- 38 divergences quantité/unité à référence identique.

Décision: **Exp 14b rejetée comme meilleur état**. Elle gagne deux commandes
au contenu exact, mais régresse nettement sur les métriques de ligne et sur
l'exact automatique. Le meilleur état reste **Exp 13**: 4/43 stricts,
précision/rappel ligne exacte 64,54 % / 50,70 %, précision/rappel référence
73,05 % / 57,38 %, acceptation 37,21 %.

Artifacts distants:

- `evaluation/predictions/development-codex-exp14b-llama70b-client-history.json`;
- checkpoint homonyme;
- SHA-256 prédiction:
  `09b304c750ce8c56cfc55cb0b0cb851e804b097aa29d8c01053a0eed6d9d72a0`;
- score privé:
  `/opt/emalo-autotune/private/development-codex-exp14b-llama70b-client-history-score.json`.

### Causes générales établies

1. La transcription complète est répétée dans chaque lot de quatre requêtes.
   Le modèle sort parfois des produits appartenant à d'autres lots, jusqu'à
   dix lignes, puis la consolidation crée des extras ou contamine les
   quantités.
2. Les sorties longues sont parfois tronquées à 768 jetons. Le client retente
   les erreurs réseau, mais pas encore les erreurs de décodage JSON.
3. Le nombre explicite de contenants peut être perdu au profit de la mesure
   interne du conditionnement, par exemple «deux bidons ... de 10 L».
4. Une unité proposée incorrectement par le modèle provoque le rejet de la
   ligne alors que l'unité officielle du catalogue doit faire autorité.
5. Le modèle peut inventer une quantité usuelle en l'absence de nombre
   prononcé; l'historique doit aider le classement, jamais fournir la
   quantité.
6. Le Llama récupère néanmoins de vraies omissions de segmentation depuis la
   transcription. La prochaine architecture doit donc conserver ce bénéfice
   tout en limitant chaque lot à ses clauses pertinentes.

### Prochaine expérimentation recommandée — Exp 14c

Réutiliser les expansions de requêtes déjà figées dans Exp 14b afin d'éviter
43 appels coûteux, puis:

- sélectionner pour chaque lot uniquement les clauses vocales liées à ses
  requêtes;
- refuser les lignes sans relation avec le lot;
- borner le schéma JSON et retenter un décodage tronqué;
- exiger une preuve numérique prononcée pour toute quantité;
- faire autorité à l'unité du catalogue;
- donner priorité au nombre explicite de contenants avant toute conversion de
  poids ou volume;
- smoke-tester ces garanties sur des entrées publiques, exécuter les tests,
  puis seulement relancer les 43 audios si la structure est saine.

Le holdout final de 20 audios n'a pas été ouvert. Le verrou central ERP reste
actif et ne doit jamais être désactivé.

## Exp 14c en cours — contexte ciblé et validations fermées

Implémentation et validation locale achevées:

- clauses vocales ciblées par lot, sans réécriture de la preuve;
- maximum d'une ligne par requête imposé dans le schéma JSON;
- nouvelle tentative avec budget croissant après JSON tronqué;
- rejet d'une ligne sans quantité explicitement prononcée;
- unité officielle du catalogue autoritaire;
- priorité au nombre explicite de contenants compatibles avec l'unité ERP;
- rejet d'un produit sans relation suffisante avec les requêtes du lot;
- **194/194 tests**.

Smoke GPU sur deux audios de développement, avec expansions Exp 14b
réutilisées:

- 2/2 audios terminés en **512,829 s**;
- zéro erreur JSON et zéro erreur de lot;
- jamais plus de quatre lignes pour quatre requêtes;
- contextes de lot réduits à 126–324 caractères sur le long audio;
- produit hors périmètre et quantité non prouvée effectivement rejetés;
- récupération des deux produits absents de la segmentation déterministe
  conservée.

La passe complète des 43 audios est active dans
`evaluation/predictions/development-codex-exp14c-focused-scope-v1.json`,
avec son checkpoint homonyme. Elle part d'Exp 13 et ne refait pas les
expansions Llama. Ne pas lancer une seconde copie en parallèle. Le meilleur
état officiel reste Exp 13 jusqu'à l'évaluation privée finale d'Exp 14c.

## Campagne d'Optimisation Déterministe et Hybride Additif (Août 2026)

À la suite de la revue des pistes d'optimisation, l'approche déterministe d'abord (Pistes C -> A -> E -> D -> B) a été menée, suivie de l'architecture hybride additive (Piste F).

### Résultats mesurés sur les 43 audios de développement

1. **Exp 15 (Piste C - Pluriels contenants & synonymes)** :
   - Normalisation des contenants pluriels et synonymes métier (`src/produits.py`, `config/synonymes-produits.json`).
   - Zéro régression, réduction des erreurs de classement produit de 32 à 31.

2. **Exp 16 & 16b (Piste A - Multiplicateurs $N \times \text{taille}$ & Incompatibilités)** :
   - Résolution du découpage sur `x`/`fois` (`10 x 1 kg`), capture de l'unité multiple et protection anti-fusion de conditionnements distincts.
   - Incompatibilité `famille_puree_contradictoire_avec_sucre` éliminant le faux positif de purée de framboise sur sucre semoule.
   - Résolution intégrale de la commande `LOPEZSJL` (3/3 lignes conformes).
   - **Commandes parfaites en contenu** : **5/43 (11,63 %)** (record absolu).
   - **Précision référence** : **73,24 %** | **Rappel référence** : **57,94 %**.
   - **Précision ligne exacte** : **64,79 %** | **Rappel ligne exacte** : **51,25 %**.
   - **Décision** : **CONSERVÉE — Nouvelle baseline déterministe de production**.

3. **Exp 17 & 17b (Piste F - Architecture Hybride Additive)** :
   - Base déterministe Exp 16b verrouillée et 100 % protégée (aucun remplacement). Llama intervient uniquement de façon additive sur les omissions de détection.
   - **Exp 17b (Filtrage sélectif)** :
     - **Rappel référence** : bondit à **64,90 %** (+6,96 %).
     - **Rappel ligne exacte** : bondit à **56,55 %** (+5,30 %).
     - **Précision référence** : 68,13 % | **Précision ligne exacte** : 59,36 %.
     - Toutes les 5 commandes parfaites et 4 commandes auto sont préservées.

4. **Exp 18b (Piste F3 bis - Hybride Sélectif Cadencier & Anti-Doublons)** :
   - Filtrage sémantique rigoureux sur les ajouts Llama (anti-doublon vocal, incompatibilités sémantiques, guidage cadencier).
   - Précision référence : **73,54 %** | Rappel référence : **59,61 %** | Précision exacte : **65,29 %** | Rappel exact : **52,92 %**.

5. **Exp 19 (Moteur Déterministe Flawless - 0 Faux Rejet Interne)** :
   - Élimination de l'ambiguïté résiduelle sur les commandes parfaites : exclusion des crêpes/gaufres lors des demandes de sucre semoule (écartant les marges artificiellement réduites) et non-blocage sur les mentions introductives sans quantité lorsque des lignes valides sont extraites.
   - **194/194 tests unitaires passés**.
   - **Faux rejets internes de commandes correctes** : **0 (Éliminés à 100 %)**.
   - **Commandes strictes automatiques** : **5/43 (11,63 %)** (100 % des 5 commandes parfaites en contenu sont désormais automatiquement acceptées).

6. **Exp 20 (Architecture Hybride Sélective Ultime)** :
   - Combinaison de la base déterministe flawless Exp 19 avec le filtre hybride sélectif cadencier.
   - Automatisation stricte : **11,63 % (5/43)** | Faux rejets internes : **0**.

7. **Exp 21 (Conversions Conditionnements & Portions Physiques)** :
   - Ajout des règles déterministes de conversion physique d'emballages :
     - Conversion des plaquettes en grammes vers KG quand l'unité de vente catalogue/ERP est le KG (ex. 8 plaquettes de 250g = 2 KG).
     - Résolution de la contenance unitaire des bacs/boîtes de glace artisanale (2.5L / 5L) vers 1 unité BOITE lorsque la mention porte sur la contenance du bac.
   - **Résultats mesurés sur les 43 audios de développement** :
     - **Exactitude d'automatisation stricte** : **11,63 % (5/43 commandes parfaites 100 % automatisées)**.
     - **Taux de faux rejets internes** : **0 (ZÉRO)**.
     - **Précision Références** : **73,54 % (Record historique préservé)**.
     - **Rappel Références** : **59,61 % (Record historique préservé)**.
     - **Précision Ligne Exacte** : **65,64 % (NOUVEAU RECORD HISTORIQUE ABSOLU)**.
     - **Rappel Ligne Exacte** : **53,20 % (NOUVEAU RECORD HISTORIQUE ABSOLU)**.
     - **Faux Produits** : **32** (aucun faux positif supplémentaire).
     - **Erreurs Classement Produit** : **29**.
   - **Décision** : **CONSERVÉE — Nouveau record historique absolu**.

## Reprise Claude du 17 août 2026 — Exp22 à Exp25 (reranking Top-N)

Cette section documente une reprise autonome (mandat : auditer une
contradiction de scoring, diagnostiquer Exp24 vs Exp21, puis poursuivre avec
Exp25+). Elle a été menée entièrement via SSH sur la copie de calcul
`/opt/emalo-repondeur-worker` (`ubuntu@51.210.2.253`), sans toucher au
holdout, sans fournir de vérité au prédicteur ni à Llama, sans écriture ERP.
`config/erp-safety.json` a été vérifié inchangé avant et après
(`evaluation_lock=true`, `allow_erp_writes=false`).

### Diagnostic de la contradiction de scoring

`evaluer_predictions_sans_fuite.py` (scorer officiel) et
`detailed_dev_error_breakdown.py` (diagnostic détaillé) appellent tous deux
la même fonction `evaluate_rows`/`compare_order` dans
`src/evaluation_metrics.py` : il n'existe donc **aucune divergence réelle de
définition**. La contradiction (« Strict automation = 0/43 » côté
diagnostic contre `automation_order_accuracy = 0.1628` côté scorer) venait
d'un bug de clé : `detailed_dev_error_breakdown.py` (et une seconde copie,
`print_all_dev_errors.py`) lisaient `r.get('automation_order_accuracy')` sur
une ligne individuelle, alors que cette clé n'existe que dans le dict
`metrics` agrégé — les lignes individuelles portent `automation_exact`. La
somme retournait donc toujours 0, quelle que soit la réalité. Corrigé dans
les deux scripts (copie locale `L:\...\scripts\` et copie distante
`/opt/emalo-repondeur-worker/scripts/`) ; après correction,
`detailed_dev_error_breakdown.py` affiche bien `Strict automation: 7/43`,
identique au scorer officiel. La définition canonique du strict automatique
(bon client + bonne date + multiensemble exact code/quantité/unité + statut
`VALIDEE`) était déjà correcte et identique partout ; aucune métrique n'a
été modifiée pour faire monter un score.

### Diagnostic Exp24 vs Exp21

Trois causes racines identifiées dans `scripts/fusion_hybride_topn.py`
(script Exp24, arbitrage Top-N à un appel Llama par ligne ambiguë) :

1. **Perte de la couche additive de rappel.** Le script reconstruit
   `row["lines"]` uniquement depuis `diagnostics.products`, ce qui
   supprime silencieusement la fusion additive cadencier-sélective
   (`fusion_hybride_additive.py`, Exp18b/20/21) — seule source du record de
   rappel d'Exp21. Exp24 n'est pas un raffinement d'Exp21, c'est un
   pipeline différent qui repart de la base déterministe pure. Rappel
   référence 59,61 % → 56,27 % ; rappel ligne exacte 53,20 % → 49,58 %.
2. **Fiabilité gonflée artificiellement.** Le flag `reliable` maison du
   script traite une ligne supprimée (réponse Llama « AUCUN ») comme une
   preuve de fiabilité, puisqu'une ligne absente ne peut jamais faire
   échouer son test `all(...)`. Cela remplace `determiner_statut_commande`
   (déjà validé, 0 rejet interne depuis Exp19) par un proxy trivialement
   satisfait : `automatic_acceptance_rate` bondit de 51,16 % à 97,67 % sans
   gain de justesse proportionnel (`order_content_accuracy` = 16,28 %
   seulement). Risque réel si ce taux devait un jour guider une
   soumission ERP automatique.
3. **Quantité/unité non revalidées après remplacement.** Quand Llama
   propose un nouveau code, la quantité/unité déterministe de l'ancien
   candidat est recopiée telle quelle, sans revalidation face au
   conditionnement officiel du nouveau code. Cas tracé en détail : la
   mention ambiguë « vinaigre bals[amique] » a pour bon code `00051270`,
   absent des 10 candidats offerts au LLM (défaillance de recherche en
   amont) ; Llama choisit par défaut `00051265` (vinaigre de xérès, déjà
   présent ailleurs dans la commande) → doublon de code avec une unité non
   revalidée. D'où l'apparition de la cause `unite_conditionnement`
   (0 → 9 occurrences) et une part de la hausse de `quantite` (16 → 18).

Le gain réel et généralisable d'Exp24 a été confirmé : sur les 2 commandes
devenues parfaites (`2026-08-12_18-13-33_De-Inconnu.wav` et
`2026-08-13_01-15-05_De-0686306294.wav`), Llama a correctement identifié et
supprimé un produit isolé issu d'une segmentation ASR bruitée
(« 1 majestique a saint jean de luce », « guethary rajoute commande de » —
des mentions de lieux/remplissage conversationnel mal segmentées), toutes
deux avec un score de confiance déterministe (`score_global`) très inférieur
à `SEUIL_PRODUIT_MIN` (60).

### Exp25 / Exp25b / Exp25c — reconstruction en troisième couche

Plutôt que corriger `fusion_hybride_topn.py` en place, une nouvelle couche
additive a été écrite (`scripts/fusion_hybride_topn_valide.py`) qui :

- part de l'artefact figé `development-exp21-ultimate-hybrid.json`
  (empreinte applicative `fcac66b2...`), contournant ainsi la régression
  Exp22 non résolue (voir ci-dessous) ;
- ne touche que les lignes issues de mentions déterministes ambiguës
  (`produit_fiable=False`), en laissant toutes les autres lignes
  (déterministe fiable + additions Llama cadencier-sélectives) strictement
  intactes ;
- revalide tout remplacement proposé par Llama via `valider_candidat_llama`
  (le même filtre sélectif déjà validé d'Exp18b, importé directement depuis
  `fusion_hybride_additive.py`) : autorité du référentiel/unité officielle
  recalculée pour le **nouveau** code, bornes de quantité, anti-doublon,
  incompatibilités sémantiques, seuil de chevauchement lexical
  cadencier-conscient (≥ 50 dans le cadencier, ≥ 75 hors cadencier) ;
- protège toute ligne déjà gardée dont `score_global ≥ SEUIL_PRODUIT_MIN`
  (60) contre une suppression fondée sur un seul verdict Llama « AUCUN »
  (garde ajoutée après un premier passage sans garde — voir ci-dessous) ;
  la suppression reste possible et autorisée en dessous de ce seuil, c'est
  le mécanisme qui recrée les 2 gains réels d'Exp24 ;
- ne touche **jamais** `row["status"]` pendant l'arbitrage : le statut reste
  entièrement celui, déjà validé, calculé par
  `extraire_informations.determiner_statut_commande` avant toute
  intervention Llama. `automatic_acceptance_rate` ne peut donc plus être
  gonflé par ce mécanisme.

Premier passage sans garde de score (43 audios, 60 appels Llama, 0 erreur) :
8 suppressions dont 3 se sont révélées être de vraies lignes correctes
supprimées à tort (`00051250` vinaigre de vin rouge, `00404831` burrata,
`00051760` noix — les trois avaient un `score_global` déterministe ≥ 60,
c'est-à-dire déjà jugées plausibles par le moteur avant même l'appel Llama).
Après ajout de la garde `score_global < SEUIL_PRODUIT_MIN`, seule la
suppression sur le cas « burrata » (score 30, en dessous du seuil) persiste
— un cas limite irréductible : la mention source (« chiffon brera ») n'a
quasiment aucun recouvrement lexical avec le libellé officiel malgré une
correspondance ERP correcte, un pur hasard de correspondance floue/ASR
qu'aucun signal disponible au moment de la décision ne permet de
distinguer d'un vrai faux positif sans consulter la vérité — ce qui est
exclu par construction.

Un second script (`scripts/exp25c_recompute_status.py`, sans aucun appel
réseau/LLM) recalcule ensuite le statut, mais **uniquement** pour les
mentions effectivement modifiées par la couche précédente, en rappelant
`extraire_informations.construire_lignes_commande` — la vraie fonction de
production — sur une copie ajustée de `diagnostics.products`. Le recalcul
est strictement *upgrade-only* (`PROBLEMATIQUE → VALIDEE` seulement, jamais
l'inverse) : 3 commandes ont été mises à niveau, dont 1 des 2 nouvelles
commandes à contenu parfait (l'autre reste bloquée par une mention non
liée, distincte, encore ambiguë ailleurs dans la même commande — comportement
prudent et correct, pas un bug).

**Résultat final (`development-exp25c-topn-valide-status.json`, SHA-256
`afae17a5b5b0305b7788241977b742a0c542cf0a80bf1f7efb55b091631098ea`) :**

| Métrique | Exp21 | Exp24 (rejetée) | **Exp25c (retenue)** |
| --- | ---: | ---: | ---: |
| Précision référence | 73,54 % | 68,71 % | **74,20 % (record)** |
| Rappel référence | 59,61 % | 56,27 % | 58,50 % |
| Précision ligne exacte | 65,64 % | 60,54 % | **66,43 % (record)** |
| Rappel ligne exacte | 53,20 % | 49,58 % | 52,37 % |
| Commandes contenu parfait | 5/43 | 7/43 | **7/43** |
| Commandes auto parfaites | 5/43 | 7/43 (gonflé) | 6/43 (honnête) |
| Taux d'acceptation auto | 51,16 % | 97,67 % (gonflé) | 58,14 % (honnête) |

Les deux précisions battent le record Exp21 ; les deux rappels restent
légèrement en dessous (-1,11 et -0,83 point), expliqué par le cas limite
« burrata » ci-dessus et par une variance mesurée entre deux lancements
Llama strictement identiques (température 0, seed 0 non parfaitement
reproductible sur ce backend Ollama — un audio a gagné une ligne vraie,
un autre en a perdu une par pur aléa de génération, sans lien avec la
garde de score). L'objectif « restaurer au minimum les métriques de ligne
d'Exp21 » est donc atteint sur 2 des 4 métriques (avec record), et manque
de peu sur les 2 autres, sans régression systémique.

### Régression Exp22 non corrigée (piste Exp26)

Une régression distincte, non liée au reranking Top-N, a été localisée
sans être corrigée faute de sauvegarde pré-modification permettant un
diff ciblé : entre Exp21 et Exp22, le moteur déterministe
(`extraire_informations.py` / `src/produits.py`, empreinte applicative
passée de `fcac66b2...` à `d0cdfbb1...`) a réintroduit un rejet interne
sur une commande par ailleurs 100 % correcte
(`2026-08-12_12-42-47_De-0559268233.wav`, client mundacap) : les deux
lignes SUCRE SEMOULE (1K et 25K), toutes deux correctement résolues,
déclenchent désormais `produit_ambigu`/`produit_non_fiable`. Hypothèse :
une pénalité de confiance croisée quand deux conditionnements très
proches du même produit coexistent dans la même commande — un cas
légitime fréquent chez ce type de client. Exp25 contourne le problème en
repartant de l'artefact figé Exp21 plutôt que de régénérer depuis le
moteur courant ; une future passe (Exp26+) devrait localiser précisément
et corriger cette pénalité (zones candidates : `src/produits.py` autour
des blocs `ambigu = True`, lignes ~2700-2970 et ~4880-4920) avant de
regénérer une prédiction depuis le code courant.

### État opérationnel laissé en place

- `ollama stop llama3.1:70b` exécuté, VRAM libérée (0 Mio utilisé avant
  redémarrage du worker).
- `emalo-repondeur-worker.service` redémarré et actif sur `127.0.0.1:8787`.
- `config/erp-safety.json` inchangé : `mode=evaluation`,
  `evaluation_lock=true`, `allow_erp_reads=true`, `allow_erp_writes=false`.
- Le holdout de 20 audios n'a pas été ouvert.
- Nouveaux fichiers : `scripts/fusion_hybride_topn_valide.py`,
  `scripts/exp25c_recompute_status.py` (copiés localement et sur la copie
  de calcul). Corrections : `scripts/detailed_dev_error_breakdown.py`,
  `scripts/print_all_dev_errors.py` (bug de clé `automation_order_accuracy`
  → `automation_exact`, local et distant).
- Prédiction retenue :
  `evaluation/predictions/development-exp25c-topn-valide-status.json`.
- Score privé :
  `/opt/emalo-autotune/private/development-exp25c-topn-valide-status-score.json`.
- `ANTIGRAVITY_NIGHT_STATE.json` mis à jour (historique Exp22-25, champs
  `best_*` alignés sur Exp25c), synchronisé sur les deux copies.

## Reprise Claude (suite, même journée) — changement de priorité et Exp26

L'utilisateur a explicitement changé la priorité de la phase : **atteindre
au moins 90 % de précision produit ET 90 % de rappel produit par des
méthodes généralisables**, avant de reprioriser le strict commande/
quantité/unité. `best_*` dans `ANTIGRAVITY_NIGHT_STATE.json` continue de
pointer vers Exp25c (état complet le plus défendable) ; Exp26 est un
diagnostic + correctif de la chaîne de reconnaissance produit, pas encore
refusionné avec la couche additive/Top-N.

### Diagnostic Top-N (côté évaluateur uniquement, artefacts Exp21/Exp25 non modifiés)

Nouveau script `scripts/diagnostiquer_topn_candidats.py`. Rappel candidat
sur les 359 lignes vérité development, identique entre Exp21 et Exp25 (la
sélection finale diffère, pas le pool de candidats) :

| | Top-1 | Top-3 | Top-5 | Top-10 |
|---|---:|---:|---:|---:|
| End-to-end | 59,89 % | 70,19 % | 74,09 % | 78,55 % |
| Conditionnel (hors 1 audio à 0 segment) | 60,22 % | 70,59 % | 74,51 % | 78,99 % |

Causes des 145 lignes manquantes au niveau code (comptes absolus) :
`recherche_candidats_insuffisante` 62, `present_top5_mauvais_top1` 52,
`present_top10_absent_top5` 16, `omission_segmentation_probable` 13,
`aucun_segment_produit_cree` 2. Top-10 très inférieur à 95-98 % → par la
règle de décision donnée, priorité à la recherche/génération de candidats,
pas au ranking ni à la segmentation (10,3 % seulement des manques).

### Exp26 — recherche catalogue global toujours exécutée (CONSERVÉE)

Root cause tracée avec un sous-agent puis vérifiée manuellement sur deux
cas réels (`MOUTARDE 5K` vs `MOUTARDE ANCIENNE 1K` ; `PIMENT ESPELETTE AOP
40G` vs `...1K`) : dans `chercher_produits` (`src/produits.py`), la
recherche du catalogue global était **entièrement sautée** dès qu'un
article du cadencier client atteignait `score_global >= 95` — y compris
quand cet article était la mauvaise variante de conditionnement (`MOUTARDE
ANCIENNE 1K` scorait exactement 100). Correctif : la recherche globale
s'exécute désormais toujours en complément du cadencier. Test de
non-régression ajouté
(`test_score_cadencier_parfait_n_empeche_pas_recherche_catalogue_global`).
195/195 tests passés. Impact performance négligeable (395,4 s vs 391,5 s
de base). Résultat sur la prédiction déterministe pure régénérée
(`development-exp26-catalogue-global-toujours.json`, empreinte
`ae960620...`) : **zéro régression** (73,24 % / 57,94 %, identique à
`development-exp21-deterministic.json`), plafond Top-10 en légère hausse
(78,55 % → 79,39 %), `recherche_candidats_insuffisante` 62 → 59. Nécessaire
mais pas suffisant seul : `MOUTARDE 5K` apparaît désormais candidate (rang
7, score 97,63) mais la sélection finale choisit toujours la variante
cadencier à cause du bonus fixe détaillé ci-dessous.

### Exp26b — tentative sur la sélection finale, REJETÉE et annulée immédiatement

`_score_selection_ponderee` ajoute un bonus **fixe et inconditionnel de
+40** pour tout candidat `dans_cadencier_client`, assez grand pour écraser
un écart de `score_texte` de quelques points même quand le catalogue
global correspond mieux au texte prononcé. Le garde-fou existant de
`_selectionner_meilleur_candidat` ne rattrape ce cas que si le cadencier
est *faible* (`score_texte <= 68`) ; il ne couvrait pas le cas où les deux
candidats sont forts (93,57 vs 97,63 dans l'exemple moutarde). Tentative :
élargir ce garde-fou pour basculer aussi quand le candidat global a un
`score_texte` égal ou supérieur au meilleur candidat cadencier. **Résultat :
régression sévère et large** — précision référence 73,24 % → 61,19 %
(-12,05 points), rappel référence 57,94 % → 48,75 % (-9,19 points), sur
l'ensemble des 43 audios, pas seulement les 2 cas ciblés. Le bonus +40 est
chargé de sens sur un grand nombre de mentions courtes/génériques du
corpus ; une comparaison brute de `score_texte` est beaucoup trop
permissive et bascule à tort de nombreuses sélections cadencier
auparavant correctes. **Modification intégralement annulée** dès cette
première mesure — le code sur disque ne contient que le correctif Exp26,
pas cette tentative. Piste de correction plus ciblée pour Exp27 : utiliser
un signal explicite (mot-contenant prononcé — seau/sachet/bidon/carton —
ou format de quantité comparé au conditionnement officiel du candidat)
plutôt qu'une simple comparaison de `score_texte`, et valider sur plusieurs
cas avant tout déploiement large.

### Reproductibilité Llama (documenté, aucun changement appliqué)

Ollama 0.32.9 ; nos scripts passent `temperature=0.0, seed=0` explicitement
; le Modelfile de `llama3.1:70b` ne fixe que des `stop` sequences (pas de
`top_k`/`top_p`/`repeat_penalty` custom, donc défauts Ollama/llama.cpp).
Une divergence réelle a été mesurée entre deux lancements strictement
identiques (Exp25 vs Exp25b non gardé) sur au moins 2 audios — limite
connue de l'inférence GPU batchée (llama.cpp/Ollama) : `seed`/
`temperature=0` ne garantissent pas un résultat bit-identique d'une
invocation serveur à l'autre. Recommandation pour comparaisons futures :
`OLLAMA_NUM_PARALLEL=1` côté serveur + `top_k:1` explicite en défense, et
ne jamais interpréter un delta <~1 point entre deux runs Llama comme
significatif sans réplication.

### État laissé en place

- `src/produits.py` : correctif Exp26 uniquement (recherche catalogue
  global toujours exécutée). La tentative Exp26b est annulée, absente du
  code.
- Nouveaux fichiers : `scripts/diagnostiquer_topn_candidats.py` (local et
  distant) ; nouveau test dans `tests/test_produits.py`.
- 195/195 tests passés sur le code actuellement sur disque.
- Prédictions de diagnostic (non gelées comme référence, à la différence
  d'Exp21/Exp25) :
  `evaluation/predictions/development-exp26-catalogue-global-toujours.json`,
  `development-exp26b-selection-corrigee.json` (issue de la tentative
  rejetée, conservée pour audit uniquement, ne pas réutiliser comme base).
- Scores privés :
  `/opt/emalo-autotune/private/development-exp26-catalogue-global-toujours-score.json`,
  `/opt/emalo-autotune/private/development-exp21-deterministic-score.json`
  (généré pour comparaison directe, même mode `deterministic_no_network_no_llm`),
  `/opt/emalo-autotune/private/development-exp26b-selection-corrigee-score.json`
  (tentative rejetée),
  `/opt/emalo-autotune/private/topn-diagnostic-exp21-exp25-v2.json`,
  `/opt/emalo-autotune/private/topn-diagnostic-exp26.json`.
- Holdout de 20 audios non ouvert ; aucune vérité fournie au prédicteur, au
  générateur de candidats, au ranking ni à Llama ; aucune écriture ERP ;
  `config/erp-safety.json` inchangé.

## Chantier règles métier sûres — clôture Codex du 20 août 2026

Le meilleur état courant est `development-safe-rules-final`. L'évaluation a
été produite à partir des 43 transcriptions development gelées, sans réseau ni
LLM, puis scorée seulement après enregistrement de la prédiction. Le holdout de
20 audios n'a pas été ouvert.

Baseline du chantier : 288 lignes prédites pour 359 vraies, précision/rappel
référence 80,90 % / 64,90 %, précision/rappel ligne exacte 70,83 % / 56,82 %,
10 commandes parfaites en contenu et 8 automatiques strictement exactes.

État final : 289 lignes, précision/rappel référence **82,35 % / 66,30 %**,
précision/rappel ligne exacte **72,32 % / 58,22 %**, 12 commandes parfaites en
contenu, 10 automatiques strictement exactes (23,26 %). Transition exacte face
à la baseline : **5 TP gagnés, 0 TP perdu, 5 FP retirés, 1 FP ajouté**. Six
décisions produit sur six audios ont changé.

Décisions individuelles :

- KEEP `conditionnement_physique_sur` v2 : seul gain mesuré, chiffres ci-dessus.
- KEEP `relations_semantiques_variantes` : 0 décision development modifiée ;
  cas ciblé coulis exotique couvert par test, borné au même noyau.
- KEEP `telephone_exact_verrouille` v2 : 0 décision development modifiée. Les
  alias confirmés verrouillent ; un téléphone `info-clients` cède uniquement
  devant une identité nom + ville forte, pour gérer les numéros obsolètes.
- KEEP `contexte_enumeration_ambigu`, `reappro_attribut_explicite` v2,
  `product_gate_noyau` v2 et `historique_modificateur` : chacun 0 décision
  development modifiée, tous couverts par des tests ciblés.
- ROLLBACK et drapeau final `false` pour `reappro_variante_intra_famille` :
  0 TP gagné, 1 TP perdu, 3 FP ajoutés, 1 FP retiré.
- Tentatives intermédiaires rejetées : Réapro attribut v1 (0 TP gagné, 1 perdu,
  4 FP ajoutés, 2 retirés) ; product gate v1 (0 TP gagné, 5 perdus, 2 FP
  retirés). Leurs versions sûres v2 sont neutres.

Fichiers principaux : `src/product_hierarchy.py`, `src/business_rules.py`,
`src/produits.py`, `src/clients.py`, `extraire_informations.py`,
`config/regles-metier-sures.json`, `config/aliases-telephoniques-confirmes.json`
et `tests/test_regles_metier_sures.py`. L'alias confirmé demandé est
`0609549702 -> PLANBID`. Le générateur d'évaluation inclut désormais les deux
nouvelles configurations dans `application_fingerprint`.

Artefacts :

- prédiction finale :
  `evaluation/predictions/development-safe-rules-final.json`, SHA-256
  `d8b264345525e26c4a8dedcfb9dac9c05c86b5e7d81c37d3185eca30b0ce2c0c` ;
- score privé :
  `/opt/emalo-autotune/private/development-safe-rules-final-score.json`,
  SHA-256 `a5cd2477c9942dd48e1cd2a972958ea2c3fb3ac40d0586063eeef6bbb788a684`.

Tests : 60/60 tests ciblés et sécurité passent ; la suite globale donne
276 succès et 12 échecs déjà présents dans l'état antérieur (segmentation
Belloteka, anciens contrats de ranking/client et deux appels positionnels à
`chercher_produits`). Aucun nouvel échec n'a été introduit par ce chantier.

Sécurité finale vérifiée localement et sur l'instance : `mode=evaluation`,
`evaluation_lock=true`, `allow_erp_writes=false`. Chaque artefact de prédiction
porte `truth_received_by_predictor=false` et `erp_write_attempted=false`.

## Correctifs de resolution produit — KEEP du 20 aout 2026

Perimetre strict : classement et recherche de candidats produit uniquement.
Ni segmentation, ni reconnaissance client, ni UI, ni logique ERP n'ont ete
modifies par ce chantier. Le verrou ERP reste actif.

Mecanismes conserves :

- Dans une veritable enumeration de parfums de glace, les accords simples
  ASR (`carameles`) sont ramenes vers leur saveur (`caramel`). Un noyau
  explicite tel que `poivrons caramelises` reste prioritaire.
- Un attribut explicite de variante bloque un candidat contradictoire :
  `cassis` ne devient pas `cerise`, `pistache` ne devient pas `coco`. Le
  cadencier reste un departageur parmi les candidats compatibles.
- Le secours phonetique accepte uniquement un fragment ASR opaque de trois
  caracteres au plus, apres ancrage de famille. Ainsi `vinaigre de XRF` peut
  trouver `vinaigre de Xeres`, sans fuzzy global ni detourner une creme.
- Le referentiel officiel devient un dernier recours uniquement s'il y a au
  moins deux ancrages explicites, par exemple `pistache hachee`. Le meme
  garde-fou empeche un prior cadencier sans ancrage de battre un candidat
  precis a deux ancrages.

Validation A/B reelle, sur les 43 transcriptions `development` gelees, sans
LLM ni reseau. La passe OFF desactivait seulement ces quatre mecanismes avec
`EMALO_DISABLED_BUSINESS_RULES`; la passe ON utilise le code final. La verite
ERP n'a ete lue que par le scoreur apres enregistrement de chaque prediction.

| Metrique | OFF | ON final |
| --- | ---: | ---: |
| Precision reference | 81,94 % | **82,29 %** |
| Rappel reference | 65,74 % | **66,02 %** |
| Precision ligne exacte | 72,22 % | **72,57 %** |
| Rappel ligne exacte | 57,94 % | **58,22 %** |
| Commandes strictement automatiques | 10/43 | 10/43 |

Transition exacte : **+1 TP, -1 FP, 0 TP perdu, 0 FP ajoute**. La decision
modifiee est generale : `12 flacons verseurs souples` quitte un faux candidat
cadencier sans ancrage pour `00120161 FLACON VERSEUR SOUPLE 400ML`.

Rejeux de controle sans verite :

- JOLIES GLACES : `2 carameles` -> `00020295`, glace caramel ;
- GAUA : cassis -> `00011303`, pistache hachee -> `P0003668`, creme 35 %
  reste `00401206` ;
- BARMADA : `vinaigre de xrf` -> `00051265 VINAIGRE DE XERES 1L`.

Artefacts de reprise sur l'instance :

- prediction finale :
  `/opt/emalo-repondeur-worker/evaluation/predictions/development-regles-generales-v2.json`,
  SHA-256 `6dc2afdafac54b94f80c0411dd5da46ca80cc4c50812a78e281353e61d13e68b` ;
- score prive post-prediction :
  `/opt/emalo-autotune/private/development-regles-generales-v2-score.json`,
  SHA-256 `a833474d913f1d4a8464c42dc3f13545eb3ef4ceb92039c94eccccfd3eece982` ;
- empreinte applicative :
  `7c12579ff5685b1de5f80cbcfbd8f4edf2a463fd3deff5efee5a031cc05d9ff3`.

Tests de ce chantier : **40/40** ciblés passent. La suite globale conserve
l'echec Belloteka preexistant dans `tests/test_belloteka_regressions.py`
(extraction de faux spans avant le matching) ; il est hors perimetre et le
handoff precedent documentait deja les echecs globaux historiques.

## Barriere structurelle anti-faux-produits — KEEP du 21 aout 2026

Cause traitee : les dates, presentations client, phrases de commande et
en-tetes d'enumeration pouvaient atteindre le matching avant d'etre classes.
Le cadencier/historique leur attribuait alors parfois une vraie reference.

Etat final v3 dans `src/produits.py` :

- le nombre d'une date jour+mois est neutralise avant le parseur de quantite,
  mais `demain` et les jours de semaine restent disponibles pour borner les
  introductions et queues de livraison ;
- les presentations d'etablissement et `X de chez Y` sont classees CLIENT
  avant le matching ;
- les flexions regulieres des verbes de discours, dont `souhaitais completer
  ma commande`, sont classees ORDER_DISCOURSE sans liste de phrases exactes ;
- un en-tete non quantifie (`avec des glaces...`) n'est pas une ligne lorsqu'il
  est suivi d'au moins deux elements quantifies ; il continue de transmettre
  le contexte de famille aux vrais elements ;
- une sous-clause produit quantifiee est extraite avant de rejeter le preambule
  client/livraison, ce qui preserve `Maison Amae ... 6l de lait` et le dernier
  `guacamole ... pour mercredi`.

Le cas reel `2026-08-21_00-27-37_De-0615671299` produit exactement 7 mentions
(chocolat, pistache, mangue, citron vert, framboise, caramel sale, vanille),
contre 10 auparavant. Aucune ligne n'est creee pour Maison Tenoy, la phrase de
complement ou `21 aout avec des glaces en tholin`.

Deux versions intermediaires ont ete rollbackees : v1 supprimait trop de
contexte temporel et perdait lait/guacamole ; v2 perdait encore le lait colle
au preambule client. Ne pas les restaurer.

A/B final sur les 43 transcriptions development gelees, face a la version
immediatement precedente `development-asr-alias-context-v1` :

| Metrique | Avant | V3 KEEP |
| --- | ---: | ---: |
| Precision reference | 80,62 % | **80,97 %** |
| Rappel reference | 64,90 % | **65,18 %** |
| Precision ligne exacte | 71,28 % | **71,97 %** |
| Rappel ligne exacte | 57,38 % | **57,94 %** |
| Commandes parfaites contenu | 12 | 12 |
| Commandes automatiques exactes | 10 | 10 |

Transition : **1 TP gagne, 0 TP perdu, 1 FP retire, 0 FP ajoute**, et 2 lignes
exactes gagnees. Tests ciblant segmentation, dates, glaces, formulations et
verrou ERP : 38/38 sur l'instance ; 45/45 pour la barriere et regressions de
segmentation localement. Suite globale sur l'instance : **220 succes, 16
echecs** dans les anciens contrats Belloteka/ranking/client/conditionnement ;
aucun echec ne concerne le nouveau fichier de tests ni les cas de regression
du chantier. Cette suite etait deja non verte avant ce chantier : ne pas
presenter les 16 echecs comme introduits par la barriere sans A/B specifique.

Artefacts sur l'instance :

- prediction :
  `evaluation/predictions/development-nonproduct-gate-v3-w8.json`, SHA-256
  `342b5d183e8814a3bf62001f8b5d1f4297d33c09a5d4cac9e9bc147d9f62c227` ;
- score prive post-prediction :
  `/opt/emalo-autotune/private/development-nonproduct-gate-v3-w8-score.json`,
  SHA-256
  `a222832c91566e627e0b53612ec37b3ee22a072bb50aa33d3176a4628376c475` ;
- mode `deterministic_no_network_no_llm`, 43 audios, 8 workers, 394,116 s,
  `truth_received_by_predictor=false`, `erp_write_attempted=false`.

Holdout final non ouvert. Le verrou ERP reste `mode=evaluation`,
`evaluation_lock=true`, `allow_erp_writes=false` localement et sur l'instance.

## Priorite de parfum glace et alias Ruisseau — KEEP du 21 aout 2026

Cause du cas reel ARCBAY : `deux packs de glace vanille` classait d'abord
`00020240 MENTHE CHOCOLAT`, article du cadencier, devant plusieurs vanilles du
catalogue pourtant a 100 de score texte. Le bonus historique/cadencier
masquait donc l'attribut explicitement prononce.

Etat final dans `src/produits.py` :

- vocabulaire generique de parfums, sans code article attendu ;
- action uniquement si mention et candidats sont deja des glaces/sorbets ;
- le gagnant d'origine doit venir du cadencier et la ligne doit deja etre
  fiable avant la regle ;
- l'alternative doit porter le parfum prononce, atteindre au moins 98 de score
  texte et depasser le gagnant d'au moins 15 points ;
- remplacement 1-pour-1, sans creer de candidat ni rendre une ligne fiable ;
- si plusieurs mentions avaient le meme code d'origine, la correction est
  annulee pour ne pas deconsolider une enumeration dont les quantites ne sont
  pas encore arbitrees.

Tentatives rejetees : le filtrage semantique global perdait 14 TP reference.
Le filtrage limite aux glaces gagnait des codes mais ajoutait des lignes non
exactes. La version 1-pour-1 sans verrou d'enumeration gagnait 2 TP reference,
0 TP perdu et 0 faux code, mais separait deux mentions avec des quantites
incorrectes (+2 FP ligne exacte). Le verrou final annule exactement ces deux
activations sur development.

A/B controle sur le meme code avec uniquement
`parfum_glace_explicite_prioritaire` OFF, puis passe finale exacte :

| Metrique | OFF controle | Final KEEP |
| --- | ---: | ---: |
| Lignes predites | 270 | 270 |
| Precision reference | 82,22 % | 82,22 % |
| Rappel reference | 61,84 % | 61,84 % |
| Precision ligne exacte | 71,85 % | 71,85 % |
| Rappel ligne exacte | 54,04 % | 54,04 % |
| Commandes parfaites contenu | 11 | 11 |
| Commandes automatiques exactes | 11 | 11 |

Comparaison ligne par ligne : **0 audio modifie** sur les 43 transcriptions
development. Le holdout est reste ferme. La baisse face a l'ancien artefact
`development-nonproduct-gate-v3-w8` ne doit pas etre attribuee a cette regle :
plusieurs autres correctifs avaient modifie le code entre les deux artefacts ;
l'A/B controle ci-dessus est la comparaison causale valide.

Rejeu reel UI, sans verite ERP :

- `2026-08-21_00-05-07_De-0633283240.wav` conserve le statut `VALIDEE` et
  produit maintenant `00020149 5L VANILLE ESSENTIELLE`, `4 BOITE`, pour
  `2 packs de glace vanille` ;
- l'UI a ete regeneree apres le rejeu ; aucun envoi ERP n'a ete appele.

Alias telephone confirme ajoute dans
`config/aliases-telephoniques-confirmes.json` :
`0678649622 -> RUISSBIDART / LE RUISSEAU MS EXPLOITATION`. Le numero existait
deja exactement dans `info-clients`, mais l'alias confirme lui donne la
priorite maximale et persistante. Rejeu UI du dernier audio du numero : client
`RUISSBIDART`, decision automatique, commande `VALIDEE`.

Alias telephone confirme ajoute le 21 aout 2026 :
`0786564042 -> XISTERA / CHISTERA ET COQUILLAGES`. Le code, le nom et la ville
`BIARRITZ` ont ete verifies dans `info-clients.xlsx`. Rejeu UI en lecture seule
de `2026-08-21_00-07-23_De-0786564042.wav` : client `XISTERA`, commande
`VALIDEE`, meme avec la transcription ASR approximative `Acheteria et
Coquillages`. Aucun envoi ERP n'a ete appele.

Tests : 56/56 ciblant produit/glaces/consolidation passent ; 42/42 ciblant
alias, verrou ERP et absence de fuite passent ; suite globale locale : 309
succes et 15 echecs historiques deja documentes (Belloteka, anciens contrats
client/ranking, appels positionnels historiques), aucun dans le nouveau test.
Sur l'instance apres redemarrage : worker `active`, 37/37 tests cibles et
securite passent.

Artefacts finaux sur l'instance :

- prediction :
  `evaluation/predictions/development-frozen-flavor-safe-final.json`, SHA-256
  `2692886afd8d8e00d7043f601d8d9ba5c9b0995c1b67a7d7868d0a88f253b3aa` ;
- score prive :
  `/opt/emalo-autotune/private/development-frozen-flavor-safe-final-score.json`,
  SHA-256 `7e52caed86e7a4b00247efe301861e754643523f99d51d797e7dcf57d751c4c3` ;
- empreinte applicative :
  `834dfe1d1a713e723862559a05681882187b263db73fa7b810bf23ce136e02af` ;
- mode `deterministic_no_network_no_llm`, 43 audios, 8 workers, 401,776 s,
  `truth_received_by_predictor=false`, `erp_write_attempted=false`.

Securite finale revalidee apres deploiement : `mode=evaluation`,
`evaluation_lock=true`, `allow_erp_reads=true`, `allow_erp_writes=false`.

## BIBAMPIZZ : telephone confirme et homonyme ASR — KEEP du 24 aout 2026

Cas reel : `2026-08-21_00-00-38_De-0686843096.wav`. Whisper produit
`Bibim Pits`. Sans telephone confirme, le moteur donnait `60,0` au court
`BIBAM` mais seulement `5,83` a `BIBAMPIZZ`; le cadencier beaucoup plus riche
de `BIBAM` amplifiait ensuite ce mauvais prior.

Corrections conservees :

- `0686843096 -> BIBAMPIZZ / BIBAMPIZZ` dans la table persistante des alias
  confirmes, avec verrouillage avant tout matching de nom ;
- signature consonantique uniquement dans le score contextuel enseigne+ville,
  pour les noms ayant au moins cinq consonnes. Les voyelles et espaces ASR
  peuvent varier, et `ts`/`zz` sont rapproches. Une ville compatible reste
  obligatoire et un nom court/prefixe ne peut pas activer ce signal.

Rejeu UI en lecture seule : client `BIBAMPIZZ`, statut `VALIDEE`, seulement
deux lignes (`00441310` creme, 6; `00406110` oeufs, 1). La fausse ligne issue
de `35 % de matiere grasse` disparait avec le bon cadencier.

Validation : 32/32 tests cibles; worker `active`; passe developpement finale de
43 audios en 401,414 s, mode `deterministic_no_network_no_llm`,
`truth_received_by_predictor=false`, `erp_write_attempted=false`. Comparaison
avec `development-frozen-flavor-safe-final` : un audio modifie, aucun TP perdu,
une fausse ligne `demi jambon serrano` retiree. Precision reference
`82,22 % -> 82,53 %`; precision ligne exacte `71,85 % -> 72,12 %`; rappels,
clients et commandes parfaites inchanges. Holdout ferme, aucune ecriture ERP.

Artefacts :

- prediction `evaluation/predictions/development-bibampizz-client-safe-final-20260824.json`,
  SHA-256 `e1789a9b420be9c14dd6e2782f3413d6952b2017307eefdcb1ab3a1e9f930e8b` ;
- score prive `/opt/emalo-autotune/private/development-bibampizz-client-safe-final-20260824-score.json`,
  SHA-256 `a577e7b96b2bd85968e2989025b8377362e46b428b668ea47cc5f4b9d5367ea1` ;
- empreinte applicative
  `e16887197a3edf3259c900eb42eeb9f225a40812458e1a327bc3e081e6f5914d`.

## UI prod et remarques par audio - 24 aout 2026

Chantier limite a l'interface, sans modification du moteur produit/client et
sans appel d'ecriture ERP.

- `app-desktop/renderer/prod.html` ne depend plus de Tailwind CDN ni de Google
  Fonts. La connexion et l'ecran principal sont entierement rendus localement.
- Les commandes et problemes sont indexes une fois par audio. La recherche est
  temporisee et seulement 40 audios sont rendus par lot, au lieu de reconstruire
  les 4 067 lignes a chaque frappe. Test navigateur : 40 cartes/40 champs de
  remarque, environ 1,3 s au premier affichage, aucun appel externe.
- Chaque audio possede un champ `Remarque` visible et un bouton `Enregistrer`.
  Les brouillons survivent aux rerendus de la page et une fermeture avec des
  brouillons non enregistres declenche un avertissement.
- Les remarques sont conservees par cle audio dans
  `resultats/remarques-audios/remarques_audios.json`. Le module
  `src/audio_notes.py` utilise un verrou inter-processus et un remplacement
  atomique. Une remarque vide supprime uniquement l'entree concernee.
- Ponts disponibles : `electron_bridge.py load-audio-notes` et
  `electron_bridge.py save-audio-note <payload-base64>`. Le meme mecanisme est
  accessible depuis l'UI navigateur via `/api/run`.
- `preload-prod.js` est maintenant inclus dans les fichiers du build Electron.

Validation : enregistrement puis suppression reels depuis l'UI verifies ;
`tests/test_audio_notes.py`, `tests/test_prod_ui_notes.py` et
`tests/test_erp_safety.py`, 14/14 succes. Le verrou ERP n'a pas ete desactive et
aucune commande n'a ete envoyee.

## Clients forts et formats de bacs - KEEP du 24 aout 2026

Corrections bornees conservees :

- `0763003079 -> BAHIABID / RESTAURANT LE BAHIA BEACH` dans la table des
  alias confirmes, apres 6 transcriptions concordantes sur 6 ;
- un nom phonetique distinctif (score >=95, au moins deux tokens) n'est plus
  evince du top N par de simples correspondances de ville ;
- une enseigne explicitement annoncee apres une date initiale est recuperee
  dans une zone bornee avant l'intention de commande ou la premiere quantite ;
- la quantite glace reutilise la contenance structuree extraite du libelle
  brut. Un decimal sans unite egal a la taille du bac (`2.5 citron`) devient
  un bac, mais une quantite commerciale explicite (`5 boites`) reste cinq.

Evaluation deterministe sur les memes 43 transcriptions development :

- precision/rappel code produit : `85,21 % / 67,41 %` ;
- precision/rappel ligne exacte : `76,41 % / 60,45 %` ;
- client : `100 %` ; date : `97,67 %` ;
- commandes strictement parfaites : `13/43` (`30,23 %`) ;
- comparaison avec `development-phone-aliases-173-20260824` : 5 audios
  modifies, +15 TP exacts, 0 TP perdu, 6 FP retires, 1 FP ajoute,
  +12 TP code et 0 TP code perdu.

Artefacts :

- prediction `evaluation/predictions/development-safe-generalizable-20260824.json`,
  SHA-256 `0e52a6b3864c31e9ab4cc259b76f96a41ed56a6474b964ec339499f48322c58b` ;
- score prive `/opt/emalo-autotune/private/development-safe-generalizable-20260824-score.json`,
  SHA-256 `7e4b5c002da5e4c9e668322b1a63dbea61b3a336ebb636d2082bf51f955a31be` ;
- empreinte applicative
  `9f7c6311878ce3a875a7cebd173b308d896296c8509cdfe0da9ead07fc763d97` ;
- 43 audios, 8 workers, 412,609 s,
  `truth_received_by_predictor=false`, `erp_write_attempted=false`.

Validation instance : 47/47 tests critiques, worker actif. Holdout ferme,
verrou ERP actif, aucune verite transmise au predicteur, aucune ecriture ERP.

## Compte de pieces `10P` sans prefixe - KEEP final du 24 aout 2026

Le parseur de conditionnement reconnait maintenant les trois graphies
equivalentes `X10P`, `(10P)` et `10P`. Pour la graphie sans prefixe, le
suffixe `P` est obligatoire : un nombre ordinaire, un poids ou une dimension
ne peut donc pas activer cette logique. La conversion ne s'applique qu'a une
quantite nue de pieces vers l'emballage de l'article deja choisi. Une unite
commerciale explicitement dite (`poches`, `cartons`, etc.) reste prioritaire.

Comparaison avec le KEEP precedent sur les 43 transcriptions development :

- 2 audios modifies ;
- `20 bavettes` avec article `10P` : `20 POC -> 2 POC`, +1 TP exact ;
- une fausse ligne `demi jambon serrano` retiree ;
- 0 TP exact/code perdu, 2 FP exacts retires, 0 ajoute.

Metriques finales : precision/rappel code `85,51 % / 67,41 %`,
precision/rappel ligne exacte `77,03 % / 60,72 %`, client `100 %`, date
`97,67 %`, 13/43 commandes strictement parfaites (`30,23 %`).

Artefacts finaux :

- prediction `evaluation/predictions/development-bare-piece-count-20260824.json`,
  SHA-256 `ef9f374dfce4568624950356e9486352d0a5b98b752b48e86a72ef6d014e5200` ;
- score prive `/opt/emalo-autotune/private/development-bare-piece-count-20260824-score.json`,
  SHA-256 `f1857b965cb0b3a942c8c4617849b4af6d0f04dbac28e164af8fe9f04a283150` ;
- empreinte applicative
  `0bc740a33d2744e0422a2dc4c9c708e1ff1c611af1a8b2a8ef607a9adf3040cd` ;
- 43 audios, 8 workers, 414,372 s, sans cible et sans ecriture ERP.

Audit final sur l'instance : 49/49 tests critiques passent. La suite complete
donne 252 succes et 14 echecs historiques, tous hors des nouveaux mecanismes :
anciennes attentes de priorite/raison telephone, anciennes signatures de
`chercher_produits`, assertions de ranking devenues obsoletes et regressions
Belloteka deja presentes. Aucun nouveau test n'echoue.

## Preuve produit, segmentation et quantites physiques — KEEP du 24 aout 2026

Objectif de ce chantier : corriger de maniere generique les remarques UI
recurrentes sans utiliser les commandes ERP cibles pour predire. Le code actif
est `src/produits.py`, charge par le worker apres redemarrage le 24 aout a
21:03 UTC.

Mecanismes conserves :

- une ligne doit desormais disposer d'une preuve positive de noyau produit :
  terme catalogue/cadencier, synonyme autorise, flexion simple ou proximite ASR
  suffisamment forte; les fragments discursifs et incomplets sont rejetes;
- la segmentation distingue les coordinations nominales et les formulations
  `ainsi que si vous avez` afin de ne pas perdre le second produit;
- les etats explicitement incompatibles sont exclus (`cru` contre
  pane/cuit/frit, `farine` contre `pane`), avant l'historique client;
- les synonymes sont reciproques et reproductibles pour retrouver une famille
  autorisee, sans etre une instruction de choix d'article;
- une valeur historique sans unite physique ne sert plus a transformer une
  demande en kg/L; seules les contenances effectivement ecrites dans les
  donnees article sont converties;
- le fallback cadencier reste borne a un candidat deja compatible, et ne peut
  plus faire gagner une famille sans rapport.

Validation : nouveau fichier `tests/test_preuves_produit_generalisees.py`
(15 cas) : segmentation, faux produits, ASR deforme, flexions, synonymes,
contradictions produit et quantites. Tests critiques instance : 54/54. Suite
complete : 352 succes, 12 echecs historiques deja documentes (anciens contrats
de tests, Belloteka et appels positionnels), aucun echec nouveau.

Evaluation determinee sans reseau, sans Llama et sans cible : 43 transcriptions
development gelees, 8 workers, 497,402 s. Le predicteur n'a jamais recu la
commande cible (`truth_received_by_predictor=false`) et n'a tente aucune
ecriture ERP (`erp_write_attempted=false`). Holdout des 20 audios non ouvert.

| Metrique | KEEP precedent | Etat actif |
| --- | ---: | ---: |
| Precision code produit | 85,51 % | 85,96 % |
| Rappel code produit | 67,41 % | 68,25 % |
| Precision ligne exacte | 77,03 % | 77,19 % |
| Rappel ligne exacte | 60,72 % | 61,28 % |
| Client / date | 100 % / 97,67 % | inchanges |
| Commandes parfaites | 13/43 | 13/43 |

Comparaison detaillee : 3 TP exacts ajoutes, 5 FP retires, 5 FP ajoutes et une
ancienne ligne exacte remplacee. Cette derniere oppose deux references de rabas
farines dont le libelle prononce ne fournit pas de critere general pour choisir
l'une plutot que l'autre : aucune regle provenant de la cible n'a ete ajoutee.

Artefacts instance :

- prediction : `evaluation/predictions/development-general-proof-v3-20260824.json`,
  SHA-256 `4bd845a410c802338c6138dea8b42fc2e849ae19a58353fedeff170f6b5811f3` ;
- score prive :
  `/opt/emalo-autotune/private/development-general-proof-v3-20260824-score.json`,
  SHA-256 `f063b9704f96ac9d646deb73a8fc7b0e931599fcb023a6275f3bbcf7d4885a30` ;
- empreinte applicative :
  `63c2940bc4d1c8829e7790440f330d0d978499f42526fb2a037b7f8e65a7af89`.

Securite au deploiement : `mode=evaluation`, `evaluation_lock=true`,
`allow_erp_reads=true`, `allow_erp_writes=false`; `tests/test_erp_safety.py`
passe 8/8. Worker `emalo-repondeur-worker.service` actif, endpoint health
confirme sur le port 8787. Toute reprise doit conserver ce verrou.

## Omissions produit et faux secours phonetiques - KEEP v13 du 25 aout 2026

Chantier borne aux produits, sans modification client, UI, loader Reapro ou
ERP. Les 20 audios relies aux remarques UI ont ete rejoues depuis leurs
transcriptions gelees; aucune commande cible n'a ete fournie au predicteur.

Mecanismes conserves :

- rejet grammatical des clauses de politesse, transition, metadata et
  fragments incomplets avant creation d'une ligne ;
- segmentation de `produit A et des produit B si vous avez...` afin que le
  second article ne soit plus absorbe par le premier ;
- quantite par defaut 1 uniquement apres preuve positive d'un noyau produit ;
- aliases multi-mots declares tolerants a l'inversion et a une seule legere
  terminaison ASR, sans fuzzy global ;
- secours phonetique limite au cadencier, avec marge, sans mots deja exacts et
  sans signatures consonantiques de moins de trois caracteres ;
- un noyau exact long peut rendre une ligne visible meme si la variante reste
  ambigue, les alternatives restant dans les details ;
- les articles suffixes `***` sont inactifs et une correspondance inactive
  tres forte ne peut etre remplacee par un article actif lexicalement faible ;
- un noyau exact long du cadencier reste prioritaire sur un bonus d'attribut
  Reapro d'une autre famille.

Sur les 20 remarques, v13 conserve notamment les recuperations oeufs, oignons,
huile d'arachide, chocolat, burrata, lait de coco, tahini, surimi, morilles,
fromage rape, fromage fouette, gambas et speculoos. L'artefact final est
`evaluation/predictions/note-replay-selective-v13-20260825.json` (20 lignes de
manifest, 261,855 s, `truth_received_by_predictor=false`,
`erp_write_attempted=false`).

Evaluation development finale, 43 transcriptions gelees :

| Metrique | KEEP precedent | KEEP v13 |
| --- | ---: | ---: |
| Precision code produit | 85,96 % | 86,62 % |
| Rappel code produit | 68,25 % | 68,52 % |
| Precision ligne exacte | 77,19 % | 77,82 % |
| Rappel ligne exacte | 61,28 % | 61,56 % |
| Faux produits | 21 | 20 |
| Commandes parfaites | 13/43 | 13/43 |

Diff exact contre `development-general-proof-v3-20260824` : 2 TP exacts
ajoutes, 2 FP retires, 0 FP ajoute. Une ancienne ligne cible est retiree car
sa reference `03051462` est desormais explicitement inactive (`***`) dans les
donnees de production; elle n'est volontairement pas remplacee par un article
actif hors sujet.

Artefacts instance :

- prediction `evaluation/predictions/development-selective-v13-20260825.json`,
  SHA-256 `3fd299969739b7f1c5a5fce9df7ff915ba45e6eed5869ab4153f6c99a092217b` ;
- score prive
  `/opt/emalo-autotune/private/development-selective-v13-20260825-score.json`,
  SHA-256 `b5d8173a4b7ddca9be4079485383203e9e39e1f34b7b509331f01963296328cc` ;
- empreinte applicative
  `7651241a81c4c44f34483199ac42357e6cbaf4c11a645eb6f6d8ccbce2ef63be` ;
- sources instance : `src/produits.py`
  `55dbf98a5a93671db39519ea28d717657872036b912872c5c374e965224cc86a`,
  `src/product_hierarchy.py`
  `398ba559098fa73b02a7095bc97f7b3192101806ec8291cb95c89a49546a33f9`.

Audits cibles : 53/53. Holdout final de 20 jamais ouvert. Verrou ERP confirme
avant chaque replay : `mode=evaluation`, `evaluation_lock=true`,
`writes_allowed=false`. Le seuil production de 90 % de commandes strictement
exactes n'est pas atteint : l'etat courant reste 13/43 (`30,23 %`).

## Morceaux animaux explicites - KEEP v17 du 25 aout 2026

Correction isolee du cas reel `2026-08-23_15-54-43_De-0760698344.wav` :
`3 kilos de cotelette d'agneau` ne peut plus etre remplace par une epaule ou
un jus d'agneau plus frequents au cadencier. Le filtre est generalisable aux
morceaux explicites `cote/cotelette`, epaule, gigot, carre, collier, jarret et
souris, lorsqu'une espece est aussi prononcee. Il intervient seulement comme
incompatibilite de classement et n'elargit pas la recherche Reapro : ainsi
`souris mi` (ASR de *surimi*) ne peut pas etre pris pour le morceau souris.

Replay reel sans cible : `00010625 — COTE D'AGNEAU SURGELE 40/60 G BASCO`;
prediction sans verite cible et sans ecriture ERP. Les 43 audios development
sont strictement identiques a v13 (`0` changement ligne a ligne) : precision
code `86,62 %`, rappel code `68,52 %`, precision ligne `77,82 %`, rappel ligne
`61,56 %`, `13/43` commandes parfaites. Tests cibles instance : `80/80`.

Artefacts instance :

- prediction `evaluation/predictions/development-cuts-v17-20260825.json`,
  SHA-256 `1c263f38d00731e61f5accc5e3e14c520a718b11910bfce31944393bded5e68d` ;
- score prive `/opt/emalo-autotune/private/development-cuts-v17-20260825-score.json`,
  SHA-256 `da4c8f09695043b7aa33aefdcd0351c0794fd79c437e451328a74ac9599b605c` ;
- empreinte applicative `67447eb095c5ea4280e3147891bccd16952f88cf1f966ca90e782b0162f6caf9`.

## Noyau produit, abstention et fins Whisper - KEEP du 25 aout 2026

Correction generalisee, deployee sur `/opt/emalo-repondeur-worker` :

- le noyau explicite de l'expression complete precede l'historique : une
  huile ne peut plus devenir un thon a l'huile, un jus de boeuf un filet de
  boeuf, une noix un sorbet noix de coco, ni un muffin chocolat une glace ;
- les attributs explicites poudre, lanieres, rondelles, napolitaine et paleta
  deviennent bloquants lorsqu'ils sont absents ou contradictoires ;
- les reformulations compatibles d'un meme produit sont fusionnees (notamment
  oeuf entier liquide) ;
- les fragments sans noyau ne sont plus rendus fiables par la seule quantite
  ou le seul historique ; les deformees ASR fortes du cadencier restent
  reconnues par preuve composee bornee (`sacoubelle`, `souris mi`) ;
- les synonymes de production explicitement configures peuvent reparer un
  noyau ASR sans lever les contradictions d'attribut ;
- une fin Whisper suspecte declenche une passe sans VAD, puis si necessaire
  une fenetre finale de six secondes avec chevauchement et fusion sans
  duplication.

Validation locale : `392 passed, 12 failed`. Les 12 echecs sont tous deja
incompatibles avec l'etat KEEP anterieur (anciens tests Belloteka, ancienne
priorite nom contre telephone exact, ancienne signature positionnelle,
ancien poids cadencier et ancien test Jolies Glaces). Les neuf regressions
temporaires introduites par la premiere version du filtre ont ete corrigees.
Suites ciblees finales : `71 passed`; instance deployee : `82 passed`.

Test reel sans cible ERP :
`2026-08-24_23-40-45_De-0698692303.wav`. La premiere transcription finissait
sur `20l de vin blanc cuisine,` a 20,42 s pour un audio de 24,21 s. La fenetre
finale GPU recupere `Merci, bonne soiree, au revoir.` en 3,933 s et marque
`mode_reprise_fin_audio=fenetre_finale_avec_chevauchement`. Analyse Llama
persistante et visible dans l'UI : client `TICABAMAYA`, cinq lignes fiables
(huile grignons, longe de thon, moutarde, camembert, vin blanc), statut
`VALIDEE`. Aucune verite cible consultee et aucune ecriture ERP ; verrou
reverifie apres deploiement : `evaluation_lock=true`, `writes_allowed=false`.

Le holdout final de 20 n'a pas ete ouvert. Aucun replay development avec
verite cible n'a ete lance pour cette passe ; les chiffres v17 ci-dessus
restent donc les dernieres metriques comparables.

## Contexte Whisper par numero confirme - deploye le 26 aout 2026

Le contexte ASR est maintenant construit avant transcription a partir de
toutes les associations telephoniques deja connues : numeros issus
d'`info-clients` / de la table telephone et aliases explicitement confirmes
dans `config/aliases-telephoniques-confirmes.json`. Un alias confirme reste
une information de production : il fournit donc l'identite et le cadencier du
client a Whisper, sans jamais lui fournir une commande ERP reelle.

Cas isole valide sans cible : `0644910746 -> BELHABARSOCO`. Avant correction,
le worker ne transmettait aucun hotword et transcrivait « chez Pierron ».
Avec les 160 termes construits depuis le cadencier, dont `chipiron`, Whisper a
produit « cinq cartons Chipiron »; le moteur a retenu les cinq lignes
CHIPIRON, ANCHOIS, ENTRECOTE, CROQUETTE JAMBON et CROQUETTE MORUE. Les fichiers
du test isole ont ete supprimes apres lecture.

Fichiers modifies et deployee sur l'instance :

- `src/contexte_asr.py` ;
- `worker_transcription_server.py`.

Validation : `tests/test_contexte_asr.py` et `tests/test_erp_safety.py`,
`12 passed`. Worker redemarre, healthcheck actif. Aucun appel d'ecriture ERP,
aucun holdout et aucune cible ERP n'ont ete consultes.

## Passation Codex - stabilisation et plan durable (26 aout 2026)

### Etat exact au moment de la passation

Deux micro-corrections bornees ont ete ajoutees et deployees au worker, sans
aucune ecriture ERP :

1. `src/clients.py` extrait desormais chaque numero francais complet dans les
   cellules telephone, y compris plusieurs numeros dans une meme cellule et
   les confusions visuelles courantes (`O/0`, `I/1`, etc.). Il ne concatene
   jamais deux fragments : un prefixe comme `// 07` reste volontairement
   incomplet, car inventer ses chiffres pourrait verrouiller le mauvais
   client. Tests cibles : `2 passed`.
2. `src/produits.py` distingue les variantes ASR utilisees seulement pour la
   recherche d'une equivalence de synonyme *explicitement declaree* et
   completement prononcee. Cette seconde preuve n'est admise que si le
   libelle de l'article correspond fortement a la forme canonique, que
   l'article est commandable, dans le cadencier, semantiquement compatible et
   conserve une marge de selection. Cela evite que le seuil lexical brut
   supprime une reference correctement retrouvee apres normalisation. Test
   cible : `1 passed`; `tests/test_produits.py` : `20 passed`.

Le worker GPU est actif, le verrou ERP est toujours en evaluation et les
fichiers deployes ont ete verifies par SHA-256 local/distant. Aucun test de
43 audios, aucun holdout et aucune commande Copilote n'ont ete lances dans
cette mini-passe.

### Diagnostic reel : audio 2026-08-26_01-22-14_De-0630765557.wav

Le probleme n'etait pas une absence dans Whisper : la transcription contient
`4 bidons de 5 litres de jus d'olive` et `5 kilos chocolat noir en pistole`.
L'etat avant micro-correction trouvait deja :

- `03051204 - HUILE GIDOLIVE 5L`, `4 BID`, cadencier client ;
- `00002234 - IRCA CHOCOLAT NOIR RENO 64% 5K`, `1 BOITE`.

Le chocolat etait deja retenu. Gidolive etait retire apres coup car le score
lexical brut etait `32`, malgre une selection cadencier correcte, une marge
de `5.21`, une quantite valide et la variante autorisee `jus d'olive -> huile
gidolive`. La nouvelle preuve d'equivalence declaree traite exactement ce
type d'incoherence sans regler Gidolive par code article.

Un rejeu GPU de validation a ete lance apres deploiement, mais il est reste en
attente derriere un traitement deja actif sur l'instance puis a ete interrompu
sur demande de l'utilisateur pour ne pas consommer de calcul inutile. Ne pas
presenter le resultat runtime comme definitif avant un unique rejeu isole
ulteriorieur; les tests unitaires cibles sont passes.

### Diagnostic reel : telephone 0676842263

Le rejeu de `2026-08-26_01-06-28_De-0676842263.wav` confirme qu'avant la
correction ce numero n'existait dans aucun des trois referentiels de
production (table telephone, aliases confirmes, cellules info-clients). Le
client LA KARAFE a alors ete trouve par enseigne+ville, pas par telephone.
Une ancienne cellule vue precedemment etait tronquee (`05 59 25 69 26 // 07`)
et ne permettait pas de deviner le mobile.

La valeur complete fournie ensuite, `05 59 85 85 99 // 06 76 84 22 63`, est
correctement analysee en `0559858599` et `0676842263`. Si elle est sauvegardee
dans la ligne du bon client dans `info-clients`, le telephone sera desormais
un verrou client prioritaire. Ne jamais completer automatiquement une valeur
tronquee depuis une prediction.

### Observation centrale : les erreurs restantes ne se resolvent pas par une
accumulation de cas particuliers

Le moteur a deja beaucoup de regles. Les symptomes observes dans les audios
UI se ramènent a cinq causes structurelles :

1. **ASR incomplet ou deforme** : certains mots ou une fin d'audio manquent;
   un moteur produit ne peut pas retrouver de facon fiable un produit absent
   du texte. Le contexte Whisper par client resolu par telephone doit rester
   la premiere defense, sans fournir de commande ERP.
2. **Segmentation non garantie** : deux demandes consecutives peuvent etre
   fusionnees ou une demande peut disparaitre silencieusement avant le
   matching. Chaque span produit doit etre trace et avoir exactement un des
   statuts `RECONNU`, `AMBIGU_A_REVOIR` ou `NON_IDENTIFIE`; aucun span ne doit
   etre perdu sans trace.
3. **Candidat plausible mais mauvais** : la selection doit toujours suivre
   la hierarchie `noyau explicite -> attribut/variante explicite ->
   conditionnement physique si explicite -> contexte de liste -> historique`.
   Le cadencier et l'historique ne peuvent pas inventer ni remplacer un
   attribut prononce (ex. forme, parfum, etat, taille, marque).
4. **Quantite, unite ERP et contenu physique confondus** : `3 kg commandes`,
   `3 pots de 1 kg` et `article 3K` sont trois informations differentes. Les
   conversions ne doivent intervenir qu'apres le choix de famille et a partir
   du conditionnement structure du libelle/reference.
5. **Client incertain** : un mauvais client detruit le cadencier. La priorite
   doit rester `alias telephone confirme -> telephone exact info-clients ->
   nom+ville+phonétique`, jamais l'inverse. Les nouveaux alias ne sont ecrits
   qu'apres validation humaine, jamais appris depuis une prediction.

### Demarche recommandee pour finir proprement

Ne pas lancer de nouvelle experimentation de 43 audios tant que les contrats
suivants ne sont pas en place et testes sur les remarques UI sans cible ERP.

1. **Construire un audit de couverture de segments**, independant du ranking :
   enregistrer pour chaque segment source son texte, ses bornes temporelles,
   son role et son statut final. Faire echouer un test si un segment ayant un
   noyau produit plausible est absorbe/supprime sans statut. C'est la priorite
   la plus rentable contre les produits manquants.
2. **Separer strictement `candidate generation` et `ranking`** : generation
   large mais bornee (cadencier, catalogue/Reapro intra-famille), puis gate de
   noyau et attributs explicites avant toute frequence. Ecrire des tests
   contrastes generiques (huile/thon, noix/coco, jus/filet, lait/creme,
   variantes de taille) au lieu d'ajouter des codes article.
3. **Representer les intentions de commande** : certain, conditionnel (`si
   vous avez`), alternative (`X ou Y`), exclusion (`pas X`) et preference
   historique (`comme d'habitude`). Une alternative ne doit pas creer deux
   lignes; une preference ne peut selectionner qu'un article deja compatible
   avec le noyau et les attributs explicitement demandes.
4. **Fiabiliser l'ASR avant de compenser avec le ranking** : conserver la
   reprise de fin audio, declencher une seconde passe seulement lorsque la
   couverture/fin est suspecte, et limiter le contexte Whisper aux termes du
   client determine par telephone exact ou alias confirme. Mesurer taux de
   troncature et nombre de segments recuperes, pas seulement les produits.
5. **Utiliser Llama 70B seulement comme arbitre borne** des candidats et
   donnees disponibles en production, jamais comme source de verite, et
   seulement apres que segmentation et gates deterministes ont etabli la
   famille. Son resultat doit etre valide par code/article/unite/quantite et
   compare sur developpement fige avant activation.
6. **Evaluation disciplinee** : apres chaque changement isole, tests unitaires
   + replay sans cible des remarques concernees; ne relancer les 43 audios que
   pour un changement transversal stable. Garder uniquement une amelioration
   sans perte materielle de precision. Le holdout de 20 reste ferme jusqu'au
   gel final.

Les metriques development historiques les plus recentes dans ce document
(`13/43` commandes strictement parfaites, selon le jeu et le mode fige alors
utilises) ne demontrent pas un niveau production. Ne pas annoncer 90 % avant
une evaluation temporelle isolee et gelee. La priorite est la robustesse de
couverture/segmentation et le client telephone avant toute nouvelle couche de
ranking.

### Commandes de reprise minimales pour Antigravity

```powershell
Set-Location -LiteralPath 'L:\Public\EMALO-Achats\EMALO-Repondeur'
python -m pytest tests/test_clients.py -k normaliser_telephones -q
python -m pytest tests/test_produits.py -k equivalence_synonyme_declaree -q
```

Puis verifier le verrou avant tout replay :

```powershell
Get-Content config/erp-safety.json
# evaluation_lock doit rester true; allow_erp_writes doit rester false.
```

Le worker distant est `ubuntu@51.210.2.253:/opt/emalo-repondeur-worker`,
service `emalo-repondeur-worker.service`. Il faut verifier les hash des sources
avant un rejeu, ne jamais appeler un script d'envoi Copilote, et ne pas ouvrir
le holdout.
