# Agentic-AIoT — MVP Cloud et rejeu B3

B2 calcule les prédictions sur l’Edge et journalise les incidents. Le pont lit
ce journal et transmet les incidents à MCP sur HTTP. L’orchestrateur soumet
les incidents Cloud au point d’accès JSON-RPC A2A, qui applique les règles
`rule_based_v1`. La réponse associe une sévérité et une recommandation à
l’incident. Cette chaîne démontre la coordination entre services et la
traçabilité. Les recommandations sont déterministes et leur production
n’intervient pas dans la prédiction B2.

## Identité des événements

| Niveau | Identifiants |
|---|---|
| Observation | `session_id` + `iteration` + `device_id` lorsque l’itération est connue |
| Incident Edge | `id`, généré séparément pour chaque incident et conservé tel quel dans le journal Cloud |
| Incident Cloud | `cloud_incident_id`, créé à l’enregistrement MCP. La réponse historique MCP nomme cet ID `incident_id`. |
| Décision | `cloud_incident_id` pour la jointure Cloud et `incident_id` pour l’ID Edge `id`, lorsque celui-ci est fourni. `a2a_task_id` identifie la tâche A2A. |

La décision reprend la session, l’itération, le capteur, la température, la
référence et le motif lorsqu’ils figurent dans la source. L’orchestrateur
rejette une réponse dont l’ID Cloud diffère de celui de l’incident envoyé.
Les anciens journaux restent lisibles avec les champs dont ils disposent.

## Démarrage reproductible sous PowerShell

Depuis la racine et avec la venv active, installer les dépendances et
démarrer Mosquitto.

~~~powershell
python -m pip install -r requirements.txt
python -m pip install mcp fastapi uvicorn httpx pytest
docker compose up -d mosquitto
~~~

Pour le rejeu automatisé, un seul terminal suffit. Le test attend le
démarrage des serveurs HTTP, lance MCP/A2A et CoAP sur des ports temporaires,
démarre la passerelle MQTT-SN et le pont, puis injecte les mesures. Chaque
répétition utilise ses propres journaux temporaires et un préfixe MQTT
unique. La sortie `B3_METRICS` donne les résultats de chaque répétition.

~~~powershell
$env:AIOT_TEST_NETWORK = '1'
python -B -m pytest -p no:cacheprovider -s tests/test_b3_integration.py
~~~

Pour un lancement manuel, choisir un nouveau dossier par expérience et
définir ces variables dans chaque terminal avant de lancer son service.

~~~powershell
$run = Join-Path $env:TEMP 'agentic-aiot-b3-run-001'
$env:AIOT_EDGE_INCIDENT_FILE = Join-Path $run 'edge.jsonl'
$env:AIOT_CLOUD_INCIDENT_FILE = Join-Path $run 'cloud.jsonl'
$env:AIOT_CLOUD_DECISION_FILE = Join-Path $run 'decisions.jsonl'
~~~

1. Démarrer MCP avec `python src/cloud_mcp_server.py` et A2A avec
   `python -m uvicorn cloud_a2a_server:app --app-dir src --host 127.0.0.1 --port 9000`.
2. Démarrer `python src/mqttsn_gateway.py --broker 127.0.0.1`,
   `python src/mqtt_edge_adapter.py` et `python src/coap_server.py`.
3. Lancer `python src/edge_cloud_bridge.py --watch` et attendre
   « EDGE-CLOUD : surveillance active ». Le pont démarre à la fin du journal.
4. Lancer `python src/cloud_orchestrator.py --watch`, puis injecter les
   mesures. Comparer les journaux par leurs identifiants. Arrêter les
   services avec Ctrl+C dans leurs terminaux.

## Vérification des décisions

| Motif | Sévérité attendue | Recommandation attendue |
|---|---|---|
| `SENSOR_INCONSISTENCY` | HIGH | Vérifier la cohérence du capteur et maintenir l’isolement logique |
| `LOCAL_ML_ANOMALY` | HIGH | Examiner la mesure et maintenir le mode sûr |
| Motif inconnu, ici `COAP_UNKNOWN` | MEDIUM | Transmettre l’incident pour analyse complémentaire |

## Mesures locales du 23 novembre 2026

Trois répétitions indépendantes en boucle locale, chacune avec huit triplets
MQTT-SN et huit triplets CoAP. Dans chaque triplet, B1 vaut zéro et le
capteur cible s’écarte de 3,00 °C de la médiane. Chaque répétition comprend
aussi une alerte locale et un signalement CoAP de motif inconnu. Le banc
utilise une scrutation de 20 ms entre opérations du pont et de
l’orchestrateur. Le mode CLI utilise une seconde par défaut. Les temps du
banc caractérisent cette configuration sur une seule machine.

| Répétition | Incidents livrés et décisions conformes | Edge → Cloud (ms) | Cloud → décision (ms) | Edge → décision (ms) |
|---|---:|---:|---:|---:|
| 1 | 18/18 | 526,36 | 60,38 | 586,73 |
| 2 | 18/18 | 403,28 | 65,51 | 468,79 |
| 3 | 18/18 | 430,50 | 64,00 | 494,50 |
| Moyenne | 54/54 au total | 453,38 | 63,30 | 516,67 |

Ces moyennes utilisent les horodatages de création Edge, d’enregistrement
Cloud et de journalisation de la décision. Le délai de collecte, du premier
au troisième message accepté, est en moyenne de 22,82 ms sur MQTT-SN/MQTT
et de 22,52 ms sur CoAP. Le délai depuis l’apparition simulée reste à mesurer.
Les traces historiques à deux incidents restent exploratoires et séparées.

Chaque répétition a envoyé 24 publications MQTT-SN (6 696 octets de
charge utile), 26 POST CoAP (7 034 octets de charge utile), 108 requêtes
HTTP MCP et 18 requêtes HTTP A2A, soit sept requêtes HTTP par incident.
Les corps HTTP totalisent 39 720 octets pour MCP et 22 639 pour A2A par
répétition. Ces volumes excluent les en-têtes réseau, les accusés de
réception et le trafic de contrôle MQTT-SN/MQTT. Sur les trois répétitions,
l’orchestrateur a effectué 41 scrutations, dont six sans nouvelle décision.
La charge CPU et les octets sur le fil restent à mesurer.

## Reprise et limites

Le test de reprise simule une panne A2A et une réponse associée au mauvais
ID Cloud. Chaque répétition redémarre ensuite l’orchestrateur dans un
nouveau processus et vérifie qu’il ne soumet aucun incident déjà traité.
Les incidents sans décision
sont repris au passage suivant. Une décision déjà enregistrée empêche un
nouvel appel pour le même `cloud_incident_id`. Si deux envois MCP du même
incident Edge produisent deux ID Cloud, l’orchestrateur peut enregistrer
deux décisions. Les trois répétitions nominales ont livré 54 incidents sur
54, sans doublon observé ni reprise nécessaire. Elles ne démontrent aucune
garantie de livraison unique. Le point d’accès A2A est un MVP JSON-RPC à
règles. Sa conformité protocolaire complète et son déploiement distribué
restent hors de cette évaluation.
