---
name: save-review-comments
description: Save the actionable comments from an implementation-plan review or a code review into a markdown file. Use this skill after a review, so you can hand off or track the comments later.
disable-model-invocation: true
---

# Save Review Comments

Persist only the *surviving actionable* review comments/findings of the current session.
Do not include rejected or refuted candidates, general summaries, coverage notes, or test
strategy, unless one of those is itself an actionable finding.

## Path Conventions

Paths in this document use `<SKILL_DIR>` to mean this skill's installation directory — for
example `.claude/skills/save-review-comments` in Claude Code, or
`.codex/skills/save-review-comments` in Codex CLI. Whenever you see `<SKILL_DIR>` in a Bash
invocation, substitute the actual installation path resolved from the harness. Do not
synthesize an absolute path from your own filesystem assumptions.

## Review Types

This skill serves two review types. They never share an identifier or an output path, so
determine the type first, from the session context, and then follow only that branch.

| Review type                  | Identifier | Source of the identifier                        |
| :--------------------------- | :--------- | :---------------------------------------------- |
| Implementation-plan review   | `plan-id`  | the implementation plan file path               |
| Code review                  | `pr-id`    | the numeric GitHub PR id                        |

- **Implementation-plan review** requires the plan file path. The `plan-id` is the plan
  file's stem, and the output goes next to the plan itself — no issue needs to exist for
  the plan, and the plan does not need to live under `.ai/impl_plans`. If the path is not
  known, ask the user.
- **Code review** requires a numeric GitHub PR id. If it is not known, ask the user. Do not
  fall back to a branch name.

## Workflow

1. Determine the review type and its identifier, as described above.

2. Create this run's output directory with the bundled script. Run exactly one of:

   ```bash
   <SKILL_DIR>/scripts/new_comments_dir.sh --plan-file <plan-file>
   ```

   ```bash
   <SKILL_DIR>/scripts/new_comments_dir.sh --pr-id <numeric-pr-id>
   ```

   The script prints the absolute path of a fresh timestamped directory on stdout and
   nothing else. Use exactly that printed path — never glob, guess, or reuse a path under
   `comments/` yourself, and never construct the timestamp on your own. The two modes
   resolve their base directory differently:

   - `--plan-file` → `<plan-dir>/<plan-id>/comments/<timestamp>/`, alongside the
     `scratchpads/` directory that `implementation-plan-review` creates for the same plan.
   - `--pr-id` → `<repo-root>/.ai/pr-review/<pr-id>/comments/<timestamp>/`, anchored at the
     git repository root. Pass `--pr-review-dir <path>` if the project keeps PR review
     material somewhere else.

   On failure the script prints `error: <message>` on stderr; fix the cause and rerun it
   before doing any writing.

3. The output file for this run is `comments.md` inside the printed directory.

4. Add the required metadata blocks first, using the block script below.

   - Implementation-plan review: `meta` slug `implementation-plan-source-file`, body = the
     plan file path.
   - Code review: `meta` slug `github-pr-id`, body = the numeric PR id; then `meta` slug
     `commit-id`, body = the output of `git rev-parse HEAD`.

5. For each surviving actionable comment/finding, add a separate `comment` block with a
   stable slug, preserving the comment text almost verbatim.

## Script Contract

Use the bundled script for every block. Do not write tagged blocks by hand.

```bash
<SKILL_DIR>/scripts/review_comment_block.py <file-to-update> <meta|comment> <slug> <<'EOF'
block body
EOF
```

The script creates parent directories, appends the block, rejects duplicate slugs, and
validates the whole file after every write.

Blocks have this exact shape:

```md
<!-- meta:begin slug="github-pr-id" -->
1234
<!-- meta:end slug="github-pr-id" -->

<!-- comment:begin slug="retry-budget-unbounded" -->
1. **[worker/dispatch.go:214](https://github.com/owner/repo/blob/abc1234/worker/dispatch.go#L214) - CONFIRMED.** The retry loop has no upper bound, so a permanently failing job blocks the queue. Recommendation: cap attempts and move exhausted jobs to the dead-letter path.
<!-- comment:end slug="retry-budget-unbounded" -->
```

Slug rules: lowercase ASCII letters, digits, and hyphens only; must match
`^[a-z0-9][a-z0-9-]*$`. Prefer concise slugs derived from the finding topic, for example
`retry-budget-unbounded`, `config-defaults-undocumented`, or `first-delta-spike`.

## Preservation Rules

- Keep the original review wording almost verbatim.
- Do not normalize findings into a new schema.
- Do not rewrite links, severity labels, verdicts, recommendations, or action text unless a
  tiny edit is required to make the single finding self-contained.
- One surviving finding equals one `comment` block.
- If the review output contains numbered findings, include the numbering text inside the
  block body.
