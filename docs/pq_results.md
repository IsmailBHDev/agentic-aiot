# E16 — Axe post-quantique : utilisation, reproduction et résultats

**Date :** 23 novembre 2026
**Tickets :** IOT-172 à IOT-179 (branche `feature/e16-pq-axis`)
**Documents liés :** [modèle de menace](pq_threat_model.md), [choix de la bibliothèque](pq_library_choice.md)

La signature des messages neutralise, dans la simulation, l'usurpation de capteurs, le rejeu et les fausses alertes, et restitue exactement les décisions B2 de référence. Elle coûte moins d'une milliseconde de calcul par message, mais ML-DSA-44 multiplie la taille d'un message de télémétrie par 10,25. Le seuil B2 de 2,50 °C, les données et les résultats historiques ne sont pas modifiés.

## 1. Utilisation

Tout est désactivé par défaut (C0) : sans variable d'environnement, le prototype se comporte comme avant.

| Variable | Valeurs | Effet |
|---|---|---|
| `AIOT_AUTH_MODE` | `none` (défaut), `ed25519`, `ml-dsa-44`, `ml-dsa-65`, `ml-dsa-87` | Les capteurs signent leurs messages ; l'Edge (MQTT, CoAP `/telemetry` et `/alert`) rejette tout message non signé, modifié, rejoué ou signé par une autre clé |
| `AIOT_CHANNEL_MODE` | `none` (défaut), `x25519`, `ml-kem-768`, `x25519+ml-kem-768` | Le pont Edge → Cloud signe et chiffre chaque incident ; le Cloud refuse les incidents non scellés |
| `AIOT_MODEL_SIGNING` | `none` (défaut), `ed25519`, `ml-dsa-44`, … | Le capteur vérifie la signature du modèle avant `joblib.load` |
| `AIOT_KEY_DIR` | dossier | Emplacement des clés ; par défaut `artifacts/keys/`, exclu de Git |

Création des clés (PowerShell ou Linux, venv active) :

```text
python src/message_auth.py ml-dsa-44                       # clés des capteurs node-01 à node-03
python src/secure_channel.py ml-kem-768                    # clés du Cloud (ML-KEM) et de l'Edge (ML-DSA-44)
python src/model_signing.py models/device_model.joblib ml-dsa-44   # écrit models/device_model.joblib.sig
```

La dernière commande crée un fichier de signature à côté du modèle de référence, sans modifier le modèle. Ne pas versionner ce fichier sans décision explicite.

Démarrer ensuite chaque service avec les mêmes variables, par exemple sous PowerShell :

```text
$env:AIOT_AUTH_MODE = 'ml-dsa-44'
$env:AIOT_CHANNEL_MODE = 'ml-kem-768'
```

## 2. Reproduction

```text
python -B -m pytest -p no:cacheprovider tests
python -B src/evaluate_pq_attacks.py --output artifacts/pq-attacks-reproduction.json
python -B src/evaluate_pq_cost.py --output artifacts/pq-cost-reproduction.json
```

Créer `artifacts/` avant les deux dernières commandes. Les comptes d'attaque sont déterministes et doivent être identiques à `results/pq_attacks_2026-11-23.json`. Les temps dépendent de la machine : comparer leurs ordres de grandeur à `results/pq_cost_2026-11-23.json`.

| Fichier de tests | Tests | Ce qu'ils vérifient |
|---|---:|---|
| `tests/test_pq_primitives.py` | 10 | ML-DSA, ML-KEM et Ed25519 disponibles, tailles des standards |
| `tests/test_message_auth.py` | 29 | Rejet des messages falsifiés, modifiés ou rejoués ; parité des 600 décisions B2 en Ed25519 et ML-DSA-44 |
| `tests/test_pq_attacks.py` | 5 | S1 à S3 dégradent C0 et sont neutralisés en C1 et C2 (20 itérations) |
| `tests/test_model_signing.py` | 10 | Modèle modifié, remplacé ou non signé refusé avant chargement |
| `tests/test_secure_channel.py` | 23 | Incident chiffré, altération, rejeu et mauvaise clé refusés ; intégration au stockage Cloud |
| `tests/test_pq_cost.py` | 3 | Cohérence des mesures de coût |

Les 80 tests de l'axe et les tests existants qui ont pu être exécutés passent dans l'environnement de vérification Linux (Python 3.13.18, `cryptography` 50.0.1). Les tests Cloud qui demandent `httpx`, `mcp` ou `fastapi` n'ont pas pu y être exécutés, et les tests réseau restent désactivés sans `AIOT_TEST_NETWORK=1`. La CI Windows et Linux doit confirmer l'ensemble.

## 3. Résultats

### Protection (IOT-175)

Attaques rejouées par le vrai chemin Edge MQTT sur les 600 observations du test historique. Sans attaque, C0, C1 et C2 reproduisent la référence : F1 de 96,30 % (39 vrais positifs, 2 faux positifs, 1 faux négatif).

| Scénario | C0 — sans protection | C1 — Ed25519 | C2 — ML-DSA-44 |
|---|---|---|---|
| S1 — node-02 et node-03 usurpés (+3,50 °C) | F1 28,92 % ; 173 FP, 4 FN | 96,30 % ; 400 messages rejetés | 96,30 % ; 400 messages rejetés |
| S2 — mesures précédentes rejouées | F1 4,88 % ; 40 FP, 38 FN | 96,30 % ; 597 rejeux rejetés | 96,30 % ; 597 rejeux rejetés |
| S3 — 200 fausses alertes locales | 200 incidents inventés | 0 incident | 0 incident |

