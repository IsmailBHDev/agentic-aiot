# E07 — Protocole et résultats du 23 novembre 2026

## Reproduction

Depuis la racine, avec l’environnement Python actif :

~~~powershell
python -B src/evaluate_e07.py --output results/e07_reproduction.json
python -B -m pytest -p no:cacheprovider tests
~~~

Le script exige une destination nouvelle et génère les sessions en mémoire.
Les données, modèles et CSV historiques restent intacts. Le résultat
versionné est dans [e07_synthetic_2026-11-23.json](../results/e07_synthetic_2026-11-23.json)
et contient les versions des bibliothèques, les affectations des sessions,
les effectifs et les matrices de confusion. L’exécution de référence utilise
Python 3.14.6, NumPy 2.5.4, pandas 3.1.0 et scikit-learn 1.9.1.

## Détection et orchestration

L’expérience historique conserve ses 600 observations, ses F1 de 84,93 %
pour B1 et 96,30 % pour B2 et son seuil validé de 2,50 °C. E07 est une
expérience distincte sur les graines 101, 202, 303, 404 et 505. Chaque
session contient 1 000 triplets, dont 200 observations positives sur 3 000.
Les cinq plis réservent chacun une session entière au test et la session
suivante dans la liste à la validation, avec retour au début de la liste.
Les trois autres sessions servent à entraîner un arbre de profondeur 3
sur température et vibration, avec `random_state=42`. Le groupement par
session maintient toutes les mesures d’une itération dans le même rôle.
Chaque session est testée une fois. Les ensembles d’entraînement des plis
se recouvrent.

Les méthodes évaluées sur les mêmes observations sont :

- Seuil local de 32 °C, fixé avant l’expérience comme comparateur simple.
- B1, prédiction de l’arbre local.
- Collaboration seule, écart absolu strictement supérieur à 2,50 °C.
- B2, disjonction de B1 et de la collaboration au seuil figé.
- B2 avec seuil sélectionné sur la seule session de validation du pli.
  La grille historique départage par F1 maximal, puis faux positifs
  minimaux, puis seuil minimal.

La comparaison principale utilise les F1, rappels et faux positifs de test.
Le rapport résume les résultats par session entière, avec écart-type
empirique, minimum et maximum. Cette dispersion descriptive respecte le
groupement des observations. Elle ne constitue pas un intervalle de
confiance, compte tenu des cinq sessions et du recouvrement des entraînements.

B3 transmet et analyse les incidents de B2 sans modifier ses décisions de
détection. L’ablation Cloud préserve donc la même prédiction B2 par
construction. Le [rejeu B3](../README-CLOUD-MVP.md) mesure séparément la
livraison, les duplications, la conformité aux règles, la latence et les
charges utiles.

## Résultats nominaux

| Méthode | F1 moyen | Écart-type du F1 | F1 min–max | Rappel moyen | Faux positifs / 14 000 négatifs |
|---|---:|---:|---:|---:|---:|
| Seuil local | 66,84 % | 0,24 pt | 66,67–67,11 % | 50,20 % | 0 |
| B1 | 84,43 % | 0,89 pt | 83,48–85,64 % | 79,00 % | 81 |
| Collaboration seule | 99,04 % | 0,55 pt | 98,22–99,75 % | 98,10 % | 0 |
| B2 à 2,50 °C | 95,52 % | 3,77 pts | 90,74–99,50 % | 98,60 % | 81 |
| B2 réglé dans chaque validation | 96,03 % | 3,72 pts | 91,53–99,26 % | 99,90 % | 84 |

Sur les 15 000 observations de test, dont 1 000 positives, B2 au seuil
figé gagne en moyenne 11,09 points de F1 sur B1 (écart-type 4,04 points,
intervalle observé 6,91–16,02 points). Le rappel contextuel passe de
290/500 à 486/500, soit de 58,00 % à 97,20 %. Le seuil sélectionné vaut
1,50 °C dans trois plis et 2,00 °C dans deux. Cette comparaison quantifie
la sensibilité dans le générateur utilisé. La règle opérationnelle reste
à 2,50 °C. Sur ce générateur, le ML ajoute cinq vrais positifs à la règle
collaborative seule, mais aussi 81 faux positifs.

## Tests de stress

Chaque scénario comprend 30 triplets planifiés par session test, soit
150 au total. L’arbre du pli est réutilisé et B2 applique le calcul Edge
au seuil figé. Les scénarios sont construits pour isoler des mécanismes,
sans servir à l’ajustement.

| Scénario | Résultat B2 |
|---|---|
| Bruit indépendant, σ = 0,90 °C | 90/150 anomalies détectées, 5 faux positifs |
| Dérive saine d’un capteur jusqu’à +4 °C | 55 faux positifs sur 450 observations saines |
| Troisième capteur manquant | B2 indisponible sur 150/150 lots. B1 reste mesurable sur 300 observations reçues. |
| Décalages hétérogènes −2/0/+2 °C | 0 faux positif sur 450 observations dans cette configuration |
| Défaillance simultanée, +4 °C sur les trois capteurs | 255/450 anomalies détectées. La composante collaborative ne déclenche pas. |
| Deux capteurs décalés ensemble de +3,5 °C | Médiane contaminée. B2 produit 150 faux positifs sur le capteur sain et manque 196/300 anomalies. |
| Anomalie progressive de 0 à +4 °C, cible annotée dès le départ | 55/150 observations positives détectées |
| Écart de 2,50 °C puis de 2,5001 °C | Respectivement 0/150 et 150/150 détections |

## Validité et transfert

Les labels nominaux découlent de perturbations injectées. Le générateur
favorise les écarts individuels dans un groupe autrement homogène, ce
qui aide à expliquer l’excellent score de la règle collaborative seule.
La dérive, les températures décalées en commun, les absences et la
contamination de la médiane révèlent des limites que les scores nominaux
masquent. Les choix artificiels de bruit, de décalages et d’étiquettes
d’apparition limitent l’extrapolation. Des graines différentes réduisent
la dépendance à un tirage unique tout en conservant le même générateur
et la même distribution. La simulation ne valide ni le matériel réel,
ni la synchronisation de capteurs distribués, ni l’autonomie des agents.

[Intel Lab Data](https://db.csail.mit.edu/labdata/labdata.html) est un
candidat réel pour étudier la couverture et les écarts thermiques par
époque. Le schéma publié comporte des mesures de température, des
coordonnées et des époques manquantes, mais aucun label d’anomalie et
aucune vibration. Il ne permet donc pas de reproduire directement le
classement B1/B2 ni le F1. IOT-099 reste facultatif et ouvert pour une
évaluation quantitative externe avec un protocole de référence adapté.
