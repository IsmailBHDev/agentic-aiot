# E13 — Réentraînement et OTA simulé

**Branche :** `feature/e13-retraining-ota`
**Règles :** le seuil B2 de 2,50 °C, les données, les 600 décisions de référence et les fichiers du manifeste (dont `models/device_model.joblib`) ne sont pas modifiés ; les nouveaux résultats vont dans des fichiers datés.

## IOT-157 — Réentraînement à partir des journaux de l'Edge

**Résultat :** le pipeline construit un jeu de données à partir de ce que l'Edge a journalisé, réentraîne B1, n'accepte le candidat que s'il ne régresse pas en validation, et le publie par l'OTA avec les empreintes du modèle et des données. Sur la session de test tenue à l'écart, les deux candidats ne changent presque rien au B1 actif (F1 de 83,52 % à 83,71 % ou 84,70 %) : l'écart repose sur une seule session de 3 000 observations et n'est pas concluant. Le constat principal porte sur les étiquettes : les incidents de l'Edge sont surtout les alertes du B1 lui-même, et ne couvrent presque pas les anomalies contextuelles.

### Pipeline (`src/retrain_b1.py`)

| Étape | Contenu |
|---|---|
| Collecte | Sessions synthétiques nouvelles du générateur d'E07 (graines 606 et 707 pour le retour, 808 pour la validation, 909 pour le test), jamais utilisées par l'expérience historique ni par E07. Le capteur exécute la v1 ; chaque mesure passe par le vrai chemin Edge MQTT, qui journalise ses incidents. Le pipeline tient le journal de télémétrie de l'Edge (mesures reçues). |
| Jeu de données | Jointure télémétrie × incidents par (session, itération, capteur). Étiquettes `incidents` : 1 si l'Edge a journalisé un incident (aucune intervention humaine). Étiquettes `annotated` : étiquette du générateur, qui simule un opérateur confirmant chaque mesure. |
| Réentraînement | Entraînement historique (2 400 observations) + 6 000 observations de retour ; mêmes hyperparamètres que B1 (profondeur 3, graine 42), aucun réglage. |
| Validation | Promotion si F1 de B1 sur la session 808 ≥ celui de la v1. |
| Test | Session 909, utilisée seulement pour le rapport. Le test historique n'est jamais utilisé. |
| Version | SHA-256 du jeu d'entraînement et du modèle ; avec `--publish-repo`, publication OTA du candidat promu sous la version suivante (signée selon `AIOT_MODEL_SIGNING`). |

```text
python -B src/retrain_b1.py --output artifacts/retraining.json --publish-repo artifacts/ota/repo
```

### Résultats (`results/retraining_b1_2026-11-25.json`)

Mesuré sous Windows (Python 3.14.6, scikit-learn 1.9.1) le 25 novembre 2026. Le pipeline est déterministe.

| Collecte (par session de retour) | 606 | 707 |
|---|---:|---:|
| Mesures journalisées | 3 000 | 3 000 |
| Incidents `LOCAL_ML_ANOMALY` | 168 | 162 |
| Incidents `SENSOR_INCONSISTENCY` | 3 | 3 |

Qualité des étiquettes `incidents` sur les 6 000 mesures, contre l'annotation : précision 94,56 %, rappel 78,25 % (313 vrais positifs, 18 faux positifs, 87 anomalies sans incident).

| Modèle | F1 validation (808) | F1 B1 test (909) | Faux positifs B1 test | Anomalies contextuelles détectées par B1 | F1 B2 test |
|---|---:|---:|---:|---:|---:|
| v1 active (B1 de référence) | 85,79 % | 83,52 % | 12 | 52/100 | 96,59 % |
| Candidat `incidents` | 86,11 % (promu) | 83,71 % | 7 | 49/100 | 97,78 % |
| Candidat `annotated` | 87,10 % (promu) | 84,70 % | 11 | 55/100 | 96,82 % |

Les deux candidats détectent les 100 anomalies locales du test, comme la v1. F1 B2 : candidat combiné à la règle collaborative au seuil figé de 2,50 °C.

