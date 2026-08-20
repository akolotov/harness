#!/usr/bin/env python3
"""Spawn one Claude Code Remote Control (RC) session per review comment.

Two steps per comment, pipelined (no barrier between them — see the handoff
doc for rationale):

  Step 1 (seed, headless, parallel):
      claude -p --verbose --output-format stream-json --session-id <uuid> \
          --name review-<slug> --permission-mode <config> ...
      Creates a persisted session under a self-minted UUID and feeds it the
      composite prompt. The permission mode comes from the config
      ('permission_mode', falling back to 'plan' when unset); the shipped
      prompts tell the session not to modify files yet, so a permissive mode
      still leaves the decision to the operator. The event stream is written to
      seed-<slug>.jsonl (tail -f for live status); the terminal 'result' event
      is the success/error verdict.

  Step 2 (steer, RC in tmux):
      tmux new-session -d -s review-<slug> -c <project_dir> \
          "<claude> --remote-control --resume <uuid>"
      Resumes the same session with RC enabled, backgrounded in tmux, so the
      operator can steer it from claude.ai/code or the mobile app and end it
      with /exit whenever they decide.

Seeds run in parallel (capped at seed_concurrency); each session's RC is raised
the moment ITS seed succeeds, so the operator can start reading the first ready
session while slower seeds are still running — no waiting for the whole batch.

The only durable state is the slug -> uuid mapping (mapping.tsv), persisted
incrementally as each session comes up. Auth, workspace trust and CLI version
are assumed to be handled beforehand.

Nothing here is project-specific. Binaries are found on PATH unless the config
pins them, and both the config and the prompt templates are overridable per
project (see OVERRIDE_SUBDIRS) so the shipped defaults never have to be forked.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_DIR / "config.json"

# One regex for every begin/end marker of either namespace.
MARKER_RE = re.compile(
    r'<!--\s*(?P<ns>meta|comment):(?P<kind>begin|end)\s+slug="(?P<slug>[^"]+)"\s*-->'
)

PLACEHOLDER_COMMENT = "<comment-statement>"
PLACEHOLDER_PLAN_PATH = "<implementation-plan-file-path>"
PLACEHOLDER_VERDICT_LANG = "<verdict-language>"
PLACEHOLDER_PROJECT_CONTEXT = "<project-context>"

# Language of the explanation the seeded session writes back, when the config
# leaves it unset. Free-form string, not an enum: "Russian, but keep identifiers
# in English" is as valid as "Russian".
DEFAULT_VERDICT_LANGUAGE = "English"

# Per-project override roots, relative to the project dir, in precedence order.
# Each may hold a 'config.json' (shallow-merged over the shipped one) and any
# template named by the config's 'templates' entries.
OVERRIDE_SUBDIRS = (".claude/spawn-review-sessions", ".codex/spawn-review-sessions")

# meta slugs that decide which prompt template applies when --type is absent.
META_PLAN_PATH = "implementation-plan-source-file"
META_PR_ID = "github-pr-id"


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def override_roots(project_dir: Path) -> list[Path]:
    """Existing per-project override dirs, highest precedence first."""
    return [d for d in (project_dir / sub for sub in OVERRIDE_SUBDIRS) if d.is_dir()]


def read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def merge_config(base: dict, over: dict) -> dict:
    """Shallow merge, except 'templates' which merges key-wise so an override
    can replace one template without restating the other."""
    merged = dict(base)
    for key, value in over.items():
        if key == "templates" and isinstance(value, dict):
            merged["templates"] = {**base.get("templates", {}), **value}
        else:
            merged[key] = value
    return merged


def resolve_binary(raw: str, name: str, config_key: str) -> str:
    """A configured path wins (and must exist); otherwise fall back to PATH.

    Pinning binaries is machine-specific, not project-specific, so the shipped
    config leaves both empty and this resolves them at run time.
    """
    raw = (raw or "").strip()
    if raw:
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
        if not path.exists():
            sys.exit(f"FATAL: {name} binary not found at {path} (config {config_key})")
        return str(path)
    found = shutil.which(name)
    if not found:
        sys.exit(f"FATAL: {name} not found on PATH; set '{config_key}' in the config")
    return found


def load_config(path: Path, project_dir: Path) -> tuple[dict, list[Path]]:
    """Shipped config, shallow-merged with the first per-project override found.

    Returns (config, override_roots) — the roots are reused for template lookup.
    """
    cfg = read_json(path)
    roots = override_roots(project_dir)
    applied = None
    for root in roots:
        candidate = root / "config.json"
        if candidate.is_file():
            cfg = merge_config(cfg, read_json(candidate))
            applied = candidate
            break
    cfg["_override_config"] = str(applied) if applied else ""
    cfg["_claude_path"] = resolve_binary(cfg.get("claude_path", ""), "claude",
                                         "claude_path")
    cfg["_tmux_path"] = resolve_binary(cfg.get("tmux_path", ""), "tmux", "tmux_path")
    return cfg, roots


def resolve_template(rel: str, roots: list[Path]) -> Path:
    """Per-project template if one exists under an override root, else shipped."""
    candidate = Path(rel)
    if candidate.is_absolute():
        return candidate
    for root in roots:
        override = root / candidate
        if override.is_file():
            return override
    return (SKILL_DIR / candidate).resolve()


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def parse_blocks(text: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Return (meta: slug->body, comments: [(slug, body), ...] in file order).

    Handles missing END, mismatched/nested markers, duplicate slugs and empty
    bodies by warning and skipping the offending block rather than aborting.
    """
    meta: dict[str, str] = {}
    comments: list[tuple[str, str]] = []
    comment_slugs: set[str] = set()

    open_marker = None  # (ns, slug, body_start_index)
    for m in MARKER_RE.finditer(text):
        ns, kind, slug = m.group("ns"), m.group("kind"), m.group("slug")
        if kind == "begin":
            if open_marker is not None:
                o_ns, o_slug, _ = open_marker
                eprint(f"WARN: '{o_ns}:{o_slug}' has no matching end before "
                       f"'{ns}:begin {slug}'; skipping the former")
            open_marker = (ns, slug, m.end())
        else:  # end
            if open_marker is None:
                eprint(f"WARN: stray '{ns}:end {slug}' with no open block; ignoring")
                continue
            o_ns, o_slug, body_start = open_marker
            open_marker = None
            if (o_ns, o_slug) != (ns, slug):
                eprint(f"WARN: end '{ns}:{slug}' does not match open "
                       f"'{o_ns}:{o_slug}'; skipping")
                continue
            body = text[body_start:m.start()].strip()
            if not body:
                eprint(f"WARN: empty body for {ns}:{slug}; skipping")
                continue
            if ns == "meta":
                meta[slug] = body
            else:
                if slug in comment_slugs:
                    eprint(f"WARN: duplicate comment slug '{slug}'; skipping duplicate")
                    continue
                comment_slugs.add(slug)
                comments.append((slug, body))

    if open_marker is not None:
        o_ns, o_slug, _ = open_marker
        eprint(f"WARN: '{o_ns}:{o_slug}' never closed (missing end); skipping")

    return meta, comments


