# Agentic-AIoT — Cloud MVP (MCP + A2A)

## Scope

New files only. Existing Device, MQTT-SN, CoAP and Edge algorithms are not modified. This MVP uses a real MCP Streamable HTTP server and a **minimal mock A2A JSON-RPC endpoint**. It is **not** a fully A2A-SDK-compliant server, and does not implement LLM/RAG or OTA.

The bridge forwards the latest Edge incident manually, **not automatically**. A later PR can integrate an event-driven forwarding queue with retries and idempotency.

## Windows PowerShell quick start

From repository root, with `.venv` active:

```powershell
python -m pip install -r requirements-cloud.txt
python -m unittest discover -s tests -p 'test_*cloud*mvp.py' -v
python -m unittest discover -s tests -p 'test_a2a_mvp.py' -v
```

Terminal 1 (MCP):

```powershell
python src/cloud_mcp_server.py
```

Terminal 2 (A2A):

```powershell
python -m uvicorn cloud_a2a_server:app --app-dir src --host 127.0.0.1 --port 9000
```

Terminal 3 (Edge to Cloud, after an incident exists in `data/incidents.jsonl`):

```powershell
python src/edge_cloud_bridge.py
Get-Content data/cloud_incidents.jsonl -Tail 1
```

A2A agent card:

```powershell
Invoke-RestMethod http://127.0.0.1:9000/.well-known/agent-card.json
```

A2A mock analysis:

```powershell
$body = @{jsonrpc='2.0';id='demo-1';method='message/send';params=@{message=@{parts=@(@{type='text';text='Analyze node-02'})}}} | ConvertTo-Json -Depth 8
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9000/ -ContentType 'application/json' -Body $body
```

## Known integration gaps

- GitHub main `src/coap_server.py` may lag behind the locally validated `/health` and `/alert` code. Preserve/synchronize local changes separately.
- GitHub main `requirements.txt` has a malformed combined `aiocoappaho-mqtt>=2,<3` line. Cloud dependencies are isolated in `requirements-cloud.txt` to avoid changing the existing installation.
- No automatic Edge→Cloud forwarding or A2A task orchestration in this MVP.
- MCP and A2A bind only to localhost; add authentication/TLS before any remote deployment.
- Existing `docker-compose.yml` only starts Mosquitto; Docker integration is a follow-up.
