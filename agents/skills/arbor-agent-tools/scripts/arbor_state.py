#!/usr/bin/env python3
"""Small stdlib helper for Arbor-style local research state.

This is not the real Arbor runtime. It preserves the open-source session/tree
shape and implements deterministic equivalents for the stateful coordinator
tools so Codex/Claude can forward-test the skill suite without native tools.
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback.
    fcntl = None


VERSION = 3
STATUSES = {"pending", "running", "done", "merged", "pruned"}
PROTECTED_BRANCHES = {"main", "master"}
MUTATING_COMMANDS = {"init", "meta", "add", "update", "prune", "propagate", "eval", "record", "worktree", "merge"}

DEFAULT_META: dict[str, Any] = {
    "baseline_score": None,
    "trunk_score": None,
    "test_baseline_score": None,
    "test_trunk_score": None,
    "eval_cmd": None,
    "eval_cmd_test": None,
    "eval_timeout": None,
    "eval_retries": None,
    "eval_retry_base_delay": None,
    "eval_retry_max_delay": None,
    "dataset_info": None,
    "metric_direction": "maximize",
    "trunk_branch": None,
    "submission_path": None,
    "sample_submission_path": None,
}


def session_dir(cwd: str | Path, run_name: str) -> Path:
    return Path(cwd).resolve() / ".arbor" / "sessions" / run_name


def coordinator_dir(cwd: str | Path, run_name: str) -> Path:
    return session_dir(cwd, run_name) / ".coordinator"


def tree_paths(cwd: str | Path, run_name: str) -> tuple[Path, Path]:
    cdir = coordinator_dir(cwd, run_name)
    return cdir / "idea_tree.json", cdir / "idea_tree.md"


@contextlib.contextmanager
def state_lock(cwd: str | Path, run_name: str):
    lock_path = coordinator_dir(cwd, run_name) / ".state.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def default_tree(task: str, max_depth: int | None) -> dict[str, Any]:
    return {
        "version": VERSION,
        "meta": dict(DEFAULT_META),
        "root_id": "ROOT",
        "max_depth": max_depth,
        "nodes": {
            "ROOT": {
                "id": "ROOT",
                "parent_id": None,
                "children_ids": [],
                "depth": 0,
                "hypothesis": task or "Research optimization",
                "status": "done",
            }
        },
    }


def load_tree(cwd: str | Path, run_name: str) -> dict[str, Any]:
    json_path, _ = tree_paths(cwd, run_name)
    if not json_path.exists():
        raise SystemExit(f"no idea tree found: {json_path}")
    try:
        tree = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"corrupt idea tree {json_path}: {exc}") from exc
    tree.setdefault("version", VERSION)
    tree.setdefault("meta", {})
    tree["meta"] = {**DEFAULT_META, **tree.get("meta", {})}
    tree.setdefault("root_id", "ROOT")
    tree.setdefault("nodes", {})
    return tree


def save_tree(cwd: str | Path, run_name: str, tree: dict[str, Any]) -> None:
    json_path, md_path = tree_paths(cwd, run_name)
    atomic_write(json_path, json.dumps(tree, indent=2, ensure_ascii=False))
    atomic_write(md_path, render_markdown(tree))


def parse_scalar(text: str) -> Any:
    low = text.lower()
    if low in {"none", "null"}:
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if re.fullmatch(r"[-+]?\d+", text):
            return int(text)
        if re.fullmatch(r"[-+]?\d*\.\d+(e[-+]?\d+)?", text, re.I):
            return float(text)
    except ValueError:
        pass
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


def short(text: str, n: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 3] + "..."


def fmt_score(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{float(value):.4g}"
    return str(value)


def node(tree: dict[str, Any], node_id: str) -> dict[str, Any]:
    try:
        return tree["nodes"][node_id]
    except KeyError as exc:
        raise SystemExit(f"node not found: {node_id}") from exc


def children(tree: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    n = node(tree, node_id)
    return [tree["nodes"][cid] for cid in n.get("children_ids", []) if cid in tree["nodes"]]


def next_child_id(tree: dict[str, Any], parent_id: str) -> str:
    parent = node(tree, parent_id)
    nums: list[int] = []
    for child_id in parent.get("children_ids", []):
        if parent_id == tree.get("root_id", "ROOT"):
            match = re.fullmatch(r"(\d+)", child_id)
        else:
            match = re.fullmatch(re.escape(parent_id) + r"\.(\d+)", child_id)
        if match:
            nums.append(int(match.group(1)))
    nxt = max(nums, default=0) + 1
    return str(nxt) if parent_id == tree.get("root_id", "ROOT") else f"{parent_id}.{nxt}"


def is_improvement(tree: dict[str, Any], new: float, old: float) -> bool:
    if tree.get("meta", {}).get("metric_direction", "maximize") == "minimize":
        return new < old
    return new > old


def render_constraints(tree: dict[str, Any]) -> str:
    lines: list[str] = []
    depth_counts: dict[int, dict[str, int]] = {}
    for n in tree["nodes"].values():
        depth = int(n.get("depth", 0))
        if depth == 0:
            continue
        bucket = depth_counts.setdefault(depth, {})
        status = n.get("status", "pending")
        bucket[status] = bucket.get(status, 0) + 1
    if depth_counts:
        parts = [f"max_depth: {tree.get('max_depth') or 'unlimited'}"]
        for depth in sorted(depth_counts):
            counts = depth_counts[depth]
            detail = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
            parts.append(f"depth-{depth}: {sum(counts.values())} nodes ({detail})")
        lines.extend(["## TREE SHAPE", " | ".join(parts), ""])

    root = node(tree, tree.get("root_id", "ROOT"))
    if root.get("insight"):
        lines.extend([
            "## ROOT INSIGHT (current best global understanding - your priors)",
            root["insight"].strip(),
            "",
        ])

    pruned = [
        n for n in tree["nodes"].values()
        if n.get("status") == "pruned" and (n.get("insight") or n.get("hypothesis"))
    ]
    if pruned:
        lines.append(
            f"## PRUNED LESSONS ({len(pruned)} - these directions FAILED. "
            "Do NOT re-propose the same hidden assumption or mechanism class "
            "without explaining the counter.)"
        )
        for n in pruned:
            lines.append(f"- [{n['id']}] {short(n.get('hypothesis', ''), 100)}")
            lines.append(f"  -> {short(n.get('insight') or '(no insight recorded)', 200)}")
        lines.append("")

    validated = [
        n for n in tree["nodes"].values()
        if n.get("status") in {"done", "merged"} and n.get("insight")
    ]
    if validated:
        lines.append(
            f"## VALIDATED FINDINGS ({len(validated)} - build on these; "
            "do not re-derive them.)"
        )
        for n in validated:
            tag = "merged" if n.get("status") == "merged" else "done"
            score = f" {float(n['score']):.1f}" if isinstance(n.get("score"), (int, float)) else ""
            lines.append(f"- [{tag} {n['id']}{score}] {short(n.get('hypothesis', ''), 100)}")
            lines.append(f"  -> {short(n.get('insight', ''), 200)}")
        lines.append("")

    if not lines:
        return (
            "No prior insights yet - this is an early-stage tree. Focus on "
            "understanding the task and proposing diverse initial directions."
        )
    return "\n".join(lines).rstrip()


def render_compact(tree: dict[str, Any]) -> str:
    meta = tree.get("meta", {})
    counts: dict[str, int] = {}
    best: dict[str, Any] | None = None
    for n in tree["nodes"].values():
        if n.get("depth", 0) == 0:
            continue
        status = n.get("status", "pending")
        counts[status] = counts.get(status, 0) + 1
        if isinstance(n.get("score"), (int, float)) and n.get("status") in {"done", "merged"}:
            if best is None or is_improvement(tree, float(n["score"]), float(best["score"])):
                best = n
    counts_s = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    best_s = f", best={best['id']} score={fmt_score(best['score'])}" if best else ""
    lines = [
        f"TREE (baseline={fmt_score(meta.get('baseline_score'))}, "
        f"trunk={fmt_score(meta.get('trunk_score'))}, nodes={len(tree['nodes'])}, "
        f"{counts_s}{best_s}):"
    ]

    def walk(n: dict[str, Any], indent: int) -> None:
        prefix = "  " * indent
        score = ""
        if isinstance(n.get("score"), (int, float)):
            score = f" ({float(n['score']):.1f})"
            trunk = meta.get("trunk_score")
            if isinstance(trunk, (int, float)):
                score = f" ({float(n['score']):.1f}, delta {float(n['score']) - float(trunk):+.1f})"
        insight = f" | {short(n.get('insight', ''), 80)}" if n.get("insight") else ""
        lines.append(f"{prefix}{n['id']} [{n.get('status', 'pending')}]{score}: {short(n.get('hypothesis', ''))}{insight}")
        for child in children(tree, n["id"]):
            walk(child, indent + 1)

    walk(node(tree, tree.get("root_id", "ROOT")), 0)
    pending = [
        n for n in tree["nodes"].values()
        if n.get("status") == "pending" and n.get("depth", 0) > 0 and not n.get("children_ids")
    ]
    if pending:
        lines.extend(["", f"PENDING LEAVES ({len(pending)}):"])
        for n in pending:
            lines.append(f"  {n['id']}: {short(n.get('hypothesis', ''))}")
    return "\n".join(lines)


def render_markdown(tree: dict[str, Any]) -> str:
    meta = tree.get("meta", {})
    lines = [
        "# Idea Tree",
        "",
        f"**Baseline**: {fmt_score(meta.get('baseline_score'))} | **Trunk**: {fmt_score(meta.get('trunk_score'))}",
        "",
    ]

    def walk(n: dict[str, Any], level: int) -> None:
        h = "#" * min(level, 6)
        score = f" (score: {float(n['score']):.4g})" if isinstance(n.get("score"), (int, float)) else ""
        lines.append(f"{h} {n['id']}: {n.get('hypothesis', '')} [{str(n.get('status', 'pending')).upper()}]{score}")
        lines.append("")
        for key, label in [
            ("insight", "Insight"),
            ("related_work", "Related work"),
            ("result", "Result"),
            ("code_ref", "Branch"),
        ]:
            if n.get(key):
                lines.append(f"**{label}**: {n[key]}")
                lines.append("")
        for child in children(tree, n["id"]):
            walk(child, level + 1)

    walk(node(tree, tree.get("root_id", "ROOT")), 2)
    return "\n".join(lines).rstrip() + "\n"


def render_node_detail(tree: dict[str, Any], node_id: str) -> str:
    n = node(tree, node_id)
    lines = [
        f"Node: {n['id']} (depth={n.get('depth', 0)}, status={n.get('status', 'pending')})",
        f"  Hypothesis: {n.get('hypothesis', '')}",
    ]
    for key, label in [
        ("insight", "Insight"),
        ("related_work", "Related work"),
        ("result", "Result"),
        ("score", "Score"),
        ("code_ref", "Branch"),
    ]:
        if n.get(key) is not None and n.get(key) != "":
            lines.append(f"  {label}: {n[key]}")
    if n.get("children_ids"):
        lines.append(f"  Children: {', '.join(n['children_ids'])}")
    return "\n".join(lines)


def validate_hypothesis(text: str) -> list[str]:
    labels = ["Mechanism:", "Hypothesis:", "Observable:", "Conflicts:"]
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    warnings: list[str] = []
    if len(lines) != 4:
        warnings.append("hypothesis should contain exactly four nonblank labelled lines")
    for idx, label in enumerate(labels):
        if idx >= len(lines) or not lines[idx].startswith(label):
            warnings.append(f"line {idx + 1} should start with {label}")
    return warnings


def cmd_init(args: argparse.Namespace) -> None:
    json_path, _ = tree_paths(args.cwd, args.run_name)
    if json_path.exists() and not args.force:
        raise SystemExit(f"tree already exists: {json_path} (use --force to replace)")
    max_depth = None if args.max_depth.lower() in {"none", "unlimited"} else int(args.max_depth)
    tree = default_tree(args.task, max_depth)
    save_tree(args.cwd, args.run_name, tree)
    (session_dir(args.cwd, args.run_name) / "experiments").mkdir(parents=True, exist_ok=True)
    (session_dir(args.cwd, args.run_name) / "submissions").mkdir(parents=True, exist_ok=True)
    print(json_path)


def cmd_view(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    if args.format == "compact":
        print(render_compact(tree))
    elif args.format == "full":
        print(render_markdown(tree), end="")
    elif args.format == "node":
        if not args.node_id:
            raise SystemExit("--node-id is required for --format node")
        print(render_node_detail(tree, args.node_id))
    elif args.format == "pending":
        pending = [
            n for n in tree["nodes"].values()
            if n.get("status") == "pending" and n.get("depth", 0) > 0 and not n.get("children_ids")
        ]
        if not pending:
            print("No pending leaf nodes.")
        else:
            print("Pending leaf nodes:")
            for n in pending:
                print(f"  {n['id']} (depth={n.get('depth', 0)}): {n.get('hypothesis', '')}")
    elif args.format == "constraints":
        print(render_constraints(tree))


def cmd_meta(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    if not args.set:
        print(json.dumps(tree.get("meta", {}), indent=2, ensure_ascii=False))
        return
    updated: list[str] = []
    for item in args.set:
        if "=" not in item:
            raise SystemExit(f"--set expects key=value, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if key not in DEFAULT_META and key != "achieved_medal":
            raise SystemExit(f"unknown metadata key: {key}")
        tree["meta"][key] = parse_scalar(value.strip())
        updated.append(key)
    save_tree(args.cwd, args.run_name, tree)
    print("updated metadata: " + ", ".join(updated))


def cmd_add(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    parent = node(tree, args.parent_id)
    new_depth = int(parent.get("depth", 0)) + 1
    max_depth = tree.get("max_depth")
    if max_depth is not None and new_depth > int(max_depth):
        raise SystemExit(f"cannot add depth {new_depth}; max_depth={max_depth}")
    node_id = next_child_id(tree, args.parent_id)
    tree["nodes"][node_id] = {
        "id": node_id,
        "parent_id": args.parent_id,
        "children_ids": [],
        "depth": new_depth,
        "hypothesis": args.hypothesis,
        "status": "pending",
    }
    parent.setdefault("children_ids", []).append(node_id)
    save_tree(args.cwd, args.run_name, tree)
    print(f"Added node {node_id} (depth={new_depth}) under {args.parent_id}")
    for warning in validate_hypothesis(args.hypothesis):
        print(f"WARNING: {warning}", file=sys.stderr)


def cmd_update(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    n = node(tree, args.node_id)
    fields = {
        "status": args.status,
        "score": args.score,
        "insight": args.insight,
        "result": args.result,
        "code_ref": args.code_ref,
        "hypothesis": args.hypothesis,
        "related_work": args.related_work,
    }
    changed: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        if key == "status" and value not in STATUSES:
            raise SystemExit(f"invalid status: {value}")
        n[key] = value
        changed.append(key)
    if not changed:
        print(f"No updates provided for {args.node_id}.")
        return
    save_tree(args.cwd, args.run_name, tree)
    print(f"Updated {args.node_id}: " + ", ".join(changed))


def cmd_prune(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    root = node(tree, args.node_id)

    def walk(n: dict[str, Any]) -> None:
        n["status"] = "pruned"
        if n is root and args.reason:
            prior = n.get("insight", "")
            n["insight"] = (prior + f"\n[Pruned: {args.reason}]").strip()
        for child in children(tree, n["id"]):
            walk(child)

    walk(root)
    save_tree(args.cwd, args.run_name, tree)
    print(f"Pruned {args.node_id} and descendants. Reason: {args.reason}")


def synthesize_parent_insight(tree: dict[str, Any], ancestor: dict[str, Any]) -> str:
    parts = []
    for child in children(tree, ancestor["id"]):
        if child.get("insight"):
            score = f", score={fmt_score(child.get('score'))}" if child.get("score") is not None else ""
            parts.append(f"[{child['id']}, {child.get('status')}{score}] {child['insight']}")
    if not parts:
        return ancestor.get("insight", "")
    text = "Children findings: " + " | ".join(parts)
    return short(text, 1200)


def cmd_propagate(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    current = node(tree, args.node_id)
    updated: list[str] = []
    while current.get("parent_id"):
        current = node(tree, current["parent_id"])
        summary = args.summary if current["id"] == tree.get("root_id") and args.summary else synthesize_parent_insight(tree, current)
        if summary:
            current["insight"] = summary
            updated.append(current["id"])
    save_tree(args.cwd, args.run_name, tree)
    print("Propagated through: " + (", ".join(updated) if updated else "(none)"))


SCORE_PATTERNS = [
    re.compile(r'"score"\s*:\s*([-+]?\d+(?:\.\d+)?)'),
    re.compile(r"\bval_bpb\s*[:=]\s*([-+]?\d+(?:\.\d+)?)", re.I),
    re.compile(r"\bprimary_score\s*[:=]\s*([-+]?\d+(?:\.\d+)?)", re.I),
    re.compile(r"\bscore\s*[:=]\s*([-+]?\d+(?:\.\d+)?)", re.I),
    re.compile(r"\baccuracy\s*[:=]\s*([-+]?\d+(?:\.\d+)?)", re.I),
    re.compile(r"\bacc\s*[:=]\s*([-+]?\d+(?:\.\d+)?)", re.I),
    re.compile(r"\bf1\s*[:=]\s*([-+]?\d+(?:\.\d+)?)", re.I),
    re.compile(r"\bloss\s*[:=]\s*([-+]?\d+(?:\.\d+)?)", re.I),
    re.compile(r"\brmse\s*[:=]\s*([-+]?\d+(?:\.\d+)?)", re.I),
    re.compile(r"\bmae\s*[:=]\s*([-+]?\d+(?:\.\d+)?)", re.I),
]

METRIC_LINE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_%/-]*)\s*[:=]\s*([-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?)",
    re.I,
)

DEFAULT_LOG_METRICS = {
    "score",
    "primary_score",
    "val_bpb",
    "accuracy",
    "acc",
    "f1",
    "loss",
    "rmse",
    "mae",
    "peak_vram_mb",
    "training_seconds",
    "total_seconds",
    "mfu_percent",
    "num_steps",
}


def parse_score(text: str) -> float | None:
    for match in re.finditer(r"\{[^{}]+\}", text):
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        for key in ("score", "primary_score", "accuracy", "acc"):
            if isinstance(obj.get(key), (int, float)):
                value = float(obj[key])
                return value * 100.0 if key in {"accuracy", "acc"} and 0 <= value <= 1 else value
    for pattern in SCORE_PATTERNS:
        match = pattern.search(text)
        if match:
            return float(match.group(1))
    pct = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%", text)
    if pct:
        return float(pct.group(1))
    return None


def extract_log_metrics(text: str, allowed: set[str] | None = None) -> dict[str, float]:
    metrics: dict[str, float] = {}
    normalized = text.replace("\r", "\n")
    allowed_lc = {item.lower() for item in allowed} if allowed else None
    for line in normalized.splitlines():
        match = METRIC_LINE.match(line)
        if not match:
            continue
        key = match.group(1)
        if allowed_lc is not None and key.lower() not in allowed_lc:
            continue
        try:
            metrics[key] = float(match.group(2))
        except ValueError:
            continue
    return metrics


def substitute(cmd: str, cwd: str | Path, node_id: str) -> str:
    return cmd.replace("{cwd}", str(Path(cwd).resolve())).replace("{node_id}", node_id)


def run_shell(cmd: str, cwd: str | Path, timeout: int) -> tuple[int, str, bool]:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "TERM": "dumb"},
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode or 0, out, False
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        return -1, out + f"\n[timed out after {timeout}s]", True


def apply_eval_meta(tree: dict[str, Any], mode: str, score: float, cmd: str | None, split: str) -> None:
    meta = tree["meta"]
    if mode == "baseline":
        meta["baseline_score"] = score
        if meta.get("trunk_score") is None:
            meta["trunk_score"] = score
        if cmd and not meta.get("eval_cmd"):
            meta["eval_cmd"] = cmd
    elif mode == "trunk":
        meta["trunk_score"] = score
        if cmd and not meta.get("eval_cmd"):
            meta["eval_cmd"] = cmd
    elif mode == "test_baseline":
        meta["test_baseline_score"] = score
        if meta.get("test_trunk_score") is None:
            meta["test_trunk_score"] = score
        if cmd and not meta.get("eval_cmd_test"):
            meta["eval_cmd_test"] = cmd
    elif mode == "test_trunk":
        meta["test_trunk_score"] = score
        if cmd and not meta.get("eval_cmd_test"):
            meta["eval_cmd_test"] = cmd
    elif mode != "none":
        raise SystemExit(f"unknown --set-meta mode: {mode}")
    if split == "test" and cmd and not meta.get("eval_cmd_test"):
        meta["eval_cmd_test"] = cmd


def cmd_eval(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    node_id = args.node_id or ("TEST" if args.split == "test" else "DEV")
    exec_cwd = Path(args.exec_cwd or args.cwd).resolve()
    cmd = substitute(args.cmd, exec_cwd, node_id)
    timeout = args.timeout or int(tree["meta"].get("eval_timeout") or 7200)
    rc, output, timed_out = run_shell(cmd, exec_cwd, timeout)
    log_dir = coordinator_dir(args.cwd, args.run_name) / "eval_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{args.split}_{node_id}_{int(time.time())}.log"
    log_path.write_text(output, encoding="utf-8")
    score = parse_score(output)
    if score is not None and args.set_meta != "none":
        apply_eval_meta(tree, args.set_meta, score, args.cmd, args.split)
        save_tree(args.cwd, args.run_name, tree)
    print(json.dumps({
        "returncode": rc,
        "timed_out": timed_out,
        "score": score,
        "log_path": str(log_path),
        "command": cmd,
        "exec_cwd": str(exec_cwd),
    }, indent=2))
    if rc != 0:
        raise SystemExit(rc)


def cmd_parse_log(args: argparse.Namespace) -> None:
    path = Path(args.log)
    if not path.exists():
        raise SystemExit(f"log not found: {path}")
    allowed = set(args.allow_metric or DEFAULT_LOG_METRICS)
    metrics = extract_log_metrics(path.read_text(encoding="utf-8", errors="replace"), allowed)
    if args.metric:
        for key, value in metrics.items():
            if key.lower() == args.metric.lower():
                print(f"{key}: {value:g}")
                return
        raise SystemExit(f"metric not found in {path}: {args.metric}")
    if args.json:
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
        return
    for key in sorted(metrics):
        print(f"{key}: {metrics[key]:g}")


def executor_prompt(
    tree: dict[str, Any],
    cwd: str | Path,
    node_id: str,
    additional: str | None,
    smoke: bool = False,
) -> str:
    n = node(tree, node_id)
    meta = tree["meta"]
    eval_lines: list[str] = []
    if meta.get("eval_cmd"):
        eval_lines.append(f"- **Evaluation command (B_dev)**: `{substitute(meta['eval_cmd'], cwd, node_id)}`")
    if meta.get("eval_cmd_test"):
        eval_lines.append(f"- **Evaluation command (B_test, do not use for routine experiments)**: `{substitute(meta['eval_cmd_test'], cwd, node_id)}`")
    if meta.get("dataset_info"):
        eval_lines.append(f"- **Dataset info**: {meta['dataset_info']}")
    if meta.get("baseline_score") is not None:
        eval_lines.append(f"- **Baseline score**: {meta['baseline_score']}")
    if meta.get("trunk_score") is not None:
        eval_lines.append(f"- **Current trunk score**: {meta['trunk_score']}")

    ancestors: list[str] = []
    cur = n
    while cur.get("parent_id"):
        cur = node(tree, cur["parent_id"])
        if cur.get("insight"):
            ancestors.append(f"- {cur['id']}: {cur['insight']}")
    ancestors.reverse()

    parts = [
        f"## Codebase\n\nWorking directory: {Path(cwd).resolve()}",
        (
            "## Git Isolation\n\n"
            "Work in the assigned experiment branch/worktree. Do not switch back "
            "to the main repository for implementation or evaluation."
        ),
        f"## Research Idea\n\n**ID**: {n['id']}\n**Hypothesis**:\n{n.get('hypothesis', '')}",
    ]
    if eval_lines:
        parts.append(
            "## Evaluation Info\n\n"
            + "\n".join(eval_lines)
            + "\n\nUse B_dev for final experiment scoring. Do NOT use B_test."
        )
    if ancestors:
        parts.append("## Insights From Prior Experiments\n\n" + "\n".join(ancestors))
    if additional:
        parts.append("## Additional Context\n\n" + additional)
    if smoke:
        parts.append(
            "## Smoke Mode\n\n"
            "This is a forward-test of Arbor orchestration only. Do not edit "
            "source code, create a real worktree, commit, run training, run "
            "GPU jobs, or execute minute-scale eval commands. If an eval "
            "command above invokes training or an expensive benchmark, treat "
            "it as metadata and replace it with a cheap cached-score parser "
            "or an explicitly marked mocked score."
        )
        parts.append(
            "## Instructions\n\n"
            "1. Read only concise context needed to validate the dispatch.\n"
            "2. Use `arbor_state.py parse-log` or a small parser for cached "
            "metrics. If using shell tools on training logs, normalize carriage "
            "returns first, for example `tr '\\r' '\\n' < run.log | grep ...`. "
            "Do not `cat`, raw `rg`, raw `grep`, or `tail` long training logs "
            "unless debugging a failure, and then cap output to 20 lines.\n"
            "3. Do not implement the idea in smoke mode.\n"
            "4. Record a smoke-only report with Changes, Baseline vs Result, "
            "Score, Analysis, and Insight.\n"
            "5. Make the score an absolute metric from a cached/cheap source "
            "or clearly label it as mocked evidence for plumbing only.\n\n"
            f"Save smoke artifacts under `.arbor/sessions/<run>/experiments/{node_id}/`."
        )
    else:
        parts.append(
            "## Instructions\n\n"
            "1. Understand the code before editing.\n"
            "2. Implement the idea faithfully.\n"
            "3. Run quick checks to ensure the new logic is active.\n"
            "4. Iterate on implementation bugs.\n"
            "5. Run the B_dev evaluation when credible.\n"
            "6. Report Changes, Baseline vs Result, Score, and Insight. The score "
            "must be the absolute primary metric, not a delta.\n\n"
            f"Save results to `results/{node_id}-<brief-description>/`."
        )
    return "\n\n".join(parts)


def cmd_prompt_executor(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    inferred_smoke = bool(args.additional_context and "SMOKE" in args.additional_context.upper())
    prompt_cwd = Path(args.workdir or args.cwd).resolve()
    prompt = executor_prompt(tree, prompt_cwd, args.node_id, args.additional_context, args.smoke or inferred_smoke)
    output = Path(args.output) if args.output else session_dir(args.cwd, args.run_name) / "experiments" / args.node_id / "executor_prompt.md"
    atomic_write(output, prompt + "\n")
    print(prompt)


def cmd_record(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    n = node(tree, args.node_id)
    raw = args.raw_report or ""
    if args.report_file:
        report_path = Path(args.report_file)
        if not report_path.exists():
            raise SystemExit(
                f"report file not found: {report_path}. "
                "Create it first, or pass --raw-report instead."
            )
        raw = report_path.read_text(encoding="utf-8")
    score = args.score if args.score is not None else parse_score(raw)
    insight = args.insight or ""
    result = args.result or short(raw, 300)
    code_ref = args.code_ref or n.get("code_ref")
    n.update({
        "status": "done",
        "score": score,
        "insight": insight,
        "result": result,
    })
    if code_ref:
        n["code_ref"] = code_ref

    exp_dir = session_dir(args.cwd, args.run_name) / "experiments" / args.node_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    report = raw or (
        f"# Experiment {args.node_id}\n\n"
        f"**Hypothesis**: {n.get('hypothesis', '')}\n\n"
        f"**Score**: {score}\n\n"
        f"**Insight**: {insight}\n\n"
        f"**Result**: {result}\n"
    )
    (exp_dir / "report.md").write_text(report, encoding="utf-8")
    (exp_dir / "metrics.json").write_text(json.dumps({
        "node_id": args.node_id,
        "hypothesis": n.get("hypothesis", ""),
        "score": score,
        "insight": insight,
        "result": result,
        "branch": code_ref,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    save_tree(args.cwd, args.run_name, tree)
    if not args.no_propagate:
        ns = argparse.Namespace(cwd=args.cwd, run_name=args.run_name, node_id=args.node_id, summary=None)
        cmd_propagate(ns)
    print(f"Recorded {args.node_id}: score={score}, branch={code_ref}")


def git(cwd: str | Path, *argv: str, check: bool = False) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *argv],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise SystemExit(proc.stdout.strip())
    return proc.returncode, proc.stdout.strip()


def branch_name(prefix: str, node_id: str, hypothesis: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", hypothesis.lower()).strip("-")[:32] or "idea"
    digest = hashlib.sha1(hypothesis.encode("utf-8")).hexdigest()[:8]
    safe_id = node_id.replace(".", "-")
    return f"{prefix}/n{safe_id}-{slug}-{digest}"


def cmd_worktree(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    n = node(tree, args.node_id)
    branch = args.branch or branch_name(args.branch_prefix, args.node_id, n.get("hypothesis", ""))
    base = Path(tempfile.gettempdir()) / f"arbor-worktrees-{os.getuid()}"
    base.mkdir(parents=True, exist_ok=True)
    wt = base / branch.replace("/", "__").replace(".", "_")
    if wt.exists():
        git(args.cwd, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(wt, ignore_errors=True)
    start = args.trunk or "HEAD"
    rc, out = git(args.cwd, "worktree", "add", "-b", branch, str(wt), start)
    if rc != 0:
        raise SystemExit(out)
    n["status"] = "running"
    n["code_ref"] = branch
    save_tree(args.cwd, args.run_name, tree)
    print(json.dumps({"worktree": str(wt), "branch": branch}, indent=2))


def cmd_merge(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    target = args.target_branch or tree["meta"].get("trunk_branch")
    if not target:
        raise SystemExit("--target-branch is required, or set metadata trunk_branch=<branch>")
    if target in PROTECTED_BRANCHES:
        raise SystemExit(f"refusing to merge into protected branch: {target}")
    src = args.source_branch
    test_score = args.test_score

    eval_cmd_test = tree["meta"].get("eval_cmd_test")
    if test_score is None and eval_cmd_test:
        base = Path(tempfile.gettempdir()) / f"arbor-merge-eval-{os.getuid()}"
        wt = base / src.replace("/", "__").replace(".", "_")
        if wt.exists():
            git(args.cwd, "worktree", "remove", "--force", str(wt))
            shutil.rmtree(wt, ignore_errors=True)
        wt.parent.mkdir(parents=True, exist_ok=True)
        rc, out = git(args.cwd, "worktree", "add", "--detach", str(wt), src)
        if rc != 0:
            raise SystemExit(out)
        try:
            timeout = args.timeout or int(tree["meta"].get("eval_timeout") or 7200)
            rc, output, _ = run_shell(substitute(eval_cmd_test, wt, args.node_id), wt, timeout)
            test_score = parse_score(output)
            if rc != 0 or test_score is None:
                raise SystemExit("B_test evaluation failed or score missing:\n" + output[-2000:])
        finally:
            git(args.cwd, "worktree", "remove", "--force", str(wt))
            shutil.rmtree(wt, ignore_errors=True)

    if test_score is None:
        raise SystemExit("no test score available; configure eval_cmd_test or pass --test-score")

    ref_score = tree["meta"].get("test_trunk_score")
    if ref_score is None:
        ref_score = tree["meta"].get("test_baseline_score")
    if isinstance(ref_score, (int, float)) and not is_improvement(tree, float(test_score), float(ref_score)):
        raise SystemExit(f"merge rejected: test_score={test_score} is not an improvement over {ref_score}")

    if args.protected_path:
        rc, diff = git(args.cwd, "diff", "--name-only", f"{target}...{src}")
        if rc == 0:
            files = [ln.strip() for ln in diff.splitlines() if ln.strip()]
            for pattern in args.protected_path:
                for path in files:
                    if fnmatch.fnmatch(path, pattern):
                        raise SystemExit(f"merge rejected: protected path {path} matches {pattern}")

    for output in args.required_output or []:
        rc, _ = git(args.cwd, "show", f"{src}:{output}")
        if rc != 0:
            raise SystemExit(f"merge rejected: required output missing on branch: {output}")

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "test_score": test_score}, indent=2))
        return

    _, current = git(args.cwd, "branch", "--show-current")
    rc, out = git(args.cwd, "checkout", target)
    if rc != 0:
        raise SystemExit(out)
    message = args.commit_message or f"coordinator: merge {args.node_id} from {src}"
    rc, out = git(args.cwd, "merge", "--no-ff", "-m", message, src)
    if rc != 0:
        git(args.cwd, "merge", "--abort")
        if current:
            git(args.cwd, "checkout", current)
        raise SystemExit("merge failed:\n" + out)
    _, merge_hash = git(args.cwd, "rev-parse", "--short", "HEAD")
    if current and current != target:
        git(args.cwd, "checkout", current)

    tree["meta"]["test_trunk_score"] = float(test_score)
    n = node(tree, args.node_id)
    n["status"] = "merged"
    n["code_ref"] = src
    save_tree(args.cwd, args.run_name, tree)
    print(json.dumps({"merged": src, "target": target, "test_score": test_score, "merge_hash": merge_hash}, indent=2))


def cmd_check(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    sdir = session_dir(args.cwd, args.run_name)
    errors: list[str] = []
    if tree.get("version") != VERSION:
        errors.append(f"version should be {VERSION}, got {tree.get('version')}")
    root_id = tree.get("root_id")
    if root_id not in tree.get("nodes", {}):
        errors.append("root_id missing from nodes")
    for nid, n in tree.get("nodes", {}).items():
        if n.get("id") != nid:
            errors.append(f"{nid}: id field mismatch")
        if n.get("status") not in STATUSES:
            errors.append(f"{nid}: invalid status {n.get('status')}")
        parent = n.get("parent_id")
        if parent is not None:
            if parent not in tree["nodes"]:
                errors.append(f"{nid}: missing parent {parent}")
            elif nid not in tree["nodes"][parent].get("children_ids", []):
                errors.append(f"{nid}: not listed in parent children")
    required_files = [
        (coordinator_dir(args.cwd, args.run_name) / "idea_tree.json", "missing idea_tree.json"),
        (coordinator_dir(args.cwd, args.run_name) / "idea_tree.md", "missing idea_tree.md"),
    ]
    if args.require_report or args.strict_artifacts:
        required_files.append((sdir / "REPORT.md", "missing REPORT.md"))
    if args.require_events or args.strict_artifacts:
        required_files.append((sdir / "events.jsonl", "missing events.jsonl"))
    if args.require_run_stats or args.strict_artifacts:
        required_files.append((sdir / "run_stats.json", "missing run_stats.json"))
    for path, message in required_files:
        if not path.exists():
            errors.append(message)
    if args.require_experiment or args.strict_artifacts:
        exp_root = sdir / "experiments"
        exp_dirs = sorted(p for p in exp_root.iterdir() if p.is_dir()) if exp_root.exists() else []
        if not exp_dirs:
            errors.append("missing experiment artifact directory")
        for exp_dir in exp_dirs:
            for name in ("report.md", "metrics.json"):
                if not (exp_dir / name).exists():
                    errors.append(f"{exp_dir.name}: missing {name}")
            if (args.require_executor_prompt or args.strict_artifacts) and not (exp_dir / "executor_prompt.md").exists():
                errors.append(f"{exp_dir.name}: missing executor_prompt.md")
    elif args.require_executor_prompt:
        exp_root = sdir / "experiments"
        prompts = sorted(exp_root.glob("*/executor_prompt.md")) if exp_root.exists() else []
        if not prompts:
            errors.append("missing executor_prompt.md artifact")
    if errors:
        print("INVALID")
        for err in errors:
            print(f"- {err}")
        raise SystemExit(1)
    print("OK")


def cmd_report(args: argparse.Namespace) -> None:
    tree = load_tree(args.cwd, args.run_name)
    sdir = session_dir(args.cwd, args.run_name)
    meta = tree.get("meta", {})
    lines = [
        f"# Research Report: {short(node(tree, tree.get('root_id', 'ROOT')).get('hypothesis', 'Research session'), 100)}",
        "",
        "## Results",
        "",
        f"- B_dev baseline: `{fmt_score(meta.get('baseline_score'))}`",
        f"- B_dev final trunk: `{fmt_score(meta.get('trunk_score'))}`",
        f"- B_test baseline: `{fmt_score(meta.get('test_baseline_score'))}`",
        f"- B_test final trunk: `{fmt_score(meta.get('test_trunk_score'))}`",
        "",
        "## Exploration",
        "",
    ]
    scored = [
        n for n in tree["nodes"].values()
        if isinstance(n.get("score"), (int, float)) and n.get("depth", 0) > 0
    ]
    reverse = meta.get("metric_direction", "maximize") != "minimize"
    scored.sort(key=lambda n: float(n["score"]), reverse=reverse)
    merged = [n for n in tree["nodes"].values() if n.get("status") == "merged"]
    lines.append(f"- Nodes total: `{max(0, len(tree['nodes']) - 1)}`")
    lines.append(f"- Scored nodes: `{len(scored)}`")
    lines.append(f"- Merged nodes: `{len(merged)}`")
    if merged:
        lines.extend(["", "### Merged Ideas", ""])
        for n in merged:
            lines.append(f"- **{n['id']}** `{fmt_score(n.get('score'))}`: {short(n.get('hypothesis', ''), 120)}")
    if scored:
        lines.extend(["", "### Top Ideas By Score", ""])
        for n in scored[:10]:
            lines.append(f"- **{n['id']}** `{fmt_score(n.get('score'))}` _{n.get('status')}_: {short(n.get('hypothesis', ''), 120)}")
    root = node(tree, tree.get("root_id", "ROOT"))
    if root.get("insight"):
        lines.extend(["", "## Global Insight", "", root["insight"]])
    lines.extend([
        "",
        "## Artifacts",
        "",
        f"- Idea tree JSON: `{coordinator_dir(args.cwd, args.run_name) / 'idea_tree.json'}`",
        f"- Idea tree Markdown: `{coordinator_dir(args.cwd, args.run_name) / 'idea_tree.md'}`",
        f"- Experiments: `{sdir / 'experiments'}`",
    ])
    out = sdir / "REPORT.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(out)


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cwd", default=".", help="target project directory")
    parser.add_argument("--run-name", default="skill_run", help="session name under .arbor/sessions")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init")
    add_common(sp)
    sp.add_argument("--task", required=True)
    sp.add_argument("--max-depth", default="2")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("view")
    add_common(sp)
    sp.add_argument("--format", choices=["compact", "full", "node", "pending", "constraints"], default="compact")
    sp.add_argument("--node-id")
    sp.set_defaults(func=cmd_view)

    sp = sub.add_parser("meta")
    add_common(sp)
    sp.add_argument("--set", action="append", default=[])
    sp.set_defaults(func=cmd_meta)

    sp = sub.add_parser("add")
    add_common(sp)
    sp.add_argument("--parent-id", required=True)
    sp.add_argument("--hypothesis", required=True)
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("update")
    add_common(sp)
    sp.add_argument("--node-id", required=True)
    sp.add_argument("--status", choices=sorted(STATUSES))
    sp.add_argument("--score", type=float)
    sp.add_argument("--insight")
    sp.add_argument("--result")
    sp.add_argument("--code-ref")
    sp.add_argument("--hypothesis")
    sp.add_argument("--related-work")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("prune")
    add_common(sp)
    sp.add_argument("--node-id", required=True)
    sp.add_argument("--reason", required=True)
    sp.set_defaults(func=cmd_prune)

    sp = sub.add_parser("propagate")
    add_common(sp)
    sp.add_argument("--node-id", required=True)
    sp.add_argument("--summary")
    sp.set_defaults(func=cmd_propagate)

    sp = sub.add_parser("eval")
    add_common(sp)
    sp.add_argument("--split", choices=["dev", "test"], required=True)
    sp.add_argument("--cmd", required=True)
    sp.add_argument("--exec-cwd", help="directory where the eval command runs; defaults to --cwd")
    sp.add_argument("--node-id")
    sp.add_argument("--timeout", type=int)
    sp.add_argument("--set-meta", choices=["none", "baseline", "trunk", "test_baseline", "test_trunk"], default="none")
    sp.set_defaults(func=cmd_eval)

    sp = sub.add_parser("parse-log")
    sp.add_argument("--log", required=True)
    sp.add_argument("--metric")
    sp.add_argument("--allow-metric", action="append")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_parse_log)

    sp = sub.add_parser("prompt-executor")
    add_common(sp)
    sp.add_argument("--node-id", required=True)
    sp.add_argument("--additional-context")
    sp.add_argument("--workdir", help="working directory shown in the executor prompt; defaults to --cwd")
    sp.add_argument("--output", help="path for executor_prompt.md; defaults under the session experiment directory")
    sp.add_argument("--smoke", action="store_true", help="emit smoke-only executor instructions")
    sp.set_defaults(func=cmd_prompt_executor)

    sp = sub.add_parser("record")
    add_common(sp)
    sp.add_argument("--node-id", required=True)
    sp.add_argument("--report-file")
    sp.add_argument("--raw-report")
    sp.add_argument("--score", type=float)
    sp.add_argument("--insight")
    sp.add_argument("--result")
    sp.add_argument("--code-ref")
    sp.add_argument("--no-propagate", action="store_true")
    sp.set_defaults(func=cmd_record)

    sp = sub.add_parser("worktree")
    add_common(sp)
    sp.add_argument("--node-id", required=True)
    sp.add_argument("--branch-prefix", default="coordinator")
    sp.add_argument("--branch")
    sp.add_argument("--trunk")
    sp.set_defaults(func=cmd_worktree)

    sp = sub.add_parser("merge")
    add_common(sp)
    sp.add_argument("--source-branch", required=True)
    sp.add_argument("--target-branch")
    sp.add_argument("--node-id", required=True)
    sp.add_argument("--test-score", type=float)
    sp.add_argument("--timeout", type=int)
    sp.add_argument("--protected-path", action="append")
    sp.add_argument("--required-output", action="append")
    sp.add_argument("--commit-message")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser("check")
    add_common(sp)
    sp.add_argument("--require-report", action="store_true")
    sp.add_argument("--require-experiment", action="store_true")
    sp.add_argument("--require-executor-prompt", action="store_true")
    sp.add_argument("--require-events", action="store_true")
    sp.add_argument("--require-run-stats", action="store_true")
    sp.add_argument("--strict-artifacts", action="store_true")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("report")
    add_common(sp)
    sp.set_defaults(func=cmd_report)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "cmd", None) in MUTATING_COMMANDS:
        with state_lock(args.cwd, args.run_name):
            args.func(args)
    else:
        args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
