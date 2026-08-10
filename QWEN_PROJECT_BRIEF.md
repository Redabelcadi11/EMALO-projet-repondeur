# Briefing permanent Qwen ? EMALO R?pondeur

Derni?re consolidation : 28 juillet 2026.

Ce document r?sume les d?cisions prises avec le propri?taire du projet. Il doit
?tre lu comme le contexte permanent de toutes les missions Qwen sur ce d?p?t.
Les faits d'exploitation peuvent ?voluer : v?rifier l'?tat r?el du code, des
fichiers et des services avant d'affirmer qu'une op?ration est termin?e.

## 1. Finalit? m?tier

EMALO R?pondeur doit remplacer progressivement le travail d'un op?rateur qui :

1. ?coute les commandes vocales d?pos?es sur Nextcloud ;
2. identifie le client, la date de livraison, les produits, quantit?s et unit?s ;
3. recherche les r?f?rences articles ;
4. pr?pare la commande destin?e ? Copilote ERP.

L'op?rateur de r?f?rence dans Copilote est `ES`. Ses commandes historiques
servent de v?rit? terrain priv?e afin de mesurer puis am?liorer le programme.

L'objectif demand? est au moins 90 % de fiabilit? sur un ensemble s?par? d'au
moins 20 messages audio. Un bon r?sultat sur les exemples utilis?s pour
corriger le programme ne suffit jamais.

## 2. D?cisions d?j? prises avec le propri?taire

- L'ancienne VM est abandonn?e. Le calcul distant se fait sur l'instance
  `51.210.2.253` (nom syst?me `l4-90-2026-07-21-14-45`).
- L'interface du TSE doit d?l?guer la transcription et l'analyse lourde ? cette
  instance.
- Whisper reste enti?rement local. Le mod?le retenu apr?s comparaison est
  `large-v3`, plus pr?cis que le mod?le pr?c?dent malgr? un temps sup?rieur.
- L'API OpenAI est compl?tement abandonn?e. Ne jamais la r?introduire.
- Qwen utilis? pour le d?veloppement autonome est
  `ollama_chat/qwen3-coder:30b`, servi localement par Ollama sur l'instance.
- Le programme doit chercher les produits dans le cadencier du client avant de
  chercher dans le catalogue g?n?ral. Le cadencier est dans
  `ressources-originales`.
- Les commandes r?ellement saisies par ES servent uniquement ? un ?valuateur
  priv?. Le programme principal ne doit jamais pouvoir les lire.
- Pour l'instant, aucune commande ne doit ?tre envoy?e, cr??e, modifi?e,
  valid?e ou annul?e dans Copilote.
- Les extractions Copilote autoris?es sont exclusivement en lecture seule.
- Une correction ne doit jamais m?moriser un num?ro de commande, un nom de
  fichier audio, une r?ponse ES ou une exception ad hoc destin?e ? r?ussir un
  cas pr?cis.

## 3. P?rim?tre de donn?es consolid? au 28 juillet 2026

L'inventaire priv? d?ploy? sur l'instance contient :

- 820 audios Nextcloud, avec une limite pr?vue de 1 000 ;
- 1 000 commandes ES retenues parmi 1 043 commandes disponibles ;
- 151 appariements audio/commande suffisamment fiables ;
- 101 paires d'apprentissage ;
- 50 paires de validation ;
- 669 audios encore non appari?s ;
- 333 audios dont le num?ro de t?l?phone correspond sans ambigu?t? ? un client.

Dates audio couvertes : du 23 au 29 juin 2026, du 7 au 9 juillet 2026, puis le
28 juillet 2026.

Les 669 audios non appari?s ne doivent pas ?tre associ?s artificiellement. Un
second processus priv? pourra les rapprocher des commandes ES avec Qwen, mais
uniquement avec un score de confiance ?lev?. Les cas ambigus doivent rester
exclus.

## 4. R?gle correcte d'appariement

Attention ? ne pas confondre les dates :

- le nom du fichier audio indique la date de l'appel ;
- `order_date` est la date de cr?ation de la commande Copilote ;
- `departure_date`, `delivery_date` et `search_date` peuvent ?tre un ? trois
  jours apr?s l'appel.

Un appariement strict utilise d'abord :

1. date de l'audio ?gale ? `order_date` ;
2. client identique ;
3. exactement un audio et une commande dans ce groupe.

Ne jamais apparier uniquement sur la date de livraison. Ne jamais utiliser les
produits pr?dits par le programme principal pour choisir la commande ES : cela
biaiserait ensuite la mesure du programme.

Pour augmenter la couverture, un agent d'appariement s?par? peut utiliser la
transcription brute, le t?l?phone, le nom annonc?, la date et les m?tadonn?es
ind?pendantes. Cet agent ne doit pas avoir le droit de modifier le programme
principal. L'agent qui modifie le code ne doit pas voir les commandes ES brutes.

## 5. Architecture actuelle

### TSE

Projet de r?f?rence :

`L:\Public\EMALO-Achats\EMALO-Repondeur`

Le TSE conserve le projet, l'interface, les ressources originales et les
r?sultats. Les changements produits sur l'instance sont rapatri?s avec contr?le
d'empreinte et sauvegarde.

### Instance de calcul

Chemins principaux :

- production worker : `/opt/emalo-repondeur-worker` ;
- agent autonome R?pondeur : `/opt/emalo-autotune` ;
- agent g?n?rique pour les projets TSE : `/opt/local-codex`.

Services principaux :

- `emalo-repondeur-worker.service` : transcription/analyse locale ;
- `ollama.service` : mod?le Qwen local ;
- `emalo-autodev.service` : am?lioration autonome du R?pondeur.

Configuration Whisper de production :

