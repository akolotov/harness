# save-review-comments

This skill saves the surviving actionable comments of a review session into a
machine-readable Markdown file. A later session, or a later skill, can then use the
findings without the original chat.

Each comment becomes a tagged block. A bundled script writes the block and checks the
whole file after every addition. The script keeps the original review wording almost
exactly, instead of rewriting it into a new format.

You must invoke this skill by name. It does not start on its own. It serves two review
types:

| Review type                | Output                                                                |
| :-------------------------- | :--------------------------------------------------------------------- |
| Implementation-plan review | `<plan-dir>/<plan-id>/comments/<timestamp>/comments.md`               |
| Code review                | `<repo-root>/.ai/pr-review/<pr-id>/comments/<timestamp>/comments.md`  |

## Notes

The skill works with any project. The plan-review output lands next to the plan file
itself. It sits alongside the `scratchpads/` directory that the sibling
`implementation-plan-review` skill creates for the same plan. The plan file does not have
to live under `.ai/impl_plans`. A numeric PR id has no fixed location in the file system.
For that reason, the code-review branch finds the project root through git, and it works
the same way in a linked worktree.

The code-review branch also works with any harness. Code review is a built-in feature of
both Claude Code and Codex CLI. For this reason, the plugin ships no code-review skill. It
ships only this step, which saves the comments that such a review produces.
