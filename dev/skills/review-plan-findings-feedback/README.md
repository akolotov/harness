# review-plan-findings-feedback

Follow-up step for `implementation-plan-review`. Reviews the feedback file written
after plan-review findings were addressed, and checks whether each original finding
is genuinely closed, acceptably rejected, or still open — plus whether the plan edits
introduced or exposed anything new.

Only *new* candidate problems are adjudicated again, by independent subagents under
the `implementation-plan-review` protocol. Surviving findings are written to
`.ai/impl_plans/<plan-id>/findings/<timestamp>/findings.md`; the chat reply is just the
path, or a short no-new-findings status.

## Notes

The skill is project-agnostic and reuses the sibling `implementation-plan-review`
skill's protocol, report template, and scripts through relative paths inside the same
plugin.
