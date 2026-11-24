import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evaluate_e07 import SEEDS, STRESS_ITERATIONS, select_threshold, session_folds, stress_results


def test_outer_folds_reserve_whole_sessions_for_validation_and_test():
    folds = list(session_folds(SEEDS))

    assert [test for _, _, test in folds] == list(SEEDS)
    assert {validation for _, validation, _ in folds} == set(SEEDS)
    for train, validation, test in folds:
        assert len(train) == 3
        assert validation != test
        assert set(train) == set(SEEDS) - {validation, test}


def test_threshold_selection_applies_strict_boundary_and_tie_break():
    validation = pd.DataFrame({"label": [0, 1, 0], "deviation": [2.5, 3.2, 0.0]})

    threshold, scores = select_threshold(validation, np.zeros(3, dtype=int))

    assert threshold == 2.5
    assert next(row for row in scores if row["threshold"] == 2.5)["fp"] == 0


def test_stress_results_show_coverage_and_contaminated_median():
    class NegativeBaseline:
        def predict(self, features):
            return np.zeros(len(features), dtype=int)

    results = stress_results(NegativeBaseline(), SEEDS[0])

    assert results["missing_sensor"]["missing_observations"] == STRESS_ITERATIONS
    assert results["missing_sensor"]["b2"] is None
    contamination = results["two_coordinated_faults"]["b2"]
    assert contamination["fp"] == STRESS_ITERATIONS
    assert contamination["fn"] == 2 * STRESS_ITERATIONS
    assert results["exact_threshold"]["b2"]["tp"] == 0
    assert results["above_threshold"]["b2"]["tp"] == STRESS_ITERATIONS
