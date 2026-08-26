# Audit des acces ERP en mode evaluation

Ce document decrit les chemins trouves par inspection statique. Il ne constitue pas une preuve fonctionnelle d'envoi : aucun appel d'ecriture ERP n'est execute pendant l'evaluation.

## Politique centrale

La politique est dans `config/erp-safety.json`. Le module central Python est `src/erp_safety.py` et le garde des scripts Groovy est `copilote/erp_write_guard.groovy`.

La configuration courante est volontairement fail-closed :

- `mode` vaut `evaluation` ;
- `evaluation_lock` vaut `true` ;
- les lectures ERP sont autorisees ;
- les ecritures ERP sont interdites ;
- une politique absente, invalide ou incomplete interdit aussi les ecritures ;
- le chemin de la politique n'est pas substituable par variable d'environnement ;
- une variable d'environnement ne peut pas annuler `evaluation_lock`.

Une future remise en production exige simultanement une modification explicite de la politique, la desactivation du verrou d'evaluation, l'autorisation d'ecriture et une confirmation d'environnement. Ces conditions ne sont pas reunies pendant ce travail.

## Implementations capables d'ecrire dans Copilote

| Implementation | Effet potentiel | Protection |
| --- | --- | --- |
| `copilote_integration.send_service_request` | Lance `send_order_service.groovy` | garde Python avant session, Java et reseau |
| `copilote/send_order_service.groovy` | `CommandeService.create`, construction des lignes, puis `ValidCdeService.saveCdeBatch` | garde Groovy avant l'initialisation du service distant |
| `copilote_integration.send_direct_request` | Rejoue une capture binaire de creation via `POST /ventes/ProxyServlet` | garde Python avant lecture du modele et reseau |
| `scripts/copilote_order.py --mode create-order` | Pilote l'interface web, cree une commande et clique sur `Enregistrer` | garde au debut du mode et dans chaque etape mutante |
| `copilote/probe_line_quantities.groovy` | Appelle `CommandeService.create` pour construire un diagnostic | bloque comme ecriture potentielle, meme sans `saveCdeBatch` visible |

## Points d'entree menant aux implementations d'ecriture

| Point d'entree | Chemin |
| --- | --- |
| Fenetre historique `copilote_integration.App` | `_send_worker` -> verrou d'envoi -> `send_service_request` |
| Interface Python `ui_repondeur.py` | `send_refs` / `_send_refs_worker` -> verrou -> `send_service_request` |
| Interface Electron | `app-desktop/main.js` -> `electron_bridge.py send` -> `_send_orders` |
| Interface web locale | `POST /api/run` -> `repondeur_web_server.run_bridge` -> `electron_bridge.py` |
| Bouton audio production | `send-audio-order` ou `send --mode prod` -> `_send_orders` |
| CLI historique | `app_cli.py copilote-order` -> `scripts/copilote_order.py` |
| Invocation directe | fonctions Python ou scripts Groovy ci-dessus ; les gardes profonds restent actifs |

La creation ou la correction d'une commande dans les CSV locaux n'est pas une ecriture ERP. Ces operations restent disponibles pour produire et evaluer une prediction, mais elles ne peuvent plus declencher un envoi Copilote.

## Acces ERP conserves en lecture

| Composant | Operations observees |
| --- | --- |
| `scripts/extract_copilote_repondeur_orders.py` + `copilote/extract_repondeur_orders.groovy` | requetes Infocentre `execute2`, puis `CommandeService.loadNumCde` |
| `copilote/load_order.groovy` | `CommandeService.loadNumCde` |
| `copilote/probe_clients.groovy` | `CliLivSearcherService.getCliLivByCode` |
| `copilote_integration.verify_order_in_search` | rejeu d'une requete de recherche Infocentre |

Les RPC de lecture Copilote utilisent eux aussi HTTP `POST`. Le filtrage ne repose donc pas sur le verbe HTTP, mais sur les operations et scripts explicitement classes.

## Regle d'evaluation sans fuite

Les commandes reelles ERP sont des etiquettes de comparaison uniquement. Elles ne doivent etre chargees ni par la transcription, ni par la reconnaissance client, ni par la reconnaissance produit, ni par le calcul de quantite. L'apparieur et l'evaluateur doivent rester separes du moteur de prediction et utiliser un jeu temporel final jamais exploite pour regler les regles.

La politique `config/evaluation-safety.json` impose cette separation. Les profils agressifs, l'enrichissement depuis l'historique ERP et les regles client/article generees depuis la comparaison ES sont conserves pour audit, mais exclus du moteur principal. Seules des regles generales dont l'origine est explicitement autorisee peuvent etre chargees ; une politique absente exclut toutes les regles optionnelles.
