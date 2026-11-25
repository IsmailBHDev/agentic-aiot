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

## IOT-153 — Coupure Device → Edge

**Résultat :** quelles que soient les pertes, l'Edge ne prend jamais deux décisions B2 pour un même lot, ne prend aucune décision fausse, et journalise immédiatement chaque alerte B1 reçue, même quand le lot reste incomplet. En revanche, la disponibilité de B2 chute vite avec les pertes, car un lot exige les trois capteurs.

**Protocole (`src/evaluate_device_loss.py`) :** les 600 observations du test historique (200 itérations) sont rejouées par le vrai chemin Edge MQTT, avec une horloge simulée qui fait expirer un lot incomplet après 5 s. Pour chaque taux de perte, 10 % des messages reçus sont aussi dupliqués (retransmissions QoS 1) et l'ordre est mélangé dans chaque lot ; 3 graines par taux. Une coupure franche de node-02 sur 60 itérations est simulée à part. Résultats : `results/resilience_device_loss_2026-11-25.json`.

| Perte de messages | Lots complets | Lots expirés | Décisions B2 conformes / fausses | Doubles décisions | Alertes B1 reçues → journalisées | Rappel B2 | Rappel B2 ou alerte B1 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 % | 200,0 | 0,0 | 600,0 / 0 | 0 | 33,0 → 33,0 | 97,5 % | 97,5 % |
| 1 % | 193,3 | 6,7 | 580,0 / 0 | 0 | 32,7 → 32,7 | 95,0 % | 95,8 % |
| 5 % | 170,3 | 29,7 | 511,0 / 0 | 0 | 31,3 → 31,3 | 85,0 % | 92,5 % |
| 10 % | 143,0 | 57,0 | 429,0 / 0 | 0 | 29,7 → 29,7 | 74,2 % | 87,5 % |
| 20 % | 100,0 | 98,3 | 300,0 / 0 | 0 | 25,0 → 25,0 | 41,7 % | 65,8 % |
| 30 % | 74,0 | 121,3 | 222,0 / 0 | 0 | 20,7 → 20,7 | 28,3 % | 55,0 % |

Moyennes sur 3 graines. Le rappel est calculé sur les 40 anomalies du test historique.

**Coupure franche de node-02 (60 itérations) :** exactement 60 lots expirés et 140 lots complets, 420 décisions B2 toutes conformes, 31 alertes B1 reçues et journalisées ; rappel B2 de 67,5 %, et de 80,0 % en comptant les alertes B1.

**Lecture :**
- Avec trois capteurs obligatoires, la part de lots complets suit à peu près (1 − p)³ : 10 % de pertes font perdre environ 28 % des lots, et le rappel B2 tombe de 97,5 % à 74,2 %.
- Le repli sur B1 limite la perte de détection (87,5 % à 10 % de pertes), mais il ne voit que les anomalies locales, pas les anomalies contextuelles.
- Piste d'amélioration, non implémentée : décider à deux capteurs quand le troisième manque (écart entre deux mesures), au prix d'une référence moins robuste.

**Tests :** `tests/test_device_loss.py` (6 tests) — parité complète sans perte, retransmissions ignorées, aucune décision double ou fausse sous pertes, chaque alerte B1 reçue journalisée, coupure franche expirant exactement les itérations coupées, état de l'Edge restauré après l'évaluation.
