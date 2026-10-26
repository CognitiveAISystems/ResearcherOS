> ACP отложен и недоступен в тестовой версии. Используются Cursor, Codex и Claude CLI.
> Ниже сохранены заметки для будущего подключения; SDK не входит в зависимости релиза.

# ACP configuration and API

ResearcherOS uses the official `agent-client-protocol==0.12.1` Python SDK
and stable ACP v1. Install Python dependencies from `requirements.txt`.

## Agent installation

Plain Codex, Claude, and Cursor CLI commands are not ACP servers. Install
and authenticate an ACP-compatible adapter separately. The maintained Codex
adapter is https://github.com/agentclientprotocol/codex-acp.

For a source checkout:

```sh
npm install --prefix .tools/acp --no-audit --no-fund @agentclientprotocol/codex-acp@2.3.0
```

Discovery checks PATH and `<tools_dir>/acp/node_modules/.bin/` for `codex-acp`
and `claude-agent-acp`. Additional agents can be configured in the server's
private environment as a JSON mapping of names to executable argument arrays:

```sh
KOI_ACP_AGENTS='{"my-agent":["/absolute/path/to/agent","--acp"]}'
```

Do not put credentials in argument arrays or commit `.env` and `.tools/`.
Agents inherit the server environment and their existing login. Sending a
message never downloads an executable. The selector prefers an installed ACP
agent initially; ordinary CLI backends remain available. ACP failures are
reported in the same chat without retrying the task through another backend.

## HTTP API

- `GET /agent-conversations`: all chats, optionally filtered by `project_id`
  and paired `board_id` / `card_id`.
- `POST /agent-conversations`: create with `project_id`, optional paired
  `board_id` / `card_id`, `title`, and `backend`.
- `GET /agent-conversations/{id}`: metadata, messages, and optional live output
  with a pending permission request.
- `GET /agent-conversations/{id}/activity`: activity for that chat only.
- `POST /agent-chat`: existing request plus `conversation_id`. Project/card
  must match. Only one pending turn per chat; other chats can run independently.
- `POST /agent-conversations/{id}/permission`: `permission_id` and `option_id`
  from the active request. Unknown or expired choices return 409.
- `POST /agent-conversations/{id}/cancel`: cancel the active ACP turn and
  its permission requests; stop an uncooperative process after a grace period.

## State and lifecycle

Metadata and native session ids persist in `<run_dir>/agent-conversations.json`;
messages remain in `<run_dir>/agent-chat-queue.json`. Explicit conversations
are exempt from the old 50-message pruning rule. Legacy messages appear as
one chat per original project/card scope without rewriting their history.

Each turn starts an agent subprocess. If the same backend advertises session
loading, the saved native session is loaded; replayed output is excluded from
the current reply. Otherwise a new native session receives the saved chat
history in its context. The process closes after the turn; the chat persists.

The client does not advertise file or terminal capabilities: agents use their
own tools. Permission requests are shown for user choice and are never
implicitly approved by this client. ACP itself does not provide an OS sandbox;
configure the agent's sandbox and approval policy separately.

On application restart, unfinished explicit-chat turns are marked interrupted
instead of being automatically replayed. Continue with a new message. The
existing report-interview summary/review pipeline remains in use.

## Checks

```sh
.venv/bin/python -m pytest tests/test_chat_conversations.py tests/test_agent_chat.py tests/test_agent_chat_local.py -q
node --test tests/test_agent_chat_active_project.cjs
.venv/bin/python tests/test_chat_conversations_browser.py
```
