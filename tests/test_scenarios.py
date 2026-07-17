from pathlib import Path

import pytest

from runtime.mock_worker import load_scenario
from runtime.worker import RealWorker

SC = Path(__file__).resolve().parent.parent / "scenarios"

EXPECTED = {"green": "rise_cross", "trap_b": "rise_cross",
            "plateau": "rise_plateau", "hung": "hang"}


@pytest.mark.parametrize("name,profile", EXPECTED.items())
def test_scenarios_load(name, profile):
    s = load_scenario(SC / f"{name}.yaml")
    assert s.name == name
    assert s.profile == profile


def test_trap_b_injects_bad_hash():
    s = load_scenario(SC / "trap_b.yaml")
    assert s.override_for("N4")["data_hash"] == "WRONG_HASH"


def test_realworker_is_live_only():
    with pytest.raises(NotImplementedError):
        RealWorker()
