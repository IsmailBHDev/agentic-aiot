# E08 — État de l’art et positionnement scientifique

## Stratégie de recherche

Revue ciblée menée le 23 novembre 2026. La recherche bibliographique a
utilisé un index de publications scientifiques, arXiv et le repérage par
titre ou DOI. Les références retenues ont été recoupées dans IEEE Xplore,
Wiley Online Library, SpringerLink, les actes NeurIPS et les
spécifications officielles MCP et A2A.

| Axe | Exemples de requêtes |
|---|---|
| Détection | `IoT wireless sensor networks anomaly detection supervised random forest`, `distributed autoencoder WSN anomaly detection` |
| Collaboration et coût | `in-network outlier detection wireless sensor networks communication`, `mobile edge cloud collaboration outlier detection delay energy` |
| Coordination | `multi-agent actor-critic cooperative competitive environments`, `MCP specification architecture tools`, `A2A 0.3 message/send Agent Card` |

Ont été retenus les travaux primaires décrivant une méthode et son
évaluation, ou les spécifications officielles versionnées pour
l’interopérabilité. La sélection privilégie les mesures physiques, la
topologie de collecte et les métriques utiles au prototype. Les travaux
centrés uniquement sur les paquets réseau, les billets promotionnels et
les sources sans méthode identifiable ont été écartés de la comparaison.
Les prépublications ont servi à consulter le texte quand le DOI
éditorial identifiait le même travail. Les références rapprochées par
titre et DOI sont comptées une fois. Le corpus est ciblé et ne permet
pas une conclusion sur l’absence de travaux antérieurs.

## Matrice de littérature