- mod?le `large-v3` ;
- CPU ;
- calcul `float32` ;
- 20 threads ;
- `beam_size=5` ;
- un worker ;
- pas de timestamps mot ? mot ;
- `condition_on_previous_text=0`.

Le worker ?coute uniquement sur `127.0.0.1:8787` sur l'instance. Les appels du
TSE passent par la connexion s?curis?e configur?e par le projet.

## 6. Fichiers importants du d?p?t

- `extraire_informations.py` : extraction m?tier client, date et lignes de
  commande ? partir des transcriptions.
- `prod_pipeline.py` : pipeline de production et pr?paration de commande.
- `worker_client.py` : client TSE du worker de l'instance.
- `worker_transcription_server.py` : serveur local de transcription/analyse.
- `transcrire_audios.py` : configuration et logique Whisper.
- `recuperer_nextcloud.py` : synchronisation des audios Nextcloud.
- `copilote_integration.py` : int?gration Copilote, ? traiter comme sensible.
- `scripts/extract_copilote_repondeur_orders.py` : extraction ES en lecture
  seule depuis une session BASCO/Copilote.
- `copilote/extract_repondeur_orders.groovy` : requ?te de lecture Copilote.
- `scripts/evaluer_commandes_vs_copilote.py` : ?valuateur historique priv?.
- `ressources-originales/audio-nextcloud` : audios disponibles.
- `ressources-originales` : clients, articles et cadenciers.
- `resultats/transcriptions` : caches Whisper.
- `tests` : r?gressions obligatoires.

Le corpus ES priv? de l'instance est sous `/opt/emalo-autotune/private`, avec
r?pertoire en mode `700` et fichiers en mode `600`. L'utilisateur de
l'application principale ne peut pas le lire.

## 7. Agent autonome d'am?lioration

L'agent autonome proc?de audio par audio :

1. l'?valuateur priv? calcule la sortie actuelle ;
2. il compare cette sortie ? la commande ES ;
3. Qwen re?oit un diagnostic limit?, pas la base ES brute ;
4. Qwen corrige uniquement les fichiers m?tier autoris?s dans un worktree ;
5. la correction est test?e sur le cas courant et un corpus de r?gression ;
6. une validation s?par?e d?cide si une promotion est autoris?e.

Seuils actuels du service : rappel produit cible 92 %, pr?cision minimale 82 %,
rappel exact minimal 70 %, tests complets r?ussis. Le besoin m?tier exprim? par
le propri?taire reste au moins 90 % de fiabilit? globale.

L'ensemble de validation ne doit jamais servir ? choisir ou ?crire une r?gle.
Il sert uniquement ? mesurer la g?n?ralisation et autoriser ou refuser une
promotion.

## 8. Priorit?s d'am?lioration

1. transcription fid?le des noms propres, nombres, unit?s et produits ;
2. identification correcte du client ;
3. cadencier client avant catalogue g?n?ral ;
4. rappel produit sans explosion des faux positifs ;
5. quantit?s et unit?s exactes ;
6. date de livraison ;
7. r?gles g?n?rales, explicables et testables ;
8. absence de r?gression sur les corrections pr?c?dentes.

Diagnostiquer avant de modifier. Les causes possibles incluent : transcription
impr?cise, client mal identifi?, alias produit absent, mauvaise priorit? entre
cadencier et catalogue, quantit?/unit? mal rattach?e, date ambigu? ou
appariement de v?rit? incorrect.

## 9. Interdictions absolues

- Aucun appel OpenAI, Copilot, API de LLM distante ou service cloud.
- Aucun envoi ? Copilote tant que le propri?taire n'a pas explicitement chang?
  cette r?gle.
- Aucune ?criture Copilote pendant les tests ou l'appariement.
- Aucun acc?s ? une cl? SSH, un mot de passe, un `.env` ou une configuration
  contenant des secrets.
- Aucune fuite du corpus ES vers l'application principale.
- Aucune r?gle cod?e ? partir d'un num?ro de commande ou fichier audio pr?cis.
- Aucune baisse des seuils ou modification des tests pour faire passer une
  correction.
- Aucun d?ploiement si les tests ou la validation s?par?e ?chouent.
- Aucune affirmation de r?sultat sans mesure reproductible.

## 10. Mani?re de travailler avec le propri?taire

Le propri?taire ?crit en fran?ais, parfois avec des fautes de frappe. R?pondre
en fran?ais clair, directement, sans jargon inutile. Il souhaite parler ? Qwen
comme ? un agent de d?veloppement : comprendre l'objectif, inspecter le projet,
agir lorsqu'une modification est demand?e, tester, puis donner le r?sultat.

Une mission de diagnostic n'autorise pas automatiquement une modification. Une
mission de correction autorise les changements strictement n?cessaires dans la
copie isol?e. Les modifications ne reviennent sur le TSE que si le mode
PowerShell `/appliquer oui` est actif et que les tests r?ussissent.

Pour un autre projet TSE, ne r?utiliser que les r?gles g?n?riques de s?curit?.
Le pr?sent contexte m?tier concerne uniquement EMALO R?pondeur.

## 11. ?tat attendu lors d'une nouvelle mission

Avant de commencer :

1. lire ce briefing en entier ;
2. lire le code r?ellement concern? ;
3. v?rifier les changements existants ;
4. confirmer que la t?che ne demande ni secret ni action Copilote interdite ;
5. d?finir une v?rification proportionn?e ;
6. pr?server la s?paration entre programme principal et v?rit? ES.

Si l'?tat r?el contredit ce document, signaler pr?cis?ment l'?cart et se fier ?
l'observation la plus r?cente sans affaiblir les interdictions de s?curit?.
