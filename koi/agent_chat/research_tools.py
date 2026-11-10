"""Arbor-facing CLI tools over ResearcherOS's existing project commands.

Send one JSON request on stdin. This is also usable from any agent CLI.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import sys
import time
from dataclasses import fields
from pathlib import Path
from uuid import uuid4

from koi.adapters import repository, card_reports
from koi.core.models import NodeType, EdgeType
from koi.projects import commands
from koi.agent_chat import research


def perform(run_id, operation, args):
    if args.get("title") is not None and len(str(args["title"]).split()) > 8:
        raise ValueError("Node and card titles must contain at most eight words")
    # The same cross-process lock serializes tree changes from all executors.
    # No second editable Idea Tree is created.
    with research._db() as db:
        db.execute("BEGIN IMMEDIATE")
        run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise KeyError(run_id)
        metadata = json.loads(run["metadata"])
        skill_scope = metadata.get("skill_execution_scope")
        if skill_scope and skill_scope["level"] != "tree" and operation in ("scope", "meta"):
            raise ValueError("A skill cannot expand its execution level or edit tree settings")
        scope = metadata.get("research_scope")
        if not scope and skill_scope and skill_scope["level"] == "method":
            scope = skill_scope
        if operation == "scope":
            if scope and scope.get("level"):
                raise ValueError("The agreed research scope cannot be changed; start a new research request")
            level = args.get("level")
            if level not in ("tree", "method"):
                raise ValueError("Choose tree or method after user confirmation")
            method_id = (scope or {}).get("method_id") if level == "method" else None
            if level == "method" and not method_id:
                raise ValueError("No method in the launch context")
            metadata["research_scope"] = {"level": level, "method_id": method_id}
            db.execute("UPDATE runs SET metadata=? WHERE id=?", (json.dumps(metadata, ensure_ascii=False), run_id))
            return metadata["research_scope"]
        if scope is not None and not scope.get("level") and operation != "view":
            raise ValueError("Confirm the research scope with the user before starting")
        if operation == "meta":
            allowed = {"baseline_score", "trunk_score", "eval_cmd", "eval_cmd_test", "dataset_info",
                       "metric_direction", "trunk_branch", "test_trunk_score", "run_mode", "permissions"}
            if set(args) - allowed:
                raise ValueError("Only Arbor execution metadata belongs here; scientific state stays in the project")
            metadata = {**json.loads(run["metadata"]), **args}
            db.execute("UPDATE runs SET metadata=? WHERE id=?", (json.dumps(metadata, ensure_ascii=False), run_id))
            return metadata
        if operation == "contract":
            import time
            seconds, executors = args.get("max_seconds"), args.get("max_executors")
            parallel = args.get("max_parallel", min(4, executors) if type(executors) is int else 1)
            condition = args.get("stop_condition")
            if type(seconds) is not int or not 0 < seconds <= 604800:
                raise ValueError("max_seconds must be between 1 and 604800")
            if type(executors) is not int or not 0 < executors <= 1000:
                raise ValueError("max_executors must be between 1 and 1000")
            if type(parallel) is not int or not 1 <= parallel <= min(4, executors):
                raise ValueError("max_parallel must be between 1 and min(4, max_executors)")
            if not isinstance(condition, str) or not condition.strip():
                raise ValueError("A stopping criterion is required")
            existing = db.execute("SELECT * FROM budgets WHERE run_id=?", (run_id,)).fetchone()
            if existing:
                raise ValueError("A recorded budget cannot be silently replaced")
            db.execute("INSERT INTO budgets VALUES (?,?,?,0,?)", (run_id, time.time()+seconds, executors, condition))
            metadata = {**json.loads(run["metadata"]), "max_parallel": parallel}
            db.execute("UPDATE runs SET metadata=? WHERE id=?", (json.dumps(metadata, ensure_ascii=False), run_id))
            return dict(db.execute("SELECT * FROM budgets WHERE run_id=?", (run_id,)).fetchone())
        project_id = run["project_id"]
        project = repository.load_project(project_id, sync_reports=False)
        if project is None:
            raise ValueError("Project not found")
        if operation == "view":
            budget = db.execute("SELECT * FROM budgets WHERE run_id=?", (run_id,)).fetchone()
            return {**project.model_dump(mode="json"), "arbor_metadata": json.loads(run["metadata"]),
                    "research_budget": dict(budget) if budget else None}
        if skill_scope and skill_scope["level"] == "card" and operation != "read_report":
            if operation not in ("write_report", "complete_subtask", "publish_image", "update_card", "conclusion"):
                raise ValueError("Card-level skill may only change the current card task")
            if args.get("card_id") != skill_scope["card_id"] or args.get("board_id") != skill_scope["board_id"]:
                raise ValueError("Card-level skill cannot change another card")
        if scope and scope.get("level") == "method":
            method_id = scope["method_id"]
            board_ids = {b.id for b in project.boards if b.owner_node_id == method_id}
            if operation in ("create_node", "delete_node"):
                raise ValueError("Method research must stay within the selected method")
            if operation == "update_node" and (args.get("node_id") != method_id or
                    set(args) - {"node_id", "description"}):
                raise ValueError("Method research may only update its own description")
            refs = args.get("cards", []) if operation == "phase" else [args] if "board_id" in args and operation != "read_report" else []
            if any(ref.get("board_id") not in board_ids for ref in refs):
                raise ValueError("Experiment belongs to another method")
            if operation == "phase" and args.get("phase") == "hypotheses" and args.get("node_ids") != [method_id]:
                raise ValueError("Publish improvement hypotheses in the selected method description")
        if operation == "phase":
            metadata = json.loads(run["metadata"])
            workflow = metadata.get("research_workflow", {})
            phase = args.get("phase")
            previous = workflow.get("phase")
            transitions = {None: {"hypotheses"}, "hypotheses": {"hypotheses", "backlog"},
                           "backlog": {"hypotheses", "backlog", "execution"},
                           "execution": {"hypotheses", "execution"}}
            if phase not in transitions.get(previous, set()):
                raise ValueError("Publish hypotheses, prepare backlog, then start execution")
            if phase == "hypotheses":
                ids = args.get("node_ids", [])
                nodes = {n.id: n for n in project.nodes}
                if not ids or any(i not in nodes or nodes[i].parent_id is None
                                  or not nodes[i].description.strip() for i in ids):
                    raise ValueError("Publish non-root hypotheses with descriptions before planning")
                workflow = {"phase": phase, "node_ids": ids}
            elif phase == "backlog":
                cards = args.get("cards", [])
                if not cards:
                    raise ValueError("Prepare a nonempty backlog wave")
                for ref in cards:
                    board = next((b for b in project.boards if b.id == ref["board_id"]), None)
                    card = next((c for c in board.cards if c.id == ref["card_id"]), None) if board else None
                    if card is None or card.column_id != "backlog":
                        raise ValueError("Wave cards must exist in backlog")
                    content = card_reports.read_report(project, board.id, card.id, card.title)["content"]
                    if not all(re.search(rf"^##\s+{n}[.)]\s+\S", content, re.M) for n in (1, 2, 3)):
                        raise ValueError("Prepare every wave card's setup (§1–§3) before execution")
                workflow = {**workflow, "phase": phase, "cards": cards}
            else:
                workflow = {**workflow, "phase": phase}
            metadata["research_workflow"] = workflow
            db.execute("UPDATE runs SET metadata=? WHERE id=?", (json.dumps(metadata, ensure_ascii=False), run_id))
            return workflow
        if operation in ("update_node", "delete_node"):
            node = next((n for n in project.nodes if n.id == args["node_id"]), None)
            if node is None:
                raise ValueError("Node not found")
            if node.parent_id is None:
                raise ValueError("The main node is protected")
        if operation == "create_node":
            payload = dict(args)
            payload["node_type"] = NodeType(payload["node_type"])
            payload["edge_type"] = EdgeType(payload.get("edge_type", "direction"))
            result = commands.create_node(project_id, commands.CreateNodeCommand(**payload))
        elif operation == "update_node":
            payload = {k: v for k, v in args.items() if k != "node_id"}
            if "edge_type" in payload:
                payload["edge_type"] = EdgeType(payload["edge_type"])
            if "root_type" in payload or "research_questions" in payload:
                raise ValueError("Use the research-result protocol for conclusions; root type is protected")
            result = commands.update_node(project_id, args["node_id"], commands.UpdateNodeCommand(**payload))
        elif operation == "delete_node":
            result = commands.delete_node(project_id, args["node_id"])
        elif operation == "create_card":
            payload = {k: v for k, v in args.items() if k != "board_id"}
            if payload.get("column_id", "backlog") != "backlog":
                raise ValueError("New experiments must start in backlog")
            payload["column_id"] = "backlog"
            result = commands.create_card(project_id, args["board_id"], commands.CreateCardCommand(**payload))
        elif operation in ("read_report", "write_report", "complete_subtask", "publish_image", "update_card", "conclusion"):
            board = next((b for b in project.boards if b.id == args["board_id"]), None)
            card = next((c for c in board.cards if c.id == args["card_id"]), None) if board else None
            if card is None:
                raise ValueError("Card not found")
            if operation == "read_report":
                return card_reports.read_report(project, board.id, card.id, card.title)
            if operation == "write_report":
                return card_reports.write_report(project, board.id, card.id, card.title, args["content"])
            if operation in ("complete_subtask", "publish_image"):
                if card.column_id != "running":
                    raise ValueError("Publish experiment progress while the card is running")
                content = card_reports.read_report(project, board.id, card.id, card.title)["content"]
                if operation == "complete_subtask":
                    # Match the task text, never a shifting numeric index or the whole report.
                    task = str(args["task"]).strip()
                    section = re.search(r"^##\s+3[.)]\s+.*?(?=^##\s|\Z)", content, re.M | re.S)
                    if not section or not task:
                        raise ValueError("Subtask must exist in report section 3")
                    pattern = re.compile(r"^(\s*-\s+)\[([ xX])\](\s+" + re.escape(task) + r"\s*)$", re.M)
                    if len(list(pattern.finditer(section.group()))) != 1:
                        raise ValueError("Subtask text must match exactly one checklist item in section 3")
                    updated = pattern.sub(lambda m: m[1] + "[x]" + m[3], section.group())
                    content = content[:section.start()] + updated + content[section.end():]
                else:
                    heading = str(args["section"]).strip()
                    if not re.fullmatch(r"#{2,6}\s+\S[^\n]*", heading) or content.splitlines().count(heading) != 1:
                        raise ValueError("Image section must match exactly one existing report heading")
                    caption = str(args["caption"]).strip()
                    if not caption or any(c in caption for c in "\r\n[]"):
                        raise ValueError("Provide a one-line image caption without brackets")
                    source = Path(args["source_path"])
                    if not source.is_absolute():
                        raise ValueError("Image source_path must be absolute in the executor workspace")
                    mime = mimetypes.guess_type(source.name)[0] or ""
                    if mime not in card_reports.MIME_TO_EXT:
                        raise ValueError("Unsupported image type")
                    with source.open("rb") as stream:
                        data = stream.read(card_reports.MAX_ASSET_BYTES + 1)
                    asset = card_reports.save_report_asset(project, board.id, card.id, card.title, data, mime)
                    report_dir = card_reports._report_dir_for_card(project, board.id, card.id, card.title)
                    # Each card has its own gallery even when reports share a method directory.
                    gallery = "card-" + hashlib.sha256(card.id.encode()).hexdigest()[:16]
                    target = report_dir / "assets" / gallery / asset["filename"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    (report_dir / asset["markdown_path"]).replace(target)
                    markdown_path = f"assets/{gallery}/{asset['filename']}"
                    content = re.sub(r"^" + re.escape(heading) + r"$",
                                     lambda _: heading + f"\n\n![{caption}]({markdown_path})",
                                     content, count=1, flags=re.M)
                    hint = "metrics_dir: " + str(target.parent.resolve())
                    content = re.sub(r"^metrics_dir:[^\n]*\n?", "", content, flags=re.M | re.I)
                    content = hint + "\n" + content
                result = card_reports.write_report(project, board.id, card.id, card.title, content)
                return {**result, **({"markdown_path": markdown_path, "metrics_dir": str(target.parent)}
                                      if operation == "publish_image" else {})}
            if operation == "conclusion":
                if card.column_id != "done":
                    raise ValueError("Only a completed card can produce a final conclusion")
                from koi.projects.done_research_cli import build_context
                from koi.projects.done_research_auto import _save
                from koi.adapters.done_research_queue import dequeue
                conclusion = _save(build_context(project_id, board.id, card.id), args["conclusion"])
                dequeue(project_id, board.id, card.id)
                return {"question_id": conclusion.id, "card_id": card.id}
            allowed = {f.name for f in fields(commands.UpdateCardCommand)}
            payload = {k: v for k, v in args.items() if k in allowed}
            unknown = set(args) - allowed - {"board_id", "card_id"}
            if unknown:
                raise ValueError(f"Unknown card fields: {sorted(unknown)}")
            if payload.get("column_id") == "running":
                workflow = json.loads(run["metadata"]).get("research_workflow", {})
                ref = {"board_id": board.id, "card_id": card.id}
                if workflow.get("phase") != "execution" or ref not in workflow.get("cards", []):
                    raise ValueError("Publish hypotheses and the prepared backlog wave before execution")
                report = card_reports.read_report(project, board.id, card.id, card.title)["content"]
                if not all(re.search(rf"^##\s+{number}[.)]\s+\S", report, re.M) for number in (1, 2, 3)):
                    raise ValueError("Prepare the experiment setup (§1–§3) before execution")
            if payload.get("column_id") == "done":
                report = card_reports.read_report(project, board.id, card.id, card.title)["content"]
                if card.column_id != "running":
                    raise ValueError("Execute the card in running before marking it done")
                if re.search(r"^\s*-\s+\[ \]", report, re.M):
                    raise ValueError("Complete or explicitly resolve all report subtasks before done")
                if not re.search(r"^##\s+4[.)]\s+\S", report, re.M):
                    raise ValueError("Record results and conclusions before done")
            result = commands.update_card(project_id, board.id, card.id, commands.UpdateCardCommand(**payload))
        else:
            raise ValueError(f"Unknown operation: {operation}")
        return result.model_dump(mode="json")


def request(run_id, operation, args, *, timeout=60):
    """Let the live host perform validated operations outside the CLI sandbox."""
    with research._db() as db:
        host = db.execute('SELECT * FROM brokers WHERE run_id=?', (run_id,)).fetchone()
    if host is None or research._process_start(host['pid']) != host['started']:
        if os.environ.get('CODEX_SANDBOX'):
            raise RuntimeError('ResearcherOS host is unavailable; restart the research from the app')
        return perform(run_id, operation, args)
    if host['pid'] == os.getpid():
        return perform(run_id, operation, args)
    request_id = 'tool-' + uuid4().hex
    with research._db() as db:
        db.execute('INSERT INTO tool_requests VALUES (?,?,?,?,?)',
                   (request_id, run_id, json.dumps({'operation': operation, 'args': args}), 'pending', ''))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if research.cancelled(run_id):
            raise RuntimeError('Research was cancelled')
        with research._db() as db:
            row = db.execute('SELECT * FROM tool_requests WHERE id=?', (request_id,)).fetchone()
        if row['status'] == 'completed':
            return json.loads(row['result'])
        if row['status'] == 'failed':
            raise RuntimeError(row['result'])
        time.sleep(.1)
    with research._db() as db:
        db.execute("UPDATE tool_requests SET status='failed',result='Request timed out' WHERE id=? AND status='pending'", (request_id,))
    raise TimeoutError('ResearcherOS host did not finish the operation; inspect state before retrying')


def main():
    payload = json.load(sys.stdin)
    try:
        result = request(payload["run_id"], payload["operation"], payload.get("args", {}))
    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
