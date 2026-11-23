"""Minimal A2A JSON-RPC demonstration endpoint (not full A2A SDK conformance)."""
import uuid
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import json

app = FastAPI(title='Agentic-AIoT Cloud A2A MVP')


@app.get('/.well-known/agent-card.json')
def agent_card():
    return {
        'name': 'Agentic-AIoT Cloud Supervisor',
        'description': 'Mock incident analysis agent for Agentic-AIoT',
        'url': 'http://127.0.0.1:9000/',
        'version': '0.1.0',
        'capabilities': {'streaming': False},
        'defaultInputModes': ['text'],
        'defaultOutputModes': ['text'],
        'skills': [{'id': 'incident_analysis', 'name': 'Incident analysis', 'description': 'Mock incident analysis', 'tags': ['iot', 'incident']}],
    }


class RpcRequest(BaseModel):
    jsonrpc: str
    id: str | int | None = None
    method: str
    params: dict = {}


def analyze_incident(incident: dict) -> dict:
    """Analyse déterministe d'un incident IoT."""

    reason = incident.get("reason", "UNKNOWN")
    device_id = incident.get("device_id", "unknown")

    if reason == "SENSOR_INCONSISTENCY":
        severity = "HIGH"
        recommendation = (
            "Verify sensor consistency and maintain "
            "logical isolation pending investigation."
        )

    elif reason == "LOCAL_ML_ANOMALY":
        severity = "HIGH"
        recommendation = (
            "Investigate abnormal sensor measurements "
            "and maintain safe mode."
        )

    else:
        severity = "MEDIUM"
        recommendation = (
            "Escalate incident for further analysis."
        )

    return {
        "cloud_incident_id": incident.get("cloud_incident_id"),
        "device_id": device_id,
        "reason": reason,
        "severity": severity,
        "recommendation": recommendation,
        "analysis_method": "rule_based_v1"
    }


@app.post('/')
def rpc(request: RpcRequest):

    if request.jsonrpc != '2.0':
        return JSONResponse({
            'jsonrpc': '2.0',
            'id': request.id,
            'error': {
                'code': -32600,
                'message': 'Invalid Request'
            }
        })

    if request.method != 'message/send':
        return JSONResponse({
            'jsonrpc': '2.0',
            'id': request.id,
            'error': {
                'code': -32601,
                'message': 'Method not found'
            }
        })

    try:
        parts = request.params['message']['parts']
        text = next(
            part['text']
            for part in parts
            if part.get('type') == 'text'
        )

        incident = json.loads(text)

        if not isinstance(incident, dict):
            raise ValueError('Incident must be an object')

        if not incident.get('device_id') or not incident.get('reason'):
            raise ValueError('Missing device_id or reason')

        analysis = analyze_incident(incident)

    except (KeyError, TypeError, ValueError, StopIteration) as error:
        return JSONResponse({
            'jsonrpc': '2.0',
            'id': request.id,
            'error': {
                'code': -32602,
                'message': f'Invalid params: {error}'
            }
        })

    return {
        'jsonrpc': '2.0',
        'id': request.id,
        'result': {
            'id': str(uuid.uuid4()),
            'status': {'state': 'completed'},
            'artifacts': [{
                'name': 'incident_analysis',
                'parts': [{
                    'type': 'text',
                    'text': json.dumps(analysis)
                }]
            }]
        }
    }
