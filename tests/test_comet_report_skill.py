from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "agents/skills/koi-comet-report/scripts/comet_report.py"
SPEC = importlib.util.spec_from_file_location("koi_comet_report", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeExperiment:
    def __init__(self, rows):
        self.rows = rows

    def get_metrics(self, name):
        return self.rows[name]


def test_metric_points_keep_finite_values_and_apply_cutoff() -> None:
    experiment = FakeExperiment(
        {
            "score": [
                {"step": "3", "metricValue": "0.3"},
                {"step": "1", "metricValue": "0.1"},
                {"step": "2", "metricValue": "nan"},
                {"step": "4", "metricValue": "0.4"},
            ]
        }
    )

    assert MODULE.metric_points(experiment, "score", max_step=3) == [(1, 0.1), (3, 0.3)]


def test_summary_describes_complete_series_and_tail() -> None:
    summary = MODULE.summarize([(1, 1.0), (2, 2.0), (3, 9.0)], tail_size=2)

    assert summary == {
        "count": 3,
        "first": {"step": 1, "value": 1.0},
        "last": {"step": 3, "value": 9.0},
        "min": 1.0,
        "max": 9.0,
        "tail_count": 2,
        "tail_mean": 5.5,
        "tail_min": 2.0,
        "tail_max": 9.0,
    }


def test_example_config_is_valid_and_references_unique_outputs() -> None:
    path = ROOT / "agents/skills/koi-comet-report/references/example-config.json"
    config = MODULE.load_config(path)
    files = [panel["file"] for panel in config["panels"]]

    assert config["workspace"]
    assert config["project"]
    assert config["runs"]
    assert len(files) == len(set(files))
    assert "cost_critic/vf_loss" in MODULE.configured_metrics(config)
    json.dumps(config)
