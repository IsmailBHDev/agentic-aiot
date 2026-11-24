
"""Forward Edge incidents to Cloud MCP, manually or continuously."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from secure_channel import sealer_from_env

# IOT-177 : incidents signés et chiffrés pour le Cloud (None en C0)
edge_sealer = sealer_from_env()

DEFAULT_INCIDENTS = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "incidents.jsonl"
)


async def send_mcp(incident, url):
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            response = await session.call_tool(
                "report_incident",
                {"incident": edge_sealer.seal(incident) if edge_sealer else incident}
            )

            if response.isError:
                raise RuntimeError(
                    f"MCP tool error: {response.content}"
                )

            print(
                f"CLOUD : incident {incident['id']} transmis",
                flush=True
            )


def latest_incident(path):
    with path.open("r", encoding="utf-8") as stream:
        lines = [
            line.strip()
            for line in stream
            if line.strip()
        ]

    if not lines:
        raise ValueError(f"No incidents in {path}")

    return json.loads(lines[-1])


async def watch_incidents(path, url, interval=1.0):
    """Watch new JSONL lines and forward them to Cloud."""

    print("EDGE-CLOUD : surveillance active", flush=True)

    # Start at EOF to avoid resending historical incidents.
    position = path.stat().st_size if path.exists() else 0

    while True:
        try:
            if not path.exists():
                await asyncio.sleep(interval)
                continue

            if path.stat().st_size < position:
                position = 0

            with path.open("r", encoding="utf-8") as stream:
                stream.seek(position)
                lines = stream.readlines()
                next_position = stream.tell()

            for line in lines:
                if not line.strip():
                    continue

                incident = json.loads(line)
                await send_mcp(incident, url)

            position = next_position

        except Exception as exc:
            print(
                f"EDGE-CLOUD : erreur : {exc}",
                flush=True
            )

        await asyncio.sleep(interval)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--file",
        type=Path,
        default=Path(os.environ.get("AIOT_EDGE_INCIDENT_FILE", str(DEFAULT_INCIDENTS)))
    )

    parser.add_argument(
        "--mcp-url",
        default="http://127.0.0.1:8000/mcp"
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously forward new incidents"
    )

    args = parser.parse_args()

    if args.watch:
        asyncio.run(
            watch_incidents(args.file, args.mcp_url)
        )
    else:
        asyncio.run(
            send_mcp(
                latest_incident(args.file),
                args.mcp_url
            )
        )


if __name__ == "__main__":
    main()
