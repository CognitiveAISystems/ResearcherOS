from __future__ import annotations

from fastapi import APIRouter

from koi.projects.views import allowed_children
from koi.core.models import NodeType

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "storage": "markdown"}


@router.get("/meta/node-types")
def node_types_meta() -> dict:
    return {
        "types": [t.value for t in NodeType],
        "labels": {
            NodeType.TOPIC.value: "Тема",
            NodeType.DIRECTION.value: "Направление",
            NodeType.PROGRAM.value: "Инженерное решение",
            NodeType.PROBLEM.value: "Проблема",
            NodeType.CAUSE.value: "Причина",
            NodeType.CAUSE_EVIDENCE.value: "Доказательство причины",
            NodeType.REMEDIATION.value: "Гипотеза устранения",
            NodeType.METHOD.value: "Метод",
            NodeType.EXPERIMENT.value: "Эксперимент",
        },
        "kanban_owners": ["method"],
        "allowed_children": {
            "topic": allowed_children("topic"),
            "direction": allowed_children("direction"),
            "program": allowed_children("program"),
            "problem": allowed_children("problem"),
            "cause": allowed_children("cause"),
            "cause_evidence": allowed_children("cause_evidence"),
            "remediation": allowed_children("remediation"),
            "method": allowed_children("method"),
            "experiment": allowed_children("experiment"),
            None: allowed_children(None),
        },
    }
