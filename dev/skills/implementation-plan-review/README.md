# implementation-plan-review

This skill reviews an implementation plan against an issue or enhancement description (a
local file or a GitHub issue number) and the current codebase. It produces a structured
review with actionable comments. It never implements the plan.

The skill treats every suspected problem as a candidate. An independent subagent judges
each candidate under a fixed protocol. Because of this, a finding is confirmed,
downgraded, or closed on evidence, before it reaches the final review.

## Notes

The skill works with any project. It finds the project conventions, such as agent-facing
rule files, spec documents, and the test layout, at review time. It does not assume a
fixed project layout.
