# Roles Overview

This file is for the **orchestrator** of the research-codebase skill. It catalogs the four roles, when to use each, what slot information each one consumes, and how to delegate. Sub-agents do not read this file — they Read their per-role file in `roles/<role>.md` directly.

## Role IDs

- **Locator** → [`roles/locator.md`](roles/locator.md) — finds where things live. Read-only directory and grep work; does not read file contents.
- **Analyzer** → [`roles/analyzer.md`](roles/analyzer.md) — explains how a specific flow works, with `file:line` citations.
- **PatternFinder** → [`roles/pattern-finder.md`](roles/pattern-finder.md) — surfaces 2–4 comparable examples elsewhere in the codebase.
- **WebResearcher** → [`roles/web-researcher.md`](roles/web-researcher.md) — fetches outside documentation when live code is insufficient.

## Slot Information per Role

When the orchestrator writes the task statement for a sub-agent, it must supply the slots each role expects. If a slot does not apply, fill it with `n/a` — do not omit it.

- **Locator** — `<topic>`, `<scope hints, or "n/a">`.
- **Analyzer** — `<component or flow>`, `<entry points, or "n/a — start by locating them">`.
- **PatternFinder** — `<topic>`, `<hint areas, or "n/a">`.
- **WebResearcher** — `<topic>`, `<specific question>`.

## Model Selection (only if the harness supports per-call model choice)

- Locator and PatternFinder may run on a smaller / cheaper model — they are mostly grep-and-list work.
- Analyzer and WebResearcher should run on the primary model — they reason over multi-file evidence.
- Synthesis stays in the orchestrator's main thread on the primary model.

If the harness has no per-call model selector, ignore this section — every role inherits the orchestrator's model.

## Delegation Rules

- Start with Locator passes when the terrain is unclear.
- Move to Analyzer on the most relevant code paths the Locator returned.
- Use PatternFinder when the question benefits from analogous examples.
- Use WebResearcher only when the question genuinely needs outside context.
- Prefer several narrow prompts over one vague prompt.
- **Roles fan out.** A single research run may spawn multiple instances of the same role in parallel — for example three Analyzers on three sub-flows, or two Locators on backend vs. frontend. Split by component, layer, or concern; do not try to make one agent cover a topic that naturally decomposes. Each instance gets its own task statement with its own slot fills.
- Keep the main thread responsible for combining findings across roles. Sub-agents do not synthesize across each other's results, and they do not know that other instances of their role are running.
- Wait for every delegated pass to finish before writing the final note.

## WebResearcher caveat (harnesses without local Read)

If WebResearcher is invoked in a harness without local-file Read access, the orchestrator must include the contents of `roles/web-researcher.md` inline in the prompt instead of issuing a Read directive. In every other case the Read directive is sufficient.