| Source primaire | Problème et approche | Données et métriques | Limite et différence avec Agentic-AIoT |
|---|---|---|---|
| Safaei, Driss, Boulila, Sundararajan et Safaei (2022, en ligne en 2021). [DOI 10.1002/spe.3020](https://onlinelibrary.wiley.com/doi/10.1002/spe.3020) | Détection collaborative supervisée. Sélection adaptative de voisins à partir de séries temporelles et de l’entropie, puis forêt aléatoire. | Traces Intel Berkeley avec bruit injecté. L’article annonce jusqu’à 99 % d’exactitude. | L’injection et l’exactitude rendent le chiffre non comparable au F1 du projet. Le choix adaptatif des voisins et l’historique temporel diffèrent du triplet fixe et de la médiane instantanée de B2. |
| Luo et Nagarajan (2018). [DOI 10.1109/ICC.2018.8422402](https://doi.org/10.1109/ICC.2018.8422402), [texte des auteurs](https://arxiv.org/abs/1812.04872) | Autoencodeur non supervisé. Apprentissage déporté au Cloud et inférence par capteur sans échange avec les voisins lors de la décision. | Banc intérieur de capteurs, quatre mois de collecte. Courbes ROC et AUC pour la détection et les fausses alertes. | Le détecteur exploite son contexte appris localement. L’étude ne mesure pas le gain d’une médiane de triplet ni le coût d’une recommandation Cloud par incident. |
| Branch, Giannella, Szymanski, Wolff et Kargupta (2013, en ligne en 2012). [DOI 10.1007/s10115-011-0474-5](https://link.springer.com/article/10.1007/s10115-011-0474-5), [texte des auteurs](https://arxiv.org/abs/0909.0685) | Détection non supervisée distribuée dans le réseau, par échanges à un saut et mises à jour dynamiques. | Simulation sur flux de capteurs réels. Exactitude de détection, communication et consommation. | Le calcul est réparti entre capteurs. B2 centralise la décision collaborative sur un Edge et attend trois mesures associées à une même itération. |
| Gao, Song, Wang et Chen (2021). [DOI 10.1049/cmu2.12231](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/cmu2.12231) | Détection à l’Edge par description de données à vecteurs supports. Le Cloud entraîne et met à jour le modèle. | Traces Intel Lab et simulation. Délai, énergie et durée de vie du réseau. | C’est le rapprochement architectural le plus direct du corpus. Dans B3, le Cloud qualifie les incidents après la détection. Le banc du projet mesure la latence et les charges utiles, sans valider la consommation énergétique. |
| Lowe, Wu, Tamar, Harb, Abbeel et Mordatch (2017). [Actes NeurIPS](https://proceedings.neurips.cc/paper/2017/hash/68a9750337a418a86fe06c1991a1d64c-Abstract.html) | Apprentissage de politiques d’action multiagents par acteur-critique, avec exécution décentralisée. | Environnements simulés coopératifs et compétitifs. Retours ou critères de réussite propres aux tâches. | Cette étude fournit un exemple de coordination apprise. Les services de B3 suivent des règles et un ordre d’appels prédéfinis. |
| Model Context Protocol (2025-11-25). [Architecture officielle](https://modelcontextprotocol.io/specification/2025-11-25/architecture) | Architecture client-serveur et primitives pour exposer outils, ressources et prompts. | Spécification. Aucun jeu de données ni F1. | Le projet utilise un appel d’outil pour remonter un incident. Le protocole décrit l’interface, et les tests portent sur le parcours implémenté. |
| Agent2Agent Protocol (v0.3.0). [Spécification officielle](https://a2a-protocol.org/v0.3.0/specification/) | Interopérabilité entre agents. Carte de capacités, messages et tâches, dont `message/send` dans cette version. | Spécification. Aucun jeu de données ni F1. | Le MVP emprunte une partie de l’interface JSON-RPC. Il exécute des règles prédéfinies, et la conformité intégrale à la spécification n’a pas été testée. |

Les études de détection utilisent des définitions de l’anomalie, des
protocoles d’injection et des métriques différents. Leurs chiffres
situent les approches, sans constituer un classement commun.

## Positionnement et hypothèses

**Architecture.** La contribution est un prototype reproductible qui
fait transiter des incidents de télémétrie de l’Edge vers le Cloud,
avec corrélation des identifiants et séparation entre classification
et décision opérationnelle. Les travaux de Gao et de Luo montrent
que le partitionnement Edge–Cloud et la détection distribuée ont déjà
été étudiés. L’intégration du projet est évaluée sur ses parcours
MQTT-SN/MQTT et CoAP, jusqu’à la recommandation Cloud.

**Expérimentation.** La question mesurée est l’effet d’un contexte
synchrone minimal sur les anomalies contextuelles, puis la stabilité
de cet effet face à un changement de session, aux triplets incomplets
et à la contamination de la médiane. Le [protocole E07](experimental_protocol.md)
compare le seuil local, B1, la collaboration seule et B2 sur les mêmes
observations. Le meilleur F1 nominal de la collaboration seule dans E07
limite la revendication d’une contribution systématique du ML.

**Orchestration.** Le [rejeu B3](../README-CLOUD-MVP.md) évalue la
livraison, le lien incident–décision, la conformité aux règles et
les délais. La recommandation découle du motif fourni à une fonction
déterministe. Une contribution d’autonomie exigerait une expérience
dédiée, avec politiques d’action et comparateur explicites.

- **H1** — Dans les sessions synchronisées du protocole, B2 améliore le
  rappel contextuel par rapport à B1. L’ablation collaboration seule
  mesure ce que le ML ajoute à la règle.
- **H2** — À seuil figé, le gain de rappel s’accompagne de peu de faux
  positifs supplémentaires sur les scénarios nominaux. Les comptes et
  taux par scénario, avec la dérive et les pannes communes, bornent
  cette hypothèse. Aucun seuil d’acceptabilité opérationnelle n’est fixé.
- **H3** — Dans le banc local, B3 peut relier chaque incident livré à une
  recommandation conforme aux règles avec un délai et un trafic
  observables. Le test porte sur la livraison, la traçabilité, la
  conformité et les coûts, indépendamment du F1.

La littérature retenue justifie ces comparaisons dans le périmètre
du projet. Une revendication de supériorité ou de nouveauté
algorithmique nécessiterait des méthodes concurrentes reproduites
sur des données, des partitions et des métriques communes.