def detect_type(meta: dict[str, str], override: str | None) -> str:
    if override:
        return override
    if META_PLAN_PATH in meta:
        return "plan-review"
    if META_PR_ID in meta:
        return "code-review"
    sys.exit("FATAL: cannot detect review type from meta blocks "
             f"(need '{META_PLAN_PATH}' or '{META_PR_ID}'); pass --type explicitly")


def sanitize_slug(slug: str) -> str:
    """tmux session names may not contain '.' or ':'; keep it conservative."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", slug)


def build_tmux_name(review_type: str, slug: str, meta: dict[str, str]) -> str:
    """tmux handle used for has-session/attach/kill and as the idempotency key.

    Embeds a meta-derived prefix so `tmux ls` groups by PR/feature:
      code-review -> 'review-PR<pr-id>-<slug>'
      plan-review -> 'review-plan-<ACRONYM>-<slug>' (acronym = first letters of
                     the plan-file stem's dash-separated words, upper-cased)
    Falls back to 'review-<slug>' when the expected meta is missing. The whole
    result is sanitized ('.'/':'/spaces are illegal in tmux names).
    """
    prefix = "review"
    if review_type == "code-review":
        pr_id = meta.get(META_PR_ID, "").strip()
        if pr_id:
            prefix = f"review-PR{pr_id}"
    elif review_type == "plan-review":
        plan_path = meta.get(META_PLAN_PATH, "").strip()
        if plan_path:
            words = [w for w in Path(plan_path).stem.split("-") if w]
            acronym = "".join(w[0] for w in words).upper()
            if acronym:
                prefix = f"review-plan-{acronym}"
    return sanitize_slug(f"{prefix}-{slug}")


def build_display_name(review_type: str, slug: str, meta: dict[str, str]) -> str:
    """Human-facing session name shown in the RC UI (claude.ai/code, mobile).

    Unlike the tmux handle, this may contain '#' and spaces. Derived from meta
    when available: 'PR#<id> - <slug>' for code review, '<feature> - <slug>' for
    plan review (feature = plan file basename without extension). Falls back to
    'review-<slug>' when the expected meta is missing.
    """
    if review_type == "code-review":
        pr_id = meta.get(META_PR_ID, "").strip()
        if pr_id:
            return f"PR#{pr_id} - {slug}"
    elif review_type == "plan-review":
        plan_path = meta.get(META_PLAN_PATH, "").strip()
        if plan_path:
            feature = Path(plan_path).stem
            if feature:
                return f"{feature} - {slug}"
    return f"review-{slug}"


PROJECT_CONTEXT_LINE_RE = re.compile(
    r"^[ \t]*" + re.escape(PLACEHOLDER_PROJECT_CONTEXT) + r"[ \t]*\n?", re.MULTILINE)


def build_prompt(template: str, review_type: str, body: str, meta: dict[str, str],
                 verdict_language: str = DEFAULT_VERDICT_LANGUAGE,
                 project_context: str = "") -> str:
    prompt = template.replace(PLACEHOLDER_COMMENT, body)
    if review_type == "plan-review":
        plan_path = meta.get(META_PLAN_PATH, "").strip()
        if not plan_path:
            eprint(f"WARN: plan-review but meta '{META_PLAN_PATH}' missing/empty")
        prompt = prompt.replace(PLACEHOLDER_PLAN_PATH, plan_path)
    prompt = prompt.replace(PLACEHOLDER_VERDICT_LANG,
                            (verdict_language or "").strip() or DEFAULT_VERDICT_LANGUAGE)
    project_context = (project_context or "").strip()
    if project_context:
        prompt = prompt.replace(PLACEHOLDER_PROJECT_CONTEXT, project_context)
    else:
        # Drop the placeholder's whole line, then collapse the blank-line run it
        # leaves behind, so an unset context costs no stray whitespace.
        prompt = PROJECT_CONTEXT_LINE_RE.sub("", prompt)
        prompt = re.sub(r"\n{3,}", "\n\n", prompt)
    return prompt


# --------------------------------------------------------------------------- #
# Mapping (idempotency)
# --------------------------------------------------------------------------- #
MAPPING_HEADER = ["slug", "uuid", "tmux_session", "name", "type"]


def read_mapping(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.rstrip("\n")
            if not line or (i == 0 and line.split("\t")[0] == "slug"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            row = dict(zip(MAPPING_HEADER, parts + [""] * (len(MAPPING_HEADER) - len(parts))))
            rows[row["slug"]] = row
    return rows


def write_mapping(path: Path, rows: dict[str, dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(MAPPING_HEADER) + "\n")
        for slug in sorted(rows):
            r = rows[slug]
            fh.write("\t".join(r.get(k, "") for k in MAPPING_HEADER) + "\n")


def tmux_alive(tmux_path: str, session: str) -> bool:
    return subprocess.run(
        [tmux_path, "has-session", "-t", session],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def list_run_sessions(tmux_path: str, handles: set[str]) -> list[str]:
    """`tmux ls` lines whose session name is in `handles` (this run only)."""
    if not handles:
        return []
    proc = subprocess.run([tmux_path, "ls"], capture_output=True, text=True)
    if proc.returncode != 0:  # no server / no sessions
        return []
    out = []
    for line in proc.stdout.splitlines():
        name = line.split(":", 1)[0]
        if name in handles:
            out.append(line)
    return out or ["(none live)"]


# --------------------------------------------------------------------------- #
# Phase 1 — progress heartbeat
# --------------------------------------------------------------------------- #
def count_jsonl_lines(path: Path) -> int:
    """Number of lines (~events) written so far to a seed's stream file."""
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def format_progress(sessions_dir: Path, slugs: list[str],
                    status: dict[str, str], elapsed: int) -> str:
    """One heartbeat block: per seed, '*' per stream line, or done/FAIL."""
    width = max((len(s) for s in slugs), default=0)
    lines = [f"  [t+{elapsed}s] seeding:"]
    for slug in slugs:
        st = status.get(slug)
        if st == "ok":
            bar = "done"
        elif st == "fail":
            bar = "FAIL"
        else:
            n = count_jsonl_lines(sessions_dir / f"seed-{slug}.jsonl")
            # one '*' per 5 stream lines, rounded up so any activity shows >=1
            bar = ("*" * ((n + 4) // 5)) if n else "(starting)"
        lines.append(f"    {slug:<{width}}  {bar}")
    return "\n".join(lines)


def _run_heartbeat(sessions_dir: Path, slugs: list[str], interval: int,
                   status: dict[str, str], lock: threading.Lock,
                   stop: threading.Event, start: float) -> None:
    # stop.wait returns True the instant stop is set, so the barrier ends the
    # loop immediately with no dangling final beat.
    while not stop.wait(interval):
        with lock:
            snap = dict(status)
        print(format_progress(sessions_dir, slugs, snap,
                              int(time.monotonic() - start)), flush=True)


# --------------------------------------------------------------------------- #
# Phase 1 — seed
# --------------------------------------------------------------------------- #
def seed_one(cfg: dict, sessions_dir: Path, slug: str, sess_uuid: str,
             name: str, prompt: str, timeout: int, max_budget: float,
             dry_run: bool) -> dict:
    # stream-json (not plain json) so the transcript lands, event by event, in a
    # path we control (next to the MD) and can `tail -f` for live status while
    # the seed runs. stream-json requires --verbose in --print mode.
    out_path = sessions_dir / f"seed-{slug}.jsonl"
    err_path = sessions_dir / f"seed-{slug}.err"

    cmd = [
        cfg["_claude_path"],
        "--name", name,
        "--session-id", sess_uuid,
        "--permission-mode", cfg.get("permission_mode", "plan"),
    ]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]
    if cfg.get("effort"):
        cmd += ["--effort", cfg["effort"]]
    if max_budget and max_budget > 0:
        cmd += ["--max-budget-usd", str(max_budget)]
    cmd += ["-p", "--verbose", "--output-format", "stream-json", prompt]

    if dry_run:
        return {"slug": slug, "uuid": sess_uuid, "name": name, "ok": True,
                "reason": "dry-run", "cmd": cmd}

    result = {"slug": slug, "uuid": sess_uuid, "name": name, "ok": False, "reason": ""}
    try:
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            proc = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                timeout=timeout,
            )
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        result["reason"] = f"timeout after {timeout}s"
        return result

    if rc != 0:
        result["reason"] = f"exit code {rc} (see {err_path.name})"
        return result

    # Validation != exit code: -p can exit 0 on failure. The stream is JSONL
    # (one event per line); the terminal 'result' event carries the verdict.
    result_event = None
    try:
        with open(out_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue  # tolerate a truncated/partial trailing line
                if ev.get("type") == "result":
                    result_event = ev
    except OSError as e:
        result["reason"] = f"cannot read seed output: {e}"
        return result

    if result_event is None:
        result["reason"] = f"no result event in seed stream (see {out_path.name})"
        return result

    subtype = result_event.get("subtype")
    if subtype != "success" or result_event.get("is_error"):
        result["reason"] = (f"seed result subtype={subtype!r} "
                            f"is_error={result_event.get('is_error')}")
        return result

    result["ok"] = True
    result["reason"] = "seeded"
    return result


# --------------------------------------------------------------------------- #
# Phase 2 — RC steer in tmux
# --------------------------------------------------------------------------- #
def raise_rc(cfg: dict, project_dir: str, tmux_name: str, sess_uuid: str,
             dry_run: bool) -> tuple[bool, str]:
    claude_cmd = f"{sh_quote(cfg['_claude_path'])} --remote-control --resume {sess_uuid}"
    cmd = [
        cfg["_tmux_path"], "new-session", "-d",
        "-s", tmux_name, "-c", project_dir, claude_cmd,
    ]
    if dry_run:
        return True, "dry-run"
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return False, proc.stderr.decode(errors="replace").strip()
    return True, "started"


def sh_quote(s: str) -> str:
    import shlex
    return shlex.quote(s)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def git_root(start: Path) -> Path:
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return start


def main() -> int:
    ap = argparse.ArgumentParser(description="Spawn RC sessions per review comment.")
    ap.add_argument("md_file", type=Path, help="review comments MD file")
    ap.add_argument("--type", choices=["code-review", "plan-review"],
                    help="override auto-detection")
    ap.add_argument("--project-dir", type=Path,
                    help="dir RC sessions start in (default: git root of cwd)")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--concurrency", type=int, help="override seed_concurrency")
    ap.add_argument("--max-budget-usd", type=float, help="override seed_max_budget_usd")
    ap.add_argument("--timeout", type=int, help="override seed_timeout_seconds")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and print planned actions without running anything")
    args = ap.parse_args()

    md_file = args.md_file.resolve()
    if not md_file.exists():
        sys.exit(f"FATAL: MD file not found: {md_file}")

    project_dir_path = (args.project_dir or git_root(Path.cwd())).resolve()
    cfg, tpl_roots = load_config(args.config.resolve(), project_dir_path)
    concurrency = args.concurrency or int(cfg.get("seed_concurrency", 4))
    max_budget = args.max_budget_usd if args.max_budget_usd is not None \
        else float(cfg.get("seed_max_budget_usd", 0) or 0)
    timeout = args.timeout or int(cfg.get("seed_timeout_seconds", 600))
    progress_interval = int(cfg.get("progress_interval_seconds", 15))
    project_dir = str(project_dir_path)
    verdict_language = cfg.get("verdict_language", "") or DEFAULT_VERDICT_LANGUAGE
    project_context = cfg.get("project_context", "") or ""

    text = md_file.read_text(encoding="utf-8")
    meta, comments = parse_blocks(text)
    if not comments:
        sys.exit("FATAL: no comment blocks found")

    review_type = detect_type(meta, args.type)
    tpl_key = "plan_review" if review_type == "plan-review" else "code_review"
    tpl_path = resolve_template(cfg["templates"][tpl_key], tpl_roots)
    if not tpl_path.is_file():
        sys.exit(f"FATAL: prompt template not found: {tpl_path}")
    template = tpl_path.read_text(encoding="utf-8")

    sessions_dir = md_file.parent / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = sessions_dir / "mapping.tsv"
    mapping = read_mapping(mapping_path)

    print(f"MD file      : {md_file}")
    print(f"Review type  : {review_type}")
    print(f"Template     : {tpl_path}")
    print(f"Project dir  : {project_dir}")
    print(f"Sessions dir : {sessions_dir}")
    print(f"Comments     : {len(comments)}")
    print(f"Concurrency  : {concurrency}  budget: "
          f"{max_budget or 'unset'}  timeout: {timeout}s")
    print(f"Model/effort : {cfg.get('model')} / {cfg.get('effort')}")
    print(f"Verdict lang : {verdict_language}")
    if cfg["_override_config"]:
        print(f"Project cfg  : {cfg['_override_config']}")
    if project_context:
        print(f"Project ctx  : {project_context.splitlines()[0][:70]}"
              + ("..." if len(project_context) > 70 else ""))
    print()

    # Classify each comment: skip-alive / resume-existing / seed-new.
    to_seed: list[dict] = []       # brand new -> phase 1 then phase 2
    to_resume: list[dict] = []     # known uuid, tmux dead -> phase 2 only
    skipped_alive: list[str] = []

    for slug, body in comments:
        tmux_name = build_tmux_name(review_type, slug, meta)
        if tmux_alive(cfg["_tmux_path"], tmux_name):
            skipped_alive.append(slug)
            continue
        prompt = build_prompt(template, review_type, body, meta,
                              verdict_language, project_context)
        existing = mapping.get(slug)
        if existing and existing.get("uuid"):
            to_resume.append({"slug": slug, "uuid": existing["uuid"],
                              "name": existing.get("name") or tmux_name,
                              "tmux_name": tmux_name})
        else:
            to_seed.append({"slug": slug, "uuid": str(uuid.uuid4()),
                            "name": build_display_name(review_type, slug, meta),
                            "tmux_name": tmux_name, "prompt": prompt})

    if skipped_alive:
        print(f"Skipping {len(skipped_alive)} slug(s) with a live tmux session: "
              f"{', '.join(skipped_alive)}")
    if to_resume:
        print(f"Resuming {len(to_resume)} previously-seeded slug(s) (no re-seed).")
    print(f"Seeding {len(to_seed)} new slug(s).")
    print()

    # --- Pipelined: raise each RC session the moment its seed succeeds ------ #
    # No barrier between seeding and RC: a done seed's session comes up right
    # away, so the operator can start reading/steering it while the slower seeds
    # are still running. Resumes need no seed and are raised up front.
    seeded_ok: list[dict] = []
    seed_failed: list[dict] = []
    started: list[dict] = []
    start_failed: list[dict] = []

    def raise_and_record(t: dict) -> None:
        ok, reason = raise_rc(cfg, project_dir, t["tmux_name"], t["uuid"],
                              args.dry_run)
        mark = "OK " if ok else "FAIL"
        print(f"  [rc   {mark}] {t['tmux_name']}  (name: {t['name']!r}): {reason}")
        if ok:
            started.append(t)
            mapping[t["slug"]] = {
                "slug": t["slug"], "uuid": t["uuid"],
                "tmux_session": t["tmux_name"],
                "name": t["name"], "type": review_type,
            }
            if not args.dry_run:
                write_mapping(mapping_path, mapping)  # persist incrementally
        else:
            start_failed.append({**t, "reason": reason})

    if to_seed or to_resume:
        print("=== Seeding + raising RC (pipelined) ===")
        for s in to_seed:
            print(f"  {s['slug']}  (uuid {s['uuid']})")
        print()

        # Resumes: no seed step, bring them up immediately.
        for t in to_resume:
            raise_and_record(t)

    if to_seed:
        heartbeat_on = progress_interval > 0 and not args.dry_run
        status: dict[str, str] = {}
        status_lock = threading.Lock()
        stop = threading.Event()
        monitor = None
        if heartbeat_on:
            monitor = threading.Thread(
                target=_run_heartbeat,
                args=(sessions_dir, [s["slug"] for s in to_seed],
                      progress_interval, status, status_lock, stop,
                      time.monotonic()),
                daemon=True)
            monitor.start()

        try:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futs = {
                    pool.submit(seed_one, cfg, sessions_dir, s["slug"], s["uuid"],
                                s["name"], s["prompt"], timeout, max_budget,
                                args.dry_run): s
                    for s in to_seed
                }
                for fut in as_completed(futs):
                    s = futs[fut]
                    res = fut.result()
                    with status_lock:
                        status[res["slug"]] = "ok" if res["ok"] else "fail"
                    mark = "OK " if res["ok"] else "FAIL"
                    print(f"  [seed {mark}] {res['slug']}: {res['reason']}")
                    if res["ok"]:
                        seeded_ok.append({**s})
                        raise_and_record(s)  # RC now, don't wait for the barrier
                    else:
                        seed_failed.append({**s, "reason": res["reason"]})
        finally:
            stop.set()
            if monitor:
                monitor.join(timeout=progress_interval + 1)
        print()

    # --- Summary ----------------------------------------------------------- #
    print("=== Summary ===")
    print(f"  seeded ok      : {len(seeded_ok)}")
    print(f"  seed failed    : {len(seed_failed)}"
          + (f" ({', '.join(x['slug'] for x in seed_failed)})" if seed_failed else ""))
    print(f"  resumed        : {len(to_resume)}")
    print(f"  rc started     : {len(started)}")
    print(f"  rc start failed: {len(start_failed)}"
          + (f" ({', '.join(x['slug'] for x in start_failed)})" if start_failed else ""))
    print(f"  skipped (alive): {len(skipped_alive)}")
    if not args.dry_run:
        print(f"  mapping        : {mapping_path}")
        # Only this run's sessions: raised now + already-live ones we skipped.
        run_handles = {t["tmux_name"] for t in started}
        run_handles |= {build_tmux_name(review_type, s, meta) for s in skipped_alive}
        print()
        print("  tmux sessions for this run:")
        for line in list_run_sessions(cfg["_tmux_path"], run_handles):
            print(f"    {line}")

    return 1 if (seed_failed or start_failed) else 0


if __name__ == "__main__":
    sys.exit(main())