**Lecture :**
- **Les incidents sont une mauvaise source d'étiquettes pour B1.** 98 % d'entre eux sont des alertes `LOCAL_ML_ANOMALY` produites par la v1 : réentraîner sur ces étiquettes revient surtout à réapprendre la v1. Les incohérences collaboratives ne sont journalisées qu'une fois par capteur et par session, car le capteur est ensuite isolé logiquement : 3 incidents par session pour une centaine d'anomalies contextuelles.
- **Un B1 local ne peut pas apprendre le contexte.** Les anomalies contextuelles dépendent des autres capteurs ; à partir de (température, vibration), aucun candidat ne dépasse 55/100. C'est le rôle de B2.
- **Les écarts de F1 sont faibles et portent sur une seule session de test** : ils ne montrent pas qu'un candidat est meilleur. Le pipeline sert ici à démontrer la boucle complète (collecte, jeu de données, réentraînement, validation, version, OTA), pas un gain de détection.
- La porte de promotion (≥) accepte un candidat équivalent ; une marge minimale ou plusieurs sessions de validation seraient plus prudentes.

**Tests :** `tests/test_retrain_b1.py` (9 tests) — sessions distinctes du test historique et d'E07, jointure et étiquettes, collecte par l'Edge, qualité imparfaite des étiquettes `incidents`, règle de promotion, publication du candidat promu en v2 signée puis installation par un capteur en v1.

**Limites :** l'annotation `annotated` utilise l'étiquette du générateur, ce qui suppose un opérateur parfait ; les sessions de retour viennent du même générateur que l'entraînement, sans dérive de distribution ; le journal de télémétrie est tenu par le pipeline, l'Edge actuel ne journalisant que les incidents.

## IOT-158 — OTA simulé

**Résultat :** le Cloud publie des versions signées du modèle B1 ; le capteur simulé n'installe une version que si elle est plus récente, intacte, signée par le Cloud et fonctionnelle, et peut revenir à la version précédente. Avec une signature Ed25519 ou ML-DSA-44, les six scénarios d'attaque ou de panne testés laissent la version active intacte. Sans signature, un dépôt compromis fait installer un modèle empoisonné (F1 de 84,93 % à 0 %).

**IOT-180 :** la version 1 publiée est le B1 de référence (profondeur 3, graine 42), réentraîné en mémoire. Une fois installée, elle reproduit les 600 prédictions de `results/baseline_b1_predictions.csv` (F1 84,93 %). Le simulateur exécute donc le B1 évalué dès qu'il passe par l'OTA, sans modifier le fichier gelé `models/device_model.joblib`. Sans OTA, le simulateur conserve son comportement historique (modèle plus faible du manifeste, F1 66,67 %).

### Fonctionnement (`src/ota.py`)

| Étape | Côté | Contrôle |
|---|---|---|
| Publication | Cloud | Fichier `device_model-v<N>.joblib`, signature `.sig` (IOT-176), entrée du catalogue : version, taille, SHA-256, algorithme |
| Choix de la version | Capteur | Strictement plus récente que la version active et non rejetée par un retour arrière |
| Téléchargement | Capteur | Copie dans une zone de transit (simulation du transfert) |
| Vérification | Capteur | Taille et SHA-256 du catalogue, puis signature du Cloud, **avant** `joblib.load` |
| Contrôle de santé | Capteur | Le modèle répond 0 ou 1 sur quatre mesures sondes (température, vibration) |
| Activation | Capteur | `state.json` remplacé d'un bloc ; version précédente conservée |
| Retour arrière | Capteur | Revient à la version précédente et rejette la version abandonnée |
| Démarrage | Capteur | Le modèle actif est revérifié (empreinte et signature) à chaque chargement |

Le nom de fichier, qui contient la version, fait partie du manifeste signé : une ancienne version signée renommée pour passer pour une nouvelle est refusée. Le catalogue lui-même n'est pas signé.

### Utilisation

