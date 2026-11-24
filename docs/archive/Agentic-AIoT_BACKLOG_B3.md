# Agentic-AIoT — Backlog d'intégration B2 et d'évaluation B3

**Statut :** plan de développement, non exécuté  
**Date de référence :** 23 novembre 2026  
**Projet :** détection collaborative d'anomalies IoT, architecture Edge–Cloud–A2A  
**Branche de travail :** `feature/edge-cloud-a2a-evaluation`  
**Répertoire local :** `C:\Users\benha\Desktop\UQO\Autumn2026\IOT\agentic-aiot`

## 1. Objectif et règles de collaboration avec Codex

Ce document sert de backlog **exécutable, progressif et vérifiable**. Commencer par un diagnostic du dépôt réel ; ne jamais présumer qu'un fichier, une interface ou un test est identique au descriptif ci-dessous sans le lire.

**Objectif scientifique :** rendre la décision B2 calculée au niveau Edge strictement équivalente à la décision B2 de l'évaluateur hors ligne, puis évaluer la chaîne B3 (Edge → MCP → Cloud → A2A).

**Règle B2 figée :** pour chaque groupe complet de **trois capteurs distincts**, de même `session_id` et même `iteration` :

```python
median_temp = median(temperatures_of_three_sensors)
collaborative_alert = abs(temperature_i - median_temp) > 2.50
b2_prediction = (payload.prediction == 1) or collaborative_alert
```

- La comparaison est **strictement supérieure** : un écart égal à `2.50` ne déclenche aucune alerte collaborative.
- La détection B2 est **sans effet de bord**. L'isolement, l'enregistrement d'incidents et les actions Cloud sont des politiques **distinctes**, appliquées après le calcul.
- Ne pas supprimer les mesures du calcul B2 au seul motif que le capteur a déjà été isolé : la **parité hors ligne** porte sur les trois mesures synchronisées reçues. Documenter séparément les limites opérationnelles de ce choix.
- Si un groupe est incomplet, ne pas fabriquer de décision collaborative ; les alertes B1 valides restent traitées indépendamment.
- Une observation produit **une seule prédiction B2**, même si les composantes locale et collaborative sont toutes deux positives. Les incidents de sources différentes restent corrélables et traçables ; éviter les enregistrements accidentellement redondants.
- Préserver les motifs historiques `LOCAL_ML_ANOMALY` et `SENSOR_INCONSISTENCY` et la compatibilité des événements consommés par MCP, stockage Cloud et A2A.
- Aucun LLM/RAG/OTA n'est attendu. L'A2A actuel est un endpoint JSON-RPC minimal à règles (`rule_based_v1`), **pas** une démonstration de conformité complète à A2A.
- **Ne modifier ni `main`, ni les datasets de référence, ni les résultats publiés.** Ne pas créer de commit, push ou pull request sans autorisation explicite.
- **Mode de travail :** une tâche à la fois. Avant chaque modification, proposer un diff/plan limité ; après modification, donner tests exécutés, résultats, fichiers touchés et éventuels problèmes. Demander accord pour passer au ticket suivant.

## 2. Référence expérimentale à préserver

Le CSV de référence du jeu de test contient **600 observations** (200 itérations × 3 capteurs), avec **40 anomalies**.

| Mesure | B1 local | B2 collaboratif |
|---|---:|---:|
| Vrais positifs | 31 | 39 |
| Faux négatifs | 9 | 1 |
| Faux positifs | 2 | 2 |
| Vrais négatifs | 558 | 558 |
| Précision | 93,94 % | 95,12 % |
| Rappel global | 77,50 % | 97,50 % |
| F1-score global | 84,93 % | 96,30 % |
| Anomalies contextuelles détectées | 11/20 | 19/20 |

Seuil retenu : **2,50 °C**, après évaluation sur **480 observations de validation**, dont 32 anomalies. B1 et B2 ci-dessus ont été comparés sur les mêmes 600 lignes de test, le modèle local de référence étant celui du fichier `results/baseline_b1_predictions.csv`.

**Cas limite constaté :** `synthetic-seed-42`, `iteration=132`, `node-03`, `temperature=28.164`, médiane `25.742`, écart `2.422`, B1 = 0, B2 = 0, étiquette réelle = 1. **Ne pas retoucher le seuil pour corriger ce cas sur le test.**

### Sources locales à inspecter en premier

