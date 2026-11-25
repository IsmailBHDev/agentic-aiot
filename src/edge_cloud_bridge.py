
"""Forward Edge incidents to Cloud MCP, manually or continuously."""

import argparse
import asyncio
import json
import os
from collections import Counter
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


# IOT-152 : compteurs du pont et reprise après panne du Cloud ou redémarrage
BRIDGE_STATE_ENV = "AIOT_BRIDGE_STATE_FILE"
bridge_metrics = Counter()


def _load_position(state_file):
    try:
        return int(json.loads(state_file.read_text(encoding="utf-8"))["position"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_position(state_file, position):
    temporary = state_file.with_name(state_file.name + ".tmp")
    temporary.write_text(json.dumps({"position": position}), encoding="utf-8")
    os.replace(temporary, state_file)


async def watch_incidents(path, url, interval=1.0, state_file=None, max_backoff=30.0):
    """Watch new JSONL lines and forward them to Cloud.

    - La position avance après CHAQUE incident transmis : une panne du Cloud au
      milieu d'un lot ne provoque pas de renvoi des incidents déjà transmis.
    - Pendant une panne, le pont réessaie avec une attente qui double jusqu'à
      ``max_backoff`` secondes, puis revient à ``interval`` dès que le Cloud répond.
    - Avec un fichier d'état (``state_file`` ou AIOT_BRIDGE_STATE_FILE), le pont
      reprend après un redémarrage là où il s'était arrêté ; sans lui, il démarre
      à la fin du journal, comme avant.
    - Une ligne incomplète (en cours d'écriture) est relue au tour suivant ; une
      ligne JSON invalide est comptée et ignorée.
    """

    path = Path(path)
    if state_file is None and os.environ.get(BRIDGE_STATE_ENV):
        state_file = os.environ[BRIDGE_STATE_ENV]
    state_file = Path(state_file) if state_file else None

    print("EDGE-CLOUD : surveillance active", flush=True)

    position = _load_position(state_file) if state_file else None
    if position is None:
        # Start at EOF to avoid resending historical incidents.
        position = path.stat().st_size if path.exists() else 0
        if state_file:
            _save_position(state_file, position)

    delay = interval
    while True:
        try:
            if path.exists():
                if path.stat().st_size < position:
                    position = 0

                with path.open("rb") as stream:
                    stream.seek(position)
                    while True:
                        raw = stream.readline()
                        if not raw or not raw.endswith(b"\n"):
                            break
                        if raw.strip():
                            try:
                                incident = json.loads(raw.decode("utf-8"))
                            except ValueError:
                                bridge_metrics["incidents_invalid"] += 1
                                print("EDGE-CLOUD : ligne invalide ignoree", flush=True)
                            else:
                                await send_mcp(incident, url)
                                bridge_metrics["incidents_sent"] += 1
                        position = stream.tell()
                        if state_file:
                            _save_position(state_file, position)

            if delay != interval:
                bridge_metrics["recoveries"] += 1
                print("EDGE-CLOUD : Cloud de nouveau joignable", flush=True)
            delay = interval

        except Exception as exc:
            bridge_metrics["send_failures"] += 1
            delay = min(delay * 2, max_backoff)
            print(
                f"EDGE-CLOUD : erreur : {exc} ; nouvel essai dans {delay:.2f} s",
                flush=True
            )

        await asyncio.sleep(delay)


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
        "--state-file",
        type=Path,
        default=None,
        help="Reprendre apres redemarrage a partir de ce fichier d'etat"
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously forward new incidents"
    )

    args = parser.parse_args()

    if args.watch:
        asyncio.run(
            watch_incidents(args.file, args.mcp_url, state_file=args.state_file)
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
