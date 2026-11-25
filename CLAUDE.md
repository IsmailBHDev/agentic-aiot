# Agentic-AIoT — instructions pour Claude Code

Projet de maîtrise (UQO, encadrement Prof. Dhaou Said) : architecture collaborative Device–Edge–Cloud pour la détection d'anomalies IoT, en **simulation logicielle** (validée par le professeur, pas de matériel ESP32). Travailler en **français**.

## Règles à respecter

- Ne jamais toucher directement à `main`, ne rien fusionner, et ne créer ni commit, ni push, ni PR sans accord explicite pour l'action concernée.
- Une branche par ticket ou par épic, créée depuis `main`.
- **Gelé :** seuil B2 strictement supérieur à 2,50 °C, données historiques, 600 décisions B2 de référence, fichiers listés dans `results/reproduction_manifest.json`. Toute nouvelle expérience écrit un **nouveau fichier daté** dans `results/`.
- Exécuter les tests pertinents et mettre à jour la documentation et le backlog quand un ticket les concerne.
- Ne jamais présenter un résultat comme plus fort qu'il n'est (portée synthétique, pas d'autonomie agentique démontrée, pas de conformité A2A complète).

## Commandes (PowerShell, venv active)

```text
python -B -m pytest -p no:cacheprovider --basetemp=artifacts\pytest-tmp tests
docker compose up -d mosquitto                     # requis pour les tests réseau
$env:AIOT_TEST_NETWORK = '1'                       # active les tests réseau (B3)
```

`--basetemp` est nécessaire : le dossier temporaire Windows de pytest refuse l'accès sur cette machine.

## Méthodes

- **B1** : arbre de décision local (température, vibration), profondeur 3, graine 42.
- **B2** : B1 OU |T − médiane des 3 capteurs synchronisés par (session_id, iteration)| > 2,50 °C. Alertes B1 traitées immédiatement.
- **B3** : incidents Edge → MCP → orchestrateur Cloud → service A2A JSON-RPC à règles (`rule_based_v1`). La classification reste à l'Edge.
- **Axe post-quantique (E16)** : `AIOT_AUTH_MODE` (none, ed25519, ml-dsa-44/65/87), `AIOT_CHANNEL_MODE` (none, x25519, ml-kem-768, x25519+ml-kem-768), `AIOT_MODEL_SIGNING`, `AIOT_KEY_DIR`. Tout est désactivé par défaut (C0). Bibliothèque : `cryptography` 50.0.2.

## Documents de référence

- `docs/Agentic-AIoT_BACKLOG.md` — backlog principal, source de vérité des statuts
- `docs/research_delivery.md`, `docs/experimental_protocol.md`, `docs/literature_review.md` — axe 1
- `docs/pq_threat_model.md`, `docs/pq_library_choice.md`, `docs/pq_results.md` — axe 2 (post-quantique)
- `docs/resilience.md` — E12 (perte du Cloud, pertes Device → Edge, surcharge, benchmark, TinyML)
- `docs/retraining_ota.md` — E13 (réentraînement, OTA signé, politique Edge signée)
- Rapport de recherche : https://claude.ai/artifact/TnoPimKtFT2AXbGLXx8Ank (onglets Rapport et Backlog)

## État au 25 novembre 2026

- Terminé et fusionné : E00–E11, E16 (IOT-172 à IOT-179, PR #16 à #18).
- Terminé sur la branche `feature/e12-resilience` (6 commits locaux, à pousser) : IOT-152 à IOT-156.
- Questions de recherche proposées : QR1 détection collaborative, QR2 coût et protection post-quantiques (H4–H6) ; formulation à valider avec le professeur.

## Prochaines étapes

1. Pousser `feature/e12-resilience` et ouvrir la PR.
2. IOT-180 : `models/device_model.joblib` (simulateur) n'est pas le B1 évalué (une comparaison, F1 66,67 %) — décider : remplacer (nouvelle version du manifeste) ou documenter.
3. Reporter E12 dans le rapport.
4. E13 : ré-entraînement et OTA simulé (IOT-157 à IOT-159), puis E14 (RAG minimal) et E15 (livraison).
5. En attente du professeur : formulation QR1/QR2, périmètre du RAG, canevas Word du rapport (IOT-129).

## Points connus

- Le trajet Edge → Cloud (pont + MCP) domine la latence et dérive au fil des répétitions d'un même processus pytest ; les écarts de latence entre configurations ne sont pas concluants.
- Le Git de l'environnement Linux de Claude voyait des fins de ligne Windows comme des modifications : sous Windows natif, `git status` doit être propre.
