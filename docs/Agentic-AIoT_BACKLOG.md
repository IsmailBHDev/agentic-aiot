# Agentic-AIoT — Backlog produit et scientifique complet

**Version :** 1.1 — 23 novembre 2026

**Projet :** Architecture collaborative Edge–Cloud pour la détection d’anomalies dans les systèmes IoT

**Encadrement :** Prof. Dhaou Said

**Périmètre :** Simulation logicielle, recherche expérimentale, rapport scientifique, éventuel article IEEE

**Base de reprise :** `main` après la PR #13 (`6f46362`), livraison `8cfb19a`, tag `experiment-2026-11-23`.
**Source de cadrage :** [Rapport de recherche Agentic-AIoT dans Google Drive](https://docs.google.com/document/d/1BjNHVtcxBXK5VWqUWsL3GtK75S_jFqE8CJHBNzsz4pw/edit)

> **Usage :** ce fichier constitue le backlog global du projet, conservé dans `docs/Agentic-AIoT_BACKLOG.md`. Il s'adresse à l'étudiant, à Codex et à toute personne réalisant une revue du dépôt. Les phases initiales déjà réalisées sont conservées pour documenter l'historique. Les cases cochées représentent les réalisations rapportées et testées à ce jour, **pas** une nouvelle vérification automatique du dépôt. Les éléments `[~]` sont partiels ; les cases `[ ]` restent à traiter. Ne pas modifier ces statuts sans résultats vérifiables.

## 1. Mission scientifique et critères de réussite

### Question de recherche

**Comment une architecture Agentic-AIoT intégrant une détection collaborative entre capteurs Edge et une orchestration d’agents Cloud peut-elle améliorer la détection d’anomalies contextuelles tout en maîtrisant la latence et les faux positifs ?**

### Hypothèses

- **H1 — Détection contextuelle :** le contexte synchronisé de plusieurs capteurs améliore le rappel d’anomalies contextuelles par rapport à une détection locale.
- **H2 — Maîtrise des faux positifs :** cette amélioration peut être obtenue sans hausse excessive des faux positifs sur les variations environnementales légitimes.
- **H3 — Orchestration :** le Cloud produit des recommandations traçables à partir des incidents, avec un coût supplémentaire en délai et communication. B3 ne doit **pas** être présentée automatiquement comme une amélioration du F1-score.

### Trois configurations expérimentales

| Configuration | Fonction exacte | Évaluation principale |
|---|---|---|
| **B1** | Arbre de décision local sur température et vibration | Accuracy, précision, rappel, F1, faux positifs et faux négatifs |
| **B2** | B1 OU écart à la médiane des 3 températures synchronisées **strictement > 2,50 °C** | Parité Edge/hors ligne ; rappel contextuel ; faux positifs |
| **B3** | B2 Edge + incidents MCP + analyse/réponse A2A par règles | Exactitude/cohérence des décisions, livraison d’incidents, latence, coûts de communication |

B2 est validée hors ligne et le test de parité reproduit les 600 décisions au niveau Edge. E07 étend l’évaluation à cinq sessions synthétiques et B3 est testé de bout en bout en boucle locale.

## 2. Référence expérimentale à ne pas modifier

- Dataset synthétique : `data/collaborative_dataset.csv`, **1 000 itérations × 3 capteurs = 3 000 lignes**, 2 800 normales et 200 anormales.
- Scénarios : `NORMAL` (700 itérations), `LOCAL_ANOMALY` (100), `CONTEXTUAL_ANOMALY` (100), `COMMON_VARIATION` (100).
- Split initial par `(session_id, iteration)` : 2 400 observations train, 600 test ; 40 anomalies dans le test.
- Split de validation issu du train : 1 920 observations entraînement, 480 validation ; 32 anomalies de validation.
- B1 : accuracy **98,17 %**, précision **93,94 %**, rappel **77,50 %**, F1 **84,93 %** ; TN=558, FP=2, FN=9, TP=31.
- B2 (τ=2,50 °C) : accuracy **99,50 %**, précision **95,12 %**, rappel **97,50 %**, F1 **96,30 %** ; TN=558, FP=2, FN=1, TP=39.
- Rappel contextuel : **55 % (11/20) en B1 → 95 % (19/20) en B2** ; huit anomalies supplémentaires détectées, sans faux positif additionnel dans ce jeu de test.
- Faux négatif B2 résiduel : `synthetic-seed-42`, itération `132`, `node-03`, `temperature=28.164`, `group_median=25.742`, `deviation=2.422 < 2.50`, B1=0, étiquette réelle=1.
- Seuil 2,50 °C : sélectionné via validation F1 ; 3,00 °C était ex æquo, départagé en faveur du plus petit seuil. **Ne jamais réajuster à partir du test final.**
- Pipeline Cloud : test préliminaire **n=2 incidents** ; Edge→Cloud 563,46 ms ; Cloud→décision 72,166 ms ; Edge→décision 635,626 ms (moyennes). Ces durées comprennent des scrutations logicielles ; elles ne constituent pas encore une caractérisation scientifique robuste.
- A2A : **point d'accès JSON-RPC minimal fondé sur des règles**, pas une preuve de conformité totale au protocole et pas un LLM.

## 3. Règles de travail pour Codex et les contributeurs

1. **Lire ce backlog, `README-CLOUD-MVP.md` et les fichiers impliqués avant de toucher au code.** Confirmer le nom de branche avec Git et inspecter les changements non enregistrés.
2. Travailler par **ticket/lot cohérent**, présenter l'approche, puis réaliser des changements minimaux. Ne pas développer toutes les phases d'un coup.
3. Ne pas réécrire silencieusement les jeux de données, les prédictions B1/B2 et les résultats de référence. Ajouter de nouveaux fichiers de résultats versionnés et datés pour toute nouvelle expérience.
4. Ne pas confondre **un incident**, **un événement d’alerte** et **une prédiction B2**. Pour un capteur/itération, B1 et collaboration simultanément positifs donnent **une seule prédiction positive**, tout en permettant plusieurs traces événementielles si le contrat l'exige.
5. Ne jamais mélanger les sessions : identité des lots = `(session_id, iteration)`. Trois `device_id` **distincts** sont requis pour B2.
6. Calculer les prédictions B2 à partir des **trois mesures synchronisées valides**, y compris celles des capteurs déjà logiquement isolés, pour préserver la parité avec le calcul hors ligne. L'isolation est une **politique distincte**.
7. Les lots incomplets n'ont **pas** de prédiction collaborative ; les alertes locales B1 reçues sont conservées et traitées. Expiration des lots = politique explicite, sans ressusciter les lots fermés.
8. Les motifs `LOCAL_ML_ANOMALY` et `SENSOR_INCONSISTENCY` doivent conserver leur sens pour MCP/A2A. Les changements au format JSON restent compatibles avec les anciens journaux ; `iteration` peut être facultatif.
9. Ajouter ou adapter des **tests déterministes** ; lancer les tests concernés et la suite régression ; afficher les résultats et les diffs. Ne pas prétendre avoir testé ce qui ne l'a pas été.
10. **Aucun commit, push, pull request, merge ou modification directe de `main` sans instruction explicite.** Inspecter les secrets, fichiers `.env`, journaux et modèles avant l'ajout Git.
11. Documenter toute différence entre comportement **hors ligne** et comportement **en flux réel**.
12. Les nouvelles propriétés (tolérance aux pertes, garantie de livraison, conformité protocolaire, autonomie agentique) doivent être **testées**, et non présumées.

## 4. Vue des épics et statut

| Épic | Thème | Situation au 23/11/2026 | Priorité actuelle |
|---|---|---|---|
| E00 | Cadrage, architecture, gouvernance Git | Majoritairement réalisé | P2 |
| E01 | Simulation IoT et communication | Prototype fonctionnel, robustesse à compléter | P1 |
| E02 | Détection locale B1 | Référence expérimentale réalisée | P2 |
| E03 | Dataset, validation et B2 hors ligne | Réalisé sur une simulation synthétique | P1 |
| **E04** | **Intégration B2 au Edge opérationnel** | Livré, parité 600/600 | **P0** |
| **E05** | **Synchronisation des transports MQTT/CoAP/TCP** | Livré et testé en boucle locale | **P0** |
| E06 | MCP, A2A et validation B3 de bout en bout | B3 mesuré en boucle locale ; coût réseau complet encore ouvert | P1 |
| E07 | Robustesse, validité et reproductibilité scientifique | Livré sur cinq graines ; évaluation externe facultative ouverte | P1 |
| E08 | État de l'art et positionnement scientifique | Revue ciblée et citations livrées | P1 |
| E09 | Rapport, article IEEE et démonstration | Rapport, figures et démonstration livrés ; canevas et manuscrit ouverts | P1 |
| E10 | CI, documentation technique et livraison | CI et tag publiés ; revue de PR formelle non établie | P2 |

**Statuts** : `[x]` terminé sur la base des échanges/résultats ; `[~]` partiel ou à vérifier ; `[ ]` non terminé.

**Priorités** : **P0** indispensable à la prochaine démonstration ; **P1** indispensable à la validation scientifique ; **P2** amélioration/documentation ; **P3** extension facultative.

---

## E00 — Cadrage, architecture et gouvernance

- [x] **IOT-001 [P1] — Définir le sujet et la question de recherche.** Livrable : question commençant par « Comment », H1/H2/H3 dans le rapport. Réf. : `3dbf661` et `8cfb19a`, rapport Google Docs, sections 2 et 6 et annexes B/C.
- [x] **IOT-002 [P1] — Définir B1, B2 et B3.** Livrable : trois configurations distinguant performance de détection et orchestration. Réf. : `3dbf661` et `8cfb19a`, rapport Google Docs, sections 2 et 6 et annexes B/C.
- [x] **IOT-003 [P1] — Initialiser le dépôt et l'environnement local Python.** Livrable : dépôt Git et `.venv` opérationnel. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [x] **IOT-004 [P1] — Développer et fusionner le MVP Cloud MCP/A2A.** Référence Git : PR #8, merge `ef730e0`. Réf. : PR #8, `ef730e0`, tests MVP Cloud/A2A.
- [x] **IOT-005 [P1] — Développer et fusionner la première expérience B2 hors ligne.** Référence Git : PR #9, merge `aa6468c`. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-006 [P1] — Créer la branche d'intégration B3.** `feature/edge-cloud-a2a-evaluation`. Réf. : PR #10, `1d1bcdf`.
- [x] **IOT-007 [P2] — Mettre à jour le README global et le diagramme d'architecture.** Acceptation : composants, ports, commandes, limites et flux documentés sans confusion entre MVP et conformité. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [~] **IOT-008 [P2] — Maintenir un registre des décisions scientifiques (ADR/research log).** Acceptation : chaque modification de méthode ou seuil est motivée et datée. Réf. : le protocole et le manifeste de la PR #13 documentent les choix. Le registre ADR dédié reste à constituer.
- [x] **IOT-009 [P2] — Définir une stratégie de gestion des artefacts générés.** Acceptation : `.gitignore`, données sources, rapports reproduisibles, journaux non sensibles clairement distingués. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.

## E01 — Capteurs simulés et bus IoT

- [x] **IOT-010 [P1] — Produire les mesures de trois capteurs simulés.** Fichier : `src/device_simulator.py`. Réf. : PR #11, `2f491b9`, validation télémétrie et rejeu B3 avec B1 explicite.
- [x] **IOT-011 [P1] — Mettre en place la passerelle MQTT-SN → MQTT/Mosquitto.** Source : `src/mqttsn_gateway.py` ; UDP 10000 / MQTT TCP 1883. Réf. : PR #11, `2f491b9`, validation télémétrie et rejeu B3 avec B1 explicite.
- [x] **IOT-012 [P1] — Mettre en place l'adaptateur MQTT → Edge.** Source : `src/mqtt_edge_adapter.py`. Réf. : PR #11, `2f491b9`, validation télémétrie et rejeu B3 avec B1 explicite.
- [x] **IOT-013 [P1] — Mettre en place la télémétrie CoAP et les alertes.** Source : `src/coap_server.py` ; routes `/telemetry`, `/alert`, `/health`. Réf. : PR #11, `2f491b9`, validation télémétrie et rejeu B3 avec B1 explicite.
- [x] **IOT-014 [P1] — Vérifier le contrat commun de télémétrie.** Acceptation : `session_id`, `iteration`, `id`, `src.agent`, `payload.temperature`, `payload.vibration`, `payload.prediction` validés ou rejetés explicitement. Réf. : PR #11, `2f491b9`, validation télémétrie et rejeu B3 avec B1 explicite.
- [x] **IOT-015 [P1] — Ajouter un mode de rejeu déterministe de données annotées.** Acceptation : même triplet reproduit via différents transports avec mêmes prédictions, sans modifier les données de référence. Réf. : PR #11, `2f491b9`, validation télémétrie et rejeu B3 avec B1 explicite.
- [~] **IOT-016 [P2] — Ajouter des compteurs de messages et événements de diagnostic.** Acceptation : reçu, accepté, doublon, invalide, expiré par transport et session. Réf. : `2f491b9` : compteurs agrégés par transport, ventilation par session à compléter.

## E02 — Modèle B1 et baseline

- [x] **IOT-020 [P1] — Générer le premier dataset local (`sensor_dataset.csv`).** 1 000 observations équilibrées ; considéré comme dataset technique initial. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-021 [P1] — Entraîner un arbre de décision de référence.** `DecisionTreeClassifier(max_depth=3, random_state=42)`. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-022 [P1] — Évaluer B1 sur le test collaboratif.** `src/evaluate_baseline_b1.py` ; métriques et matrice de confusion sauvegardées. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-023 [P1] — Conserver le modèle expérimental distinct de celui opérationnel.** `models/baseline_b1.joblib` différent de `models/device_model.joblib`. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-024 [P1] — Clarifier le modèle utilisé en simulation B3.** Acceptation : mode explicite de rejeu des prédictions CSV ou chargement du modèle B1 expérimental ; pas de substitution silencieuse de modèles. Réf. : PR #11, `2f491b9`, validation télémétrie et rejeu B3 avec B1 explicite.
- [ ] **IOT-025 [P2] — Tester le chargement, la version et l'intégrité du modèle.** Acceptation : erreurs contrôlées si fichier absent/incompatible.

## E03 — Données expérimentales, validation et B2 hors ligne

- [x] **IOT-030 [P1] — Générer le dataset multi-capteurs annoté.** `src/generate_collaborative_dataset.py`, 3 000 observations. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-031 [P1] — Contrôler les étiquettes et trois capteurs par itération.** 1 000 itérations valides, 0 lot invalide dans le dataset observé. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-032 [P1] — Réaliser la séparation train/test par itération.** `src/prepare_experiment.py`. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-033 [P1] — Réserver une validation indépendante du test.** `src/prepare_b2_validation.py` : 640 itérations d'entraînement, 160 de validation. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-034 [P1] — Sélectionner le seuil sur validation.** `src/select_b2_threshold.py` : τ = **2,50 °C** ; comparaison stricte `>`. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-035 [P1] — Comparer B1 et B2 sur les 600 observations du test.** `src/evaluate_collaborative_b2.py`, résultats dans `results/collaborative_b2_predictions.csv`. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-036 [P1] — Analyser les métriques par scénario.** Rappel contextuel B1 55 % ; B2 95 %. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-037 [P1] — Documenter l'unique faux négatif B2.** Itération 132, `node-03`, écart 2,422 °C ; pas de réoptimisation sur test. Réf. : PR #9, `aa6468c`, scripts et CSV historiques.
- [x] **IOT-038 [P1] — Verrouiller un manifeste de reproductibilité du dataset.** Acceptation : graine, versions, configuration du générateur, splits et empreintes de fichiers documentés. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [x] **IOT-039 [P2] — Ajouter un script de vérification des références expérimentales.** Acceptation : arrêt explicite en cas de divergence des comptes et prédictions attendues. Réf. : `test_edge_b2_matches_reference_predictions` et `src/verify_reproduction.py`.

## E04 — Intégration B2 dans l'agent Edge (**priorité P0**)

> Le noyau B2 Edge applique déjà le seuil strict de 2,50 °C. Le test de parité préserve les 600 décisions de référence.

- [x] **IOT-040 [P0] — Inventorier les appels et effets de bord de `analyze_devices`.** Fichiers : `edge_agent.py`, `mqtt_edge_adapter.py`, `coap_server.py`, `edge_server.py`. Acceptation : contrats d'entrée/sortie et impact sur les incidents documentés. Réf. : PR #10, `1d1bcdf`, `calculate_b2` et `tests/test_edge_b2.py`.
- [x] **IOT-041 [P0] — Extraire une fonction B2 pure et réutilisable.** Entrée : trois mesures de capteurs distincts d'une même session/itération. Sortie : médiane, écart signé/absolu, alerte collaborative et prédiction `B1 OU alerte`. Aucun journal, aucune isolation. Réf. : PR #10, `1d1bcdf`, `calculate_b2` et `tests/test_edge_b2.py`.
- [x] **IOT-042 [P0] — Appliquer strictement la règle `abs(T - median(T1,T2,T3)) > 2.50`.** Acceptation : 2,50 exact = négatif ; 2,5001 = positif ; écarts positifs et négatifs ; trois capteurs distincts requis. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-043 [P0] — Conserver les mesures des capteurs déjà isolés pour le calcul scientifique.** Acceptation : un groupe complet reste analysable après isolation ; politique de sûreté distincte. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-044 [P0] — Distinguer prédiction B2, événements d'alerte et politique d'isolation.** Acceptation : B1=1 et collaboration=1 comptent une seule prédiction ; traçabilité des raisons conservée. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-045 [P0] — Préserver le traitement immédiat de `LOCAL_ML_ANOMALY`.** Acceptation : lot incomplet / expiration n'empêchent pas une alerte locale reçue. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-046 [P1] — Préserver le contrat d'incident existant.** Champs : `device_id`, `temperature`, `reference`, `reason`, `session_id`, `timestamp`, `action`. `iteration` ajout facultatif, rétrocompatible. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-047 [P0] — Ajouter les tests unitaires Edge B2.** Normaux, seuil exact, sous/sur-seuil, contexte, alerte locale seule, double signal, groupe incomplet, capteur isolé, sessions distinctes. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-048 [P0] — Exécuter la suite de régression avant toute intégration réseau.** Acceptation : tous tests existants et nouveaux réussis ; résultats et diff consignés. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.

**Définition de terminé de E04 :** la fonction pure produit les décisions attendues, conserve les motifs d'incidents, traite les trois capteurs malgré l'isolement et n'altère pas les résultats B1/B2 de référence.

## E05 — Regroupement et robustesse MQTT, CoAP et TCP (**priorité P0**)

- [x] **IOT-050 [P0] — Corriger le cycle de vie des lots MQTT.** Contrôler le bug signalé `completed_iterations.add(key)` sur un dictionnaire ; corriger selon la structure réelle et tester l'expiration. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-051 [P0] — Valider les messages avant la mémorisation de leurs ID.** Acceptation : message invalide ne bloque pas un retransfert valide portant le même ID. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-052 [P0] — Cléer les lots par `(session_id, iteration)` dans MQTT.** Acceptation : deux sessions entremêlées ne se mélangent pas. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-053 [P0] — Traiter les doublons, l'ordre variable et les messages retardés.** Acceptation : un lot terminé/expiré ne génère pas une deuxième décision B2. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-054 [P0] — Expirer proprement les lots incomplets sans casser la boucle de surveillance.** Acceptation : pas d'exception, pas d'accumulation indéfinie, alertes locales conservées. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-055 [P0] — Aligner CoAP `/telemetry` sur la clé `(session_id, iteration)`.** Le regroupement par itération seule est insuffisant. Acceptation : aucune contamination inter-session. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-056 [P0] — Ajouter expiration et déduplication CoAP.** Acceptation : triplets complets et incomplets testés, sans double décision. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-057 [P1] — Préserver CoAP `/alert` indépendant de `/telemetry`.** Acceptation : incident local reçu sans attendre trois messages. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-058 [P1] — Examiner le chemin historique `src/edge_server.py`.** Si utilisé : appliquer clé de session ; sinon : documenter son statut et éviter de l'inclure dans les résultats. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-059 [P0] — Ajouter tests d'intégration des transports.** Deux sessions, désordre, doublon MQTT QoS 1, lot incomplet puis tardif, lot post-isolement. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-060 [P1] — Ajouter métriques de collecte.** Latence de constitution d'un triplet, lots complets/incomplets, erreurs, doublons, pertes simulées. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.

## E06 — Cloud MCP/A2A et validation B3

- [x] **IOT-070 [P1] — Créer le serveur MCP et le stockage d'incidents Cloud.** `src/cloud_mcp_server.py`, `src/cloud_store.py`. Réf. : PR #8, `ef730e0`, tests MVP Cloud/A2A.
- [x] **IOT-071 [P1] — Créer le pont Edge→MCP et l'orchestrateur.** `src/edge_cloud_bridge.py`, `src/cloud_orchestrator.py`. Réf. : PR #8, `ef730e0`, tests MVP Cloud/A2A.
- [x] **IOT-072 [P1] — Créer le serveur A2A JSON-RPC minimal.** `src/cloud_a2a_server.py`, analyse déterministe par règles. Réf. : PR #8, `ef730e0`, tests MVP Cloud/A2A.
- [x] **IOT-073 [P1] — Corriger et réussir les tests MVP Cloud/A2A.** Six tests observés réussis sur six. Réf. : PR #8, `ef730e0`, tests MVP Cloud/A2A.
- [x] **IOT-074 [P1] — Mesurer une première latence Edge→décision.** Seulement deux incidents : données exploratoires. Réf. : `README-CLOUD-MVP.md`, essai exploratoire n=2 conservé séparément.
- [x] **IOT-075 [P1] — Fixer un protocole d'identité des événements de bout en bout.** Corrélation `session_id` + `iteration` + `device_id` + `incident_id` + `cloud_incident_id` lorsque disponibles ; aucune correspondance inventée. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-076 [P1] — Vérifier le démarrage et le cycle de vie des services.** Le pont `--watch` démarre à la fin du journal : lancer les services avant l'injection. Acceptation : manuel de démarrage reproductible. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-077 [P1] — Rejouer un triplet par MQTT-SN→MQTT→Edge→MCP→A2A.** Scénario : B1=0, écart **> 2,50 et < 5,00 °C** ; confirmer un incident collaboratif réel. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-078 [P1] — Rejouer un triplet dans une autre session via CoAP.** Acceptation : aucun mélange inter-session, résultat comparable. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-079 [P1] — Vérifier les champs sur toute la chaîne.** `SENSOR_INCONSISTENCY` / `LOCAL_ML_ANOMALY`, device, médiane, session et éventuelle itération conservés ; décision retrouvée via `cloud_incident_id`. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-080 [P1] — Évaluer la validité des décisions A2A.** Attentes documentées pour `SENSOR_INCONSISTENCY`, `LOCAL_ML_ANOMALY` et motifs inconnus ; mesurer décisions conformes/non conformes aux règles annoncées. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-081 [P1] — Concevoir des sessions d'évaluation de taille suffisante.** Répétitions, nombre d'incidents, ordre de lancement, configuration et journaux isolés. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-082 [P1] — Mesurer et rapporter la latence B3.** Distinguer latences Edge→Cloud, Cloud→décision, Edge→décision, latence de collecte et, si mesurée, apparition simulée→décision. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [~] **IOT-083 [P1] — Mesurer la fiabilité et le coût de communication.** Messages/incident, volumes d'octets, livraison, doublons, pertes, échecs/reprises, surcharge de scrutation. Réf. : `2f491b9` : charges utiles, livraison et scrutation mesurées ; trafic complet et charge CPU ouverts.
- [x] **IOT-084 [P2] — Évaluer la robustesse de l'orchestrateur.** Redémarrage, incidents répétés, traitement après panne, erreur A2A, traçabilité ; ne pas prétendre à « exactly-once » non démontré. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-085 [P1] — Clarifier la valeur agentique de B3.** Quelles responsabilités, coordination, autonomie observable et bénéfices par rapport à une simple fonction déterministe ? Reconnaître les limites du MVP. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.

## E07 — Validité expérimentale, robustesse et reproduction

- [x] **IOT-090 [P1] — Formaliser le protocole B1/B2/B3.** Différencier les métriques de prédiction et celles d'orchestration. Réf. : PR #12, `86de07a`, protocole, JSON E07 et `tests/test_e07.py`.
- [x] **IOT-091 [P1] — Répéter B1/B2 sur plusieurs graines indépendantes.** Rapport : moyenne, dispersion, minima/maxima, nombre de répétitions. Réf. : PR #12, `86de07a`, protocole, JSON E07 et `tests/test_e07.py`.
- [x] **IOT-092 [P1] — Faire une évaluation croisée sans fuite.** Grouper par itération et session ; réserver une validation indépendante de chaque test. Réf. : PR #12, `86de07a`, protocole, JSON E07 et `tests/test_e07.py`.
- [x] **IOT-093 [P1] — Étudier la sensibilité au seuil et les faux positifs.** Réglage sur validation uniquement ; aucun nouveau tuning sur le test historique. Réf. : PR #12, `86de07a`, protocole, JSON E07 et `tests/test_e07.py`.
- [x] **IOT-094 [P1] — Tester des scénarios difficiles supplémentaires.** Bruit, dérive, valeurs manquantes, mesures hétérogènes, défaillance simultanée, anomalies progressives, valeurs limites. Réf. : PR #12, `86de07a`, protocole, JSON E07 et `tests/test_e07.py`.
- [x] **IOT-095 [P1] — Évaluer la limite du groupe de trois capteurs.** Deux capteurs disponibles, plusieurs capteurs malveillants, médiane contaminée, référence insuffisante. Réf. : PR #12, `86de07a`, protocole, JSON E07 et `tests/test_e07.py`.
- [x] **IOT-096 [P1] — Ajouter des baselines concurrentes simples.** Seuil local fixe, règle collaborative sans ML et/ou vote, pour mesurer la contribution propre de B2. Réf. : PR #12, `86de07a`, protocole, JSON E07 et `tests/test_e07.py`.
- [x] **IOT-097 [P1] — Effectuer une étude d'ablation.** ML seul, collaboration seule, ML+collaboration, Cloud sans changement de détection ; ne pas attribuer au Cloud des gains provenant du Edge. Réf. : PR #12, `86de07a`, protocole, JSON E07 et `tests/test_e07.py`.
- [x] **IOT-098 [P1] — Rapporter la variabilité et l'incertitude.** Effectifs, intervalles ou mesures de dispersion appropriés ; tenir compte des dépendances entre mesures d'une même itération. Réf. : PR #12, `86de07a`, protocole, JSON E07 et `tests/test_e07.py`.
- [ ] **IOT-099 [P2] — Évaluer un dataset externe ou données réelles si accessible.** Facultatif pour prototype, utile pour crédibilité ; décrire les différences de domaine.
- [x] **IOT-100 [P1] — Rédiger les menaces à la validité.** Données synthétiques, distribution construite, labels, risque de surajustement, absence de matériel réel et limites d'autonomie agentique. Réf. : PR #12, `86de07a`, protocole, JSON E07 et `tests/test_e07.py`.

## E08 — État de l'art et positionnement scientifique

- [x] **IOT-110 [P1] — Définir une stratégie de recherche bibliographique.** Mots-clés, bases consultées, critères d'inclusion/exclusion et date de consultation. Réf. : PR #13, `3dbf661`, matrice de littérature et section 3 du rapport.
- [x] **IOT-111 [P1] — Lire des publications sur la détection d'anomalies IoT.** Méthodes supervisées, non supervisées et limites des détecteurs locaux. Réf. : PR #13, `3dbf661`, matrice de littérature et section 3 du rapport.
- [x] **IOT-112 [P1] — Lire des publications sur Edge AI et détection collaborative.** Topologies, synchronisation, coûts et robustesse. Réf. : PR #13, `3dbf661`, matrice de littérature et section 3 du rapport.
- [x] **IOT-113 [P1] — Étudier les travaux sur multiagents, MCP et A2A.** Ne pas confondre protocole de communication et intelligence autonome. Réf. : PR #13, `3dbf661`, matrice de littérature et section 3 du rapport.
- [x] **IOT-114 [P1] — Construire la matrice de littérature.** Auteur/année, problème, approche, données, métriques, limites, différence avec Agentic-AIoT, DOI/URL vérifié. Réf. : PR #13, `3dbf661`, matrice de littérature et section 3 du rapport.
- [x] **IOT-115 [P1] — Identifier les lacunes réellement adressées par ce projet.** Aucune revendication de nouveauté sans comparaison sérieuse. Réf. : PR #13, `3dbf661`, matrice de littérature et section 3 du rapport.
- [x] **IOT-116 [P1] — Raffiner contributions et hypothèses à partir de la littérature.** Contraster contribution d'architecture, contribution expérimentale et contribution agentique. Réf. : PR #13, `3dbf661`, matrice de littérature et section 3 du rapport.
- [x] **IOT-117 [P1] — Intégrer des citations vérifiées dans le rapport.** Ne jamais inventer auteurs, DOI ou résultats d'articles. Réf. : PR #13, `3dbf661`, matrice de littérature et section 3 du rapport.

## E09 — Rapport de recherche, article IEEE et démonstration

- [x] **IOT-120 [P1] — Créer le rapport Google Docs.** Rapport français avec problématique, architecture, méthodologie et résultats. Réf. : `3dbf661` et `8cfb19a`, rapport Google Docs, sections 2 et 6 et annexes B/C.
- [x] **IOT-121 [P1] — Documenter la validation du seuil B2 et les résultats B1/B2.** Annexes B/C du Google Docs. Réf. : `3dbf661` et `8cfb19a`, rapport Google Docs, sections 2 et 6 et annexes B/C.
- [x] **IOT-122 [P1] — Documenter le faux négatif résiduel.** Annexe C.5. Réf. : `3dbf661` et `8cfb19a`, rapport Google Docs, sections 2 et 6 et annexes B/C.
- [x] **IOT-123 [P1] — Consolider le rapport principal.** Sections principales réconciliées avec les résultats B2, B3 et E07 ; passages antérieurs à B2 et contradictions avec les annexes B/C supprimés. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [x] **IOT-124 [P1] — Décrire précisément l'architecture et les flux.** Schémas du flux MQTT-SN/CoAP → Edge → MCP → A2A, rôles et limites. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [x] **IOT-125 [P1] — Documenter les algorithmes.** Pseudocode B1, B2 et politique d'incident B3 ; inclure `>` strict. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [x] **IOT-126 [P1] — Compléter la méthodologie reproductible.** Variables, scénarios, splits, seuils, métriques, nombre d'exécutions, outils et versions. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [x] **IOT-127 [P1] — Insérer les résultats B3 après expérimentation.** Tableaux de latences, livraison, décisions, communication et comparaison. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [x] **IOT-128 [P1] — Rédiger la discussion et les menaces à la validité.** Justifier les interprétations modestes et les limites observées. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [ ] **IOT-129 [P1] — Aligner le rapport sur le canevas du professeur.** Le modèle Word antérieurement transmis doit être rechargé s'il n'est plus accessible.
- [x] **IOT-130 [P1] — Préparer figures, tableaux et légendes scientifiques.** Traces d'exécution, matrices de confusion, métriques par scénario, incertitude. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [ ] **IOT-131 [P2] — Préparer un manuscrit anglais au format IEEE.** Seulement si positionnement, littérature et expérimentations sont suffisamment solides.
- [x] **IOT-132 [P2] — Préparer une démonstration courte reproductible.** Sans prétendre à une simulation matérielle ; montrer anomalie, incident et décision Cloud. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [~] **IOT-133 [P2] — Effectuer une relecture scientifique finale.** Références, figures, tableaux, cohérence code↔résultats↔manuscrit, orthographe. Réf. : `8cfb19a` : rapport, figures, tableau et références relus ; relecture finale avec canevas/manuscrit encore ouverte.

## E10 — Qualité du dépôt, tests et livraison

- [x] **IOT-140 [P1] — Maintenir les tests de base Cloud/A2A.** Six tests réussis observés ; élargir leur couverture. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-141 [P1] — Créer une suite testable sans réseau pour le cœur B2.** Tests déterministes, isolés, rapides. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-142 [P1] — Créer tests d'intégration par transport.** MQTT, MQTT-SN, CoAP, Edge, MCP et A2A selon services disponibles. Réf. : PR #11, `2f491b9`, tests Edge/transport/B3 et `README-CLOUD-MVP.md`.
- [x] **IOT-143 [P2] — Ajouter une CI GitHub Actions.** Lint, compilation, tests unitaires, rapport de résultats ; éviter de dépendre systématiquement de services réseau externes. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [x] **IOT-144 [P2] — Épingler les dépendances et versions Python.** Dépendances reproductibles, compatibilité Windows et Linux documentée. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [x] **IOT-145 [P1] — Vérifier l'absence de secrets ou données non destinées à Git.** Ne pas versionner `.env`, journaux incidentels, tokens ou identifiants. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [x] **IOT-146 [P2] — Fournir un guide « démarrage en une session ».** Pré-requis, ports, services, commandes, ordre de démarrage, nettoyage. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [x] **IOT-147 [P1] — Geler une version reproductible de l'expérience.** Tag, manifests, commits, tests, données, configuration, tableaux et graphiques. Réf. : PR #13, `8cfb19a`, guide de livraison et manifeste.
- [~] **IOT-148 [P2] — Faire une revue de PR avant fusion.** Contrôle tests, diff, objectifs du ticket, documents affectés ; préserver `main`. Réf. : Diff contre main et CI vérifiés avant livraison ; PR #13 fusionnée, revue formelle non établie.

---

## Suite du projet — E11 à E16

Périmètre validé par le professeur : simulation logicielle, sans matériel ESP32 requis. Ordre retenu : **E11 → E16 → E12 → E13 → E14 (minimal) → E15**. L’axe post-quantique est prioritaire sur le RAG. Une branche par ticket depuis main. Accord explicite requis pour chaque commit, push, PR ou fusion. Le seuil B2 de 2,50 °C, les données historiques et les 600 décisions de référence sont gelés. Toute nouvelle expérience produit un fichier séparé et daté. Exécuter les tests pertinents et actualiser le rapport pour les tickets qui le concernent.

### E11 — Reprise et gouvernance

- [x] **IOT-150 — Réconcilier le backlog et archiver le plan B3.** État E00–E10 recoupé avec les commits et tests, épics E11–E16 ajoutés et [ancien backlog archivé](archive/Agentic-AIoT_BACKLOG_B3.md). Réf. : PR #14, commit `06cc00e`, fusion `3dadd44`.
- [x] **IOT-151 — Repartir de main.** PR #13 fusionnée sur `6f46362` avec [CI du merge verte](https://github.com/IsmailBHDev/agentic-aiot/actions/runs/45309269913) ; PR #14 fusionnée sur `3dadd44` ; branche `docs/iot-151-backlog-fixes` créée depuis main. Contrôler la CI du merge `3dadd44` dans l’onglet Actions.

### E16 — Axe post-quantique

- [x] **IOT-172 — Modéliser les menaces** Réf. : [`docs/pq_threat_model.md`](pq_threat_model.md) — 5 actifs, 7 contrôles existants analysés, attaquants A1 à A4, menaces T1 à T8, scénarios S1 à S5 ; section 5.6 du rapport mise à jour.
  1. Lister les attaques : télémétrie falsifiée, rejeu, modèle OTA corrompu, interception Edge–Cloud.
  2. Distinguer attaquant classique et attaquant quantique (« récolter maintenant, déchiffrer plus tard »).
  3. Fixer ce qui est hors périmètre : capteur compromis avec sa clé privée.
  4. Reporter le résultat dans la section 5.6 du rapport.
- [x] **IOT-173 — Choisir la bibliothèque** Décision : `cryptography` 50.0.2, déjà épinglée, pour Ed25519, ML-DSA-44 (défaut) et ML-KEM-768 ; FN-DSA (C3) reporté et optionnel. Réf. : [`docs/pq_library_choice.md`](pq_library_choice.md), `tests/test_pq_primitives.py` (10 tests réussis sous Linux). Confirmé sous Windows le 25 novembre 2026 (Python 3.14.6, suite complète : 130 réussis, 5 ignorés car réseau).
  1. Installer liboqs et son interface Python sous Windows et Linux ; noter les versions.
  2. Vérifier ML-DSA, ML-KEM et FN-DSA, plus Ed25519 comme référence classique.
  3. Mettre ces dépendances dans un fichier séparé pour ne pas casser la CI.
- [x] **IOT-174 — Signer la télémétrie et la vérifier à l'Edge** Réf. : `src/message_auth.py` (C0 à C2 via `AIOT_AUTH_MODE`, compteur anti-rejeu), vérification dans `src/mqtt_edge_adapter.py` et `src/coap_server.py` (`/telemetry` et `/alert`), signature dans `src/device_simulator.py`, `tests/test_message_auth.py` (29 tests, dont parité 600/600 en Ed25519 et ML-DSA-44).
  1. Générer une paire de clés par capteur simulé ; enregistrer les clés publiques côté Edge.
  2. Signer chaque message avec un compteur ou un horodatage contre le rejeu.
  3. Vérifier avant le regroupement par (session_id, iteration) ; compter les rejets.
  4. Rendre la protection configurable (C0 sans protection, C1 Ed25519, C2 ML-DSA, C3 FN-DSA).
  5. Acceptation : les 600 décisions B2 de référence restent identiques ; un message modifié ou rejoué est rejeté ; tests sur MQTT-SN et CoAP.
- [x] **IOT-175 — Rejouer l'attaque des deux capteurs falsifiés** Réf. : `src/evaluate_pq_attacks.py`, `results/pq_attacks_2026-11-23.json`, `tests/test_pq_attacks.py`. Sur les 600 observations du test historique, S1 fait passer le F1 de 96,30 % à 28,92 % en C0 (173 faux positifs) ; C1 et C2 rejettent les 400 messages falsifiés et retrouvent exactement la référence. S2 (rejeu) et S3 (fausses alertes) sont aussi neutralisés.
  1. Reprendre le scénario E07 « deux capteurs décalés de +3,5 °C » comme injection par un attaquant.
  2. Mesurer les faux positifs et les anomalies manquées de B2 en C0, puis en C2.
  3. Enregistrer dans un nouveau fichier de résultats daté.
- [x] **IOT-176 — Signer les modèles distribués** Réf. : `src/model_signing.py` (fichier `<modèle>.sig`, vérification avant `joblib.load`, activée par `AIOT_MODEL_SIGNING`), chargement du simulateur via `load_model`, `tests/test_model_signing.py` (10 tests : modèle modifié, remplacé, non signé ou mal algorithmé refusé sans chargement). La distribution OTA elle-même reste à faire dans IOT-158.
  1. Le Cloud signe chaque modèle publié.
  2. Le capteur simulé refuse un modèle non signé ou modifié.
- [x] **IOT-177 — Établir le canal Edge–Cloud avec ML-KEM** Réf. : `src/secure_channel.py` (modes `x25519`, `ml-kem-768` et hybride `x25519+ml-kem-768` via `AIOT_CHANNEL_MODE` ; HKDF-SHA256, AES-256-GCM, incident signé par l'Edge en Ed25519 ou ML-DSA-44, rejeu refusé), scellement dans `src/edge_cloud_bridge.py`, ouverture dans `src/cloud_store.py`, `tests/test_secure_channel.py` (23 tests). Le passage réel par MCP reste à valider avec `AIOT_TEST_NETWORK=1`.
  1. Échanger une clé de session ML-KEM, puis chiffrer les incidents.
  2. Option : version hybride classique + post-quantique.
- [x] **IOT-178 — Mesurer le coût** Réf. : `src/evaluate_pq_cost.py`, `results/pq_cost_2026-11-23.json`, `tests/test_pq_cost.py`. Mesures hors réseau : primitives sur 1 000 opérations, tailles des messages et incidents scellés, traitement Edge sur 5 × 600 messages. Message de télémétrie : 356 octets en clair, 508 avec Ed25519, 3 650 avec ML-DSA-44 (× 10,25). Calcul ajouté inférieur à 1 ms par message ou incident. Banc B3 en réseau local (25 novembre 2026, Windows, 6 répétitions et 108 incidents par configuration) : `results/pq_b3_network_2026-11-25.json`, `src/summarize_pq_b3.py`. 108/108 livrés et conformes partout, y compris incidents scellés via MCP ; volume × 13 vers l'Edge et × 11 vers MCP en ML-DSA-44 ; effet sur la latence non distinguable de la variabilité du banc.
  1. Tailles des clés, des signatures et des messages.
  2. Temps de signature et de vérification sur 1 000 opérations.
  3. Latence Edge → décision et octets par incident avec le banc B3 (3 répétitions), pour C0, C1, C2 et C3.
  4. Comparer aux ordres de grandeur publiés (section 2.1 du rapport).
- [x] **IOT-179 — Rédiger les résultats : section 6.5, discussion de H4 à H6, menaces à la validité.** Réf. : [`docs/pq_results.md`](pq_results.md) (utilisation, reproduction, résultats) ; rapport mis à jour (sections 5.6, 6.5, 7 et 9). H4 soutenue pour le calcul, H5 soutenue en simulation, H6 non testée (FN-DSA reporté).

### E12 — Résilience et performances

- [x] **IOT-152 — Perte du Cloud** Réf. : [`docs/resilience.md`](resilience.md), `tests/test_cloud_outage.py` (6 tests). L'Edge continue B1, B2 et la journalisation pendant la panne (600 décisions identiques) ; le pont transmet ensuite tous les incidents en attente, une fois chacun et dans l'ordre. Pont corrigé : position avancée par incident, fichier d'état optionnel pour la reprise, attente bornée, compteurs.
  1. Arrêter MCP et A2A pendant un rejeu.
  2. Vérifier que l'Edge continue B1, B2 et la journalisation.
  3. Relancer le Cloud et vérifier que le pont transmet les incidents en attente.
  4. Acceptation : aucun incident perdu ; décisions B2 identiques avec ou sans Cloud.
- [x] **IOT-153 — Coupure Device → Edge** Réf. : `src/evaluate_device_loss.py`, `results/resilience_device_loss_2026-11-25.json`, `tests/test_device_loss.py` (6 tests), [`docs/resilience.md`](resilience.md). De 0 à 30 % de pertes, avec doublons et désordre : aucune double décision, aucune décision B2 fausse, chaque alerte B1 reçue journalisée immédiatement. Le rappel B2 tombe de 97,5 % à 74,2 % à 10 % de pertes (87,5 % avec les alertes B1), car un lot exige les trois capteurs.
- [x] **IOT-154 — Surcharge** Réf. : `src/evaluate_edge_load.py`, `results/resilience_edge_load_2026-11-25.json`, `tests/test_edge_load.py` (2 tests), [`docs/resilience.md`](resilience.md). Calcul de l'Edge seul (sans broker ni réseau) : C0 suit jusqu'à environ 48 000 msg/s (plus haut débit testé) ; avec ML-DSA-44, 5 000 msg/s tenus et saturation vers 6 000, sans perte mais avec attente croissante. Défaut corrigé : l'anti-rejeu d'IOT-174 devenait coûteux sous charge (débit tombé à ~260 msg/s).
- [x] **IOT-155 — Benchmark des trois niveaux** Réf. : `src/evaluate_tiers.py`, `tests/test_tiers.py`. Mesure par niveau : inférence et signature au Device, traitement d'un message et calcul B2 à l'Edge, enregistrement, ouverture d'un incident scellé et analyse A2A au Cloud ; latences réseau reprises du banc B3 ; colonne RAG réservée à E14. Mesuré sous Windows le 25 novembre 2026 (`results/tiers_benchmark_2026-11-25.json`) : moins de 0,5 ms de calcul par opération et par niveau ; la latence de bout en bout vient du trajet Edge → Cloud.
- [x] **IOT-156 — Simuler la contrainte TinyML** Réf. : `src/evaluate_tinyml.py`, `results/tinyml_b1_2026-11-25.json`, `tests/test_tinyml.py` (7 tests), [`docs/resilience.md`](resilience.md). B1 élagué (15 → 11 nœuds) et quantifié en int16 : 42 octets au lieu de 2 793, prédictions identiques sur 3 000 observations, F1 inchangé (84,93 %). L'inférence via DataFrame et scikit-learn coûte 0,37 ms contre 0,0005 ms pour la table.
- [x] **IOT-180 — Aligner le modèle du simulateur sur le B1 évalué.** `models/device_model.joblib` (une seule comparaison, F1 de 66,67 % sur le test, 13 écarts sur 600 avec le B1 de référence) diffère du B1 des résultats. Décision : le fichier gelé n'est pas modifié ; la version 1 publiée par l'OTA (IOT-158) est le B1 de référence et reproduit les 600 prédictions (F1 84,93 %). Le simulateur l'exécute avec `AIOT_OTA_DEVICE_DIR` ; sans OTA, il garde le modèle historique. Réf. : [`docs/retraining_ota.md`](retraining_ota.md).

### E13 — Réentraînement et OTA simulé

- [ ] **IOT-157 — Pipeline de ré-entraînement**
  1. Construire un jeu de données à partir des incidents et décisions journalisés.
  2. Ré-entraîner l'arbre ; versionner le modèle avec son empreinte.
  3. Évaluer sur des sessions tenues à l'écart, jamais sur le test historique.
- [x] **IOT-158 — OTA simulé : publication, téléchargement, vérification d'empreinte et de signature, activation, retour arrière ; version active visible dans la télémétrie ; modèle corrompu refusé.** Réf. : `src/ota.py`, `src/evaluate_ota.py`, `results/ota_2026-11-25.json`, `tests/test_ota.py` (28 tests), [`docs/retraining_ota.md`](retraining_ota.md). Avec Ed25519 ou ML-DSA-44, altération, dépôt compromis, version non signée, rétrogradation déguisée, catalogue antérieur et modèle incompatible sont refusés sans toucher à la version active ; sans signature, un dépôt compromis fait installer un modèle empoisonné (F1 0 %). Vérification ML-DSA-44 : 0,37 ms ; signature de 3 405 octets. Champ facultatif `payload.model_version` dans la télémétrie.
- [ ] **IOT-159 — Ajuster les règles Edge depuis le Cloud : délai d'expiration des lots et politique d'isolement, sans toucher au seuil B2.**

### E14 — RAG minimal

- [ ] **IOT-160 — Choisir un petit modèle de langage local : licence, taille, latence, fonctionnement hors ligne.**
- [ ] **IOT-161 — Base vectorielle : incidents, décisions, documentation des capteurs et procédures.**
- [ ] **IOT-162 — Agent superviseur RAG : cas similaires, analyse et recommandation sourcées ; retour aux règles en cas de doute.**
- [ ] **IOT-163 — Synthèse automatique des incidents. Facultatif si le temps le permet.**
- [ ] **IOT-164 — Évaluation : conformité, pertinence des cas retrouvés, latence, réponses non fondées ; comparaison avec rule_based_v1 ; aucun effet sur le F1.**
- [ ] **IOT-165 — Étudier la valeur agentique. Facultatif si le temps le permet.**

Le périmètre E14 reste à confirmer avec le professeur.

### E15 — Démonstration et livraison finale

- [ ] **IOT-166 — Conteneuriser l'Edge et le Cloud : une seule commande démarre toute la chaîne.**
- [ ] **IOT-167 — Manuel d'installation et d'utilisation (Windows et Linux).**
- [ ] **IOT-168 — Vidéo de démonstration : incident capté, traité à l'Edge, analysé au Cloud, message signé.**
- [ ] **IOT-169 — Rapport final : axes 1 et 2 ; alignement sur le canevas du professeur (IOT-129, fichier Word attendu).**
- [ ] **IOT-170 — Présentation de synthèse.**
- [ ] **IOT-171 — Geler la version finale : nouveau tag, manifeste mis à jour, CI verte.**

IOT-099 reste facultatif. IOT-131 reste conditionné à la solidité des résultats.

---

## 5. Ordre d'exécution recommandé (sprints / jalons)

> Planning **indicatif** ; les dépendances techniques priment sur les dates. Les semaines ne constituent pas des délais garantis.

| Sprint | Objectif | Tickets prioritaires | Condition de sortie |
|---|---|---|---|
| **S0 — Baseline gelée** | Inventaire du code et des références, sans modification destructive | IOT-040, IOT-038, IOT-024 | Contrats analysés, résultats historiques préservés |
| **S1 — Cœur B2 Edge** | Fonction pure, seuil exact, séparation détection/isolation | IOT-041 à IOT-048 | Tests unitaires réussis, incident compatible |
| **S2 — Collecte robuste** | Lots, déduplication, timeout, deux sessions | IOT-050 à IOT-059 | MQTT/CoAP fiables sur scénarios de test |
| **S3 — Parité Edge vs hors ligne** | Rejouer les 600 observations avec mêmes prédictions B1 | IOT-015, IOT-024, IOT-039, IOT-047 | **600/600 prédictions B2 égales ligne à ligne** ; mêmes métriques |
| **S4 — B3 bout en bout** | Vérifier MCP, stockage, A2A et décisions | IOT-075 à IOT-080 | Un incident ciblé et sa décision corrélés |
| **S5 — Mesures B3** | Rejouer plusieurs sessions, fiabilité, latence et surcoûts | IOT-081 à IOT-085 | Rapport n suffisant, méthodes de temps explicites |
| **S6 — Validité scientifique** | Robustesse, répétitions, ablations, incertitudes | IOT-090 à IOT-100 | Résultats multi-graines et limites documentées |
| **S7 — Écriture** | Revue scientifique, rapport, figure, manuscript éventuel | IOT-110 à IOT-133 | Rapport cohérent, sources vérifiées, résultats traçables |
| **S8 — Livraison** | CI, reproduction, revue, tag, démonstration | IOT-140 à IOT-148 | Dépôt reproductible, PR validées, présentation prête |
| **S9 — Reprise (E11)** | Backlog réconcilié, reprise depuis main | IOT-150, IOT-151 | Backlog versionné, branche du ticket suivant créée |
| **S10 — Axe post-quantique (E16)** | Menaces, signature de la télémétrie, attaque rejouée, coûts | IOT-172 à IOT-179 | Décisions B2 de référence inchangées ; coûts et protection mesurés pour C0 à C3 |
| **S11 — Mode dégradé (E12)** | Perte du Cloud, coupure Device → Edge, surcharge, benchmark 3 niveaux | IOT-152 à IOT-155 | Aucun incident perdu ; résultats dans des fichiers séparés |
| **S12 — Ré-entraînement et OTA (E13)** | Contrainte TinyML, ré-entraînement, OTA simulé et signé | IOT-156 à IOT-159 | Modèle versionné, OTA vérifié, test historique non utilisé pour le réglage |
| **S13 — RAG minimal (E14)** | SLM local, base vectorielle, agent superviseur, évaluation | IOT-160 à IOT-162, IOT-164 | Comparaison chiffrée avec `rule_based_v1`, F1 inchangé |
| **S14 — Livraison finale (E15)** | Conteneurs, manuel, vidéo, rapport, présentation, tag | IOT-166 à IOT-171 | Chaîne démarrée en une commande ; version finale gelée |

**Travail transversal :** l'état de l'art (E08) et la rédaction du rapport (E09) peuvent commencer dès S0 et progresser en parallèle.

### Dépendances critiques

`IOT-040 → IOT-041/042 → IOT-043/044 → IOT-047/048 → IOT-050...059 → parité 600/600 → IOT-077...080 → IOT-081...085 → analyses scientifiques → conclusion`.

L'intégration dans le pipeline doit **précéder** les affirmations sur les performances de B3.

**Suite (E11 à E16) :** `IOT-150/151 → IOT-172 → IOT-173 → IOT-174 → IOT-175 et IOT-178 → IOT-179`. `IOT-152...155` peut suivre IOT-174. `IOT-157 → IOT-158 → IOT-176` (l’OTA signé dépend de l’OTA simulé et de la bibliothèque d’IOT-173). `IOT-160 → IOT-161 → IOT-162 → IOT-164`. E15 vient en dernier, après les résultats des axes 1 et 2.

## 6. Critères d'acceptation globaux (« Definition of Done »)

Une tâche de code ne peut être marquée terminée que lorsque :

- Le comportement attendu est spécifié, avec exemples positifs/négatifs et cas limites.
- Les fichiers modifiés sont identifiés et la portée reste limitée au ticket.
- Les tests correspondants sont ajoutés ou mis à jour et **exécutés**.
- La suite de régression est exécutée lorsque le changement peut affecter d'autres composants.
- Les résultats reproductibles sont consignés (commandes, versions, données/seed, logs anonymisés pertinents).
- Aucun résultat expérimental historique n'a été écrasé silencieusement.
- Les limitations et écarts au protocole initial sont explicitement documentés.
- Les changements Git sont présentés avec `git diff`/`git status`; le commit est créé **après autorisation**.

Une expérience scientifique ne peut être considérée concluante que si :

- Les données, labels, splits, configurations et seuils sont traçables.
- Le test n'a pas servi à régler les hyperparamètres.
- Les métriques sont calculées sur des ensembles identiques pour la comparaison annoncée.
- Les faux positifs, faux négatifs et résultats par scénario sont présentés.
- La variabilité entre expériences est quantifiée (quand plusieurs runs existent).
- Les écarts entre simulation hors ligne et pipeline opérationnel sont explicités.
- Les résultats n'excèdent pas ce que les expériences démontrent.

## 7. Structure documentaire proposée dans le dépôt

```text
agentic-aiot/
├── docs/
│   ├── PROJECT_BACKLOG.md          # Ce fichier, suivi de tâches
│   ├── PROJECT_CONTEXT.md          # Résumé court stable pour Codex
│   ├── architecture.md             # Composants et contrats
│   ├── experimental_protocol.md    # Protocole B1/B2/B3
│   ├── decisions/                  # ADR et décisions scientifiques
│   └── figures/
├── src/
│   ├── edge_agent.py
│   ├── device_simulator.py
│   ├── mqtt_edge_adapter.py
│   ├── coap_server.py
│   ├── cloud_mcp_server.py
│   ├── cloud_a2a_server.py
│   ├── cloud_orchestrator.py
│   ├── edge_cloud_bridge.py
│   └── ...
├── tests/
├── data/
├── results/
├── models/
└── README-CLOUD-MVP.md
```

Les fichiers `docs/` autres que `PROJECT_BACKLOG.md` sont **proposés**, non réputés déjà présents.

## 8. Consigne initiale prête à adresser à Codex

> Reprendre dans l’ordre E11 → E16 → E12 → E13 → E14 minimal → E15. Vérifier l’état Git et travailler sur une branche par ticket issue de main. Préserver les références historiques et obtenir l’accord explicite avant chaque action de versionnement ou de publication.

## 9. Éléments de preuve et références internes

- **Rapport Google Drive** : texte du rapport et annexes A (plan de travail), B (validation du seuil), C (comparaison B1/B2 et faux négatif résiduel), consultés le 23 novembre 2026.
- **Résultats B1/B2** : `results/baseline_b1_predictions.csv`, `results/collaborative_b2_predictions.csv` ; métriques explicitement documentées dans le rapport.
- **Historique Git** : PR #8 et #9 fusionnées ; branche de travail B3 créée localement.
- **Analyse du code B3** : synthèse d'inspection fournie dans la conversation : écart seuil 5 vs 2,50 °C, séparation isolation/prédiction, risques de mélange CoAP, bug signalé du dictionnaire de lots MQTT. Ces points restent à confirmer par des tests de code au moment de leur correction.
- **Limite essentielle** : le rapport principal comprend encore des formulations antérieures à l'achèvement de B2 ; les annexes B/C constituent la source à jour pour ses résultats jusqu'à consolidation.

**Fin du backlog global.**
