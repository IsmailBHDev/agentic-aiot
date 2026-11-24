# IOT-172 — Modèle de menace de l'axe post-quantique

**Date :** 23 novembre 2026
**Base :** `main` après la PR #15 (`57f3bc8`) ; branche `feature/iot-172-pq-threat-model`
**Statut :** modèle de menace ; aucune protection n'est encore implémentée. Ce document cadre les tickets IOT-173 à IOT-179.

Ce document définit ce que l'axe post-quantique protège, contre quel attaquant et avec quelles hypothèses. Il s'appuie sur le code actuel du dépôt : chaque constat renvoie au fichier qui le justifie. Il ne modifie ni le seuil B2 de 2,50 °C, ni les données, ni les 600 décisions de référence.

## 1. Résumé

- **Aucun lien du prototype n'est authentifié ni chiffré.** Les contrôles existants vérifient la forme et la fraîcheur des messages, mais reposent sur des champs que l'émetteur choisit lui-même : un attaquant qui peut émettre sur le réseau peut les satisfaire.
- **La menace prioritaire est l'injection de télémétrie falsifiée.** E07 a montré que deux capteurs décalés ensemble de +3,5 °C contaminent la médiane : 150 faux positifs sur le capteur sain et 196 anomalies manquées sur 300. Un attaquant qui usurpe deux capteurs obtient ce résultat sans toucher au matériel.
- **La seconde menace est le modèle distribué par OTA.** Le modèle B1 est chargé avec `joblib`, qui désérialise du pickle : un fichier modifié peut exécuter du code, pas seulement fausser les prédictions.
- **Le rôle du post-quantique est double.** Les signatures et l'échange de clés classiques (RSA, courbes elliptiques) qu'on ajouterait aujourd'hui seraient cassés par un ordinateur quantique capable d'exécuter l'algorithme de Shor. ML-DSA et ML-KEM (FIPS 204 et 203) restent sûrs dans ce scénario.

## 2. Périmètre et hypothèses

- **Système étudié :** la chaîne simulée Device → Edge → Cloud décrite dans `docs/research_delivery.md`, exécutée sur une seule machine.
- **Approvisionnement des clés :** on suppose que chaque capteur reçoit sa paire de clés et que l'Edge reçoit les clés publiques par un canal de confiance, hors bande, avant le déploiement. La gestion du cycle de vie des clés (révocation, rotation) est hors périmètre de cette étude.
- **Horloges :** les horloges sont supposées synchronisées à 5 s près, comme le prévoit déjà `MAX_CLOCK_SKEW_SECONDS` dans `src/telemetry.py`.
- **Simulation :** les coûts seront mesurés sur PC. Ils ne remplacent pas les mesures sur microcontrôleur publiées dans la littérature (section 2.1 du rapport).

## 3. Actifs à protéger

| Actif | Où il se trouve | Propriété visée | Conséquence d'une atteinte |
|---|---|---|---|
| Télémétrie des capteurs | Messages MQTT-SN et CoAP vers l'Edge | Authenticité, intégrité, fraîcheur | Décision B2 faussée (faux positifs, anomalies manquées), isolement logique d'un capteur sain |
| Alertes locales B1 | Messages `anomaly_alert`, CoAP `/alert` | Authenticité, intégrité | Fausses alertes ou alertes supprimées |
| Incidents Edge | `data/incidents.jsonl`, puis appel MCP `report_incident` | Intégrité, traçabilité, confidentialité | Incident inventé, modifié ou perdu avant le Cloud |
| Décisions Cloud | Réponses A2A, `data/cloud_decisions.jsonl` | Intégrité, traçabilité | Recommandation falsifiée associée à un incident réel |
| Modèle B1 | `models/device_model.joblib` ; futur OTA (IOT-158) | Intégrité, authenticité de l'origine | Prédictions faussées ou exécution de code sur le capteur |

## 4. Contrôles existants observés dans le code