- `src/edge_agent.py`
- `src/evaluate_collaborative_b2.py`
- `src/device_simulator.py`
- `src/mqtt_edge_adapter.py`
- `src/coap_server.py`
- `src/edge_server.py` (chemin historique TCP, si encore utilisé)
- `src/edge_cloud_bridge.py`, `src/cloud_mcp_server.py`, `src/cloud_store.py`, `src/cloud_orchestrator.py`, `src/cloud_a2a_server.py`
- `tests/test_a2a_mvp.py`, `tests/test_cloud_mvp.py`
- `results/baseline_b1_predictions.csv`, `results/collaborative_b2_predictions.csv`
- `data/b2_train.csv`, `data/b2_validation.csv`, `data/collaborative_test.csv`

## 3. Backlog priorisé

### EPIC 0 — Vérification avant modification (P0)

- [ ] **B3-00** — Vérifier `git status`, branche active, tests existants, contrats de message et points d'entrée réellement utilisés. Lire les fichiers listés ci-dessus. Rédiger un bref diagnostic des divergences entre B2 hors ligne et le pipeline actuel.
  - **Acceptation :** branche correcte, état Git documenté, points d'appel de `process_message`/`analyze_devices` identifiés, aucune modification involontaire.

### EPIC 1 — Noyau B2 Edge sans effet de bord (P0)

