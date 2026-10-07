"""In-process collaborative room: peers, debounce materialize, FS watch."""

from __future__ import annotations

import base64
import difflib
import json
import secrets
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from koi.paper.collaboration.document import CollabDocument
from koi.paper.collaboration.fs_bridge import FilesystemBridge
from koi.paper.collaboration.ids import document_id, room_id, session_key
from koi.paper.collaboration.materializer import atomic_write_text
from koi.paper.collaboration.revisions import content_hash, utc_now
from koi.paper.collaboration.text_ops import (
    MergeResult,
    TextSpan,
    clamp_span,
    prefix_suffix_span,
    shift_span,
)

MATERIALIZE_DEBOUNCE_S = 0.75
WATCH_INTERVAL_S = 0.4
IDLE_TTL_S = 15 * 60

EventHandler = Callable[[dict[str, Any]], None]


@dataclass
class CollabConflict:
    id: str
    reason: str
    source: str
    base_revision: int | None
    task_id: str | None = None
    current_hash: str = ""
    incoming_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "reason": self.reason,
            "source": self.source,
            "base_revision": self.base_revision,
            "task_id": self.task_id,
            "current_hash": self.current_hash,
            "incoming_hash": self.incoming_hash,
        }


@dataclass
class PaperProposal:
    id: str
    document_id: str
    source: str
    current: str
    candidate: str
    base: str = ""
    base_revision: int | None = None
    task_id: str | None = None
    created_at: str = field(default_factory=utc_now)

    def hunks(self) -> list[dict[str, Any]]:
        current_lines = self.current.splitlines(keepends=True)
        candidate_lines = self.candidate.splitlines(keepends=True)
        matcher = difflib.SequenceMatcher(None, current_lines, candidate_lines)
        hunks: list[dict[str, Any]] = []
        for group in matcher.get_grouped_opcodes(n=1):
            changes = [opcode for opcode in group if opcode[0] != "equal"]
            if not changes:
                continue
            old_start = changes[0][1]
            old_end = changes[-1][2]
            new_start = changes[0][3]
            new_end = changes[-1][4]
            old_text = "".join(current_lines[old_start:old_end])
            new_text = "".join(candidate_lines[new_start:new_end])
            identity = content_hash(
                f"{old_start}:{old_end}:{new_start}:{new_end}\0{old_text}\0{new_text}"
            )[:12]
            display = "".join(f"-{line}" for line in current_lines[old_start:old_end])
            display += "".join(f"+{line}" for line in candidate_lines[new_start:new_end])
            hunks.append(
                {
                    "id": identity,
                    "line_start": max(1, old_start + 1),
                    "line_end": max(1, old_end),
                    "old_start": old_start,
                    "old_end": old_end,
                    "new_start": new_start,
                    "new_end": new_end,
                    "old_text": old_text,
                    "new_text": new_text,
                    "diff": display,
                }
            )
        if len(hunks) > 1:
            deleted = {
                line
                for hunk in hunks
                for line in hunk["old_text"].splitlines()
                if line
            }
            inserted = {
                line
                for hunk in hunks
                for line in hunk["new_text"].splitlines()
                if line
            }
            changed = deleted | inserted
            current_counts = Counter(line.rstrip("\r\n") for line in current_lines)
            candidate_counts = Counter(line.rstrip("\r\n") for line in candidate_lines)
            repeated = any(
                current_counts[line] > 1 or candidate_counts[line] > 1
                for line in changed
            )
            if deleted & inserted or repeated:
                old_start = min(hunk["old_start"] for hunk in hunks)
                old_end = max(hunk["old_end"] for hunk in hunks)
                new_start = min(hunk["new_start"] for hunk in hunks)
                new_end = max(hunk["new_end"] for hunk in hunks)
                old_text = "".join(current_lines[old_start:old_end])
                new_text = "".join(candidate_lines[new_start:new_end])
                identity = content_hash(
                    f"{old_start}:{old_end}:{new_start}:{new_end}\0{old_text}\0{new_text}"
                )[:12]
                hunks = [
                    {
                        "id": identity,
                        "line_start": max(1, old_start + 1),
                        "line_end": max(1, old_end),
                        "old_start": old_start,
                        "old_end": old_end,
                        "new_start": new_start,
                        "new_end": new_end,
                        "old_text": old_text,
                        "new_text": new_text,
                        "diff": "".join(f"-{line}" for line in current_lines[old_start:old_end])
                        + "".join(f"+{line}" for line in candidate_lines[new_start:new_end]),
                    }
                ]
        return hunks

    def segments(self) -> list[dict[str, str]]:
        current_lines = self.current.splitlines(keepends=True)
        candidate_lines = self.candidate.splitlines(keepends=True)
        matcher = difflib.SequenceMatcher(None, current_lines, candidate_lines)
        segments: list[dict[str, str]] = []
        for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
            if tag in {"equal", "delete", "replace"}:
                old_text = "".join(current_lines[old_start:old_end])
                if old_text:
                    segments.append(
                        {
                            "kind": "equal" if tag == "equal" else "delete",
                            "text": old_text,
                        }
                    )
            if tag in {"insert", "replace"}:
                new_text = "".join(candidate_lines[new_start:new_end])
                if new_text:
                    segments.append({"kind": "insert", "text": new_text})
        return segments

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        diff = "".join(
            difflib.unified_diff(
                self.current.splitlines(keepends=True),
                self.candidate.splitlines(keepends=True),
                fromfile="live/main.tex",
                tofile="proposal/main.tex",
            )
        )
        payload: dict[str, Any] = {
            "id": self.id,
            "document_id": self.document_id,
            "source": self.source,
            "base_revision": self.base_revision,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "current_hash": content_hash(self.current),
            "candidate_hash": content_hash(self.candidate),
            "diff": diff,
            "hunks": self.hunks(),
            "segments": self.segments(),
        }
        if include_content:
            payload.update(
                {
                    "base": self.base,
                    "current": self.current,
                    "candidate": self.candidate,
                }
            )
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperProposal | None:
        try:
            return cls(
                id=str(data["id"]),
                document_id=str(data["document_id"]),
                source=str(data.get("source") or "external"),
                current=str(data["current"]),
                candidate=str(data["candidate"]),
                base=str(data.get("base") or ""),
                base_revision=data.get("base_revision"),
                task_id=data.get("task_id"),
                created_at=str(data.get("created_at") or utc_now()),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class AgentTask:
    task_id: str
    base_revision: int
    base_hash: str
    created_at: float = field(default_factory=time.time)


@dataclass
class Peer:
    peer_id: str
    user_name: str = "anonymous"
    actor_type: str = "human"
    handler: EventHandler | None = None
    presence: dict[str, Any] = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)
    last_submitted: str | None = None


