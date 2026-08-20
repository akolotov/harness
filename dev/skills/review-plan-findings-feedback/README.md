# review-plan-findings-feedback

This skill is a follow-up step for `implementation-plan-review`. It reviews the feedback
file that you write after you address the findings of a plan review. It checks whether
each original finding is genuinely closed, acceptably rejected, or still open. It also
checks whether the plan edits introduced or exposed a new problem.

The skill adjudicates only new candidate problems again. Independent subagents adjudicate
them under the `implementation-plan-review` protocol. The skill writes surviving findings
to `.ai/impl_plans/<plan-id>/findings/<timestamp>/findings.md`. The chat reply gives only
the file path, or a short status that reports no new findings.

## Notes

The skill works with any project. It reuses the protocol, the report template, and the
scripts of the sibling `implementation-plan-review` skill, through relative paths inside
the same plugin.
