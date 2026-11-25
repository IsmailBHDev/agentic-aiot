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

## IOT-154 — Surcharge de l'Edge

**Résultat :** sans authentification, le calcul de l'Edge suit le débit jusqu'à environ 48 000 messages par seconde, la plus haute valeur testée. Avec la vérification ML-DSA-44, il tient 5 000 messages par seconde et sature vers 6 000. Au-delà, aucun message n'est perdu dans les 2 s de mesure, mais l'attente s'accumule, jusqu'à 4 s au 95ᵉ centile.

**Défaut trouvé et corrigé :** la protection anti-rejeu d'IOT-174 parcourait, à chaque message, tous les compteurs mémorisés pour oublier les plus anciens. Sous charge, le traitement passait de 0,35 ms à 3,9 ms par message et le débit tombait à environ 260 messages par seconde. Les compteurs sont maintenant gardés dans une file ordonnée et oubliés en temps constant (`src/message_auth.py`) ; un test de régression le vérifie.

**Protocole (`src/evaluate_edge_load.py`) :** le vrai chemin Edge MQTT (`on_message`) reçoit des messages à débit imposé, en temps réel, sur une seule boucle asyncio, pendant 2 s par débit (30 000 messages au plus). Les messages reprennent le test historique avec une nouvelle session à chaque passage. Le séjour mesure l'attente plus le traitement. Le broker, le réseau et l'affichage console ne sont pas inclus. Mesures réalisées dans l'environnement de vérification Linux (Python 3.13.18) ; résultats : `results/resilience_edge_load_2026-11-25.json`.

| Débit offert (msg/s) | C0 — atteint | C0 — séjour p50 / p95 | C2 ML-DSA-44 — atteint | C2 — séjour p50 / p95 |
|---:|---:|---:|---:|---:|
| 1 000 | 1 000 | 0,64 / 1,17 ms | 1 000 | 0,82 / 1,42 ms |
| 2 000 | 2 000 | 0,65 / 1,22 ms | 2 000 | 0,83 / 1,45 ms |
| 5 000 | 4 997 | 0,65 / 1,23 ms | 4 999 | 0,94 / 12,56 ms |
| 10 000 | 9 998 | 0,65 / 1,22 ms | 5 404 | 955 / 1 609 ms |
| 20 000 | 20 000 | 0,67 / 1,24 ms | 5 992 | 1 698 / 3 299 ms |
| 50 000 | 48 364 | 0,86 / 21,38 ms | 6 048 | 2 206 / 4 160 ms |

Débit tenu (au moins 95 % du débit offert et p95 ≤ 100 ms) : 50 000 msg/s en C0 dans la plage testée, 5 000 msg/s en C2. Le traitement moyen d'un message vaut environ 0,02 à 0,10 ms en C0 et 0,17 à 0,36 ms en C2.

**Lecture :**
- Le banc du projet n'envoie que trois messages par itération et par seconde : la marge est de plusieurs ordres de grandeur, même avec ML-DSA-44.
- Au-delà de la saturation, l'attente croît sans perte immédiate ; si le retard dépassait 5 s, des lots commenceraient à expirer.
- Ces chiffres décrivent le calcul de l'Edge sur un PC ; le broker MQTT, le réseau et un matériel Edge contraint réduiraient ces débits.

**Tests :** `tests/test_edge_load.py` (2 tests) — structure de la mesure et restauration de l'état, régression de l'anti-rejeu.

## IOT-156 — Contrainte TinyML (B1)

**Résultat :** le B1 historique tient en 42 octets une fois élagué et quantifié en entiers 16 bits, au lieu de 2 793 octets dans son fichier scikit-learn, sans changer une seule prédiction sur les 3 000 observations testées (F1 inchangé à 84,93 %). Au capteur, le coût d'inférence vient surtout de l'appel scikit-learn avec pandas, pas du modèle.

**Protocole (`src/evaluate_tinyml.py`) :** le B1 historique (arbre de profondeur 3, graine 42) est réentraîné en mémoire sur `data/collaborative_train.csv` ; le script vérifie d'abord qu'il reproduit les 600 prédictions de `results/baseline_b1_predictions.csv`. Aucun modèle n'est écrit. Résultats : `results/tinyml_b1_2026-11-25.json` (environnement de vérification Linux, Python 3.13.18, scikit-learn 1.9.1).

| Variante | Nœuds | Taille | Accord test / entraînement | F1 test |
|---|---:|---:|---:|---:|
| Modèle scikit-learn (joblib) | 15 | 2 793 octets | 600/600 · 2 400/2 400 | 84,93 % |
| Arbre élagué, seuils float64 | 11 | 72 octets | 600/600 · 2 400/2 400 | 84,93 % |
| Élagué, entiers en millièmes (int32) | 11 | 52 octets | 600/600 · 2 400/2 400 | 84,93 % |
| Élagué, entiers en centièmes (int16) | 11 | 42 octets | 600/600 · 2 400/2 400 | 84,93 % |

