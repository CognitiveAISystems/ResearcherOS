import json

from koi.adapters import agent_backends


def test_cli_models_parse_each_cli(monkeypatch) -> None:
    outputs = {
        "debug": json.dumps({"models": [{"slug": "gpt-6.1-sol", "display_name": "GPT-6.1-Sol"},
                                        {"slug": "hidden", "visibility": "hide"}]}),
        "models": "",
    }
    monkeypatch.setattr(agent_backends, "_MODEL_CACHE", {})
    monkeypatch.setattr(agent_backends, "_codex_bin", lambda: "codex")
    monkeypatch.setattr(agent_backends, "_opencode_bin", lambda: "opencode")
    monkeypatch.setattr(agent_backends, "_cursor_cli_bin", lambda: "agent")

    def fake(cmd):
        if cmd[0] == "agent":
            return "Available models\n\nauto - Auto (current, default)\ngpt-5.2 - GPT-5.2\n"
        if cmd[0] == "opencode":
            return "opencode/big-pickle\nnoise line\n"
        return outputs[cmd[1]]

    monkeypatch.setattr(agent_backends, "_list_command", fake)
    assert agent_backends.cli_models("codex") == [{"id": "gpt-6.1-sol", "label": "GPT-6.1-Sol"}]
    assert agent_backends.cli_models("cursor") == [{"id": "auto", "label": "Auto"}, {"id": "gpt-5.2", "label": "GPT-5.2"}]
    assert agent_backends.cli_models("opencode") == [{"id": "opencode/big-pickle", "label": "opencode/big-pickle"}]


def test_run_agent_passes_model_to_chosen_backend(monkeypatch) -> None:
    seen = {}

    def runner(prompt, **kwargs):
        seen.update(kwargs)
        return "ok"

    monkeypatch.setitem(agent_backends._RUNNERS, "opencode", runner)
    assert agent_backends.run_agent("hi", backend="opencode", model="opencode/big-pickle") == ("ok", "opencode")
    assert seen["model"] == "opencode/big-pickle"
    seen.clear()
    agent_backends.run_agent("hi", backend="opencode")
    assert "model" not in seen
