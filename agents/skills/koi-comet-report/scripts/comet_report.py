#!/usr/bin/env python3
"""Export Comet ML metrics and render reproducible comparison charts."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Any


def require_comet_api():
    if not os.environ.get("COMET_API_KEY"):
        raise SystemExit("COMET_API_KEY is not set")
    try:
        from comet_ml.api import API
    except ImportError as exc:
        raise SystemExit("Install comet_ml: python -m pip install comet_ml") from exc
    return API()


def metric_names(experiment: Any) -> list[str]:
    return sorted(item["name"] for item in experiment.get_metrics_summary() if item.get("name"))


def metric_points(experiment: Any, metric: str, max_step: int | None = None) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for row in experiment.get_metrics(metric):
        try:
            step = int(row["step"])
            value = float(row["metricValue"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value) and (max_step is None or step <= max_step):
            points.append((step, value))
    return sorted(points)


def slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned or "metric"


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    for field in ("workspace", "project", "runs"):
        if not config.get(field):
            raise SystemExit(f"Config field {field!r} is required")
    if not isinstance(config["runs"], list):
        raise SystemExit("Config field 'runs' must be a list")
    return config


def connect_runs(api: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    runs = []
    for index, spec in enumerate(config["runs"]):
        if not spec.get("id"):
            raise SystemExit(f"runs[{index}].id is required")
        item = dict(spec)
        item.setdefault("label", item["id"][:8])
        item["experiment"] = api.get_experiment(config["workspace"], config["project"], item["id"])
        runs.append(item)
    return runs


def summarize(points: list[tuple[int, float]], tail_size: int) -> dict[str, Any]:
    if not points:
        return {"count": 0}
    tail = points[-tail_size:]
    tail_values = [value for _, value in tail]
    return {
        "count": len(points),
        "first": {"step": points[0][0], "value": points[0][1]},
        "last": {"step": points[-1][0], "value": points[-1][1]},
        "min": min(value for _, value in points),
        "max": max(value for _, value in points),
        "tail_count": len(tail),
        "tail_mean": statistics.fmean(tail_values),
        "tail_min": min(tail_values),
        "tail_max": max(tail_values),
    }


def configured_metrics(config: dict[str, Any]) -> list[str]:
    return sorted({chart["metric"] for panel in config.get("panels", []) for chart in panel.get("charts", [])})


def collect(runs: list[dict[str, Any]], metrics: list[str], tail_size: int):
    data: dict[str, dict[str, list[tuple[int, float]]]] = {}
    summary: dict[str, Any] = {}
    missing: list[dict[str, str]] = []
    for run in runs:
        run_data = data.setdefault(run["id"], {})
        run_summary = summary.setdefault(run["id"], {"label": run["label"], "metrics": {}})
        available = set(metric_names(run["experiment"]))
        for metric in metrics:
            if metric not in available:
                missing.append({"run": run["id"], "metric": metric})
                run_data[metric] = []
                run_summary["metrics"][metric] = {"count": 0}
                continue
            points = metric_points(run["experiment"], metric, run.get("max_step"))
            run_data[metric] = points
            run_summary["metrics"][metric] = summarize(points, tail_size)
    return data, summary, missing


def write_csv(path: Path, runs: list[dict[str, Any]], data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["run_id", "run_label", "metric", "step", "value"])
        for run in runs:
            for metric, points in data[run["id"]].items():
                for step, value in points:
                    writer.writerow([run["id"], run["label"], metric, step, value])


def pyplot():
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("Install matplotlib: python -m pip install matplotlib") from exc
    return plt


def render_panel(path: Path, charts: list[dict[str, Any]], runs: list[dict[str, Any]], data: dict[str, Any]) -> None:
    plt = pyplot()
    figure, axes = plt.subplots(1, len(charts), figsize=(6.4 * len(charts), 4.2), squeeze=False)
    for axis, chart in zip(axes[0], charts):
        for run in runs:
            points = data[run["id"]].get(chart["metric"], [])
            if points:
                axis.plot(
                    [step for step, _ in points],
                    [value for _, value in points],
                    label=run["label"],
                    color=run.get("color"),
                    linewidth=2,
                )
        axis.set_title(chart.get("title", chart["metric"]))
        axis.set_xlabel(chart.get("xlabel", "Step"))
        axis.set_ylabel(chart.get("ylabel", "Value"))
        if chart.get("ylim") is not None:
            axis.set_ylim(*chart["ylim"])
        axis.grid(alpha=0.22)
        if any(data[run["id"]].get(chart["metric"]) for run in runs):
            axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(figure)


def command_inspect(args: argparse.Namespace) -> int:
    experiment = require_comet_api().get_experiment(args.workspace, args.project, args.run)
    pattern = re.compile(args.filter, re.IGNORECASE) if args.filter else None
    for name in metric_names(experiment):
        if pattern and not pattern.search(name):
            continue
        points = metric_points(experiment, name, args.max_step)
        last = f"step={points[-1][0]} value={points[-1][1]:.10g}" if points else "no numeric points"
        print(f"{name}\t{last}")
    return 0


def command_build(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = load_config(config_path)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    runs = connect_runs(require_comet_api(), config)
    metrics = configured_metrics(config)
    if args.all_metrics:
        discovered = set(metrics)
        for run in runs:
            discovered.update(metric_names(run["experiment"]))
        metrics = sorted(discovered)
    data, summary, missing = collect(runs, metrics, int(config.get("tail", 20)))
    numeric_metrics = [
        metric
        for metric in metrics
        if any(data[run["id"]].get(metric) for run in runs)
    ]
    if missing and args.strict:
        formatted = ", ".join(f"{item['run']}:{item['metric']}" for item in missing)
        raise SystemExit(f"Missing metrics: {formatted}")

    write_csv(out / "metrics.csv", runs, data)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    outputs: list[str] = []
    for panel in config.get("panels", []):
        filename = panel.get("file")
        charts = panel.get("charts", [])
        if not filename or not charts:
            raise SystemExit("Each panel requires non-empty 'file' and 'charts'")
        render_panel(out / filename, charts, runs, data)
        outputs.append(filename)

    if args.all_metrics:
        all_dir = out / "all-metrics"
        all_dir.mkdir(exist_ok=True)
        for metric in numeric_metrics:
            filename = f"{slug(metric)}.png"
            render_panel(all_dir / filename, [{"metric": metric}], runs, data)
        outputs.append("all-metrics/")

    manifest = {
        "workspace": config["workspace"],
        "project": config["project"],
        "config": str(config_path),
        "tail": int(config.get("tail", 20)),
        "runs": [{key: value for key, value in run.items() if key != "experiment"} for run in runs],
        "metrics": metrics,
        "numeric_metrics": numeric_metrics,
        "missing": missing,
        "panels": config.get("panels", []),
        "outputs": outputs,
        "raw_values_smoothed": False,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    if missing:
        print(f"warning: {len(missing)} run/metric pairs were missing", file=sys.stderr)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="List metric names and latest numeric values")
    inspect.add_argument("--workspace", required=True)
    inspect.add_argument("--project", required=True)
    inspect.add_argument("--run", required=True)
    inspect.add_argument("--filter", help="Case-insensitive metric-name regex")
    inspect.add_argument("--max-step", type=int)
    inspect.set_defaults(handler=command_inspect)

    build = commands.add_parser("build", help="Export metrics, summaries, and charts")
    build.add_argument("--config", required=True)
    build.add_argument("--out", required=True)
    build.add_argument("--all-metrics", action="store_true")
    build.add_argument("--strict", action="store_true")
    build.set_defaults(handler=command_build)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
