# E12 — Résilience et performances

**Branche :** `feature/e12-resilience`
**Règles :** le seuil B2 de 2,50 °C, les données et les résultats historiques ne sont pas modifiés ; les nouveaux résultats vont dans des fichiers séparés.

## IOT-152 — Perte du Cloud

**Résultat :** l'Edge ne dépend pas du Cloud pour détecter. Pendant une panne de MCP, il continue B1, B2 et la journalisation des incidents ; quand le Cloud revient, le pont transmet tous les incidents en attente, une seule fois chacun et dans l'ordre.

### Ce qui a été corrigé dans le pont (`src/edge_cloud_bridge.py`)

| Défaut constaté | Effet avant correction | Correction |
|---|---|---|
| La position n'avançait qu'après un lot entier | Une panne au milieu d'un lot renvoyait les incidents déjà transmis (doublons, donc plusieurs identifiants Cloud et décisions) | La position avance après chaque incident transmis |
| Redémarrage du pont à la fin du journal | Les incidents écrits pendant l'arrêt du pont étaient perdus | Fichier d'état optionnel (`--state-file` ou `AIOT_BRIDGE_STATE_FILE`) : le pont reprend où il s'était arrêté ; sans lui, le comportement historique est conservé |
| Nouvel essai à intervalle fixe, sans compteur | Pas de visibilité sur la panne | Attente qui double jusqu'à `max_backoff` (30 s par défaut), compteurs `send_failures`, `recoveries`, `incidents_sent`, `incidents_invalid` |
| Ligne en cours d'écriture ou JSON invalide | Erreur répétée sur la même ligne | Ligne incomplète relue au tour suivant ; ligne invalide comptée et ignorée |

### Vérification (`tests/test_cloud_outage.py`, 6 tests hors réseau)

- **Panne pendant un rejeu :** le Cloud est arrêté, puis les 600 observations du test historique sont rejouées à l'Edge. Les 600 décisions B2 restent identiques à la référence, aucun incident n'atteint le Cloud pendant la panne, puis tous les incidents journalisés lui parviennent après le retour, sans doublon et dans l'ordre.
- **Panne au milieu d'un lot :** 5 incidents, échec au 3ᵉ envoi ; le Cloud reçoit exactement les 5, une fois chacun.
- **Redémarrage du pont :** avec fichier d'état, les 3 incidents écrits pendant l'arrêt sont transmis ; sans fichier d'état, le comportement historique (départ en fin de journal) est conservé et documenté par un test.
- **Lignes incomplètes ou invalides, attente bornée :** vérifiées.

La panne d'A2A côté orchestrateur était déjà couverte par `tests/test_cloud_orchestrator.py` : les incidents sans décision sont repris au passage suivant.

### Limites

- Le Cloud est simulé par `cloud_store.report_incident` derrière une fonction d'envoi qui échoue ; l'arrêt et le redémarrage d'un vrai serveur MCP sur le réseau ne sont pas encore testés.
- Une fois un incident transmis, un renvoi volontaire (même incident Edge envoyé deux fois à MCP) produit toujours deux identifiants Cloud : la déduplication côté Cloud n'est pas traitée ici.
- Le fichier d'état est écrit après chaque incident ; une coupure entre l'envoi et l'écriture de l'état peut provoquer un seul renvoi au redémarrage (garantie « au moins une fois », pas « exactement une fois »).
