# implementation-plan-review

Expert review of an implementation plan against an issue/enhancement description
(local file or GitHub issue number) and the current repository codebase. Produces a
structured review with actionable comments; it never implements the plan.

Every suspected problem is treated as a *candidate* and adjudicated by an independent
subagent under a fixed protocol, so findings are confirmed, downgraded, or closed on
evidence before they reach the final review.

## Notes

The skill is project-agnostic: it discovers repo conventions (agent-facing rule files,
spec docs, test layout) at review time instead of assuming a particular project layout.
