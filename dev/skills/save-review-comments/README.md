# save-review-comments

Persists the surviving actionable comments of a review session into a machine-readable
Markdown file, so a later session (or a later skill) can consume the findings without the
original chat.

Each comment becomes a tagged block written by a bundled script that validates the whole
file after every append, and the original review wording is kept almost verbatim rather
than normalized into a new schema.

The skill is explicit-invocation only, and serves two review types:

| Review type                | Output                                                       |
| :------------------------- | :----------------------------------------------------------- |
| Implementation-plan review | `<plan-dir>/<plan-id>/comments/<timestamp>/comments.md`      |
| Code review                | `<repo-root>/.ai/pr-review/<pr-id>/comments/<timestamp>/comments.md` |

## Notes

The skill is project-agnostic. Plan-review output lands next to the plan file itself, so it
sits alongside the `scratchpads/` directory that the sibling `implementation-plan-review`
skill creates for the same plan, and the plan does not have to live under `.ai/impl_plans`.
A numeric PR id has no filesystem anchor of its own, so that branch resolves the project
root through git and works the same in a linked worktree.

The code-review branch is deliberately harness-agnostic too: code review itself is a
built-in capability of both Claude Code and Codex CLI, so this plugin ships no code-review
skill — only the persistence step for whatever such a review produced.
