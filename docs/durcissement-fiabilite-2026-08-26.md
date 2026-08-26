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
- Le garde-fou distingue un vrai nom métier simple d'un complément : un nom usuel comme `brebis` n'est pas rejeté uniquement parce qu'un libellé contient `fromage de brebis`.
- Les synonymes qui ne font qu'ajouter des attributs non prononcés ne spécialisent plus artificiellement la demande (`moutarde` -> `moutarde de dijon`, par exemple).
- Les vraies corrections ASR restent permises (`chistora` -> `txistorra`).
- Un prix local nul/manquant ne retire plus un article réellement vendu au client avant le product gate ; l'exception est limitée au cadencier du client et n'ouvre pas les articles globaux inactifs.
- Les ajouts formulés pendant un récapitulatif sont reparsés puis dédupliqués au lieu d'être supprimés en bloc.
- Une liste dense sous-segmentée bénéficie d'une seconde segmentation lorsque le nombre de marqueurs de commande montre que des mentions ont probablement été perdues.
- La déduplication différée exige désormais la même combinaison produit + quantité + unité : une vraie seconde demande du même article avec une autre quantité n'est plus supprimée comme répétition Whisper.
- Pour les quelques références hors cadencier, `reappro_variante_intra_famille` est activé avec un secours phonétique très borné : uniquement parmi des candidats Réappro déjà générés, dans la famille explicitement prononcée, sans contradiction sémantique, score phonétique >= 90 et marge >= 8. Le mot commun de famille (`sauce`, `filet`, etc.) est exclu du score phonétique afin que la preuve vienne réellement de la variante déformée. Ce secours ne réduit pas le bonus de priorité du cadencier.

### Client

- Le téléphone exact et les associations téléphoniques validées gardent leur priorité inchangée.
- Lorsqu'aucun verrou téléphone ne tranche, la cohérence produits/cadencier reste un signal de départage mais son poids effectif est réduit, afin qu'une première erreur de reconnaissance produit ne puisse pas à elle seule entraîner le choix d'un autre client.

### ASR

- `beam_size` par défaut passe de 1 à 3.
- Les timestamps mot à mot sont activés par défaut pour disposer des probabilités et diagnostics utiles.
- Le contrôle renforcé des listes démarre à 18 s pour les audios multi-segments. Deux couples quantité+unité, trois quantités même sans connecteurs, ou deux quantités dans un audio d'au moins 30 s peuvent déclencher la seconde écoute.
- La seconde transcription par fenêtres sans VAD déjà présente dans le projet est effectivement utilisée pour les listes détectées. Sans hotwords, un garde-fou strict exige une amélioration quantitative nette sans raccourcissement important.
- Les hotwords passent à 240 termes par défaut et réservent une place aux références rares ainsi qu'aux attributs qui changent réellement de référence (`frais`, `surgelé`, `cru`, `cuit`, `râpé`, `entier`, etc.).

## Architecture du changement

Les quatre moteurs historiques sont conservés sous les noms :

- `src/_produits_legacy.py`
- `src/_clients_legacy.py`
- `src/_contexte_asr_legacy.py`
- `_transcrire_audios_legacy.py`

Les fichiers publics d'origine deviennent des façades fines qui réexportent l'API existante et remplacent seulement les comportements décrits ci-dessus. Cela rend le changement plus facile à auditer et à retirer sans réécrire les gros moteurs.

Une CI pytest est ajoutée pour les futurs push et pull requests. Les suites `tests/test_reliability_hardening_20260826.py` et `tests/test_reliability_hardening_edgecases_20260826.py` couvrent notamment les noyaux secondaires, synonymes prudents, prix local manquant, récapitulatifs, listes tronquées, hotwords rares, répétitions Whisper et fallback Réappro intra-famille.
