# IOT-173 — Choix de la bibliothèque post-quantique

**Date :** 23 novembre 2026
**Branche :** `feature/iot-173-pq-library`, créée sur IOT-172 (`25f91f8`)
**Décision :** utiliser `cryptography` 50.0.2, déjà épinglée dans `requirements.txt`, pour Ed25519, ML-DSA et ML-KEM. FN-DSA (C3) est reporté et devient optionnel.

## 1. Décision

| Configuration | Algorithme retenu | Source | Statut du standard |
|---|---|---|---|
| C1 — référence classique | Ed25519 | `cryptography` 50.0.2 | Standard classique, non résistant à un attaquant quantique |
| C2 — post-quantique (signature) | **ML-DSA-44** par défaut ; ML-DSA-65 et ML-DSA-87 mesurés dans IOT-178 | `cryptography` 50.0.2 | FIPS 204, publié le 13 août 2024 |
| C2 — post-quantique (échange de clés, IOT-177) | **ML-KEM-768** ; ML-KEM-1024 disponible | `cryptography` 50.0.2 | FIPS 203, publié le 13 août 2024 |
| C3 — comparateur compact | FN-DSA | Non disponible dans `cryptography` ; nécessiterait liboqs | FIPS 206 encore en brouillon |

**Pourquoi `cryptography` plutôt que liboqs :**
- **Aucune nouvelle dépendance.** La version est déjà épinglée et installée ; la CI ne change pas.
- **Fonctionne sous Windows.** Le `.venv` Windows du projet (Python 3.14.6) contient `cryptography` 50.0.2 avec les modules `mldsa` et `mlkem`. Le paquet embarque sa propre bibliothèque OpenSSL (4.0.3 dans l'environnement Linux de vérification).
- **Implémentations standard.** ML-DSA et ML-KEM y suivent FIPS 204 et FIPS 203. Les tailles mesurées correspondent aux tailles des standards (section 3).
- **liboqs est plus lourd à installer.** Son interface Python dépend de la bibliothèque C liboqs, qui doit être compilée ou fournie séparément. Sous Windows, cela suppose en général CMake et un compilateur C. Cette installation n'a pas pu être testée ici, faute d'accès réseau depuis l'environnement de vérification.

**Pourquoi ML-DSA-44 par défaut :** c'est le niveau qui produit la plus petite signature (2 420 octets), ce qui compte pour des messages IoT de quelques centaines d'octets. ML-DSA-65 et ML-DSA-87 restent mesurés dans IOT-178 pour montrer le compromis entre niveau de sécurité et coût.

**Ce que devient C3 :** FN-DSA est retiré du chemin minimal. Il pourra être ajouté plus tard avec liboqs si le temps le permet, et présenté comme un comparateur dont le standard n'est pas finalisé.

## 2. Ce qui est vérifié automatiquement

`tests/test_pq_primitives.py` (10 tests, hors réseau) vérifie :

- signature et vérification ML-DSA-44, ML-DSA-65 et ML-DSA-87, avec les tailles de clé publique et de signature attendues ;
- rejet d'un message modifié (une température changée) et rejet d'une signature produite par la clé d'un autre capteur ;
- encapsulation et décapsulation ML-KEM-768 et ML-KEM-1024, avec un secret partagé de 32 octets et les tailles attendues ;
- signature et vérification Ed25519, et rejet d'un message modifié.

La CI exécute ces tests sous Windows et sous Linux. Une CI verte confirme donc que les algorithmes fonctionnent sous Windows avec Python 3.14.

## 3. Mesures exploratoires

Ces chiffres servent uniquement au choix des paramètres. Ils viennent d'un environnement de vérification Linux (Python 3.10.12, `cryptography` 50.0.2) et non de l'environnement de référence (Windows, Python 3.14.6). Ce ne sont pas des résultats : les mesures officielles seront produites par IOT-178, dans un fichier séparé.

| Algorithme | Clé publique (octets) | Signature ou texte chiffré (octets) | Signature ou encapsulation (ms) | Vérification ou décapsulation (ms) |
|---|---:|---:|---:|---:|
| Ed25519 | 32 | 64 | 0,021 | 0,067 |
| ML-DSA-44 | 1 312 | 2 420 | 0,351 | 0,073 |
| ML-DSA-65 | 1 952 | 3 309 | 0,547 | 0,105 |
| ML-DSA-87 | 2 592 | 4 627 | 0,640 | 0,174 |
| ML-KEM-768 | 1 184 | 1 088 | 0,015 | 0,022 |
| ML-KEM-1024 | 1 568 | 1 568 | 0,018 | 0,028 |

Moyennes sur 300 opérations, message de 141 octets.

**Lecture :** sur PC, le temps de calcul est faible devant la latence Edge → décision du banc (516,67 ms en moyenne). Le coût principal sera la **taille** : une signature ML-DSA-44 pèse environ 38 fois une signature Ed25519 et plusieurs fois le message de télémétrie lui-même.

## 4. Conséquences pour IOT-174

- **MQTT-SN :** l'en-tête de longueur passe sur 3 octets au-delà de 255 octets (`src/mqttsn.py`), ce qui autorise des paquets jusqu'à 65 535 octets. Un message signé passe donc en boucle locale.
- **CoAP :** un message signé dépassera environ 3 Ko. Il faudra vérifier dans IOT-174 que la requête POST arrive entière à `/telemetry`, par transfert en blocs si nécessaire.
- **Encodage :** si la signature est encodée en base64 dans le JSON, elle grossit d'environ un tiers (2 420 octets deviennent 3 228 caractères). Le format retenu devra être mesuré dans IOT-178.
- **Limite à signaler dans le rapport :** des radios IoT réelles imposent des trames bien plus petites. Une signature de 2 420 octets devrait alors être fragmentée. La simulation en boucle locale ne mesure pas ce coût.

## 5. Ce qui reste ouvert

- Confirmer l'exécution sous Windows par la CI de la PR.
- FN-DSA (C3) : optionnel, à réévaluer après IOT-178.
