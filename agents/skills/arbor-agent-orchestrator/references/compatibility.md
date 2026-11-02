# Codex And Claude Code Skill Compatibility

The suite is intentionally conservative:

- Every skill is a directory with a required `SKILL.md`.
- Frontmatter uses only `name` and `description`.
- Platform-specific metadata lives in `agents/openai.yaml`, not in
  frontmatter.
- Resources are one level below the skill directory: `references/` and
  `scripts/`.
- Instructions use progressive disclosure: the orchestrator loads phase
  skills only when needed.

When porting to Claude Code, the same `SKILL.md` bodies remain valid. If a
Claude-specific field such as `allowed-tools` or `context: fork` is desired,
add it only in a platform-specific copy or adapter, not in the shared
frontmatter.