| Contrôle | Fichier | Ce qu'il apporte | Pourquoi il ne suffit pas |
|---|---|---|---|
| Validation du schéma et des types | `src/telemetry.py`, `validate_telemetry` | Rejette les messages mal formés | Un message bien formé mais falsifié passe |
| Liste des capteurs attendus | `src/telemetry.py`, `EXPECTED_DEVICES` | Rejette un identifiant inconnu | `src.agent` est un champ libre : un attaquant écrit `node-01` |
| Fraîcheur (300 s, décalage de 5 s) | `src/telemetry.py`, `is_message_fresh` | Rejette les messages trop anciens | L'horodatage `ts` est fourni par l'émetteur ; rejeu possible pendant 300 s avec un nouvel `id` |
| Déduplication par identifiant | `src/mqtt_edge_adapter.py`, `src/coap_server.py` | Bloque un doublon exact | L'attaquant choisit un nouvel `id` |
| Clôture des lots | Adaptateurs MQTT et CoAP | Empêche une seconde décision B2 sur un lot fermé | L'attaquant peut arriver le premier dans un lot ouvert |
| Écoute locale | MCP et A2A sur `127.0.0.1` ; Mosquitto publié sur `127.0.0.1:1883` | Limite l'exposition dans le banc | Le broker accepte les connexions anonymes ; la passerelle MQTT-SN écoute par défaut sur `0.0.0.0:10000` |
| Vérification d'identifiant Cloud | `src/cloud_orchestrator.py` | Rejette une réponse A2A pour un autre incident | Ne prouve pas l'origine de la réponse |

## 5. Modèles d'attaquant

| Attaquant | Capacités | Dans le périmètre ? |
|---|---|---|
| **A1 — Réseau classique** | Écoute, rejeu, injection et modification de messages sur les liens Device → Edge et Edge → Cloud ; aucune clé privée | Oui, cible principale d'IOT-174 et IOT-175 |
| **A2 — Quantique futur** | Comme A1, plus un ordinateur quantique capable de casser RSA et les courbes elliptiques avec l'algorithme de Shor | Oui, c'est ce qui justifie ML-DSA et ML-KEM plutôt qu'Ed25519 seul |
| **A2' — Récolter maintenant, déchiffrer plus tard** | Enregistre aujourd'hui le trafic chiffré Edge → Cloud pour le déchiffrer quand A2 existera | Oui, il concerne la confidentialité des incidents (IOT-177) |
| **A3 — Capteur compromis** | Possède la clé privée d'un capteur, ou agit sur son environnement physique | Non pour la cryptographie : un message signé avec une clé volée est valide. Ce cas relève de la détection (B2) et de la révocation |
| **A4 — Accès à la machine hôte** | Lit ou modifie les fichiers JSONL et les modèles sur le disque de l'Edge ou du Cloud | Non : hors périmètre de la simulation sur une seule machine |

**Différence entre A1 et A2 pour la signature :** contre A1, Ed25519 suffit aujourd'hui. Contre A2, une signature Ed25519 peut être falsifiée dès qu'un ordinateur quantique suffisant existe. Ce risque compte surtout pour les signatures qui doivent rester valides longtemps, comme celle d'un modèle déployé par OTA. La configuration C1 (Ed25519) sert donc de référence de coût, et C2 (ML-DSA) de cible.

**Algorithmes symétriques :** l'algorithme de Grover réduit la marge de sécurité des clés symétriques sans les casser. La pratique courante consiste à utiliser des clés plus longues (par exemple AES-256) pour le chiffrement qui suit l'échange ML-KEM.

## 6. Menaces par lien

