---
name: spawn-review-sessions
description: Start one background Claude Code session for each comment in a saved review-comments file. Use this skill after save-review-comments, to work through review comments in parallel.
disable-model-invocation: true
---

# spawn-review-sessions

Thin wrapper over `scripts/spawn_review_sessions.py`. For each comment block in a
review comments MD file, it seeds a headless Claude Code session and resumes it
under Remote Control inside a backgrounded tmux session, so the operator can
steer each one from claude.ai/code or the mobile app and end it with `/exit`.
Seeds run in parallel and each session's RC is raised the moment its own seed
finishes (pipelined, no barrier), so the first ready session can be read while
slower seeds are still running.

The input file is the output of the sibling `save-review-comments` skill.

## Path Conventions

Paths in this document use `<SKILL_DIR>` to mean this skill's installation directory —
for example `.claude/skills/spawn-review-sessions` in Claude Code, or
`.codex/skills/spawn-review-sessions` in Codex CLI. Whenever you see `<SKILL_DIR>` in a
Bash invocation, substitute the actual installation path resolved from the harness. Do
not synthesize an absolute path from your own filesystem assumptions.

`<PROJECT_DIR>` means the directory the RC sessions start in: `--project-dir` when
given, otherwise the git root of the current working directory.

## Usage

Run the script directly:

```bash
python3 <SKILL_DIR>/scripts/spawn_review_sessions.py \
  <path/to/comments.md> [--type code-review|plan-review] [--dry-run]
```

- Review type is auto-detected from the MD file's `meta:` blocks
  (`implementation-plan-source-file` → plan-review, `github-pr-id` → code-review);
  override with `--type`.
- Session display names (shown in the RC UI) are derived from `meta:`:
  `PR#<id> - <slug>` for code review, `<plan-file-stem> - <slug>` for plan
  review, falling back to `review-<slug>`. The tmux handle mirrors this:
  `review-PR<id>-<slug>` / `review-plan-<ACRONYM>-<slug>` (acronym = first
  letters of the plan-file stem's words), falling back to `review-<slug>`.
- Artifacts (`seed-<slug>.jsonl/.err`, `mapping.tsv`) are written to a
  `sessions/` dir next to the MD file. The slug→UUID mapping makes reruns
  idempotent: live tmux sessions are skipped, previously-seeded slugs resume
  without re-seeding.
- Each seed prompt also tells the session where its own decision report belongs later:
  `decisions/<slug>.md`, next to `sessions/` (both under the MD file's directory, so a
  decision report inherits the same run's timestamp instead of a separately-invented
  one). The prompt says not to write it yet — that happens on a separate, later request
  within the same session, once a decision has actually been reached.
- Phase 1 seeds run with `--output-format stream-json`, so
  `seed-<slug>.jsonl` fills with events as the model works. The terminal
  `result` event carries the success/error verdict.
- While seeding, the script prints a heartbeat every
  `progress_interval_seconds` (config; `0` disables): one line per seed with a
  `*` per 5 stream lines, or `done`/`FAIL` once finished — so a long-running
  seed never looks hung. For finer detail,
  `tail -f sessions/seed-<slug>.jsonl | jq -rc .type`.

## Configuration

`<SKILL_DIR>/config.json` holds the shipped defaults: binary paths, model, effort,
permission mode, concurrency, budget, timeout, heartbeat interval, verdict language,
project context, and the template paths. `--concurrency`, `--max-budget-usd` and
`--timeout` override their config fields for a single run.

`claude_path` and `tmux_path` ship **empty**, which means "find it on `PATH`". Set them
only to pin a specific binary; a set-but-missing path is a fatal error.

Nothing in the shipped defaults is project-specific, so a project never has to fork
this skill. Both the config and the templates are overridable per project. The script
looks for override roots under `<PROJECT_DIR>`, in this order:

1. `.claude/spawn-review-sessions/`
2. `.codex/spawn-review-sessions/`

A `config.json` in the first root that has one is shallow-merged over the shipped
config (the `templates` object merges key-wise, so one template can be replaced without
restating the other). Templates are looked up by their config-relative path in each root
before falling back to `<SKILL_DIR>`, so
`<PROJECT_DIR>/.claude/spawn-review-sessions/templates/code-review.md` replaces the
shipped code-review prompt.

Two config fields exist purely so the prompt need not be forked:

| Field              | Default     | Effect                                                                                   |
| :----------------- | :---------- | :--------------------------------------------------------------------------------------- |
| `verdict_language` | `"English"` | Fills `<verdict-language>`. Free-form, not an enum: `"Russian, but keep identifiers in English"` is valid. |
| `project_context`  | `""`        | Fills `<project-context>`. One or two lines of stack/layout context. When empty, the placeholder's whole line is removed. |

## Prompt templates

`templates/code-review.md` and `templates/plan-review.md` are the seed prompts. They are
written in English and carry these placeholders: `<comment-statement>` (the comment
body), `<implementation-plan-file-path>` (plan review only), `<verdict-language>`,
`<project-context>`, `<slug>` (this comment's slug), `<review-comments-file-path>` (the
saved-comments MD file this slug came from), and `<decision-file-path>` (where the
eventual decision report belongs — see the `decisions/<slug>.md` bullet under Usage).

Beyond the verdict itself, the shipped prompts ask for an explanation aimed at a reader
who does not know the codebase or its language, and constrain it two ways at once: leave
nothing implied (name referents, spell out every step, define terms at first use, prefer
the precise term with a plain-words gloss over a vague paraphrase), and stay short by
cutting process narration, rejected alternatives and closing restatements rather than by
compressing the reasoning. Keep both halves if you override a template — brevity alone
produces elision, and anti-elision alone produces a wall of text.

## Preconditions

Handled beforehand, not by the script: claude.ai OAuth login, workspace trust, Claude
Code v2.1.51+. If OAuth lapses, attach to the tmux session
(`tmux attach -t review-<slug>`) and run `/login` by hand.

The `claude` CLI and `tmux` must be installed regardless of which harness invokes this
skill — the sessions it raises are Claude Code sessions.
