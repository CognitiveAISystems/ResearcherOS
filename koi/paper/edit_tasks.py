"""Durable paper-edit tasks: snapshot -> ordinary files -> review proposal."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import tempfile
import uuid
from pathlib import Path

from koi.adapters.workspace import RUN_DIR
from koi.paper.collaboration.ids import room_id
from koi.paper.collaboration.materializer import atomic_write_text
from koi.paper.collaboration.revisions import content_hash, utc_now
from koi.paper.collaboration.session import get_or_create_session

TASK_ROOT = RUN_DIR / "paper-edits"
ENGINE_ROOT = Path(__file__).resolve().parents[2]
_lock = threading.RLock()
_running: set[str] = set()
_TIMEOUT = 1800
_ACTIVE = {"draft", "running", "waiting"}


def _root(project_id: str, slug: str) -> Path:
    return TASK_ROOT / room_id(project_id, slug, "main.tex")


def _path(project_id: str, slug: str, task_id: str) -> Path:
    if not re.fullmatch(r"edit-[0-9a-f]{16}", task_id):
        raise ValueError("Некорректный идентификатор задачи")
    return _root(project_id, slug) / task_id


def _save(task: dict) -> None:
    atomic_write_text(_path(task["project_id"], task["slug"], task["id"]) / "task.json",
                      json.dumps(task, ensure_ascii=False, indent=2) + "\n")


def get(project_id: str, slug: str, task_id: str) -> dict:
    with _lock:
        path = _path(project_id, slug, task_id) / "task.json"
        if not path.is_file():
            raise KeyError("Задача не найдена")
        task = json.loads(path.read_text())
        if task["status"] == "running" and task_id not in _running:
            task.update(status="interrupted", error="Запуск прерван. Копия сохранена; её можно отправить на проверку.")
            _save(task)
        if task["status"] == "review":
            session = get_or_create_session(project_id, slug, Path(task["source"]) / "main.tex")
            proposal = session.proposal
            if proposal is None or proposal.task_id != task_id:
                task.update(status="resolved", finished_at=utc_now())
                _save(task)
            else:
                task["conflict"] = proposal.conflict
        return task


def list_tasks(project_id: str, slug: str) -> list[dict]:
    with _lock:
        tasks = [get(project_id, slug, p.parent.name) for p in _root(project_id, slug).glob("*/task.json")]
    return sorted(tasks, key=lambda task: task["created_at"], reverse=True)


def _copy_paper(source: Path, target: Path) -> None:
    """Copy real files, never links back into the accepted article or outside it."""
    def ignore(directory, names):
        return [name for name in names if name.startswith('.') or (Path(directory) / name).is_symlink()]
    if (source / "main.tex").is_symlink():
        raise ValueError("main.tex должен быть обычным файлом")
    shutil.copytree(source, target, ignore=ignore)


def _support_files(work: Path) -> dict:
    import hashlib
    return {str(p.relative_to(work)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in work.rglob("*") if p.is_file() and not p.is_symlink()
            and p.relative_to(work).as_posix() != "main.tex" and p.suffix in {".tex", ".bib", ".sty", ".cls", ".bst"}}


def begin(project_id: str, slug: str, slot: Path, prompt: str, *, comment_id: str | None = None) -> dict:
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("Опишите правку статьи")
    with _lock:
        session = get_or_create_session(project_id, slug, slot / "main.tex")
        if session.proposal is not None or any(t["status"] in _ACTIVE for t in list_tasks(project_id, slug)):
            raise RuntimeError("Сначала завершите текущую задачу и рассмотрите её предложение")
        base = session.snapshot_event()["text"]
        if not base.strip():
            raise ValueError("Статья пуста")
        task_id = "edit-" + uuid.uuid4().hex[:16]
        directory = _path(project_id, slug, task_id)
        directory.mkdir(parents=True)
        try:
            _copy_paper(slot, directory / "work")
            (directory / "base.tex").write_text(base, encoding="utf-8")
            (directory / "work/main.tex").write_text(base, encoding="utf-8")
            task = dict(id=task_id, project_id=project_id, slug=slug, title=prompt[:120],
                        prompt=prompt, status="draft", created_at=utc_now(), error=None,
                        comment_id=comment_id, workspace=str(directory / "work"),
                        source=str(slot.resolve()), base_hash=content_hash(base),
                        support_files=_support_files(directory / "work"))
            _save(task)
        except Exception:
            shutil.rmtree(directory)
            raise
        return task


def submit(project_id: str, slug: str, task_id: str) -> dict:
    with _lock:
        task = get(project_id, slug, task_id)
        if task["status"] in {"review", "resolved", "unchanged", "cancelled"}:
            return task
        if task["status"] == "running":
            raise RuntimeError("Дождитесь завершения агента")
        directory = _path(project_id, slug, task_id)
        tex = directory / "work/main.tex"
        if tex.parent.is_symlink() or tex.is_symlink() or not tex.is_file():
            raise ValueError("Рабочий main.tex отсутствует или заменён ссылкой")
        if _support_files(directory / "work") != task.get("support_files", {}):
            raise ValueError("Изменены файлы кроме main.tex. Копия сохранена; перенесите текстовые правки в main.tex перед отправкой.")
        candidate = tex.read_text(encoding="utf-8")
        if not candidate.strip():
            raise ValueError("Агент оставил пустую статью; копия сохранена")
        base = (directory / "base.tex").read_text(encoding="utf-8")
        session = get_or_create_session(project_id, slug, Path(task["source"]) / "main.tex")
        try:
            event = session.submit_agent_draft(base=base, candidate=candidate,
                                              task_id=task_id, title=task["title"])
        except RuntimeError as exc:
            task.update(status="waiting", error=str(exc))
            _save(task)
            return task
        proposal = event["proposal"]
        task.update(status="review" if proposal else "unchanged", error=None,
                    proposal_id=proposal["id"] if proposal else None,
                    conflict=bool(proposal and proposal["conflict"]), finished_at=utc_now())
        _save(task)
        return task


def cancel(project_id: str, slug: str, task_id: str) -> dict:
    with _lock:
        task = get(project_id, slug, task_id)
        if task["status"] in {"running", "review"}:
            raise RuntimeError("Дождитесь агента или отклоните предложение в редакторе")
        task.update(status="cancelled", finished_at=utc_now())
        _save(task)
        return task


def sandbox_command(command: list[str], source: Path, directory: Path) -> list[str]:
    """Protect accepted paper and task metadata for the whole subprocess tree."""
    source, directory = source.resolve(), directory.resolve()
    work = directory / "work"
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        quote = lambda p: json.dumps(str(p), ensure_ascii=False)
        profile = (
            '(version 1)(allow default)'
            f'(deny file-write* (subpath {quote(source)}))'
            f'(deny file-write* (require-all (subpath {quote(directory)}) '
            f'(require-not (subpath {quote(work)}))))'
        )
        return ["sandbox-exec", "-p", profile, *command]
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        temp = str(Path(tempfile.gettempdir()).resolve())
        args = ["bwrap", "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                "--bind", temp, temp]
        for name in (".codex", ".cursor", ".claude", ".cache"):
            path = Path.home() / name
            if path.is_dir() and not source.is_relative_to(path.resolve()):
                args += ["--bind", str(path), str(path)]
        return [*args, "--ro-bind", str(source), str(source),
                "--ro-bind", str(directory), str(directory), "--bind", str(work), str(work),
                "--chdir", str(work), "--", *command]
    raise RuntimeError("Защищённый запуск недоступен: нужен sandbox-exec (macOS) или bubblewrap (Linux)")


def _run(task: dict, backend: str | None) -> dict:
    directory = _path(task["project_id"], task["slug"], task["id"])
    worker = [sys.executable, "--paper-edit-worker"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "koi.paper.edit_worker"]
    command = sandbox_command(worker, Path(task["source"]), directory)
    env = dict(os.environ, PYTHONPATH=str(ENGINE_ROOT))
    prompt = (
        "Работай с локальным main.tex в текущем каталоге — это рабочая копия статьи. "
        "Редактируй текст обычными файловыми инструментами. Остальные файлы доступны для контекста "
        "и сборки LaTeX; в этой задаче предлагай изменения только main.tex. "
        "Не ищи и не меняй оригинал, не вызывай API ResearcherOS. "
        "После завершения кратко опиши результат. Правки рассмотрит человек.\n\n" + task["prompt"]
    )
    process = subprocess.Popen(command, cwd=task["workspace"], env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               start_new_session=True)
    try:
        out, err = process.communicate(json.dumps(dict(prompt=prompt, id=task["id"],
                                                       timeout=_TIMEOUT, backend=backend)), timeout=_TIMEOUT + 10)
        if process.returncode:
            raise RuntimeError("Агент завершился с ошибкой; рабочая копия сохранена. " + err[-1200:])
        return json.loads(out)
    finally:
        # Also stop descendants left behind by a timed-out agent/tool.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _work(project_id: str, slug: str, task_id: str, backend: str | None) -> None:
    try:
        task = get(project_id, slug, task_id)
        result = _run(task, backend)
        with _lock:
            task.update(status="draft", answer=result.get("answer", ""), backend=result.get("backend"))
            _save(task)
        task = submit(project_id, slug, task_id)
        if task.get("comment_id"):
            from koi.paper.comments import add_reply
            try:
                add_reply(Path(task["source"]), task["comment_id"], body=task.get("answer") or "Правка готова к проверке", author="Агент")
            except KeyError:
                pass  # The reviewer may delete a comment while its task is running.
    except Exception as exc:
        with _lock:
            task = get(project_id, slug, task_id)
            task.update(status="error", error=str(exc) or type(exc).__name__)
            _save(task)
    finally:
        with _lock:
            _running.discard(task_id)


def launch(project_id: str, slug: str, slot: Path, prompt: str, *, backend: str | None = None,
           comment_id: str | None = None) -> dict:
    if backend not in (None, "cursor", "codex", "claude"):
        raise ValueError("Неизвестный агент")
    with _lock:
        task = begin(project_id, slug, slot, prompt, comment_id=comment_id)
        try:
            sandbox_command([], slot, _path(project_id, slug, task["id"]))
        except RuntimeError as exc:
            task.update(status="error", error=str(exc)); _save(task)
            raise
        _running.add(task["id"])
        task["status"] = "running"
        _save(task)
        threading.Thread(target=_work, args=(project_id, slug, task["id"], backend),
                         daemon=True, name=f"paper-{task['id']}").start()
        return task
