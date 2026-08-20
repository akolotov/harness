# Testing `spawn_review_sessions.py`

Two layers: **unit tests** (fast, no real `claude`/`tmux`) and a **`--dry-run`
smoke check** against real comment files. No test ever launches a real RC
session or spends tokens.

## 1. Unit tests

Stdlib `unittest` only — no pytest, no third-party deps.

```bash
# from the repo root
python3 -m unittest discover -s <SKILL_DIR>/scripts/tests

# verbose
python3 -m unittest discover -s <SKILL_DIR>/scripts/tests -v

# a single test
python3 -m unittest \
  test_spawn_review_sessions.TestMainEndToEnd.test_code_review_all_ok \
  -v
```

The test file lives in `tests/test_spawn_review_sessions.py` and prepends
`scripts/` to `sys.path`, so it imports `spawn_review_sessions` directly.

### How `claude` and `tmux` are mocked

`subprocess.run` is replaced (via `unittest.mock.patch.object`) with a
`FakeRun` that:

- **records every command** into a `calls` list, so tests can assert exactly
  which flags were passed (`--model`, `--effort`, `--session-id`,
  `--max-budget-usd`, `--resume …`, `-c <project_dir>`, etc.);
- **dispatches on argv** to simulate outcomes:
  - `tmux has-session` → returns alive/dead based on `alive_names`;
  - `claude … -p …` (seed) → writes a JSONL event stream
    (`system`/`assistant`/`user` then a terminal `result` event) into the
    captured stdout file handle; the result carries `subtype: success|error`.
    Can raise `TimeoutExpired` (`timeout_names`), emit an error subtype
    (`fail_seed_names`), or omit the result event (`no_result_names`);
  - `tmux new-session` → succeeds, or fails for `rc_start_fail_names`;
  - anything else (`tmux ls`) → success.

So **no binary is executed**. The tests' temporary `config.json` points
`claude_path` and `tmux_path` at `sys.executable` only so `resolve_binary`'s
existence check passes — that binary is never actually run. Where the `PATH`
fallback itself is under test, `shutil.which` is mocked instead.

### What's covered

- **Pure functions:** block parsing incl. edge cases (empty body, duplicate
  slug, missing `end`), `detect_type` (override / auto-plan / auto-code /
  undetectable → exit), `sanitize_slug`, `build_display_name`,
  `build_tmux_name` (PR / plan-acronym / sanitized / fallback), `build_prompt`
  (placeholders substituted, plan path injected, verdict language substituted
  and defaulted when blank, project context injected or its whole line dropped),
  `mapping.tsv` roundtrip.
- **Config/template resolution:** `resolve_binary` (configured path wins,
  set-but-missing exits, blank falls back to `shutil.which`, not-on-PATH exits),
  `merge_config` (shallow, `templates` merges key-wise), `load_config` with a
  per-project override (`.claude/` beats `.codex/`, absent override leaves the
  shipped config), `resolve_template` (override root wins, falls back to
  `SKILL_DIR`, absolute path used as-is).
- **Shipped defaults:** each shipped template carries every placeholder the
  script substitutes, and `config.json` ships with unpinned binaries, the
  default verdict language and an empty project context — so a stray
  machine-specific or project-specific default cannot be committed unnoticed.
- **Seed step (`seed_one`):** success (asserts the `.jsonl` artifact and the
  `--verbose`/`--output-format stream-json` flags); budget flag present iff
  `> 0`; failure on `subtype=error`; failure when no `result` event is
  emitted; timeout; dry-run spawns nothing.
- **RC step (`raise_rc`):** RC command shape (`--resume <uuid>`, project dir);
  tmux failure surfaces the stderr reason. In `main` this is pipelined — each
  session's RC is raised as soon as its own seed succeeds, not after a barrier.
- **Progress heartbeat:** `count_jsonl_lines` (incl. missing file) and
  `format_progress` (running → `*` per line, `done`/`FAIL`, `(starting)` when
  no file yet). The heartbeat thread is exercised implicitly by the `main`
  tests — the fake seeds finish instantly, so the barrier stops the thread
  before its first tick (the suite runs in well under a second, proving no
  hang). To eyeball a live heartbeat, mock `subprocess.run` with a seed that
  writes a line every ~0.3s and set `progress_interval_seconds: 1`.
- **`tmux_alive`**, and **`main` end-to-end:** code/plan mapping rows
  (handle + display name + type), a failed seed excluded from the mapping
  (exit 1) while its sibling still starts, live-session skip (no re-seed),
  dry-run (nothing persisted, no `-p`/`new-session`), and idempotent resume
  reusing the stored UUID with no re-seed.

Add a case whenever you touch parsing, naming, the seed/RC command shape, or the
idempotency rules.

## 2. `--dry-run` smoke check

Parses a real comments file and prints the full plan (detected type, template,
project dir, per-comment tmux handle + display name) **without** invoking
`claude` or `tmux` and without writing `mapping.tsv`.

```bash
python3 <SKILL_DIR>/scripts/spawn_review_sessions.py \
  .ai/pr-review/1695/comments/20260707-1746.md --dry-run

python3 <SKILL_DIR>/scripts/spawn_review_sessions.py \
  .ai/impl_plans/chart-implementation-remapping/comments/20260707-1750.md --dry-run
```

Check that: the review type is detected correctly, comment count matches the
file, `meta:` blocks are excluded from the comment list, the handles/names look
right (`review-PR<id>-<slug>` / `review-plan-<ACRONYM>-<slug>`), and — when the
project has an override — the printed `Project cfg`/`Verdict lang` lines and the
resolved `Template` path point where you expect.

To eyeball the exact composite prompt a comment would receive:

```bash
cd <SKILL_DIR>/scripts
python3 -c "
import spawn_review_sessions as s
from pathlib import Path
md = '<path/to/comments.md>'
project = Path.cwd()  # or the --project-dir you would pass
text = Path(md).read_text()
meta, comments = s.parse_blocks(text)
rtype = s.detect_type(meta, None)
tpl_key = 'plan_review' if rtype == 'plan-review' else 'code_review'
cfg, roots = s.load_config(s.SKILL_DIR / 'config.json', project)
tpl = s.resolve_template(cfg['templates'][tpl_key], roots).read_text()
slug, body = comments[0]
print(s.build_prompt(tpl, rtype, body, meta,
                     cfg.get('verdict_language', ''),
                     cfg.get('project_context', '')))
"
```

This is the way to confirm a per-project override actually took effect: it runs
the same config/template cascade the script does. (Reading `templates/*.md`
directly still shows the shape — the prompt is that template with
`<comment-statement>`, `<implementation-plan-file-path>`, `<verdict-language>`
and `<project-context>` substituted.)

## 3. Real end-to-end (manual, spends tokens)

Only after the above pass. Requires claude.ai OAuth, workspace trust, and
Claude Code v2.1.51+ (see `../SKILL.md`). Run without `--dry-run`; watch
sessions appear via `tmux ls` and on claude.ai/code, and end each with `/exit`.
Start small — a file with a single comment block — before a full batch.
