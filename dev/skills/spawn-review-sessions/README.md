# spawn-review-sessions

This skill starts one live session for each comment in a saved review-comments file. For
each comment, it starts a headless Claude Code session. Then it resumes that session
under Remote Control, inside a background tmux session. You can then discuss and judge
each comment on its own, from claude.ai/code or the mobile app.

The skill uses the output of the `save-review-comments` skill. It works with both review
types that skill produces: code review and implementation-plan review. It finds the
review type from the `meta:` blocks in the file.

The skill starts the sessions in a pipeline, not in a batch. You can read the first ready
session while slower sessions still start. A rerun is idempotent. If a session is already
live, the skill skips it. If a comment already has a session, the skill resumes that
session by its stored UUID, instead of starting a new one.

## Notes

The skill works with any project. You do not need to fork the default settings. The skill
finds `claude` and `tmux` on the `PATH`, unless the configuration file points to different
locations. You can override the configuration file and the prompt templates for one
project, under `<project>/.claude/spawn-review-sessions/` (or `.codex/…`). Two
configuration fields, `verdict_language` and `project_context`, cover the most common
reasons to change a prompt. The templates stay generic for other cases.

Each seed prompt asks for a verdict and an explanation. Write the explanation for a reader
who does not know the codebase or its programming language. Do not leave any fact
implied. Keep the explanation short by removing narration about the process, not by
removing reasoning.

The skill starts Claude Code sessions. Because of this, the `claude` CLI and `tmux` are
required, no matter which harness runs the skill. You must invoke this skill by name. It
does not start on its own.

## Example configuration

`<SKILL_DIR>/config.json` holds the shipped defaults:

```json
{
  "claude_path": "",
  "tmux_path": "",
  "model": "opus",
  "effort": "xhigh",
  "permission_mode": "auto",
  "seed_concurrency": 4,
  "seed_max_budget_usd": 0,
  "seed_timeout_seconds": 900,
  "progress_interval_seconds": 15,
  "verdict_language": "English",
  "project_context": "",
  "templates": {
    "code_review": "templates/code-review.md",
    "plan_review": "templates/plan-review.md"
  }
}
```

An empty `claude_path` or `tmux_path` means the skill finds that binary on the `PATH`. A
value of `0` in `seed_max_budget_usd` means no budget limit.

To override the defaults for one project, add a `config.json` under
`<project>/.claude/spawn-review-sessions/` (or `.codex/spawn-review-sessions/`). List
only the fields you want to change. For example:

```json
{
  "verdict_language": "Russian, but keep identifiers in English",
  "project_context": "This project is a Django monolith. Tests live under tests/."
}
```

The skill merges this file over the shipped defaults, one field at a time. A field you
do not list keeps its shipped value, such as `"model": "opus"` or `"seed_concurrency":
4`. The `templates` object merges the same way, so you can replace one template path
without restating the other.
