# spawn-review-sessions

Turns a saved review comments file into one live session per comment: for every comment
block it seeds a headless Claude Code session, then resumes that same session under
Remote Control inside a backgrounded tmux session, so each comment can be discussed
and adjudicated on its own from claude.ai/code or the mobile app.

It consumes the output of the sibling `save-review-comments` skill and works for both
review types it produces (code review and implementation-plan review), detecting which
one from the file's `meta:` blocks.

Seeding and RC startup are pipelined rather than batched, so the first ready session can
be read while slower seeds are still running. Reruns are idempotent: a live session is
skipped and an already-seeded comment is resumed under its stored UUID instead of being
seeded again.

## Notes

The skill is project-agnostic and the shipped defaults never need forking. `claude` and
`tmux` are found on `PATH` unless the config pins them, and both the config and the
prompt templates are overridable per project from
`<project>/.claude/spawn-review-sessions/` (or `.codex/…`). Two config fields —
`verdict_language` and `project_context` — cover the usual reasons to edit a prompt, so
the templates themselves stay generic.

The seed prompts ask for a verdict plus an explanation for a reader who knows neither the
codebase nor its language, held to two constraints at once: leave nothing implied, and
stay short by cutting process narration rather than reasoning.

The sessions it raises are Claude Code sessions, so the `claude` CLI and `tmux` are
required no matter which harness invokes the skill. It is explicit-invocation only.
