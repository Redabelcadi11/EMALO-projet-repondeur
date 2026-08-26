# Architecture du Repondeur et protocole d'evaluation sans fuite

Etat de l'audit : 13 aout 2026.

## Invariants de securite

- `config/erp-safety.json` impose `evaluation_lock=true` et
  `allow_erp_writes=false`.
- Toute mutation Python doit passer par
  `src.erp_safety.assert_erp_write_allowed`.
- Les scripts Groovy mutants appellent `copilote/erp_write_guard.groovy` avant
  d'initialiser un service distant.
- La lecture ERP reste autorisee via `assert_erp_read_allowed`.
- La prediction est executee a partir d'un manifeste ne contenant que le nom
  de l'audio et le SHA-256 de sa transcription. Le corpus ERP n'est jamais
  passe au processus de prediction.
- Les profils et regles generes a partir des comparaisons ES sont desactives
  par `config/evaluation-safety.json`.

## Pipeline de production

1. `recuperer_nextcloud.py` enumere Nextcloud par `PROPFIND`, puis copie les
   nouveaux fichiers par `GET`. Il ne contient aucune operation `MOVE`, `PUT`
   ou `DELETE`. Un manifeste local evite les copies inutiles.
2. La tache Windows `EMALO-Repondeur-Nextcloud-Sync`, executee comme SYSTEM,
   lance cette synchronisation chaque jour a 03:00 et 23:00, sans session
   utilisateur.
3. L'interface appelle `prod_pipeline.run_selected_audios_pipeline`.
4. `worker_client.py` ouvre le tunnel SSH et appelle le worker impose par
   `config/worker.json`.
5. `worker_transcription_server.transcribe_payload` transcrit avec
   faster-whisper `large-v3`. Les hotwords proviennent uniquement du fichier
   clients, des variantes, des synonymes generaux et du cadencier client.
6. `worker_transcription_server.analyze_payload` appelle
   `extraire_informations.traiter_transcriptions`.
7. Le moteur identifie le client (`src/clients.py`), segmente les mentions,
   recherche d'abord dans le cadencier client puis dans le catalogue global,
   resout quantite/unite/conditionnement et calcule le statut.
8. Les commandes resultantes sont des fichiers CSV/JSON locaux. Elles ne sont
   pas automatiquement envoyees a Copilote.

## Verite ERP en lecture seule

`scripts/extract_copilote_repondeur_orders.py` lance
`copilote/extract_repondeur_orders.groovy`. Ce dernier utilise uniquement :

- `InfocentreTableauBordService.execute2` pour les entetes et lignes ;
- `CommandeService.loadNumCde` pour charger une commande existante.

Le resultat est un CSV local deduplique ensuite par numero de commande. La
lecture et la prediction restent deux flux separes.

## Appariement independant

`scripts/apparier_audio_commandes_independant.py` n'importe pas le moteur de
prediction et ne lit aucune extraction EMALO. Il utilise uniquement :

- la date et le telephone contenus dans le nom du fichier ;
- le referentiel client et ses variantes ;
- la transcription brute Whisper ;
- les libelles des commandes ERP candidates du meme jour.

Les paires exigent un meilleur choix mutuel audio-vers-commande et
commande-vers-audio. La classe la plus sure, `metadata_exact`, exige notamment
un telephone non ambigu, un seul audio et une seule commande pour le couple
client/date, une marge suffisante et une preuve textuelle. Les paires faibles
sont exclues, pas forcees.

## Evaluation en trois processus

1. `preparer_manifest_evaluation.py` lit le corpus prive et cree un manifeste
   expurge de toute cible.
2. `generer_predictions_evaluation.py`, execute sous un compte sans acces au
   dossier prive, valide strictement le schema du manifeste et produit les
   predictions. L'arbitrage LLM implicite est coupe pour rendre la baseline
   deterministe.
3. `evaluer_predictions_sans_fuite.py` lit ensuite, hors du predicteur, les
   predictions et la verite ERP, et produit les metriques et diagnostics.

La metrique de production est `automation_order_accuracy`. Une commande est
correcte seulement si le client, la date de livraison, le multiensemble exact
des triplets `(article, quantite, unite)` et le statut `VALIDEE` sont tous
corrects. Le seuil de production est 90 % sur au moins 20 audios de holdout.

Le rapport conserve egalement rappel/precision article, lignes exactes,
precision client, date, taux d'acceptation, produits manquants/en trop,
classement attendu, transcription, candidats et causes classees.

## Politique de donnees

- Le cadencier de production, anterieur aux messages evalues, est une ressource
  metier autorisee.
- Les commandes ERP correspondant aux audios evalues ne peuvent jamais
  enrichir le cadencier, les synonymes, les profils clients ou les scores de
  prediction.
- Le jeu final contient les 20 paires `metadata_exact` les plus recentes et
  reste interdit au developpement.
- Atteindre 90 % sur le developpement ne suffit pas : seul le holdout temporel
  final, execute une fois apres gel du moteur, peut ouvrir la porte production.

## Limites observees avant ameliorations

L'ancien rapport de 490 paires affichait 67,80 % de rappel article, 60,67 % de
precision article, 54,49 % de clients corrects et seulement 6,94 % de commandes
parfaites. Ce chiffre n'est pas une nouvelle baseline : le code alors deploye
contenait des profils et regles derives des comparaisons ES. Il sert uniquement
a constater que le moteur est loin du seuil et que les anciennes annonces de
fiabilite ne sont pas recevables.

Les causes structurelles deja etablies sont : identification client, faux
segments produits, candidats absents ou mal classes, quantites, conversion des
conditionnements et rejet interne de commandes pourtant correctes. Le nouvel
evaluateur quantifie ces familles sans les confondre avec les erreurs
d'appariement.