- [ ] **B3-01** — Créer une fonction commune et pure de calcul B2 (dans un module partagé ou `edge_agent.py`, selon l'architecture), à partir d'un triplet complet. Entrées explicites, validations robustes, résultats par `device_id` (`reference`, `deviation`, `b1_prediction`, `collaborative_alert`, `b2_prediction`).
  - **Acceptation :** aucun fichier écrit, aucune isolation, aucun état global modifié ; médiane calculée sur les 3 capteurs ; seuil strict `> 2.50` ; trois IDs distincts requis ; tests pour B1 seul, collaboration seule, combinaison des deux, aucune anomalie, seuil exact, écart négatif et groupe invalide.
- [ ] **B3-02** — Intégrer la fonction à `analyze_devices` et **séparer** détection, journalisation et politique d'isolement. Préserver la gestion des alertes B1 reçues immédiatement.
  - **Acceptation :** plusieurs itérations complètes de la même session restent analysables après un incident ; aucune mise en quarantaine n'altère rétroactivement la classification ; motifs historiques et API existantes préservés.
- [ ] **B3-03** — Enrichir, de façon rétrocompatible, les incidents de télémétrie avec `iteration` (optionnel) et un identifiant de corrélation si nécessaire. Spécifier la règle d'unicité de prédiction et de traçabilité des motifs B1/B2.
  - **Acceptation :** anciens JSONL encore lisibles ; les incidents transmettent `session_id`, `device_id`, `reason`, référence si applicable et, si connue, `iteration` ; pas de doublons accidentels.

### EPIC 2 — Synchronisation et transport (P1)

- [ ] **B3-04** — Vérifier/corriger le regroupement MQTT par `(session_id, iteration)` avec exactement trois capteurs distincts ; valider avant de mémoriser les IDs ; conserver les protections contre doublons QoS 1 et messages en retard.
  - **Point de vigilance :** examiner le signalement `completed_iterations.add(key)` sur un dictionnaire ; corriger selon la structure réellement utilisée.
  - **Acceptation :** deux sessions entremêlées ne se mélangent pas ; lot expiré clôturé et nettoyé ; traitement continu après timeout ; alerte B1 conservée malgré lot incomplet.
- [ ] **B3-05** — Harmoniser la collecte CoAP `/telemetry` avec la même clé session/itération, déduplication et expiration. Préserver `/alert` et `/health`.
  - **Acceptation :** aucun mélange intersession ; pas de double analyse du même lot ; les alertes CoAP `/alert` continuent à créer leur incident.
- [ ] **B3-06** — Examiner `src/edge_server.py` : si utilisé, corriger la clé de regroupement TCP ; sinon documenter le chemin comme historique et ne pas le modifier inutilement.
  - **Acceptation :** décision motivée, pas de régression sur un chemin actif.

### EPIC 3 — Parité scientifique (P0 avant mesures B3)

- [ ] **B3-07** — Réutiliser **la même fonction pure** dans `src/evaluate_collaborative_b2.py`, sans changer les entrées/sorties attendues. Conserver les résultats B1 de référence.
  - **Acceptation :** les 600 décisions B2 sont **identiques ligne par ligne** au CSV de référence, appariées par `(session_id, iteration, device_id)` ; mêmes TP/FP/TN/FN et F1.
- [ ] **B3-08** — Ajouter un mode de rejeu reproductible : injecter le CSV et ses prédictions B1, ou utiliser explicitement `models/baseline_b1.joblib` (ne pas le confondre avec `device_model.joblib` issu d'un autre entraînement).
  - **Acceptation :** provenance de `payload.prediction` documentée ; 600 lignes de référence rejouables sans mutation des résultats historiques.

### EPIC 4 — Intégration Cloud et évaluation B3 (P1)

- [ ] **B3-09** — Tester un triplet anomalie contextuelle avec B1=0 et écart **entre 2,50 et 5,00 °C**, de MQTT-SN → MQTT → Edge → MCP → Cloud → A2A ; répéter dans une autre session via CoAP.
  - **Acceptation :** incident `SENSOR_INCONSISTENCY` avec bonne session, itération, référence et capteur ; `cloud_incident_id` retrouvé dans la décision A2A ; parcours `LOCAL_ML_ANOMALY` inchangé.
- [ ] **B3-10** — Instrumenter les délais par étapes (`Edge→Cloud`, `Cloud→A2A`, `Edge→décision`), définir précisément chaque origine temporelle, mesurer taux de réussite, duplications et coût de communication.
  - **Acceptation :** plusieurs runs indépendants, sortie CSV/JSON reproductible et résumés statistiques ; les premières mesures sur seulement 2 incidents restent qualifiées de préliminaires.
- [ ] **B3-11** — Définir ce que B3 apporte réellement : traçabilité, décision structurée, latence supplémentaire, gestion des erreurs et fiabilité. Ne pas attribuer un gain de F1 à la couche Cloud sans preuve expérimentale.
  - **Acceptation :** comparaison claire B2 (détection) / B3 (orchestration), limites reconnues.

### EPIC 5 — Robustesse et livrables scientifiques (P2)

- [ ] **B3-12** — Répéter B1/B2/B3 sous différentes graines ; ajouter bruit, dérive, pertes de paquets, faux capteur, capteurs manquants et dégradations réseau ; séparer validation et test.
  - **Acceptation :** résultats par run, intervalles/dispersion si possible, scénarios et seeds documentés.
- [ ] **B3-13** — Rédiger documentation de reproduction, architecture, limites, tableau de résultats et figures, puis mettre à jour le rapport Google Docs en conservant les valeurs validées.
  - **Acceptation :** commande de reproduction vérifiée, README/doc à jour, aucune citation ou performance inventée.
- [ ] **B3-14** — Après approbation et tests verts, préparer un commit dédié, pousser sur la branche `feature/edge-cloud-a2a-evaluation`, puis demander confirmation avant PR/merge.
  - **Acceptation :** `git diff --check` et tests réussis, pas de secrets, pas de journaux/runtime, pas de merge sur `main` sans accord.

## 4. Tests de non-régression indispensables

- [ ] Tests Cloud/A2A existants : `python -m pytest tests/test_a2a_mvp.py tests/test_cloud_mvp.py -v` ; référence historique : **6 tests réussis**.
- [ ] Tests B2 : `deviation == 2.50` → pas de détection collaborative ; `deviation > 2.50` → alerte ; B1=1 avec écart faible → B2=1.
- [ ] Comparaison exacte, ligne à ligne, des sorties du rejeu avec `results/collaborative_b2_predictions.csv`.
- [ ] Deux sessions entremêlées, ordre variable, doublon, timeout suivi de message tardif, isolation préalable, alertes locales sans triplet complet.
- [ ] Un incident collaboratif bien corrélé entre Edge, MCP, stockage Cloud et décision A2A.

## 5. Définition de « terminé »

Une tâche n'est terminée que si : **(1)** son comportement est implémenté ; **(2)** les tests utiles sont exécutés et passent ; **(3)** le diff Git est revu ; **(4)** les risques et limites sont rapportés ; **(5)** la validation utilisateur autorise la suite. Aucun gain scientifique n'est déclaré à partir du seul fonctionnement du code.

## 6. Première instruction à Codex

> Lis ce backlog et le code du dépôt. Commence uniquement par B3-00 (diagnostic), puis propose l'implémentation de B3-01. Ne modifie aucun fichier tant que je n'ai pas validé ton diagnostic et ton plan. Respecte la branche actuelle. Montre les tests à créer et les critères d'acceptation. Procède ensuite ticket par ticket avec mon autorisation.