| ID | Lien | Menace | Attaquant | Effet sur le système | Contre-mesure prévue | Ticket |
|---|---|---|---|---|---|---|
| T1 | Device → Edge | Usurpation d'un capteur (télémétrie falsifiée) | A1, A2 | Écart artificiel à la médiane ; faux positif, isolement d'un capteur sain | Signature par capteur, vérifiée avant le regroupement | IOT-174 |
| T2 | Device → Edge | Usurpation de deux capteurs du même lot | A1, A2 | Médiane contaminée : faux positifs sur le capteur sain, anomalies manquées | Même signature ; mesure de l'effet en C0 et C2 | IOT-174, IOT-175 |
| T3 | Device → Edge | Rejeu d'un message ancien avec un nouvel `id` | A1 | Mesure périmée injectée dans un lot ouvert | Compteur monotone par capteur inclus dans la partie signée | IOT-174 |
| T4 | Device → Edge | Fausse alerte B1 ou suppression d'une alerte | A1, A2 | Incident `LOCAL_ML_ANOMALY` inventé ou perdu | Signature des messages `anomaly_alert` et de CoAP `/alert` | IOT-174 |
| T5 | Edge → Cloud | Incident inventé ou modifié avant MCP | A1, A2 | Recommandation sur un incident qui n'existe pas | Signature de l'incident par l'Edge, vérifiée par le Cloud | IOT-177 |
| T6 | Edge → Cloud | Lecture du trafic des incidents | A2' | Fuite d'informations sur l'installation et ses défaillances | Canal chiffré après échange ML-KEM | IOT-177 |
| T7 | Cloud → A2A | Réponse A2A falsifiée | A1 | Recommandation incorrecte enregistrée | Signature de la réponse ; vérification actuelle de l'identifiant Cloud conservée | IOT-177 (option) |
| T8 | Cloud → Device | Modèle OTA modifié ou remplacé | A1, A2 | Prédictions B1 faussées ; exécution de code au chargement `joblib` | Signature ML-DSA du modèle, vérifiée avant tout chargement | IOT-176, IOT-158 |

## 7. Hors périmètre

- Capteur compromis avec sa clé privée (A3) et attaques physiques sur l'environnement mesuré.
- Accès à la machine hôte (A4), y compris la modification directe des fichiers JSONL ou des modèles sur le disque.
- Déni de service par saturation (traité comme une mesure de robustesse dans IOT-154, pas comme une menace cryptographique).
- Attaques par canaux auxiliaires sur l'implémentation (temps, consommation), qui ne sont pas mesurables en simulation.
- Gestion du cycle de vie des clés : génération sécurisée sur le matériel, révocation, rotation.

## 8. Scénarios d'expérience dérivés

| Scénario | Menace | Configuration | Mesures attendues |
|---|---|---|---|
| S1 — Usurpation de deux capteurs (+3,5 °C) | T2 | C0, puis C2 | Faux positifs et anomalies manquées de B2 ; messages rejetés |
| S2 — Rejeu dans la fenêtre de 300 s | T3 | C0, puis C2 | Messages rejoués acceptés ou rejetés |
| S3 — Fausse alerte locale | T4 | C0, puis C2 | Incidents `LOCAL_ML_ANOMALY` inventés acceptés ou rejetés |
| S4 — Modèle OTA modifié | T8 | Sans signature, puis ML-DSA | Modèle chargé ou refusé |
| S5 — Coût nominal | — | C0, C1, C2, C3 | Tailles, temps de signature et de vérification, latence Edge → décision, octets par incident |

**Critère de non-régression commun :** sur les messages légitimes, les 600 décisions B2 de référence doivent rester identiques dans toutes les configurations.

## 9. Configurations

| Configuration | Télémétrie Device → Edge | Canal Edge → Cloud |
|---|---|---|
| C0 — sans protection | Aucune signature | Aucun chiffrement |
| C1 — référence classique | Ed25519 | Échange de clés classique |
| C2 — post-quantique | ML-DSA (FIPS 204) | ML-KEM (FIPS 203) |
| C3 — comparateur compact | FN-DSA (FIPS 206, encore en brouillon) | ML-KEM (FIPS 203) |

## 10. Limites de ce modèle

- Les menaces sont déduites du code et de l'architecture du prototype, pas d'un test d'intrusion.
- Une signature prouve l'origine et l'intégrité d'un message, pas l'exactitude de la mesure : un capteur légitime mais défaillant reste du ressort de B2.
- La simulation sur une seule machine ne reproduit ni la latence radio ni les contraintes mémoire d'un microcontrôleur.
