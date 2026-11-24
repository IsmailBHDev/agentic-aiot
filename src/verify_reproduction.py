"""Check the frozen experiment inputs and evidence against their manifest."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "results/reproduction_manifest.json"


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures = []
    for relative, expected in manifest["sha256"].items():
        try:
            content = (ROOT / relative).read_bytes()
        except FileNotFoundError:
            failures.append(f"{relative}: missing")
            continue
        if relative == ".python-version" or relative.endswith(
            (".csv", ".json", ".md", ".txt", ".yml", ".py")
        ):
            content = content.replace(b"\r\n", b"\n")
        if hashlib.sha256(content).hexdigest() != expected:
            failures.append(f"{relative}: checksum mismatch")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Verified {len(manifest['sha256'])} frozen files.")


if __name__ == "__main__":
    main()
