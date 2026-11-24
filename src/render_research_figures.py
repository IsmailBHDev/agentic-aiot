"""Generate the scientific figures from the versioned E09 data sources."""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def architecture():
    fig, ax = plt.subplots(figsize=(10, 4), layout="constrained")
    ax.set(xlim=(0, 10), ylim=(0, 4), title="Chemins de télémétrie et de traitement des incidents")
    ax.axis("off")
    nodes = {
        "Capteurs simulés\nB1 local": (1.0, 2.7),
        "Passerelle\nMQTT-SN → MQTT": (3.0, 3.45),
        "Mosquitto\n+ adaptateur": (5.0, 3.45),
        "CoAP\n/telemetry": (3.0, 1.9),
        "Edge B2\nTriplet synchronisé": (7.2, 2.7),
        "Journal\nEdge JSONL": (9.2, 2.7),
        "Pont + MCP\nStockage Cloud": (9.2, 0.65),
        "Orchestrateur Cloud\nJournal des décisions": (6.7, 0.65),
        "A2A à règles\nRecommandation": (4.35, 0.65),
    }
    artists = {
        name: ax.text(*point, name, ha="center", va="center", fontsize=9,
                      bbox=dict(boxstyle="round,pad=0.6", fc="#edf5fa", ec="#31566e"))
        for name, point in nodes.items()
    }
    paths = [(0, 1), (1, 2), (2, 4), (0, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8)]
    boxes = [artist.get_bbox_patch() for artist in artists.values()]
    points = list(nodes.values())
    for source, target in paths:
        ax.annotate(
            "", xy=points[target], xytext=points[source],
            arrowprops=dict(arrowstyle="->", color="#31566e", lw=1.3,
                            patchA=boxes[source], patchB=boxes[target]),
        )
    return fig


def confusion():
    with (ROOT / "results/collaborative_b2_predictions.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))

    fig, axes = plt.subplots(1, 2, figsize=(7, 3.3), layout="constrained")
    for ax, method in zip(axes, ("B1", "B2")):
        field = f"{method.lower()}_prediction"
        counts = Counter((int(row["label"]), int(row[field])) for row in rows)
        matrix = [[counts[(actual, pred)] for pred in (0, 1)] for actual in (0, 1)]
        ax.imshow(matrix, cmap="Blues", vmin=0, vmax=len(rows))
        ax.set(title=method, xlabel="Prédiction", ylabel="Étiquette",
               xticks=[0, 1], yticks=[0, 1])
        for actual in (0, 1):
            for pred in (0, 1):
                value = matrix[actual][pred]
                ax.text(pred, actual, str(value), ha="center", va="center",
                        color="white" if value > len(rows) / 2 else "#172637")
    fig.suptitle(f"Test historique — {len(rows)} observations")
    return fig


def session_f1():
    path = ROOT / "results/e07_synthetic_2026-11-23.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    folds = report["folds"]
    seeds = [str(fold["test_seed"]) for fold in folds]
    fig, ax = plt.subplots(figsize=(7, 3.7), layout="constrained")
    for method, label, color, marker in (
        ("b1", "B1", "#31566e", "o"),
        ("b2_fixed", "B2 à 2,50 °C", "#a44812", "s"),
        ("collaborative_only", "Collaboration seule", "#476a34", "^"),
    ):
        values = [100 * fold["test"][method]["f1"] for fold in folds]
        ax.plot(seeds, values, marker=marker, label=label, color=color)
    ax.set(xlabel="Graine de la session de test", ylabel="F1 (%)", ylim=(80, 101),
           title="Variabilité descriptive entre les cinq sessions E07")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.19), ncols=3, frameon=False)
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/figures")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, render in (("architecture", architecture), ("confusion", confusion), ("e07-f1", session_f1)):
        figure = render()
        figure.savefig(args.output_dir / f"{name}.png", dpi=200)
        plt.close(figure)


if __name__ == "__main__":
    main()
