"""Literature findings in onboarding retain only fetched paper provenance."""

from pathlib import Path
import io

from koi.adapters import onboarding_literature


def test_literature_agent_keeps_fetched_sources(monkeypatch) -> None:
    monkeypatch.setattr(onboarding_literature, "_search_papers", lambda query: [
        {"title": "Grounded Paper", "year": 2024, "url": "https://arxiv.org/abs/2401.12345", "abstract": "A measured difficulty in spatial interaction."},
        {"title": "Bad URL", "year": 2024, "url": "https://example.com/unknown", "abstract": "Abstract"},
    ])
    calls = []

    def ask(prompt, repo):
        calls.append(prompt)
        if len(calls) == 1:
            return {"query": "spatial interaction difficulty"}
        return {"findings": [
            {"id": "0", "fact": "В работе изучена трудность пространственного взаимодействия.", "quote": "measured difficulty in spatial interaction", "relevance": "problem"},
            {"id": "1", "fact": "Несуществующий источник", "quote": "Abstract", "relevance": "cause"},
        ]}

    state = {"messages": [{"role": "user", "text": "Пространственный интерфейс неудобен"}], "nodes": [], "literature": []}
    findings = onboarding_literature.update_literature(state, "code", Path("/tmp/repo"), ask)
    assert len(findings) == 1
    assert findings[0]["url"] == "https://arxiv.org/abs/2401.12345"
    assert "Пространственный интерфейс" in calls[0]
    assert "Grounded Paper" in calls[1]


def test_literature_search_failure_preserves_previous(monkeypatch) -> None:
    monkeypatch.setattr(onboarding_literature, "_search_papers", lambda query: (_ for _ in ()).throw(OSError("offline")))
    previous = [{"title": "Earlier", "url": "https://arxiv.org/abs/2401.12345", "fact": "Earlier fact", "year": "2024", "relevance": "cause"}]
    state = {"messages": [], "nodes": [], "literature": previous}
    assert onboarding_literature.update_literature(state, "code", Path("/tmp/repo"), lambda prompt, repo: {"query": "spatial interaction"}) == previous


def test_semantic_scholar_search_uses_abstract_and_source(monkeypatch) -> None:
    payload = b'{"data":[{"paperId":"abc123","title":"Interaction Study","year":2025,"abstract":"A reported spatial interaction issue.","url":"https://www.semanticscholar.org/paper/abc123"}]}'
    monkeypatch.setattr(onboarding_literature.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(payload))
    papers = onboarding_literature._search_papers("spatial interaction")
    assert papers[0]["abstract"] == "A reported spatial interaction issue."
    assert papers[0]["url"] == "https://www.semanticscholar.org/paper/abc123"
