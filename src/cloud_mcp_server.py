"""Cloud MCP server: Streamable HTTP on http://127.0.0.1:8000/mcp."""
from mcp.server.fastmcp import FastMCP
from cloud_store import report_incident as save_report, list_incidents as read_reports
from cloud_store import request_model_update as acknowledge_update

def report_incident(incident: dict) -> dict:
    """Record an incident detected by the Edge and return its Cloud identifier."""
    return save_report(incident)


def list_incidents(limit: int = 10) -> list[dict]:
    """List the most recent incidents recorded in Cloud (maximum 100)."""
    return read_reports(limit)


def request_model_update(device_id: str) -> dict:
    """Acknowledge a model-update request; no OTA is executed in this MVP."""
    return acknowledge_update(device_id)


def create_mcp():
    server = FastMCP(
        'agentic-aiot-cloud', host='127.0.0.1', port=8000, streamable_http_path='/mcp'
    )
    server.tool()(report_incident)
    server.tool()(list_incidents)
    server.tool()(request_model_update)
    return server


mcp = create_mcp()


if __name__ == '__main__':
    mcp.run(transport='streamable-http')
