---
name: research-codebase
description: Conduct comprehensive, evidence-backed research across this project and write a reusable research note to `.ai/research/`. Use whenever the user wants to investigate, document, map, or trace how something in the codebase works — architecture, implementation, behavior, dependencies, data flow, or debugging questions — by splitting the work into parallel sub-investigations and synthesizing the findings with concrete file references. Use this skill any time the user asks to "research", "investigate", "trace", "explain how X works", "map out", or "document" something in the codebase, even if the user does not say the word "research".
---

# Research Codebase

Investigate this project methodically, then leave behind a project-local research note that another engineer or AI agent can reuse.

This skill operates as a **documentarian**: it describes what exists, it does not recommend changes. The same constraint flows down to every sub-agent through the Sub-Agent Invocation Contract defined below.

## Path Conventions

Paths in this document use `<SKILL_DIR>` to mean this skill's installation directory — for example `.claude/skills/research-codebase` in Claude Code, or `.codex/skills/research-codebase` in Codex CLI. Whenever you see `<SKILL_DIR>` in a Bash invocation or a Read directive (including directives this skill emits to sub-agents), substitute the actual installation path resolved from the harness. Markdown links to sibling files such as [references/roles-overview.md](references/roles-overview.md) are already relative to this file and need no substitution.

## Initial Response

When invoked without a concrete research question, reply with:

```text
I'm ready to research this codebase. Share the question or area you want investigated, and I'll trace the relevant code paths, summarize the findings, and capture the result in a project-local research note.
```

Then wait for the user's question.

## Workflow

1. Read any files the user names before decomposing the task. Read them fully (no `limit`/`offset`).
2. Restate the question in precise technical terms and note the architectural implications likely to matter.
3. Break the work into composable research areas. Decide which directories, files, interfaces, flows, or patterns must be investigated and which **role** ([Locator / Analyzer / PatternFinder / WebResearcher](references/roles-overview.md)) handles each one.
4. Maintain a task list so every research area is tracked through synthesis.
5. Delegate to sub-agents in parallel, one task per role pass. Construct each prompt by following the Sub-Agent Invocation Contract below.
6. Start with Locator passes, follow with Analyzer passes on the most promising paths, add PatternFinder when comparable examples help, and use WebResearcher only when outside context is genuinely needed.
7. Wait for all sub-agents to complete before synthesizing.
8. Derive a short slug of 2–4 meaningful words for the research note.
9. Run the metadata script (see "Metadata Script" below) to gather timestamps, target/workspace paths, git context, and the final note path.
10. Write the research note to the path returned by the script.
11. Present a concise answer with the most relevant file references, then ask whether the user wants follow-up research or clarification.

## Sub-Agent Invocation Contract

Every sub-agent prompt this skill emits MUST contain these three components, in this order:

1. **Documentarian Doctrine — inline, verbatim.** Copy the entire contents of [references/documentarian-doctrine.md](references/documentarian-doctrine.md) into the prompt as the first text. This is the most critical block; it stays inline so the sub-agent cannot skip, skim, or partially load it.

