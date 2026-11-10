---
name: koi-create-project-skill
description: >-
  Create, install, update or attach a user's project skill through ResearcherOS
  chat. Use for requests such as «добавь скилл», «подключи навык», /add-skill,
  or a request to adapt a linked skill for card, method or tree work.
---

# Create a project skill

Use `project_skills_root`, `project_id`, `scope_method`, `card` and history from
the chat context. For a workspace chat, first select the intended research
project through the existing context-selection flow. Never install into the
ResearcherOS engine or a global IDE directory for this workflow.

## Establish the purpose and scope

Read existing project skills and `bindings.json`; extend an overlapping skill
instead of creating a duplicate. Establish what the skill should help with and
what a typical request looks like. Ask only for missing information.

Ask which WORK LEVEL the skill supports: card, method/kanban, or tree.
These are reusable capabilities, NOT bindings to particular object IDs:

- Card: visible from every card in this project; work only on the currently
  opened card's task, report and related artifacts. Do not create cards or
  change neighboring cards or tree nodes.
- Method/kanban: visible from every method's chat; may create or change cards
  in the current method's kanban. Do not change other methods or tree nodes.
- Tree: visible from the tree chat; may work with the current tree's nodes.

«В карточке» already identifies card-level work; it does not mean choosing one
specific card. Never ask which individual card or method to attach the skill to.
If a prior assistant incorrectly offered object-specific bindings, correct that
interpretation; do not present the assistant's assumption as the user's choice.
Use a level explicitly chosen by the user without asking again. If it is unclear,
ask one question explaining these three levels. The current screen can support
an explanation but does not itself select the level.

## Write or install

Create `project_skills_root/<name>/SKILL.md`. Use lowercase letters, digits and
hyphens, at most 64 characters. YAML frontmatter must contain `name` (matching
the folder) and a nonempty `description` explaining the task and trigger.
Use optional `display_name` for a short human-readable menu label.
Keep instructions concise and specific to decisions the agent needs to make.
Put templates, scripts and references beside SKILL.md only when needed; link
them from the instructions. Avoid placeholders and duplicated manuals.

For an external source, inspect its instructions and resources before adapting
them; do not execute downloaded scripts during installation. Preserve the
license, attribution and source revision in `UPSTREAM.md` when redistributing.
If the source cannot be read or licensed for reuse, report that limitation.
Never overwrite existing project instructions or resources without checking
the current files and the user's intended changes.

Use the supplied `project_skill_command` array as the command prefix and
`engine_root` as its working directory. Append the arguments below. In a bundled
app the prefix invokes `--project-skills`, not Python's `-m`:

```text
bind <project_id> --skill <name> --scope card
bind <project_id> --skill <name> --scope method
bind <project_id> --skill <name> --scope tree
```

Run only the command for the agreed scope. `bind` validates the skill and target
before saving, preserves other bindings, and is idempotent. Do not pass a
card ID or method ID. To offer a skill at multiple levels, bind each agreed level.
Use a unique command name; built-in commands cannot be replaced. To detach, use `unbind` with the same arguments;
the skill file remains available. `list <project_id>` shows all bindings.
Do not hand-edit `bindings.json`. A `.bindings-lock` directory means another
writer is active; retry after it finishes. If a crashed process left the lock,
verify no writer remains before removing that empty lock directory.

## Verify and report

Read the saved file and list the bindings. Check any referenced resources exist
inside the skill directory, and run new scripts on representative safe inputs.
Check the project skills menu endpoint for the chosen level and try a realistic
request. For a card-level skill, verify it is available from two different cards
and that both runs stay within their respective current card. Check that method
and tree menus show only their own levels. Do not claim behavioral testing if only structural
validation was possible. Report the saved path, selected scope and actual checks.

The runtime lists skills in the menu at their selected level and resolves the
current work boundary at invocation time. Opening a card does not run its skills.
Skills guide the requested task; they do not grant extra permissions or override a read-only
interview, research integrity rules or the user's instructions.

## Basis

This is a ResearcherOS adaptation of the design principles in OpenAI's public
[skill-creator](https://github.com/openai/skills/blob/main/skills/.system/skill-creator/SKILL.md),
reviewed on 2026-11-09: concise task-specific instructions, trigger metadata,
optional resources, and validation on realistic requests. It is independently
written and self-contained; no runtime dependency on a global Codex skill.
