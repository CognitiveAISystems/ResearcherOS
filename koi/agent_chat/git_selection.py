"""Project selected card changes onto the committed tree. Never stage working files."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from koi.adapters import project_sync as sync
from koi.core.md_io import KANBAN_START_RE, _write_kanban, parse_project_md


def _questions(doc):
    rows = doc.get("questions", [])
    return {r["id"]: r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)}


def _records(text):
    project = parse_project_md(text, project_id="git-preview")
    return project, {(b.id, c.id): c for b in project.boards for c in b.cards}


def _load(mount, ref, name):
    from .git_changes import _text_at
    if ref:
        return _text_at(sync._koi_git_cwd(mount), ref, sync._koi_rel(mount) + "/" + name)
    path = mount.koi_root / name
    return path.read_text() if path.is_file() and not path.is_symlink() else ""


def _json(text):
    try:
        value = json.loads(text or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def units(mount, names, base, target, cards):
    root = sync._koi_rel(mount)
    project_path, research_path = [f"{root}/{n}" for n in ("project.md", "research.json")]
    if not {project_path, research_path}.intersection(names):
        return []
    _, old = _records(_load(mount, base, "project.md"))
    _, new = _records(_load(mount, target, "project.md"))
    by_id = {c: (b, c) for b, c in old.keys() | new.keys()}
    rows = {}

    def row(key):
        card = new.get(key) or old[key]
        identifier = "/".join(key)
        return rows.setdefault(key, dict(id=identifier, title=card.title, card=identifier,
                                         label="", detail="", paths=[], questions=[]))

    if project_path in names:
        for key in sorted(old.keys() | new.keys()):
            prev, curr = old.get(key), new.get(key)
            if prev == curr:
                continue
            item = row(key)
            item["paths"].append(project_path)
            if curr is None:
                item.update(label="Удалена карточка", detail=prev.title)
            elif not prev:
                item.update(label="Добавлена карточка", detail=curr.description or curr.title)
            elif prev.column_id != curr.column_id:
                status = {"done": "Завершена карточка", "running": "Начата работа", "backlog": "Возвращена в план"}
                item.update(label=status.get(curr.column_id, "Изменён статус"), detail=curr.description or curr.title)
            else:
                item.update(label="Обновлена карточка", detail=curr.description or curr.title)
    if research_path in names:
        before, after = [_questions(_json(_load(mount, ref, "research.json"))) for ref in (base, target)]
        for qid in sorted(before.keys() | after.keys()):
            prev, curr = before.get(qid), after.get(qid)
            if prev == curr:
                continue
            record = curr or prev
            key = by_id.get(record.get("card_id"))
            if not key:
                continue
            item = row(key)
            if research_path not in item["paths"]:
                item["paths"].append(research_path)
            item["questions"].append(qid)
            label = "Удалён вывод" if not curr else "Обновлён вывод" if prev else "Добавлен вывод"
            detail = record.get("narrative") or record.get("answer") or record.get("question") or item["title"]
            item["detail"] = (item["detail"] + " " if len(item["questions"]) > 1 else "") + str(detail)
            item["label"] = label
    return sorted(rows.values(), key=lambda r: (not r["questions"], r["title"]))


def _project_text(base_text, local_text, selected):
    """Keep unrelated Markdown verbatim and replace only affected kanban tables."""
    base, _ = _records(base_text)
    local, _ = _records(local_text)
    boards = {b.id: b for b in base.boards}
    current = {b.id: b for b in local.boards}
    groups = {}
    for key in selected:
        board, card = key.split("/", 1)
        groups.setdefault(board, set()).add(card)
    lines = base_text.splitlines(keepends=True)
    nodes = {n.id: n for n in local.nodes}

    def node_end(node_id):
        for i, line in enumerate(lines):
            m = re.match(r"^(#+) \w+: (\S+)\s*$", line)
            if m and m[2] == node_id:
                depth = len(m[1])
                end = next((j for j in range(i+1, len(lines)) if re.match(r"^#{1," + str(depth) + r"} \w+: ", lines[j])), len(lines))
                return end, depth
        return None

    def ensure_node(node_id):
        found = node_end(node_id)
        if found:
            return found
        node = nodes[node_id]
        pos, depth = ensure_node(node.parent_id) if node.parent_id else (len(lines), 0)
        lines[pos:pos] = ["\n", "#" * (depth+1) + f" {node.node_type.value}: {node.id}\n", "\n", node.title + "\n", "\n"]
        return node_end(node_id)

    for bid, ids in groups.items():
        source = current.get(bid)
        board = boards.get(bid) or source.model_copy(update={"cards": []})
        replacements = {c.id: c for c in source.cards if c.id in ids} if source else {}
        merged = [replacements.pop(c.id, c) for c in board.cards if c.id not in ids or c.id in replacements]
        merged.extend(replacements.values())
        columns = list(board.columns)
        if source:
            columns.extend(c for c in source.columns if c.id in {v.column_id for v in merged}
                           and c.id not in {v.id for v in board.columns})
        table = [line + "\n" for line in _write_kanban(board.model_copy(update={"cards": merged, "columns": columns}))]
        start = next((i for i,l in enumerate(lines) if (m := KANBAN_START_RE.match(l)) and m[1] == bid), None)
        if start is None:
            end, _ = ensure_node(board.owner_node_id)
            # Attach to the owner, before any child heading.
            owner = next(i for i,l in enumerate(lines) if re.match(r"^#+ \w+: " + re.escape(board.owner_node_id) + r"\s*$", l))
            start = end = next((i for i in range(owner+1,end) if re.match(r"^#+ \w+: ", lines[i])), end)
        else:
            end = start + 1
            while end < len(lines) and (not lines[end].strip() or lines[end].lstrip().startswith("|")):
                end += 1
        lines[start:end] = table
    return "".join(lines)


def send(mount, state, selected, *, commit_only=False):
    from .git_changes import _git, snapshot
    cwd, root = sync._koi_git_cwd(mount), sync._koi_rel(mount)
    panel = state["panel"]
    rows = [r for r in panel["outgoing"] if r["id"] in selected]
    if panel["history_blocked"]:
        return "В локальной истории есть коммиты вне отбора карточек. Отправка остановлена."
    if set(selected) != {r["id"] for r in rows} or state["merging"] or (state["behind"] and not commit_only) or state["branch"] != mount.git_sync_branch:
        raise RuntimeError("Обновите список карточек перед отправкой.")
    head = state["head"]
    if rows:
        paths = sorted({p for row in rows for p in row["paths"]})
        if _git(cwd, "diff", "--cached", "--name-only", "--", *paths):
            raise RuntimeError("Файл карточек уже подготовлен к коммиту в Git. Завершите его отдельно.")
        with tempfile.TemporaryDirectory() as temp:
            env = {**os.environ, "GIT_INDEX_FILE": str(Path(temp) / "index"), "GIT_TERMINAL_PROMPT": "0"}
            def run(*args, data=None):
                res = subprocess.run(["git", "--literal-pathspecs", *args], cwd=cwd, env=env,
                                     input=data, capture_output=True, timeout=sync.GIT_COMMAND_TIMEOUT_SEC)
                if res.returncode:
                    raise RuntimeError("Не удалось подготовить выбранные карточки.")
                return res.stdout.decode().strip()
            run("read-tree", head)
            for path in paths:
                name = path.removeprefix(root + "/")
                base, local = [_load(mount, ref, name) for ref in (head, None)]
                if name == "project.md":
                    text = _project_text(base, local, [r["id"] for r in rows if path in r["paths"]])
                elif name == "research.json":
                    doc, src = _json(base), _json(local)
                    if not base and "version" in src:
                        doc["version"] = src["version"]
                    ids = {q for r in rows for q in r["questions"]}
                    new = _questions(src)
                    questions = []
                    for entry in doc.get("questions", []):
                        key = entry.get("id") if isinstance(entry, dict) else None
                        if key not in ids:
                            questions.append(entry)
                        elif key in new:
                            questions.append(new.pop(key))
                    questions.extend(v for k,v in new.items() if k in ids)
                    doc["questions"] = questions
                    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
                else:
                    raise RuntimeError("Изменение вне карточки.")
                blob = run("hash-object", "-w", "--stdin", data=text.encode())
                run("update-index", "--add", "--cacheinfo", "100644", blob, path)
            tree = run("write-tree")
            if snapshot(mount)["token"] != state["token"]:
                raise RuntimeError("Появились новые правки. Обновите список.")
            created = run("commit-tree", tree, "-p", head, "-m", "Карточки: " + ", ".join(r["title"] for r in rows))
            _git(cwd, "update-ref", "HEAD", created, head)
            _git(cwd, "update-ref", "refs/researchos/card-sync/" + mount.git_sync_branch, created)
            _git(cwd, "update-ref", "refs/researchos/card-sync/" + mount.git_sync_branch + "-base", state["remote"])
            _git(cwd, "reset", "-q", created, "--", *paths)
            head = created
    elif not state["ahead"]:
        return "Нет выбранных изменений карточек."
    if commit_only:
        return "Сохранён коммит."
    try:
        _git(cwd, "push", "origin", f"{head}:refs/heads/{mount.git_sync_branch}")
    except RuntimeError:
        return "Коммит сохранён. Отправка не удалась."
    return "Отправлено в Git: " + ", ".join(r["title"] for r in rows)