2. **Role declaration + read-and-comply directive.** Name the role and instruct the sub-agent to Read its role file before producing output. Substitute `<role-file>` for one of `locator.md`, `analyzer.md`, `pattern-finder.md`, `web-researcher.md`, and resolve `<SKILL_DIR>` to the actual installation path (see "Path Conventions" above) before emitting the prompt. Use this phrasing:

   > You are running in **\<Role\>** mode.
   >
   > Before producing any output, use Read to load `<SKILL_DIR>/references/roles/<role-file>` in full and apply it exactly. The file contains your **Tool-Restriction Block** (the tools you may use), your **Task Shape** (the procedure for your role and the slots the orchestrator's task fills), your **Locked Output Format** (the structure of your reply), and your **Self-Check Finisher** (a mandatory final pass before you return).

3. **Role task** — the task itself, stated plainly, with the slot information the role expects. See [references/roles-overview.md](references/roles-overview.md) for the slot list per role. If a slot does not apply, fill it with `n/a` — do not omit it.

**Why this shape**: the doctrine ships inline because skipping it is unrecoverable; role files are referenced so each sub-agent only loads its own.

**WebResearcher caveat**: if WebResearcher is invoked in a harness without local-file Read access, the orchestrator must include the contents of `<SKILL_DIR>/references/roles/web-researcher.md` inline in the prompt instead of issuing a Read directive. In every other case the Read directive is sufficient.

## Model Selection

If the harness allows per-call model selection: Locator and PatternFinder can run on a smaller / cheaper model (mostly grep-and-list), while Analyzer and WebResearcher should stay on the primary model. Synthesis stays in the orchestrator's main thread on the primary model. If no per-call selection is available, ignore this section.

## Planning Expectations

Before delegating, think through patterns, hidden relationships, and architectural decisions the user might care about. Do not reduce planning to keyword search alone. The plan should capture:

- the user-visible question
- the likely subsystems involved
- the specific flows or contracts to trace
- which role handles each piece (Locator, Analyzer, PatternFinder, WebResearcher)

When the user names files, read them fully before spawning sub-agents.

## Evidence Standard

Prefer live code as the primary source of truth.

Always:
- Cite exact file paths and line numbers when the code supports a claim.
- Distinguish observed facts from inference.
- Call out uncertainty, missing tests, or dead ends explicitly.
- Connect components instead of listing isolated facts.

Use prior notes or historical documents only as supplementary context. Always refresh the answer from the live codebase before trusting older research.

## GitHub Permalinks

When the researched target is a git repository and `TARGET_GIT_REMOTE` points at GitHub, prefer commit-based GitHub permalinks in the document in addition to local file references.

Use commit-based links only when you have a concrete `TARGET_GIT_COMMIT`. Normalize either SSH or HTTPS remotes to:

```text
https://github.com/<owner>/<repo>/blob/<commit>/<path>#L<line>
```

If a reliable GitHub permalink cannot be constructed, keep local file references instead of guessing.

## Research Note Format

Use the metadata script output to fill the header and choose the destination file. The note starts with YAML frontmatter followed by a concise, scannable report.

In the template below, every placeholder written `<UPPERCASE_NAME>` is the name of a key emitted by the metadata script — substitute the script's actual value at write time. Placeholders in lowercase or square brackets (`<title — ...>`, `[Original user question]`, etc.) are filled by the orchestrator from the research question and findings.

```markdown
---
date: <DATE_ISO>
researcher: <RESEARCHER>
target_project: <TARGET_PROJECT_NAME>
target_project_root: <TARGET_PROJECT_ROOT>
workspace_root: <WORKSPACE_ROOT>
research_dir: <RESEARCH_DIR>
target_git_available: <TARGET_GIT_AVAILABLE>
target_git_root: <TARGET_GIT_ROOT>
target_git_commit: <TARGET_GIT_COMMIT>
target_git_branch: <TARGET_GIT_BRANCH>
target_git_remote: <TARGET_GIT_REMOTE>
title: "<short, descriptive title — typically a refinement of the research question>"
tags: [<topic-relevant tags>]
status: complete
last_updated: <DATE>
last_updated_by: <RESEARCHER>
---
# Research: <title — same value as the title field above>

## Research Question
[Original user question]

## Summary
[Short answer first]

## Detailed Findings
### [Area]
- Finding with code reference
- Supporting behavior or relationship

## Code References
- `path/to/file.ext:12` — what matters there

## Open Questions
- Remaining uncertainty or next checks
```

Never write placeholder text (whether `<UPPERCASE_NAME>` or `[bracketed]`) into the final note. Resolve metadata first, then write the document. The note body should preserve the full research question; the metadata script only provides filesystem and repository context.

## Project-Local Conventions

Write research notes under `.ai/research/` in the current workspace by default. Resolve the workspace root with `git rev-parse --show-toplevel` when available so invocations from nested directories still write into the top-level project research folder. If you pass `--research-target-root` for a different repository, keep the note in the current workspace unless you also pass `--research-dir`.

Name files with the script-provided basename: `YYYY-MM-DD-HH-MM-slug.md`. Use a short slug — 2–4 meaningful words — that helps humans scan filenames quickly, not a restatement of the full question.

Keep the note self-contained:
- Include enough context that someone can read the note without the original chat.
- Prefer short sections and evidence-heavy bullets over long narrative prose.

## Metadata Script

Run:

```bash
<SKILL_DIR>/scripts/research-metadata.sh --slug "<short-slug>"
```

For a different research target than the current workspace:

```bash
<SKILL_DIR>/scripts/research-metadata.sh --research-target-root /absolute/path/to/target --slug "<short-slug>"
```

Resolve `<SKILL_DIR>` to the actual installation path before invoking (see "Path Conventions" near the top of this file). The script must be invoked through this resolved path — do not synthesize an absolute path from your own filesystem assumptions.

The script emits `key=value` pairs for:
- timestamps (`DATE_ISO`, `DATE`)
- the researched target project name and root
- the current workspace root and research directory
- target git availability, commit, branch, and remote when present
- the normalized filename slug
- the final note basename and full note path

If the chosen filename slug changes materially during research, rerun the script with the final slug before writing the note.

## Follow-Up Research

If the user asks a follow-up question on the same topic:

1. Reuse the existing research document instead of creating a new one.
2. Run fresh research again; do not rely solely on the previous note.
3. Spawn new sub-agents as needed for the follow-up — same Sub-Agent Invocation Contract.
4. Update frontmatter fields:
   - `last_updated`
   - `last_updated_by`
   - `last_updated_note: "Added follow-up research for <brief description>"`
5. Append a new section using the timestamp from the metadata script:

```markdown
## Follow-up Research 2026-04-18T23:30:00-06:00
```

6. Sync the updated findings back to the user with the key references and offer clarification if anything remains unclear.

## Critical Ordering Rules

Follow these rules exactly:

1. Always read user-mentioned files fully before spawning sub-agents.
2. Always plan the research areas and assign a role to each before delegating.
3. **Always assemble every sub-agent prompt as the three-component Sub-Agent Invocation Contract — inline Documentarian Doctrine, then role declaration with a Read directive pointing at the role's file under `references/roles/`, then the task — in that order.** Copy the doctrine verbatim; do not paraphrase it. The role-specific machinery (tool restrictions, task shape, output format, self-check) lives in the per-role file the sub-agent reads.
4. Always wait for all sub-agents to complete before synthesizing.
5. Always gather metadata before writing the note.
6. Never write the final note with placeholder values.