### Coût (IOT-178)

Mesures hors réseau sur une seule machine (Linux, Python 3.13.18, `cryptography` 50.0.1), moyennes sur 1 000 opérations ou 5 × 600 messages.

| Configuration | Message de télémétrie | Signature (capteur) | Traitement Edge par message |
|---|---:|---:|---:|
| C0 — sans protection | 356 octets | — | 0,015 ms |
| C1 — Ed25519 | 508 octets (× 1,43) | 0,035 ms | 0,161 ms |
| C2 — ML-DSA-44 | 3 650 octets (× 10,25) | 0,550 ms | 0,205 ms |
| ML-DSA-65 | 4 834 octets (× 13,58) | 0,901 ms | 0,251 ms |
| ML-DSA-87 | 6 594 octets (× 18,52) | 1,076 ms | non mesuré |

| Canal Edge → Cloud | Incident transmis | Scellement | Ouverture |
|---|---:|---:|---:|
| En clair | 264 octets | — | — |
| X25519 + Ed25519 | 659 octets | 0,138 ms | 0,229 ms |
| ML-KEM-768 + ML-DSA-44 | 6 260 octets | 0,756 ms | 0,203 ms |
| Hybride X25519 + ML-KEM-768 + ML-DSA-44 | 6 322 octets | 0,709 ms | 0,242 ms |

### Banc B3 en réseau local (IOT-178)

Mesuré le 25 novembre 2026 sous Windows (Python 3.14.6), Mosquitto dans Docker, scrutation de 20 ms : 4 configurations × 2 tours entrelacés × 3 répétitions, soit 6 répétitions et 108 incidents par configuration. Fichier : `results/pq_b3_network_2026-11-25.json`.

| Configuration | Livrés et décisions conformes | Edge → décision, médiane (min–max) | Charge MQTT-SN + CoAP par répétition | Corps HTTP vers MCP par répétition |
|---|---:|---:|---:|---:|
| C0 — sans protection | 108/108 | 719,69 ms (502,43–1 260,74) | 13 730 octets | 10 920 octets |
| C1 — Ed25519 + X25519 | 108/108 | 677,55 ms (574,16–1 147,68) | 21 330 octets (× 1,55) | 18 094 octets (× 1,66) |
| C2 — ML-DSA-44 + ML-KEM-768 | 108/108 | 1 120,84 ms (595,84–1 605,59) | 178 430 octets (× 13,0) | 118 980 octets (× 10,9) |
| C2 hybride — ML-DSA-44 + X25519/ML-KEM-768 | 108/108 | 1 228,00 ms (622,35–1 470,90) | 178 430 octets (× 13,0) | 120 060 octets (× 11,0) |

Aucun message légitime n'a été rejeté. Toutes les décisions sont conformes aux règles, y compris pour les incidents scellés qui passent par le vrai serveur MCP.

**Lecture prudente des latences.** La variabilité du banc dépasse l'écart entre configurations. Dans chaque exécution de pytest, la première répétition donne de 595,84 à 804,71 ms dans les quatre configurations, C0 compris ; les répétitions suivantes dérivent jusqu'à 1 605,59 ms, C0 atteignant lui-même 1 260,74 ms. La dérive se situe sur le trajet Edge → Cloud (pont et appels MCP), tandis que le trajet Cloud → décision reste entre 63 et 115 ms. Les écarts de médiane (+401 ms pour C2) ne sont donc pas attribuables à la cryptographie avec ce banc ; le calcul ajouté mesuré hors réseau est d'environ 1,7 ms par incident. Le volume transmis, lui, est un effet net et reproductible : environ 13 fois plus d'octets vers l'Edge et 11 fois plus vers MCP avec ML-DSA-44.

## 4. Lecture des hypothèses

- **H4 (coût)** : soutenue pour le calcul. Avec ML-DSA-44 et ML-KEM-768, le calcul ajouté sur toute la chaîne (signature, vérification, scellement, ouverture) est d'environ 1,7 ms par incident. En réseau local, l'effet sur la latence n'est pas distinguable de la variabilité du banc ; le coût net et mesurable est le volume : × 13 vers l'Edge et × 11 vers MCP. La latence en réseau local reste à mesurer.
- **H5 (protection)** : soutenue dans la simulation. Contre un attaquant classique, Ed25519 protège autant que ML-DSA. L'avantage de ML-DSA face à un attaquant quantique découle de l'état de l'art et n'est pas mesurable ici.
- **H6 (compromis FN-DSA)** : non testée, FN-DSA étant reporté.

## 5. Ce qui reste ouvert

- Stabiliser le banc B3 (dérive du trajet Edge → Cloud au fil des répétitions d'un même processus) avant toute conclusion fine sur la latence.
- Refaire les mesures hors réseau dans l'environnement de référence Windows.
- Réduire la taille en remplaçant le double encodage base64 par un encodage binaire.
- Intégrer la vérification des modèles à la distribution OTA (IOT-158).
- FN-DSA (C3), si le temps le permet.
