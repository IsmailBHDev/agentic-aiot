# Installer et démontrer Agentic-AIoT

Ce guide présente une démonstration de cours en simulation logicielle.
Trois capteurs simulés envoient de la télémétrie à l’Edge. Le Cloud
enregistre les incidents via MCP et produit une recommandation à règles
via A2A. Le scénario utilise la configuration Docker par défaut.

## Prérequis

| Système | Environnement |
|---|---|
| Windows | Docker Desktop démarré en mode conteneurs Linux, PowerShell et Git |
| Linux | Docker Engine démarré, plugin Docker Compose et Git |

Vérifier `docker info` et `docker compose version`. La première
construction demande une connexion Internet pour télécharger les images
et les dépendances. Python est fourni dans l’image. Les ports locaux
TCP 1883, 8000 et 9000 et UDP 5683 et 10000 doivent être disponibles.

## 1. Partir d’un clone propre

~~~text
git clone https://github.com/IsmailBHDev/agentic-aiot.git
cd agentic-aiot
docker compose config --services
~~~

Utiliser une révision qui contient IOT-166. Si la liste affiche uniquement
`mosquitto`, la révision sélectionnée précède la conteneurisation de la
chaîne. Si un autre exemplaire du projet tourne déjà, arrêter ses services
depuis son propre dossier avant de lancer la démonstration.

## 2. Démarrer la chaîne

~~~text
docker compose up -d --build
docker compose ps
docker compose logs --tail=30 edge-gateway edge-mqtt edge-bridge cloud-orchestrator
~~~

Les huit services de fond doivent être actifs. Attendre que la passerelle
et l’adaptateur MQTT soient prêts, puis que le pont Edge et l’orchestrateur
annoncent leur surveillance. Le simulateur est lancé séparément.

## 3. Rejouer une session

Dans un second terminal, depuis le même dossier, suivre les événements :

~~~text
docker compose logs -f edge-mqtt edge-bridge cloud-orchestrator
~~~

Dans le premier terminal, lancer trois capteurs sur dix itérations :

~~~text
docker compose --profile demo run --rm device-sim
~~~

Relever le `session_id` affiché au début. La session inclut une
température falsifiée dans le simulateur et une surchauffe. Cette
démonstration opérationnelle utilise le modèle embarqué par défaut.
Les métriques historiques B1/B2 se reproduisent avec le
[protocole expérimental](experimental_protocol.md).

## 4. Vérifier un incident jusqu’à la décision Cloud

Attendre la confirmation de traitement dans les logs, puis lire les
journaux depuis le premier terminal :

~~~text
docker compose exec -T edge-mqtt cat /data/edge/incidents.jsonl
docker compose exec -T cloud-orchestrator cat /data/cloud/cloud_incidents.jsonl
docker compose exec -T cloud-orchestrator cat /data/cloud/cloud_decisions.jsonl
~~~

1. Dans le journal Edge, relever un incident `SENSOR_INCONSISTENCY`
   de la session. Relever son `id`, le capteur, sa température et la
   référence médiane.
2. Dans le journal Cloud, retrouver le même `id` et relever le
   `cloud_incident_id`.
3. Dans le journal des décisions, retrouver ce `cloud_incident_id`.
   Pour une incohérence de capteur, montrer la sévérité `HIGH` et la
   recommandation calculée par `rule_based_v1`.

Pour la présentation, afficher ces trois lignes et expliquer comment les
identifiants relient les étapes. La recommandation Cloud se distingue
de l’isolement logique décidé localement à l’Edge. Le chemin signé
est documenté séparément dans [les résultats post-quantiques](pq_results.md).

Repère sur l’essai Windows du 25 novembre 2026 : l’itération 6 de
`node-02` a produit un incident `SENSOR_INCONSISTENCY` et une décision
`HIGH` corrélée dans les trois journaux. La session comptait
30 prédictions locales et trois décisions Cloud. Compose attribue les
noms des conteneurs à partir du nom du projet. Le lancement sur un hôte
Linux natif reste à reproduire.

## 5. Arrêter et diagnostiquer

~~~text
docker compose down
~~~

Cette commande conserve les journaux dans les volumes Compose. Pour une
nouvelle session, les distinguer par le `session_id`. Exécuter
`docker compose down -v` uniquement si les journaux et l’état de reprise
de ce projet peuvent être supprimés.

| Symptôme | Vérification |
|---|---|
| Port déjà utilisé | Examiner `docker ps` et les services locaux à l’écoute. |
| Aucune mesure Edge | Examiner `docker compose logs --tail=80 edge-gateway edge-mqtt mosquitto`. |
| Incident Edge sans décision Cloud | Examiner `docker compose logs --tail=80 edge-bridge cloud-mcp cloud-a2a cloud-orchestrator` et attendre le prochain cycle. |

Le [guide Cloud](../README-CLOUD-MVP.md) décrit le banc spécialisé et les
mesures de latence qui complètent cette démonstration.