```text
$env:AIOT_MODEL_SIGNING = 'ml-dsa-44'
python src/ota.py publish-reference --repo artifacts/ota/repo                        # Cloud : v1 = B1 de référence
python src/ota.py update --repo artifacts/ota/repo --device-dir artifacts/ota/device   # capteur
$env:AIOT_OTA_DEVICE_DIR = 'artifacts/ota/device'
python src/device_simulator.py                                                         # télémétrie avec payload.model_version
```

La première commande crée la clé du Cloud dans `AIOT_KEY_DIR` (par défaut `artifacts/keys/`) si elle n'existe pas. Sans `AIOT_OTA_DEVICE_DIR`, le simulateur garde son comportement historique et n'ajoute pas `model_version`. L'Edge accepte ce champ facultatif et refuse une valeur qui n'est pas un entier positif.

### Évaluation (`src/evaluate_ota.py`)

Neuf scénarios par mode, chacun sur un dépôt et un capteur neufs ; mesure sous Windows (Python 3.14.6, scikit-learn 1.9.1, `cryptography` 50.0.2) le 25 novembre 2026. Résultats : `results/ota_2026-11-25.json`. F1 sur les 600 observations du test historique, pour le modèle actif après le scénario.

| Scénario | Sans signature | Ed25519 | ML-DSA-44 |
|---|---|---|---|
| Installation de v1 (B1 de référence) | installée, 600/600, F1 84,93 % | idem | idem |
| Mise à jour v1 → v2 | installée | installée | installée |
| Fichier altéré en transit | refusée (empreinte) | refusée (empreinte) | refusée (empreinte) |
| Dépôt compromis : modèle empoisonné, empreinte recalculée, signé par l'attaquant | **installée, F1 0 %** | refusée (signature) | refusée (signature) |
| Dépôt compromis : modèle empoisonné non signé | **installée, F1 0 %** | refusée (signature) | refusée (signature) |
| Ancienne v1 signée renommée en v3 | installée (v1 remise en service) | refusée (signature) | refusée (signature) |
| Catalogue ramené sous la version active | refusée (pas plus récente) | idem | idem |
| Version légitime mais incompatible (trois variables) | refusée (contrôle de santé) | idem | idem |
| Retour arrière v2 → v1, puis mise à jour | v1 conservée, v2 non réinstallée | idem | idem |

| Coût (20 installations) | Sans signature | Ed25519 | ML-DSA-44 |
|---|---:|---:|---:|
| Fichier du modèle | 2 761 octets | 2 761 octets | 2 761 octets |
| Fichier de signature | — | 263 octets | 3 405 octets |
| Vérification de la signature | — | 0,371 ms | 0,368 ms |
| Installation complète, médiane | 5,27 ms | 6,80 ms | 6,97 ms |

Le modèle empoisonné est un arbre valide qui répond toujours 0 : il masque toutes les anomalies. Aucun fichier pickle malveillant n'a été fabriqué ; sans vérification préalable, un tel fichier pourrait aussi exécuter du code au chargement (menace T8). La v2 nominale est le même arbre entraîné avec une autre graine : elle sert à tester la mécanique de mise à jour, pas à améliorer la détection (IOT-157).

### Tests

`tests/test_ota.py` (28 tests, hors réseau) : reproduction des 600 prédictions par v1, mise à jour et retour arrière, refus dans chaque mode (altération, catalogue antérieur, modèle incompatible), refus des attaques de dépôt avec signature, acceptation documentée sans signature, vérification avant désérialisation, revérification du modèle actif au démarrage, champ `model_version` de la télémétrie.

### Limites

- Le dépôt OTA est un dossier local ; le transfert réseau, sa durée et les coupures en cours de téléchargement ne sont pas simulés.
- Les trois capteurs du simulateur partagent un même processus, donc un même modèle actif.
- Pas de protection contre un attaquant qui retient indéfiniment les mises à jour (gel) : le capteur reste sur sa version active.
- Les durées sont mesurées sur PC ; elles ne représentent pas un microcontrôleur.
