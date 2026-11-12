
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ============================================================
# IMPORTATION DU MODULE EDGE
# ============================================================

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "src")
)

from mqtt_edge_adapter import is_message_fresh


# ============================================================
# TEST T4 : MESSAGE EXPIRE
# ============================================================

def test_expired_message():
    # Simuler un message datant de 10 minutes
    old_timestamp = (
        datetime.now(timezone.utc) - timedelta(minutes=10)
    ).isoformat()

    message = {
        "src": "node-01",
        "ts": old_timestamp,
        "temperature": 25.0,
        "vibration": 0.3
    }

    result = is_message_fresh(message)

    assert result is False, (
        "ERREUR : le message expire a ete accepte"
    )

    print("TEST T4 REUSSI : message expire rejete")


# ============================================================
# TEST T5 : HORODATAGES INVALIDES
# ============================================================

def test_invalid_timestamps():
    invalid_timestamps = [
        None,                       # Horodatage absent
        "",                         # Chaine vide
        "invalid-date",             # Format incorrect
        "2026-99-99T25:61:00Z",     # Date impossible
        "2026-11-11T12:00:00",      # Fuseau horaire absent
        1234567890,                 # Type incorrect
    ]

    for timestamp in invalid_timestamps:
        message = {
            "src": "node-01",
            "ts": timestamp,
            "temperature": 25.0,
            "vibration": 0.3
        }

        result = is_message_fresh(message)

        assert result is False, (
            f"ERREUR : horodatage invalide accepte : {timestamp}"
        )

        print(f"REJETE : {timestamp}")

    print(
        "TEST T5 REUSSI : "
        "tous les horodatages invalides sont rejetes"
    )


# ============================================================
# TEST COMPLEMENTAIRE : MESSAGE VALIDE
# ============================================================

def test_valid_message():
    current_timestamp = datetime.now(
        timezone.utc
    ).isoformat()

    message = {
        "src": "node-01",
        "ts": current_timestamp,
        "temperature": 25.0,
        "vibration": 0.3
    }

    result = is_message_fresh(message)

    assert result is True, (
        "ERREUR : un message valide a ete rejete"
    )

    print("TEST VALIDE REUSSI : message recent accepte")


# ============================================================
# EXECUTION DES TESTS
# ============================================================

if __name__ == "__main__":
    print("\n===== TESTS DE ROBUSTESSE MQTT =====\n")

    test_expired_message()
    test_invalid_timestamps()
    test_valid_message()

    print("\n===== TOUS LES TESTS SONT REUSSIS =====")
