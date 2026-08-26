# Durcissement fiabilité métier — 26/08/2026

Ce changement cible les causes générales de faux produits, produits omis, erreurs client et transcriptions tronquées, sans utiliser les commandes ES comme vérité d'entrée.

## Invariants métier conservés

- La priorité forte du cadencier client dans la sélection produit est conservée.
- Le numéro appelant continue d'alimenter les hotwords du client et le verrou téléphone exact reste actif.
- Un client doit toujours être présent à la fois dans `info-clients` et dans le cadencier pour être actif sur le répondeur.
- Les écritures ERP restent bloquées par la politique d'évaluation existante.

## Correctifs

### Produit

- Un mot secondaire isolé d'un libellé composé ne suffit plus à prouver le produit. Exemple générique : `couteau` ne prouve pas `tartare boeuf aux couteaux`.
- Les synonymes qui ne font qu'ajouter des attributs non prononcés ne spécialisent plus artificiellement la demande (`moutarde` -> `moutarde de dijon`, par exemple).
- Les vraies corrections ASR restent permises (`chistora` -> `txistorra`).
- Un prix local nul/manquant ne retire plus un article réellement vendu au client avant le product gate ; ce secours ne rend pas commandable un article global inactif.
- Les ajouts formulés pendant un récapitulatif sont reparsés puis dédupliqués au lieu d'être supprimés en bloc.
- Une liste dense sous-segmentée bénéficie d'une seconde segmentation uniquement quand le nombre de marqueurs de commande montre que des mentions ont probablement été perdues.
- Pour les références hors cadencier, un dernier secours phonétique global très borné est disponible seulement après échec de la reconnaissance normale : candidat déjà généré par le catalogue global/Réappro, mot long, score phonétique >=92, marge >=10, quantité résolue, article commandable et aucune contradiction sémantique. Il ne modifie pas la priorité du cadencier et le garde-fou sur les noyaux secondaires reste obligatoire.

### Client

- En l'absence de verrou téléphone, la cohérence cadencier reste un signal mais son poids effectif dans le score client passe de 20 % à 5 %. Cela évite qu'une première erreur produit entraîne le choix d'un autre client, sans diminuer la confiance dans les numéros BASCO validés.

### ASR

- `beam_size` par défaut passe de 1 à 3.
- Les timestamps mot à mot sont activés par défaut pour disposer des probabilités et diagnostics utiles.
- Le contrôle des listes démarre à 18 s et peut se déclencher même si Whisper a perdu certaines unités.
- La seconde transcription par fenêtres sans VAD déjà présente dans le projet est désormais effectivement utilisée pour les listes détectées, mais seulement si elle améliore la couverture connue avant l'audio ; sans hotwords, un garde-fou strict exige au moins deux marqueurs quantitatifs supplémentaires sans raccourcissement important.
- Les hotwords passent à 240 termes par défaut et réservent une place aux références rares ainsi qu'aux attributs qui changent réellement de référence (`frais`, `surgelé`, `cru`, `cuit`, `râpé`, `entier`, etc.).

## Architecture du changement

Les quatre moteurs historiques sont conservés byte-for-byte sous les noms :

- `src/_produits_legacy.py`
- `src/_clients_legacy.py`
- `src/_contexte_asr_legacy.py`
- `_transcrire_audios_legacy.py`

Les fichiers publics d'origine deviennent des façades fines qui réexportent toute l'API existante et ne remplacent que les comportements décrits ci-dessus. Cela rend le changement facile à auditer et à retirer sans réécrire les gros moteurs.

Une CI pytest est ajoutée pour les futurs push et pull requests, ainsi qu'une suite `tests/test_reliability_hardening_20260826.py` dédiée aux régressions introduites par ce durcissement.