class CollabSession:
    def __init__(
        self,
        project_id: str,
        slug: str,
        tex_path: Path,
        *,
        repository_id: str | None = None,
        watch: bool = True,
        debounce_s: float = MATERIALIZE_DEBOUNCE_S,
        proposal_root: Path | None = None,
    ) -> None:
        self.project_id = project_id
        self.slug = slug
        self.tex_path = Path(tex_path)
        self.repository_id = repository_id or project_id
        self.document_id = document_id(self.repository_id, slug, "main.tex")
        self.room_id = room_id(self.repository_id, slug, "main.tex")
        from koi.adapters.workspace import RUN_DIR

        self.proposal_root = Path(proposal_root) if proposal_root else RUN_DIR / "collab-proposals"
        self.proposal_path = self.proposal_root / f"{self.room_id}.json"
        self.proposal = self._load_proposal()
        initial = ""
        if self.tex_path.is_file():
            initial = self.tex_path.read_text(encoding="utf-8")
        if self.proposal is not None:
            if content_hash(initial) == content_hash(self.proposal.candidate):
                initial = self.proposal.current
            elif initial != self.proposal.current:
                self.proposal.current = initial
                self._save_proposal()
        self.document = CollabDocument(initial, document_id=self.document_id)
        self.crdt_epoch = f"epoch-{secrets.token_hex(8)}"
        self.bridge = FilesystemBridge(self.document, self.tex_path)
        if self.tex_path.is_file():
            try:
                stat = self.tex_path.stat()
                self.bridge.last_mtime = stat.st_mtime
                self.bridge.last_mtime_ns = stat.st_mtime_ns
            except OSError:
                pass
        if self.proposal is not None:
            self.bridge.materialize()
        self.peers: dict[str, Peer] = {}
        self.agent_tasks: dict[str, AgentTask] = {}
        self.editor_commands: list[dict[str, Any]] = []
        self.conflict: CollabConflict | None = None
        self.op_log: list[tuple[int, TextSpan]] = []
        self.debounce_s = debounce_s
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self.closed = False
        self.last_activity = time.time()
        if watch:
            self._watch_thread = threading.Thread(
                target=self._watch_loop,
                name=f"collab-watch-{project_id}-{slug}",
                daemon=True,
            )
            self._watch_thread.start()

    def _load_proposal(self) -> PaperProposal | None:
        if not self.proposal_path.is_file():
            return None
        try:
            raw = json.loads(self.proposal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        proposal = PaperProposal.from_dict(raw) if isinstance(raw, dict) else None
        if proposal is None or proposal.document_id != self.document_id:
            return None
        return proposal

    def _save_proposal(self) -> None:
        if self.proposal is None:
            return
        atomic_write_text(
            self.proposal_path,
            json.dumps(self.proposal.to_dict(include_content=True), ensure_ascii=False, indent=2) + "\n",
        )

    def _delete_proposal(self) -> None:
        try:
            self.proposal_path.unlink()
        except FileNotFoundError:
            pass

    def proposal_event(self) -> dict[str, Any]:
        with self._lock:
            return {
                "type": "proposal",
                "proposal": self.proposal.to_dict() if self.proposal else None,
            }

    def latest_editor_command(self, after: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            if not self.editor_commands:
                return None
            command = self.editor_commands[-1]
            return None if command["id"] == after else dict(command)

    def queue_editor_sync(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            self._queue_editor_command(
                self.document.to_string(),
                force=force,
                save=True,
            )
            return dict(self.editor_commands[-1])

    def force_reload_from_disk(self) -> dict[str, Any]:
        """Replace the live CRDT with main.tex from disk and reset all peers.

        Used when a browser client has diverged/corrupted local Yjs state while
        the authoritative file on disk is still intact.
        """
        if not self.tex_path.is_file():
            raise FileNotFoundError(f"missing tex: {self.tex_path}")
        disk = self.tex_path.read_text(encoding="utf-8")
        with self._lock:
            if self.proposal is not None:
                raise ValueError("cannot reload from disk while a proposal is pending")
            self.document = CollabDocument(disk, document_id=self.document_id)
            self.crdt_epoch = f"epoch-{secrets.token_hex(8)}"
            self.bridge = FilesystemBridge(self.document, self.tex_path)
            try:
                stat = self.tex_path.stat()
                self.bridge.last_mtime = stat.st_mtime
                self.bridge.last_mtime_ns = stat.st_mtime_ns
            except OSError:
                pass
            self.op_log.clear()
            self.conflict = None
            self.last_activity = time.time()
            self._queue_editor_command(disk, force=True, save=True)
            event = {
                "type": "reset_sync",
                "update": base64.b64encode(self.document.get_update()).decode("ascii"),
                "revision": self.document.revision,
                "hash": self.document.content_hash(),
                "room_id": self.room_id,
                "crdt_epoch": self.crdt_epoch,
                "origin": "reload_from_disk",
                "tex_mtime": self.bridge.last_mtime,
            }
        self._broadcast(event)
        return event

    def _queue_editor_command(
        self,
        text: str,
        *,
        force: bool = True,
        save: bool = False,
    ) -> None:
        self.editor_commands.append(
            {
                "id": f"editor-{uuid.uuid4().hex[:10]}",
                "text": text,
                "force": force,
                "save": save,
            }
        )
        if len(self.editor_commands) > 20:
            self.editor_commands = self.editor_commands[-10:]

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": not self.closed,
                "project_id": self.project_id,
                "slug": self.slug,
                "document_id": self.document_id,
                "room_id": self.room_id,
                "crdt_epoch": self.crdt_epoch,
                "revision": self.document.revision,
                "content_hash": self.document.content_hash(),
                "peer_count": len(self.peers),
                "peers": [
                    {
                        "peer_id": peer.peer_id,
                        "user_name": peer.user_name,
                        "actor_type": peer.actor_type,
                        **peer.presence,
                    }
                    for peer in self.peers.values()
                ],
                "conflict": self.conflict.to_dict() if self.conflict else None,
                "proposal": self.proposal.to_dict() if self.proposal else None,
            }

    def snapshot_event(
        self,
        origin: str | None = None,
        applied: TextSpan | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            event = {
                "type": "state",
                "revision": self.document.revision,
                "text": self.document.to_string(),
                "hash": self.document.content_hash(),
                "room_id": self.room_id,
                "crdt_epoch": self.crdt_epoch,
            }
            if origin:
                event["origin"] = origin
            if applied is not None:
                event["applied"] = {
                    "start": applied.start,
                    "delete_len": applied.delete_len,
                    "new_text": applied.new_text,
                }
            return event

    def _reseed_from_disk_if_blank_locked(self) -> None:
        if self.document.to_string():
            return
        if not self.tex_path.is_file():
            return
        disk = self.tex_path.read_text(encoding="utf-8")
        if not disk:
            return
        self.document.replace_with(disk)

    def reseed_from_disk_if_blank(self) -> bool:
        with self._lock:
            before = self.document.to_string()
            self._reseed_from_disk_if_blank_locked()
            return bool(self.document.to_string()) and not before

    def sync_event(self) -> dict[str, Any]:
        with self._lock:
            self._reseed_from_disk_if_blank_locked()
            return {
                "type": "sync",
                "update": base64.b64encode(self.document.get_update()).decode("ascii"),
                "revision": self.document.revision,
                "hash": self.document.content_hash(),
                "room_id": self.room_id,
                "crdt_epoch": self.crdt_epoch,
            }

    def _update_event(self, update: bytes, origin: str | None = None) -> dict[str, Any]:
        event = {
            "type": "crdt_update",
            "update": base64.b64encode(update).decode("ascii"),
            "revision": self.document.revision,
            "hash": self.document.content_hash(),
            "room_id": self.room_id,
            "crdt_epoch": self.crdt_epoch,
        }
        if origin:
            event["origin"] = origin
        return event

    def adopt_remote_state(
        self,
        update: bytes,
        *,
        crdt_epoch: str,
        expected_hash: str = "",
        origin: str | None = None,
    ) -> dict[str, Any]:
        """Replace an independently seeded CRDT with the room authority's history.

        Two Yjs documents initialized separately from the same plain text do not
        share CRDT history; merging their full updates duplicates the seed text.
        A joining clean instance therefore adopts the authority's history once.
        """
        if not update or not crdt_epoch:
            raise ValueError("remote CRDT state and epoch are required")
        incoming = CollabDocument(document_id=self.document_id)
        incoming.apply_update(update)
        if expected_hash and incoming.content_hash() != expected_hash:
            raise ValueError("remote CRDT state hash does not match signaling metadata")
        with self._lock:
            if self.proposal is not None:
                raise ValueError("cannot adopt remote state while a proposal is pending")
            self.document = incoming
            self.crdt_epoch = crdt_epoch
            self.bridge = FilesystemBridge(self.document, self.tex_path)
            self.op_log.clear()
            self.conflict = None
            self.bridge.materialize()
            self._queue_editor_command(
                self.document.to_string(),
                force=True,
                save=True,
            )
            event = {
                "type": "reset_sync",
                "update": base64.b64encode(self.document.get_update()).decode("ascii"),
                "revision": self.document.revision,
                "hash": self.document.content_hash(),
                "room_id": self.room_id,
                "crdt_epoch": self.crdt_epoch,
                "origin": origin or "",
                "tex_mtime": self.bridge.last_mtime,
            }
            self.last_activity = time.time()
        self._broadcast(event)
        return event

    def join(
        self,
        peer_id: str | None = None,
        *,
        user_name: str = "anonymous",
        actor_type: str = "human",
        handler: EventHandler | None = None,
    ) -> Peer:
        pid = peer_id or f"peer-{uuid.uuid4().hex[:8]}"
        with self._lock:
            peer = Peer(
                peer_id=pid,
                user_name=user_name,
                actor_type=actor_type,
                handler=handler,
            )
            self.peers[pid] = peer
            self.last_activity = time.time()
        self._broadcast({"type": "peer_joined", "peer_id": pid, "user_name": user_name}, exclude=pid)
        self._broadcast_presence()
        return peer

    def leave(self, peer_id: str) -> None:
        with self._lock:
            self.peers.pop(peer_id, None)
            self.last_activity = time.time()
        self._broadcast({"type": "peer_left", "peer_id": peer_id})
        self._broadcast_presence()

    def set_handler(self, peer_id: str, handler: EventHandler | None) -> None:
        with self._lock:
            peer = self.peers.get(peer_id)
            if peer is not None:
                peer.handler = handler

    def update_presence(self, peer_id: str, presence: dict[str, Any]) -> None:
        with self._lock:
            peer = self.peers.get(peer_id)
            if peer is None:
                return
            peer.presence = {
                key: presence[key]
                for key in ("cursor", "selection", "active_file")
                if key in presence
            }
            peer.last_seen = time.time()
        self._broadcast_presence()

    def apply_client_op(
        self,
        peer_id: str,
        start: int,
        delete_len: int,
        insert: str,
        base_revision: int | None,
        base_hash: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state_before = self.document.get_state()
            current = self.document.to_string()
            span = TextSpan(max(0, start), max(0, start) + max(0, delete_len), insert or "")
            hash_matches = bool(base_hash) and base_hash == content_hash(current)
            if not hash_matches and base_revision is not None:
                for rev, previous in self.op_log:
                    if rev > base_revision:
                        span = shift_span(span, previous)
            span = clamp_span(span, len(current))
            applied = span if (span.delete_len or span.new_text) else None
            if applied is not None:
                self.document.apply_edit(span.start, span.delete_len, span.new_text)
                self.op_log.append((self.document.revision, span))
                if len(self.op_log) > 500:
                    self.op_log = self.op_log[-250:]
            peer = self.peers.get(peer_id)
            if peer is not None:
                peer.last_submitted = self.document.to_string()
            self.last_activity = time.time()
            event = self.snapshot_event(origin=peer_id, applied=applied)
            crdt_event = self._update_event(self.document.get_update(state_before), origin=peer_id)
        self._schedule_materialize()
        self._broadcast(crdt_event)
        return event

    def apply_client_text(self, peer_id: str, text: str, base_revision: int | None) -> dict[str, Any]:
        with self._lock:
            current = self.document.to_string()
            if text == current:
                return self.snapshot_event(origin=peer_id)
            base = None
            if base_revision is not None:
                base = self.document.log.text_at(base_revision)
            if base is None:
                base = current
            span = prefix_suffix_span(base, text)
        return self.apply_client_op(peer_id, span.start, span.delete_len, span.new_text, base_revision)

    def apply_crdt_update(self, peer_id: str, update: bytes) -> dict[str, Any]:
        with self._lock:
            before = self.document.to_string()
            self.document.apply_update(update)
            changed = self.document.to_string() != before
            peer = self.peers.get(peer_id)
            if peer is not None:
                peer.last_submitted = self.document.to_string()
                peer.last_seen = time.time()
            if changed and self.proposal is None:
                self._queue_editor_command(
                    self.document.to_string(),
                    force=False,
                    save=True,
                )
            self.last_activity = time.time()
            event = self._update_event(update, origin=peer_id)
        if changed:
            self._schedule_materialize()
        self._broadcast(event, exclude=peer_id)
        return {
            "type": "ack",
            "revision": event["revision"],
            "hash": event["hash"],
        }

    def register_agent_task(self, task_id: str | None = None) -> AgentTask:
        tid = task_id or f"task-{uuid.uuid4().hex[:8]}"
        with self._lock:
            task = AgentTask(
                task_id=tid,
                base_revision=self.document.revision,
                base_hash=self.document.content_hash(),
            )
            self.agent_tasks[tid] = task
            return task

    def import_external(
        self,
        incoming: str,
        *,
        task_id: str | None = None,
        base_revision: int | None = None,
        source: str = "external",
    ) -> MergeResult:
        event: dict[str, Any] | None = None
        with self._lock:
            current = self.document.to_string()
            if content_hash(incoming) == content_hash(current):
                cleared = self.proposal is not None
                self.proposal = None
                self.conflict = None
                if task_id:
                    self.agent_tasks.pop(task_id, None)
                if cleared:
                    self._delete_proposal()
                self.bridge.last_hash = content_hash(current)
                self.bridge.last_revision = self.document.revision
                try:
                    stat = self.tex_path.stat()
                    self.bridge.last_mtime = stat.st_mtime
                    self.bridge.last_mtime_ns = stat.st_mtime_ns
                except OSError:
                    pass
                result = MergeResult(ok=True, text=current, changed=False)
                resolved = cleared
            elif (
                self.proposal is not None
                and content_hash(incoming) == content_hash(self.proposal.candidate)
                and self.proposal.current == current
            ):
                self.bridge.materialize()
                result = MergeResult(ok=True, text=current, changed=False)
                resolved = False
            else:
                base_text = None
                used_revision = base_revision
                if task_id and task_id in self.agent_tasks:
                    task = self.agent_tasks[task_id]
                    used_revision = task.base_revision
                    base_text = self.document.log.text_at(task.base_revision)
                elif base_revision is not None:
                    base_text = self.document.log.text_at(base_revision)
                if base_text is None:
                    base_text = self.document.log.text_at(self.bridge.last_revision)
                if base_text is None:
                    base_text = current
                self.proposal = PaperProposal(
                    id=f"proposal-{uuid.uuid4().hex[:10]}",
                    document_id=self.document_id,
                    source=source,
                    current=current,
                    candidate=incoming,
                    base=base_text,
                    base_revision=used_revision,
                    task_id=task_id,
                )
                self._save_proposal()
                if task_id:
                    self.agent_tasks.pop(task_id, None)
                self.conflict = None
                self.last_activity = time.time()
                self.bridge.materialize()
                result = MergeResult(ok=True, text=current, changed=False)
                event = self.proposal_event()
                resolved = False
        if resolved:
            self._broadcast({"type": "proposal_resolved", "proposal_id": None, "resolution": "withdrawn"})
        elif event is not None:
            self._broadcast(event)
        return result

    def accept_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self._lock:
            proposal = self.proposal
            if proposal is None or proposal.id != proposal_id:
                raise KeyError("proposal is no longer current")
            state_before = self.document.get_state()
            changed = self.document.replace_with(proposal.candidate)
            update = self.document.get_update(state_before)
            self.proposal = None
            if proposal.source == "cursor-buffer":
                self._queue_editor_command(self.document.to_string())
            self.conflict = None
            self._delete_proposal()
            materialized = self.bridge.materialize()
            self.last_activity = time.time()
            update_event = self._update_event(update, origin="proposal") if changed else None
            resolved = {
                "type": "proposal_resolved",
                "proposal_id": proposal_id,
                "resolution": "accepted",
                "revision": self.document.revision,
                "hash": self.document.content_hash(),
                "tex_mtime": self.bridge.last_mtime,
                "wrote": materialized.wrote,
            }
        if update_event is not None:
            self._broadcast(update_event)
        self._broadcast(resolved)
        return resolved

    def reject_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self._lock:
            proposal = self.proposal
            if proposal is None or proposal.id != proposal_id:
                raise KeyError("proposal is no longer current")
            self.proposal = None
            if proposal.source == "cursor-buffer":
                self._queue_editor_command(self.document.to_string())
            self.conflict = None
            self._delete_proposal()
            materialized = self.bridge.materialize()
            self.last_activity = time.time()
            resolved = {
                "type": "proposal_resolved",
                "proposal_id": proposal_id,
                "resolution": "rejected",
                "revision": self.document.revision,
                "hash": self.document.content_hash(),
                "tex_mtime": self.bridge.last_mtime,
                "wrote": materialized.wrote,
            }
        self._broadcast(resolved)
        return resolved

    def resolve_proposal_hunk(
        self,
        proposal_id: str,
        hunk_id: str,
        *,
        accept: bool,
    ) -> dict[str, Any]:
        with self._lock:
            proposal = self.proposal
            if proposal is None or proposal.id != proposal_id:
                raise KeyError("proposal is no longer current")
            if self.document.to_string() != proposal.current:
                raise KeyError("live document changed after proposal")
            hunk = next((item for item in proposal.hunks() if item["id"] == hunk_id), None)
            if hunk is None:
                raise KeyError("proposal hunk is no longer current")

            update_event: dict[str, Any] | None = None
            if accept:
                state_before = self.document.get_state()
                current_lines = proposal.current.splitlines(keepends=True)
                candidate_lines = proposal.candidate.splitlines(keepends=True)
                accepted_text = "".join(
                    current_lines[: hunk["old_start"]]
                    + candidate_lines[hunk["new_start"] : hunk["new_end"]]
                    + current_lines[hunk["old_end"] :]
                )
                self.document.replace_with(accepted_text)
                proposal.current = accepted_text
                update_event = self._update_event(
                    self.document.get_update(state_before),
                    origin="proposal",
                )
            else:
                current_lines = proposal.current.splitlines(keepends=True)
                candidate_lines = proposal.candidate.splitlines(keepends=True)
                proposal.candidate = "".join(
                    candidate_lines[: hunk["new_start"]]
                    + current_lines[hunk["old_start"] : hunk["old_end"]]
                    + candidate_lines[hunk["new_end"] :]
                )
                if proposal.source == "cursor-buffer":
                    self._queue_editor_command(proposal.candidate)

            resolved_all = proposal.current == proposal.candidate
            old_id = proposal.id
            if resolved_all:
                self.proposal = None
                self._delete_proposal()
                if proposal.source == "cursor-buffer":
                    self._queue_editor_command(self.document.to_string())
            else:
                proposal.id = f"proposal-{uuid.uuid4().hex[:10]}"
                self._save_proposal()
            should_materialize = proposal.source != "cursor-buffer" or resolved_all
            materialized = self.bridge.materialize() if should_materialize else None
            self.last_activity = time.time()
            response = {
                "type": "proposal_hunk_resolved",
                "proposal_id": old_id,
                "hunk_id": hunk_id,
                "resolution": "accepted" if accept else "rejected",
                "revision": self.document.revision,
                "hash": self.document.content_hash(),
                "wrote": materialized.wrote if materialized is not None else False,
                "proposal": self.proposal.to_dict() if self.proposal else None,
            }
            next_event = self.proposal_event() if self.proposal else {
                "type": "proposal_resolved",
                "proposal_id": old_id,
                "resolution": "completed",
            }
        if update_event is not None:
            self._broadcast(update_event)
        self._broadcast(response)
        self._broadcast(next_event)
        return response

    def flush(
        self,
        *,
        expected_hash: str | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            update_event: dict[str, Any] | None = None
            if text is not None:
                # Force the editor buffer onto the room before materializing.
                # Used when CRDT acks and client hash drift (P2P / race / reseeds).
                if text != self.document.to_string():
                    if self.proposal is not None:
                        return {
                            "type": "flush_rejected",
                            "revision": self.document.revision,
                            "hash": self.document.content_hash(),
                            "expected_hash": expected_hash or "",
                            "reason": "cannot force-save while a proposal is pending",
                        }
                    state_before = self.document.get_state()
                    self.document.replace_with(text)
                    update_event = self._update_event(
                        self.document.get_update(state_before),
                        origin="force_save",
                    )
                expected_hash = None
            current_hash = self.document.content_hash()
            if expected_hash and expected_hash != current_hash:
                return {
                    "type": "flush_rejected",
                    "revision": self.document.revision,
                    "hash": current_hash,
                    "expected_hash": expected_hash,
                    "reason": "collaborative document changed before it could be saved",
                }
            result = self.bridge.materialize()
            response = {
                "type": "materialized",
                "revision": result.revision,
                "hash": result.content_hash,
                "wrote": result.wrote,
                "tex_mtime": self.bridge.last_mtime,
            }
        if update_event is not None:
            self._broadcast(update_event)
            self._queue_editor_command(text or "", force=True, save=True)
        return response

    def close(self) -> None:
        self.closed = True
        self._watch_stop.set()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        try:
            self.flush()
        except OSError:
            pass

    def _schedule_materialize(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self.debounce_s, self._debounced_flush)
        self._timer.daemon = True
        self._timer.start()

    def _debounced_flush(self) -> None:
        if self.closed:
            return
        event = self.flush()
        self._broadcast(event)

    def _watch_loop(self) -> None:
        while not self._watch_stop.wait(WATCH_INTERVAL_S):
            if self.closed:
                return
            try:
                self._poll_file()
            except OSError:
                continue

    def _poll_file(self) -> None:
        if not self.tex_path.is_file():
            return
        try:
            stat = self.tex_path.stat()
        except OSError:
            return
        with self._lock:
            if (
                self.bridge.last_mtime_ns is not None
                and stat.st_mtime_ns == self.bridge.last_mtime_ns
            ):
                return
            incoming = self.tex_path.read_text(encoding="utf-8")
            if self.bridge.is_own_materialization(incoming):
                self.bridge.last_mtime = stat.st_mtime
                self.bridge.last_mtime_ns = stat.st_mtime_ns
                return
            matching = (
                max(self.agent_tasks.values(), key=lambda task: task.created_at)
                if self.agent_tasks
                else None
            )
        source = "agent" if matching else "external"
        self.import_external(
            incoming,
            task_id=matching.task_id if matching else None,
            source=source,
        )

    def broadcast_comments(
        self,
        comments: list[Any],
        deleted_ids: list[Any] | None = None,
        *,
        exclude: str | None = None,
    ) -> None:
        self._broadcast(
            {
                "type": "comments",
                "comments": comments if isinstance(comments, list) else [],
                "deleted_ids": list(deleted_ids or []),
            },
            exclude=exclude,
        )

    def _broadcast_presence(self) -> None:
        with self._lock:
            peers = [
                {
                    "peer_id": peer.peer_id,
                    "user_name": peer.user_name,
                    "actor_type": peer.actor_type,
                    **peer.presence,
                }
                for peer in self.peers.values()
            ]
        self._broadcast({"type": "presence", "peers": peers})

    def _broadcast(self, event: dict[str, Any], exclude: str | None = None) -> None:
        with self._lock:
            targets = [peer for peer in self.peers.values() if peer.peer_id != exclude and peer.handler]
        for peer in targets:
            try:
                peer.handler(event)
            except Exception:
                continue


_REGISTRY: dict[str, CollabSession] = {}
_REGISTRY_LOCK = threading.RLock()


def get_session(project_id: str, slug: str) -> CollabSession | None:
    with _REGISTRY_LOCK:
        return _REGISTRY.get(session_key(project_id, slug))


def get_session_by_tex_path(tex_path: Path) -> CollabSession | None:
    target = Path(tex_path).resolve()
    with _REGISTRY_LOCK:
        for session in _REGISTRY.values():
            if not session.closed and session.tex_path.resolve() == target:
                return session
    return None


def get_or_create_session(project_id: str, slug: str, tex_path: Path, **kwargs: Any) -> CollabSession:
    key = session_key(project_id, slug)
    with _REGISTRY_LOCK:
        session = _REGISTRY.get(key)
        if session is not None and not session.closed:
            return session
        session = CollabSession(project_id, slug, tex_path, **kwargs)
        _REGISTRY[key] = session
        return session


def drop_session(project_id: str, slug: str) -> None:
    key = session_key(project_id, slug)
    with _REGISTRY_LOCK:
        session = _REGISTRY.pop(key, None)
    if session is not None:
        session.close()


def live_text(project_id: str, slug: str) -> str | None:
    session = get_session(project_id, slug)
    if session is None or session.closed:
        return None
    session.reseed_from_disk_if_blank()
    text = session.document.to_string()
    if not text:
        return None
    return text


def register_agent_task(project_id: str, slug: str, tex_path: Path, task_id: str | None = None) -> AgentTask:
    session = get_or_create_session(project_id, slug, tex_path)
    return session.register_agent_task(task_id)


def shutdown_all_sessions() -> None:
    with _REGISTRY_LOCK:
        sessions = list(_REGISTRY.values())
        _REGISTRY.clear()
    for session in sessions:
        session.close()