L'élagage retire les branches dont les deux feuilles portent la même classe ; il ne peut pas changer une prédiction. La quantification en centièmes perd de la précision sur les mesures, mais aucun échantillon de ces données ne tombe assez près d'un seuil pour changer de classe ; ce résultat dépend des données et doit être revérifié si elles changent.

| Inférence d'un échantillon (Python sur PC) | Moyenne |
|---|---:|
| scikit-learn avec DataFrame (comme le simulateur) | 0,371 ms |
| scikit-learn avec tableau NumPy | 0,077 ms |
| Table élaguée, seuils float | 0,0003 ms |
| Table élaguée, entiers int32 | 0,0005 ms |

Ces temps Python ne représentent pas un microcontrôleur ; seuls les tailles et les accords sont transposables. Sur microcontrôleur, la table de 42 octets se parcourt en au plus trois comparaisons d'entiers.

**Constat à traiter :** le modèle chargé par le simulateur (`models/device_model.joblib`) n'est pas le B1 évalué. C'est un arbre à une seule comparaison (température > 33,01 °C), qui atteint un F1 de 66,67 % sur le test et diffère du B1 de référence sur 13 des 600 observations. Les résultats B1/B2 du rapport ne sont pas affectés, puisqu'ils utilisent le B1 de référence, mais le prototype de bout en bout utilise un modèle plus faible. Ce fichier figurant dans le manifeste de reproduction, il n'a pas été modifié : voir IOT-180.

**Tests :** `tests/test_tinyml.py` (7 tests) — reproduction de la référence, accord total des variantes compressées, réduction des nœuds et des octets, élagage sans effet sur les prédictions, signalement du modèle du simulateur.

## IOT-155 — Benchmark des trois niveaux

**Résultat :** à chaque niveau, le calcul prend moins d'une demi-milliseconde par message ou par incident, signatures et chiffrement post-quantiques compris. Dans le banc, la latence de bout en bout (environ 0,7 à 1,2 s) vient presque entièrement du trajet Edge → Cloud, c'est-à-dire du pont et des appels MCP, et non du calcul.

**Protocole (`src/evaluate_tiers.py`) :** 1 000 opérations par mesure (200 lots pour B2), hors réseau, sous Windows (Python 3.14.6, scikit-learn 1.9.1, `cryptography` 50.0.2), le 25 novembre 2026. Les latences réseau sont les médianes du banc B3 du même jour. Résultats : `results/tiers_benchmark_2026-11-25.json`.

| Niveau | Opération | Moyenne | Médiane | p95 |
|---|---|---:|---:|---:|
| Device | Inférence B1 (DataFrame + `predict`, comme le simulateur) | 0,336 ms | 0,317 ms | 0,413 ms |
| Device | Signature ML-DSA-44 d'un message | 0,345 ms | 0,264 ms | 0,802 ms |
| Edge | Traitement d'un message, C0 | 0,039 ms | 0,011 ms | 0,303 ms |
| Edge | Traitement d'un message, vérification ML-DSA-44 | 0,127 ms | 0,095 ms | 0,370 ms |
| Edge | Calcul B2 d'un lot de trois mesures | 0,003 ms | 0,003 ms | 0,004 ms |
| Cloud | Enregistrement d'un incident (fichier JSONL) | 0,302 ms | 0,283 ms | 0,425 ms |
| Cloud | Ouverture d'un incident scellé (ML-KEM-768 + ML-DSA-44) | 0,147 ms | 0,139 ms | 0,164 ms |
| Cloud | Analyse A2A à règles (`rule_based_v1`) | 0,0005 ms | 0,0005 ms | 0,0005 ms |
| Cloud | Agent superviseur RAG | à venir (E14) | | |

Modèle B1 du simulateur : 1 801 octets, chargé en 902 ms au démarrage (import de scikit-learn compris, une seule fois).

| Banc B3 en réseau local (médianes) | Edge → Cloud | Cloud → décision | Edge → décision |
|---|---:|---:|---:|
| C0 — sans protection | 653,22 ms | 67,52 ms | 719,69 ms |
| C1 — Ed25519 + X25519 | 594,60 ms | 80,43 ms | 677,55 ms |
| C2 — ML-DSA-44 + ML-KEM-768 | 1 045,16 ms | 82,04 ms | 1 120,84 ms |
| C2 hybride | 1 154,51 ms | 78,40 ms | 1 228,00 ms |

**Lecture :**
- Le calcul cumulé d'un incident sur les trois niveaux reste de l'ordre de la milliseconde, alors que le trajet Edge → Cloud prend plusieurs centaines de millisecondes : c'est le maillon à optimiser (scrutation, session MCP ouverte à chaque incident), pas la détection ni la cryptographie.
- Comme indiqué pour IOT-178, les écarts de latence réseau entre configurations ne sont pas séparables de la variabilité du banc.
- Au Device, l'appel via DataFrame domine l'inférence ; la table compacte d'IOT-156 la réduirait à quelques microsecondes.

**Tests :** `tests/test_tiers.py` (1 test) — chaque niveau est mesuré ; l'analyse A2A est ignorée proprement si FastAPI est absent.
