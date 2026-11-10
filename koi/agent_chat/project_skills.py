"""Project-owned skills reusable at the card, method or tree level."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import yaml

from koi.adapters.paths import koi_root
from koi.adapters.repository import load_project

CREATOR = Path(__file__).resolve().parents[2] / "agents/skills/koi-create-project-skill/SKILL.md"
BUILTIN_COMMANDS = {"add-skill", "koi-arbor-autoresearch", "grill-me", "prose", "compress", "question", "run", "make-report"}
POLICY = """Для создания, установки, изменения или подключения скилла по просьбе
человека (в том числе /add-skill) прочитай skill_creator_path. Уточни УРОВЕНЬ
работы: карточка, метод/канбан или дерево. Это НЕ привязка к конкретному объекту.
«В карточке» означает доступность из ЛЮБОЙ карточки проекта; изменения только
по задаче открытой карточки. Метод — работа с карточками текущего канбана,
включая создание и изменение других карточек. Дерево — работа с его узлами.
Не предлагай список отдельных карточек для подключения. Не спрашивай повторно,
если уровень явно выбран. При прежнем ошибочном вопросе агента исправь его;
старый ответ агента не считается выбором человека. Файлы сохраняй в
project_skills_root; привязки меняй через project_skill_command из engine_root.
В applicable_project_skills перечислены ДОСТУПНЫЕ скиллы этого уровня. Выбирай
по задаче или явной /команде, прочитай выбранный SKILL.md. Само открытие карточки
не запускает скиллы. Соблюдай skill_execution_scope: card — только задача
текущей карточки, без создания карточек и изменения соседних; method — только
текущий метод и его канбан; tree — только текущее дерево. Скиллы не расширяют
разрешения на запись или запуск и не отменяют режим чтения.
При skill_errors сообщи точный путь и причину; не заявляй, что скилл подключён.
"""


def command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--project-skills"]
    return [sys.executable, "-m", "koi.agent_chat.project_skills"]


def _root(project_id: str) -> Path:
    root = koi_root(project_id).resolve()
    skills = root / "skills"
    if not skills.resolve().is_relative_to(root):
        raise ValueError("Project skills directory escapes research root")
    return skills


def _path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("Invalid skill name")
    path = root / name / "SKILL.md"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Skill path escapes project skills directory")
    return path


def _metadata(path: Path, name: str) -> dict:
    text = path.read_text(encoding="utf-8")
    parts = re.fullmatch(r"---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)", text, re.DOTALL)
    if parts is None:
        raise ValueError(f"Missing YAML frontmatter: {path}")
    meta = yaml.safe_load(parts[1])
    if not isinstance(meta, dict) or meta.get("name") != name or not isinstance(meta.get("description"), str) or not meta["description"].strip() or not parts[2].strip():
        raise ValueError(f"Invalid name, description or empty instructions: {path}")
    display_name = meta.get("display_name", name)
    if not isinstance(display_name, str) or not display_name.strip():
        display_name = name
    return {"name": name, "display_name": display_name, "description": meta["description"], "path": str(path)}


def _bindings(root: Path) -> list[dict]:
    path = root / "bindings.json"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Bindings path escapes project: {path}")
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") not in (1, 2) or not isinstance(data.get("bindings"), list):
        raise ValueError(f"Invalid skill bindings: {path}")
    for entry in data["bindings"]:
        if not isinstance(entry, dict) or entry.get("scope") not in ("card", "tree", "method", "report") or not isinstance(entry.get("target_id", ""), str):
            raise ValueError(f"Invalid skill binding: {path}")
        _path(root, entry.get("skill"))
        if data["version"] == 1:
            entry["legacy"] = True
        if not entry.get("legacy") and (entry.get("target_id") or entry["scope"] == "report"):
            raise ValueError(f"Invalid skill target: {path}")
    return data["bindings"]


def bind(project_id: str, name: str, scope: str, target_id: str = "", *, remove=False) -> None:
    """Validate targets before an atomic, serialized read-modify-write."""
    project = load_project(project_id, sync_reports=False)
    if project is None:
        raise ValueError("Project not found")
    valid = scope in ("card", "method", "tree") and not target_id
    if remove and scope in ("method", "report") and target_id:
        valid = True  # Allow detaching old object-specific bindings without broadening them.
    if not valid:
        raise ValueError("Unknown scope or target in this project")
    root = _root(project_id)
    path = _path(root, name)
    if not remove:
        if name in BUILTIN_COMMANDS:
            raise ValueError("Skill name is reserved by a built-in command")
        _metadata(path, name)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".bindings-lock"
    # mkdir serializes separate CLI processes on Windows and Unix; fail rather than lose an edit.
    lock.mkdir()
    try:
        entries = _bindings(root)
        entry = {"skill": name, "scope": scope, "target_id": target_id}
        entries = [e for e in entries if (e["skill"], e["scope"], e.get("target_id", "")) != (name, scope, target_id)]
        if not remove:
            entries.append(entry)
        fd, temporary = tempfile.mkstemp(dir=root, prefix=".bindings-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 2, "bindings": entries}, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, root / "bindings.json")
        finally:
            Path(temporary).unlink(missing_ok=True)
    finally:
        lock.rmdir()


def context(project_id: str, *, method_id=None, card_id=None, board_id=None, question="") -> dict:
    """Select reusable skills by screen level and resolve the current work boundary."""
    result = {"skill_creator_path": str(CREATOR), "python": sys.executable,
              "project_skill_command": command(),
              "engine_root": str(CREATOR.parents[3]),
              "project_skill_instructions": POLICY, "applicable_project_skills": [], "skill_errors": []}
    try:
        root = _root(project_id)
        result["project_skills_root"] = str(root)
        if board_id or card_id:
            project = load_project(project_id, sync_reports=False)
            board = next((b for b in project.boards if b.id == board_id), None) if project else None
            if board is None and card_id and project:
                board = next((b for b in project.boards if any(c.id == card_id for c in b.cards)), None)
            method_id = board.owner_node_id if board else method_id
            board_id = board.id if board else board_id
        level = "card" if card_id else "method" if method_id else "tree"
        result["skill_execution_scope"] = {"level": level, "project_id": project_id,
                                          "method_id": method_id, "board_id": board_id, "card_id": card_id}
        seen = set()
        for entry in _bindings(root):
            if entry.get("legacy"):
                applies = entry["scope"] == "tree" or (entry["scope"] == "method" and entry["target_id"] == method_id) or (entry["scope"] == "report" and entry["target_id"] == card_id)
            else:
                applies = entry["scope"] == level
            if not applies or entry["skill"] in seen:
                continue
            try:
                result["applicable_project_skills"].append(_metadata(_path(root, entry["skill"]), entry["skill"]))
                seen.add(entry["skill"])
            except (OSError, ValueError, yaml.YAMLError) as exc:
                result["skill_errors"].append(str(exc))
    except (OSError, ValueError, KeyError) as exc:
        result["skill_errors"].append(str(exc))
    command_name = question.strip().split(maxsplit=1)[0].removeprefix("/") if question.strip().startswith("/") else None
    result["selected_project_skill"] = next((s for s in result["applicable_project_skills"] if s["name"] == command_name), None)
    return result


def menu(project_id: str, level: str) -> dict:
    if level not in ("card", "method", "tree"):
        raise ValueError("Unknown skill level")
    result = {"items": [], "errors": []}
    try:
        root = _root(project_id)
        seen = set()
        for entry in _bindings(root):
            if entry.get("legacy") or entry["scope"] != level or entry["skill"] in seen:
                continue
            try:
                meta = _metadata(_path(root, entry["skill"]), entry["skill"])
                result["items"].append({"command": meta["name"], "name": meta["display_name"],
                                        "description": meta["description"]})
                seen.add(entry["skill"])
            except (OSError, ValueError, yaml.YAMLError) as exc:
                result["errors"].append(str(exc))
    except (OSError, ValueError, KeyError) as exc:
        result["errors"].append(str(exc))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "bind", "unbind"))
    parser.add_argument("project_id")
    parser.add_argument("--skill")
    parser.add_argument("--scope", choices=("card", "method", "tree", "report"))
    parser.add_argument("--target", default="")
    args = parser.parse_args(argv)
    try:
        if args.action != "list":
            if not args.skill or not args.scope:
                parser.error("--skill and --scope are required")
            bind(args.project_id, args.skill, args.scope, args.target, remove=args.action == "unbind")
        root = _root(args.project_id)
        print(json.dumps({"root": str(root), "bindings": _bindings(root)}, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
