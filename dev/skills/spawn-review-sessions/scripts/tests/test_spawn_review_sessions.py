#!/usr/bin/env python3
"""Unit tests for spawn_review_sessions.py.

`claude` and `tmux` are never actually executed: subprocess.run is replaced by a
FakeRun that dispatches on argv and records calls, so both phases can be driven
deterministically. Run with:

    python3 -m unittest discover -s .claude/skills/spawn-review-sessions/scripts/tests
    # or:
    python3 .claude/skills/spawn-review-sessions/scripts/tests/test_spawn_review_sessions.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # scripts/

import spawn_review_sessions as srs  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures / fakes
# --------------------------------------------------------------------------- #
CODE_MD = """\
<!-- meta:begin slug="github-pr-id" -->
1695
<!-- meta:end slug="github-pr-id" -->

<!-- meta:begin slug="commit-id" -->
deadbeef
<!-- meta:end slug="commit-id" -->

<!-- comment:begin slug="first-thing" -->
Body of the first comment with `code {braces}` and $shell.
<!-- comment:end slug="first-thing" -->

<!-- comment:begin slug="second.thing" -->
Second body.
<!-- comment:end slug="second.thing" -->
"""

PLAN_MD = """\
<!-- meta:begin slug="implementation-plan-source-file" -->
/Users/x/.ai/impl_plans/chart-implementation-remapping.md
<!-- meta:end slug="implementation-plan-source-file" -->

<!-- comment:begin slug="post-load-name-form" -->
Plan comment body.
<!-- comment:end slug="post-load-name-form" -->
"""


class FakeProc:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def make_fake_run(calls, *, alive_names=(), fail_seed_names=(), timeout_names=(),
                  no_result_names=(), rc_start_fail_names=()):
    """Return a fake subprocess.run.

    Dispatches on the command:
      - tmux has-session -> rc 0 iff the target name is in alive_names
      - claude -p seed    -> writes a JSONL event stream (system/assistant/...
                             then a terminal 'result' event) to the stdout file
                             handle; result subtype=error for fail_seed_names;
                             omits the result event for no_result_names; raises
                             TimeoutExpired for timeout_names
      - tmux new-session  -> rc 0, or rc 1 for names in rc_start_fail_names
      - anything else (tmux ls) -> rc 0
    """
    def fake_run(cmd, **kw):
        calls.append(list(cmd))

        if "has-session" in cmd:
            name = cmd[cmd.index("-t") + 1]
            return FakeProc(returncode=0 if name in alive_names else 1)

        if "-p" in cmd:  # claude seed (now stream-json JSONL)
            name = cmd[cmd.index("--name") + 1]
            if name in timeout_names:
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))
            is_err = name in fail_seed_names
            events = [
                {"type": "system", "subtype": "init"},
                {"type": "assistant"},
                {"type": "user"},
            ]
            if name not in no_result_names:
                events.append({"type": "result",
                               "subtype": "error" if is_err else "success",
                               "is_error": is_err})
            out = kw.get("stdout")
            if out is not None and hasattr(out, "write"):
                out.write(("\n".join(json.dumps(e) for e in events) + "\n").encode())
            return FakeProc(returncode=0)

        if "new-session" in cmd:
            name = cmd[cmd.index("-s") + 1]
            if name in rc_start_fail_names:
                return FakeProc(returncode=1, stderr=b"boom")
            return FakeProc(returncode=0)

        if cmd[-1] == "ls":  # tmux ls -> list handles created this run (text)
            names = [c[c.index("-s") + 1] for c in calls if "new-session" in c]
            listing = "\n".join(f"{n}: 1 windows (created T)" for n in names)
            return FakeProc(returncode=0, stdout=listing)

        return FakeProc(returncode=0)

    return fake_run


def write_temp_config(tmp: Path) -> Path:
    """Config whose claude/tmux paths point at a real, existing binary so
    load_config's existence check passes; the binary is never run (mocked)."""
    cfg = {
        "claude_path": sys.executable,
        "tmux_path": sys.executable,
        "model": "opus",
        "effort": "xhigh",
        "permission_mode": "plan",
        "seed_concurrency": 4,
        "seed_max_budget_usd": 0,
        "seed_timeout_seconds": 600,
        "templates": {
            "code_review": "templates/code-review.md",
            "plan_review": "templates/plan-review.md",
        },
    }
    p = tmp / "config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# Pure functions
# --------------------------------------------------------------------------- #
class TestParsing(unittest.TestCase):
    def test_parse_basic(self):
        meta, comments = srs.parse_blocks(CODE_MD)
        self.assertEqual(meta["github-pr-id"], "1695")
        self.assertEqual(meta["commit-id"], "deadbeef")
        self.assertEqual([s for s, _ in comments], ["first-thing", "second.thing"])
        self.assertIn("{braces}", comments[0][1])

    def test_parse_empty_body_skipped(self):
        md = ('<!-- comment:begin slug="a" -->\n\n<!-- comment:end slug="a" -->\n'
              '<!-- comment:begin slug="b" -->\nhi\n<!-- comment:end slug="b" -->')
        _, comments = srs.parse_blocks(md)
        self.assertEqual([s for s, _ in comments], ["b"])

    def test_parse_duplicate_slug_skipped(self):
        md = ('<!-- comment:begin slug="a" -->\nfirst\n<!-- comment:end slug="a" -->'
              '<!-- comment:begin slug="a" -->\nsecond\n<!-- comment:end slug="a" -->')
        _, comments = srs.parse_blocks(md)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0][1], "first")

    def test_parse_missing_end_skipped(self):
        md = ('<!-- comment:begin slug="a" -->\nno end here\n'
              '<!-- comment:begin slug="b" -->\nhi\n<!-- comment:end slug="b" -->')
        _, comments = srs.parse_blocks(md)
        self.assertEqual([s for s, _ in comments], ["b"])


class TestDetectType(unittest.TestCase):
    def test_override_wins(self):
        self.assertEqual(srs.detect_type({}, "plan-review"), "plan-review")

    def test_auto_plan(self):
        self.assertEqual(
            srs.detect_type({srs.META_PLAN_PATH: "/x/y.md"}, None), "plan-review")

    def test_auto_code(self):
        self.assertEqual(srs.detect_type({srs.META_PR_ID: "1"}, None), "code-review")

    def test_undetectable_exits(self):
        with self.assertRaises(SystemExit):
            srs.detect_type({}, None)


class TestNaming(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(srs.sanitize_slug("a.b:c d"), "a-b-c-d")

    def test_display_name_code(self):
        self.assertEqual(
            srs.build_display_name("code-review", "s", {srs.META_PR_ID: "1695"}),
            "PR#1695 - s")

    def test_display_name_plan(self):
        n = srs.build_display_name(
            "plan-review", "s",
            {srs.META_PLAN_PATH: "/a/chart-implementation-remapping.md"})
        self.assertEqual(n, "chart-implementation-remapping - s")

    def test_display_name_fallback(self):
        self.assertEqual(srs.build_display_name("code-review", "s", {}), "review-s")

    def test_tmux_name_code(self):
        self.assertEqual(
            srs.build_tmux_name("code-review", "first-delta", {srs.META_PR_ID: "1695"}),
            "review-PR1695-first-delta")

    def test_tmux_name_plan_acronym(self):
        self.assertEqual(
            srs.build_tmux_name(
                "plan-review", "post-load",
                {srs.META_PLAN_PATH: "/a/chart-implementation-remapping.md"}),
            "review-plan-CIR-post-load")

    def test_tmux_name_sanitized(self):
        # dotted slug must be sanitized in the handle
        self.assertEqual(
            srs.build_tmux_name("code-review", "a.b", {srs.META_PR_ID: "1"}),
            "review-PR1-a-b")

    def test_tmux_name_fallback(self):
        self.assertEqual(srs.build_tmux_name("code-review", "s", {}), "review-s")


class TestBuildPrompt(unittest.TestCase):
    def test_code_prompt(self):
        tpl = "intro\n<comment-statement>\noutro"
        p = srs.build_prompt(tpl, "code-review", "BODY {x}", {})
        self.assertIn("BODY {x}", p)
        self.assertNotIn(srs.PLACEHOLDER_COMMENT, p)

    def test_plan_prompt_path_injected(self):
        tpl = "plan <implementation-plan-file-path>\n<comment-statement>"
        p = srs.build_prompt(tpl, "plan-review", "BODY",
                             {srs.META_PLAN_PATH: "/a/b.md"})
        self.assertIn("/a/b.md", p)
        self.assertNotIn(srs.PLACEHOLDER_PLAN_PATH, p)
        self.assertNotIn(srs.PLACEHOLDER_COMMENT, p)

    def test_verdict_language_substituted(self):
        tpl = "<comment-statement>\nanswer in <verdict-language>."
        p = srs.build_prompt(tpl, "code-review", "BODY", {},
                             verdict_language="Russian")
        self.assertIn("answer in Russian.", p)
        self.assertNotIn(srs.PLACEHOLDER_VERDICT_LANG, p)

    def test_verdict_language_defaults_when_blank(self):
        tpl = "answer in <verdict-language>.\n<comment-statement>"
        p = srs.build_prompt(tpl, "code-review", "BODY", {}, verdict_language="  ")
        self.assertIn(f"answer in {srs.DEFAULT_VERDICT_LANGUAGE}.", p)

    def test_project_context_injected(self):
        tpl = "a\n\n<project-context>\n\nb\n<comment-statement>"
        p = srs.build_prompt(tpl, "code-review", "BODY", {},
                             project_context="Stack: Rust + tokio.")
        self.assertIn("Stack: Rust + tokio.", p)
        self.assertNotIn(srs.PLACEHOLDER_PROJECT_CONTEXT, p)

    def test_project_context_empty_drops_the_line(self):
        tpl = "a\n\n<project-context>\n\nb\n<comment-statement>"
        p = srs.build_prompt(tpl, "code-review", "BODY", {}, project_context="")
        self.assertNotIn(srs.PLACEHOLDER_PROJECT_CONTEXT, p)
        # the placeholder's line is gone and leaves no triple newline behind
        self.assertEqual(p, "a\n\nb\nBODY")

    def test_slug_comments_file_and_decision_path_substituted(self):
        tpl = ("<comment-statement>\nslug: <slug>\nsource: <review-comments-file-path>\n"
              "decision: <decision-file-path>")
        p = srs.build_prompt(tpl, "code-review", "BODY", {},
                             slug="my-slug",
                             comments_file_path="/x/comments.md",
                             decision_file_path="/x/decisions/my-slug.md")
        self.assertIn("slug: my-slug", p)
        self.assertIn("source: /x/comments.md", p)
        self.assertIn("decision: /x/decisions/my-slug.md", p)
        self.assertNotIn(srs.PLACEHOLDER_SLUG, p)
        self.assertNotIn(srs.PLACEHOLDER_COMMENTS_FILE_PATH, p)
        self.assertNotIn(srs.PLACEHOLDER_DECISION_PATH, p)


class TestConfigResolution(unittest.TestCase):
    """Binary lookup and the per-project config/template override cascade."""

    def test_configured_binary_wins(self):
        self.assertEqual(
            srs.resolve_binary(sys.executable, "claude", "claude_path"),
            sys.executable)

    def test_configured_binary_missing_exits(self):
        with self.assertRaises(SystemExit):
            srs.resolve_binary("/nope/claude", "claude", "claude_path")

    def test_blank_falls_back_to_path(self):
        with mock.patch.object(srs.shutil, "which", return_value="/usr/bin/tmux"):
            self.assertEqual(srs.resolve_binary("", "tmux", "tmux_path"),
                             "/usr/bin/tmux")

    def test_blank_and_not_on_path_exits(self):
        with mock.patch.object(srs.shutil, "which", return_value=None):
            with self.assertRaises(SystemExit):
                srs.resolve_binary("", "tmux", "tmux_path")

    def test_merge_config_is_shallow_but_templates_merge(self):
        base = {"model": "opus", "effort": "xhigh",
                "templates": {"code_review": "c.md", "plan_review": "p.md"}}
        over = {"model": "sonnet", "templates": {"code_review": "mine.md"}}
        merged = srs.merge_config(base, over)
        self.assertEqual(merged["model"], "sonnet")
        self.assertEqual(merged["effort"], "xhigh")
        self.assertEqual(merged["templates"],
                         {"code_review": "mine.md", "plan_review": "p.md"})

    def test_project_override_config_applied(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            base = write_temp_config(tmp)
            root = tmp / ".claude" / "spawn-review-sessions"
            root.mkdir(parents=True)
            (root / "config.json").write_text(
                json.dumps({"verdict_language": "Russian", "model": "sonnet"}),
                encoding="utf-8")
            cfg, roots = srs.load_config(base, tmp)
            self.assertEqual(cfg["verdict_language"], "Russian")
            self.assertEqual(cfg["model"], "sonnet")
            self.assertEqual(cfg["effort"], "xhigh")  # untouched by the override
            self.assertEqual(cfg["_override_config"], str(root / "config.json"))
            self.assertEqual(roots, [root])

    def test_claude_override_wins_over_codex(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            base = write_temp_config(tmp)
            for sub, lang in ((".claude", "Russian"), (".codex", "German")):
                root = tmp / sub / "spawn-review-sessions"
                root.mkdir(parents=True)
                (root / "config.json").write_text(
                    json.dumps({"verdict_language": lang}), encoding="utf-8")
            cfg, _ = srs.load_config(base, tmp)
            self.assertEqual(cfg["verdict_language"], "Russian")

    def test_no_override_leaves_shipped_config(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cfg, roots = srs.load_config(write_temp_config(tmp), tmp)
            self.assertEqual(cfg["_override_config"], "")
            self.assertEqual(roots, [])

    def test_template_override_wins(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            root = tmp / ".codex" / "spawn-review-sessions" / "templates"
            root.mkdir(parents=True)
            mine = root / "code-review.md"
            mine.write_text("mine", encoding="utf-8")
            resolved = srs.resolve_template(
                "templates/code-review.md", [root.parent])
            self.assertEqual(resolved, mine)

    def test_template_falls_back_to_skill_dir(self):
        resolved = srs.resolve_template("templates/code-review.md", [])
        self.assertEqual(resolved, (srs.SKILL_DIR / "templates/code-review.md"))
        self.assertTrue(resolved.is_file())

    def test_template_absolute_path_used_as_is(self):
        self.assertEqual(srs.resolve_template("/abs/t.md", []), Path("/abs/t.md"))


class TestProgress(unittest.TestCase):
    def test_count_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text("a\nb\nc\n", encoding="utf-8")
            self.assertEqual(srs.count_jsonl_lines(p), 3)

    def test_count_lines_missing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(srs.count_jsonl_lines(Path(d) / "nope.jsonl"), 0)

    def test_format_progress_states(self):
        with tempfile.TemporaryDirectory() as d:
            sd = Path(d)
            (sd / "seed-running.jsonl").write_text("x\n" * 12, encoding="utf-8")
            (sd / "seed-trickle.jsonl").write_text("x\n" * 2, encoding="utf-8")
            # 'starting' has no file yet
            out = srs.format_progress(
                sd, ["running", "trickle", "done1", "fail1", "starting"],
                {"done1": "ok", "fail1": "fail"}, elapsed=30)
            self.assertIn("[t+30s]", out)
            self.assertRegex(out, r"running\s+\*\*\*(?!\*)")   # 12 lines -> ceil(12/5)=3
            self.assertRegex(out, r"trickle\s+\*(?!\*)")       # 2 lines  -> 1 star
            self.assertIn("done", out)
            self.assertIn("FAIL", out)
            self.assertIn("(starting)", out)


class TestMapping(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "mapping.tsv"
            rows = {"a": {"slug": "a", "uuid": "u1", "tmux_session": "review-a",
                          "name": "n", "type": "code-review"}}
            srs.write_mapping(p, rows)
            back = srs.read_mapping(p)
            self.assertEqual(back["a"]["uuid"], "u1")
            self.assertEqual(back["a"]["type"], "code-review")

    def test_read_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(srs.read_mapping(Path(d) / "nope.tsv"), {})


# --------------------------------------------------------------------------- #
# Orchestration (mocked subprocess)
# --------------------------------------------------------------------------- #
class TestFindPrWorktree(unittest.TestCase):
    """`gh pr view` + `git worktree list --porcelain`, both mocked."""

    def _fake_run(self, *, head_ref="feature-x", head_rc=0,
                  worktree_listing="", listing_rc=0):
        def fake_run(cmd, **kw):
            if cmd[:2] == ["gh", "pr"]:
                return FakeProc(returncode=head_rc, stdout=head_ref)
            if "worktree" in cmd and "list" in cmd:
                return FakeProc(returncode=listing_rc, stdout=worktree_listing)
            raise AssertionError(f"unexpected command: {cmd}")
        return fake_run

    def test_no_pr_id_short_circuits(self):
        with mock.patch.object(srs.subprocess, "run") as run:
            self.assertIsNone(srs.find_pr_worktree("", "/repo"))
        run.assert_not_called()

    def test_gh_missing_short_circuits(self):
        with mock.patch.object(srs.shutil, "which", return_value=None), \
                mock.patch.object(srs.subprocess, "run") as run:
            self.assertIsNone(srs.find_pr_worktree("1695", "/repo"))
        run.assert_not_called()

    def test_gh_failure_returns_none(self):
        with mock.patch.object(srs.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(srs.subprocess, "run", self._fake_run(head_rc=1)):
            self.assertIsNone(srs.find_pr_worktree("1695", "/repo"))

    def test_worktree_list_failure_returns_none(self):
        with mock.patch.object(srs.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(srs.subprocess, "run",
                                  self._fake_run(listing_rc=1)):
            self.assertIsNone(srs.find_pr_worktree("1695", "/repo"))

    def test_match_under_managed_worktrees_returns_branch_not_dirname(self):
        # The worktree's directory is named "pr-1695", unrelated to the
        # branch "feature-x" -- the returned name must be the branch, since
        # that's what's passed to --worktree, not whatever the directory
        # happens to be called.
        listing = ("worktree /repo\nHEAD aaa\nbranch refs/heads/main\n\n"
                   "worktree /repo/.claude/worktrees/pr-1695\n"
                   "HEAD bbb\nbranch refs/heads/feature-x\n")
        with mock.patch.object(srs.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(srs.subprocess, "run",
                                  self._fake_run(worktree_listing=listing)):
            self.assertEqual(srs.find_pr_worktree("1695", "/repo"), "feature-x")

    def test_branch_not_checked_out_anywhere(self):
        listing = "worktree /repo\nHEAD aaa\nbranch refs/heads/main\n"
        with mock.patch.object(srs.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(srs.subprocess, "run",
                                  self._fake_run(worktree_listing=listing)):
            self.assertIsNone(srs.find_pr_worktree("1695", "/repo"))

    def test_match_outside_managed_dir_accepted(self):
        # Same branch, checked out as a sibling worktree rather than under
        # .claude/worktrees/ -- trusted and used anyway.
        listing = ("worktree /elsewhere/some-dir-name\n"
                   "HEAD bbb\nbranch refs/heads/feature-x\n")
        with mock.patch.object(srs.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(srs.subprocess, "run",
                                  self._fake_run(worktree_listing=listing)):
            self.assertEqual(srs.find_pr_worktree("1695", "/repo"), "feature-x")

    def test_slashed_branch_name_not_truncated_to_last_path_segment(self):
        # Regression: a hook-routed (or hand-created) worktree whose directory
        # mirrors a '/'-separated branch name, e.g.
        # ~/projects/.worktrees/bs-elixir/fix/arbitrum-inverted-confirmations-
        # order for branch "fix/arbitrum-inverted-confirmations-order". Taking
        # only the last path segment ("arbitrum-inverted-confirmations-order")
        # would point --worktree at an unrelated, freshly-created location.
        branch = "fix/arbitrum-inverted-confirmations-order"
        listing = (f"worktree /home/x/projects/.worktrees/bs-elixir/{branch}\n"
                  f"HEAD bbb\nbranch refs/heads/{branch}\n")
        with mock.patch.object(srs.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(srs.subprocess, "run",
                                  self._fake_run(head_ref=branch,
                                                 worktree_listing=listing)):
            self.assertEqual(srs.find_pr_worktree("14741", "/repo"), branch)

    def test_match_is_current_worktree_returns_none(self):
        # The PR's branch is already checked out in repo_dir itself -- no
        # redirect needed, even though the branch technically "matches".
        listing = "worktree /repo\nHEAD bbb\nbranch refs/heads/feature-x\n"
        with mock.patch.object(srs.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(srs.subprocess, "run",
                                  self._fake_run(worktree_listing=listing)):
            self.assertIsNone(srs.find_pr_worktree("1695", "/repo"))

    def test_repo_dir_compared_by_real_path_not_raw_string(self):
        # main() passes repo_dir as the current worktree's root already
        # resolved via git (git_root -> `git rev-parse --show-toplevel`, which
        # returns the linked worktree's own root even when invoked from one of
        # its subdirectories) -- this just needs to compare real paths, not
        # raw strings, so a trailing slash or similar doesn't cause a false
        # "different worktree" positive.
        listing = "worktree /repo\nHEAD bbb\nbranch refs/heads/feature-x\n"
        with mock.patch.object(srs.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(srs.subprocess, "run",
                                  self._fake_run(worktree_listing=listing)):
            self.assertIsNone(srs.find_pr_worktree("1695", "/repo/"))


class TestSeedOne(unittest.TestCase):
    def _cfg(self):
        return {"_claude_path": "/fake/claude", "permission_mode": "plan",
                "model": "opus", "effort": "xhigh"}

    def test_seed_success(self):
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(srs.subprocess, "run", make_fake_run(calls)):
            res = srs.seed_one(self._cfg(), Path(d), "slug", "uuid-1",
                               "review-slug", "prompt", 600, 0, None, dry_run=False)
            # stream artifact is JSONL, named after the slug
            self.assertTrue((Path(d) / "seed-slug.jsonl").exists())
        self.assertTrue(res["ok"])
        # model/effort/session-id/name and the streaming flags are all present
        seed_cmd = next(c for c in calls if "-p" in c)
        self.assertIn("--model", seed_cmd)
        self.assertIn("--effort", seed_cmd)
        self.assertIn("uuid-1", seed_cmd)
        self.assertIn("--verbose", seed_cmd)                  # required for stream-json
        self.assertEqual(seed_cmd[seed_cmd.index("--output-format") + 1], "stream-json")
        self.assertNotIn("--max-budget-usd", seed_cmd)        # budget 0 -> omitted
        self.assertNotIn("--worktree", seed_cmd)               # no name -> omitted

    def test_seed_worktree_flag(self):
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(srs.subprocess, "run", make_fake_run(calls)):
            srs.seed_one(self._cfg(), Path(d), "slug", "uuid-1", "review-slug",
                        "prompt", 600, 0, "pr-1695", dry_run=False)
        seed_cmd = next(c for c in calls if "-p" in c)
        self.assertEqual(seed_cmd[seed_cmd.index("--worktree") + 1], "pr-1695")

    def test_seed_no_result_event(self):
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(srs.subprocess, "run",
                                  make_fake_run(calls, no_result_names={"review-slug"})):
            res = srs.seed_one(self._cfg(), Path(d), "slug", "u", "review-slug",
                               "p", 600, 0, None, dry_run=False)
        self.assertFalse(res["ok"])
        self.assertIn("no result event", res["reason"])

    def test_seed_budget_flag(self):
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(srs.subprocess, "run", make_fake_run(calls)):
            srs.seed_one(self._cfg(), Path(d), "s", "u", "n", "p", 600, 2.5, None,
                         dry_run=False)
        seed_cmd = next(c for c in calls if "-p" in c)
        self.assertIn("--max-budget-usd", seed_cmd)
        self.assertIn("2.5", seed_cmd)

    def test_seed_error_subtype(self):
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(srs.subprocess, "run",
                                  make_fake_run(calls, fail_seed_names={"review-slug"})):
            res = srs.seed_one(self._cfg(), Path(d), "slug", "u", "review-slug",
                               "p", 600, 0, None, dry_run=False)
        self.assertFalse(res["ok"])
        self.assertIn("subtype", res["reason"])

    def test_seed_timeout(self):
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(srs.subprocess, "run",
                                  make_fake_run(calls, timeout_names={"review-slug"})):
            res = srs.seed_one(self._cfg(), Path(d), "slug", "u", "review-slug",
                               "p", 600, 0, None, dry_run=False)
        self.assertFalse(res["ok"])
        self.assertIn("timeout", res["reason"])

    def test_seed_dry_run_no_subprocess(self):
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(srs.subprocess, "run", make_fake_run(calls)):
            res = srs.seed_one(self._cfg(), Path(d), "s", "u", "n", "p", 600, 0,
                               None, dry_run=True)
        self.assertTrue(res["ok"])
        self.assertEqual(calls, [])


class TestRaiseRc(unittest.TestCase):
    def _cfg(self):
        return {"_claude_path": "/fake/claude", "_tmux_path": "/fake/tmux"}

    def test_raise_ok(self):
        calls = []
        with mock.patch.object(srs.subprocess, "run", make_fake_run(calls)):
            ok, _ = srs.raise_rc(self._cfg(), "/proj", "review-x", "uuid-9",
                                 dry_run=False)
        self.assertTrue(ok)
        cmd = calls[0]
        self.assertIn("new-session", cmd)
        self.assertIn("/proj", cmd)
        self.assertIn("--resume uuid-9", cmd[-1])  # resume passed to claude

    def test_raise_fail(self):
        calls = []
        with mock.patch.object(srs.subprocess, "run",
                               make_fake_run(calls, rc_start_fail_names={"review-x"})):
            ok, reason = srs.raise_rc(self._cfg(), "/p", "review-x", "u",
                                      dry_run=False)
        self.assertFalse(ok)
        self.assertEqual(reason, "boom")


class TestTmuxAlive(unittest.TestCase):
    def test_alive_true_false(self):
        calls = []
        with mock.patch.object(srs.subprocess, "run",
                               make_fake_run(calls, alive_names={"review-live"})):
            self.assertTrue(srs.tmux_alive("/fake/tmux", "review-live"))
            self.assertFalse(srs.tmux_alive("/fake/tmux", "review-dead"))


class TestListRunSessions(unittest.TestCase):
    def test_filters_to_handles(self):
        listing = ("bs-rust_1: 1 windows (created X) (attached)\n"
                   "review-PR1-a: 1 windows (created Y)\n"
                   "review-PR1-b: 1 windows (created Z)\n")
        with mock.patch.object(srs.subprocess, "run",
                               lambda cmd, **kw: FakeProc(0, listing)):
            out = srs.list_run_sessions("/t", {"review-PR1-a", "review-PR1-b"})
        self.assertEqual(len(out), 2)
        self.assertTrue(all(l.startswith("review-PR1-") for l in out))
        self.assertFalse(any("bs-rust_1" in l for l in out))

    def test_empty_handles_makes_no_call(self):
        called = []
        with mock.patch.object(srs.subprocess, "run",
                               lambda cmd, **kw: called.append(cmd) or FakeProc(0)):
            self.assertEqual(srs.list_run_sessions("/t", set()), [])
        self.assertEqual(called, [])

    def test_no_server(self):
        with mock.patch.object(srs.subprocess, "run",
                               lambda cmd, **kw: FakeProc(returncode=1)):
            self.assertEqual(srs.list_run_sessions("/t", {"x"}), [])

    def test_none_of_ours_live(self):
        with mock.patch.object(srs.subprocess, "run",
                               lambda cmd, **kw: FakeProc(0, "other: 1 windows\n")):
            self.assertEqual(srs.list_run_sessions("/t", {"x"}), ["(none live)"])


class TestMainEndToEnd(unittest.TestCase):
    def _run_main(self, md_text, calls, argv_extra=(), **fake_kw):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = tmp / "comments.md"
            md.write_text(md_text, encoding="utf-8")
            cfg = write_temp_config(tmp)
            argv = ["prog", str(md), "--config", str(cfg),
                    "--project-dir", str(tmp), *argv_extra]
            fake = make_fake_run(calls, **fake_kw)
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(srs.subprocess, "run", fake):
                rc = srs.main()
            mapping = srs.read_mapping(tmp / "sessions" / "mapping.tsv")
            return rc, mapping

    def test_code_review_all_ok(self):
        calls = []
        rc, mapping = self._run_main(CODE_MD, calls)
        self.assertEqual(rc, 0)
        self.assertEqual(set(mapping), {"first-thing", "second.thing"})
        self.assertEqual(mapping["first-thing"]["tmux_session"],
                         "review-PR1695-first-thing")
        self.assertEqual(mapping["first-thing"]["name"], "PR#1695 - first-thing")
        self.assertEqual(mapping["first-thing"]["type"], "code-review")
        # dotted slug sanitized in handle
        self.assertEqual(mapping["second.thing"]["tmux_session"],
                         "review-PR1695-second-thing")

    def test_plan_review_ok(self):
        calls = []
        rc, mapping = self._run_main(PLAN_MD, calls)
        self.assertEqual(rc, 0)
        self.assertEqual(mapping["post-load-name-form"]["tmux_session"],
                         "review-plan-CIR-post-load-name-form")

    def test_decision_and_comments_path_wired_into_prompt(self):
        # The seed prompt must carry this run's own MD path and a decision path
        # derived from it (decisions/<slug>.md next to sessions/, both under the
        # MD's own directory), rather than a separately-invented path/timestamp.
        calls = []
        rc, _ = self._run_main(PLAN_MD, calls)
        self.assertEqual(rc, 0)
        prompt = next(c for c in calls if "-p" in c)[-1]
        self.assertNotIn(srs.PLACEHOLDER_SLUG, prompt)
        self.assertNotIn(srs.PLACEHOLDER_COMMENTS_FILE_PATH, prompt)
        self.assertNotIn(srs.PLACEHOLDER_DECISION_PATH, prompt)
        self.assertIn("comments.md", prompt)
        self.assertIn("decisions/post-load-name-form.md", prompt)

    def test_seed_failure_excluded_from_mapping(self):
        calls = []
        rc, mapping = self._run_main(
            CODE_MD, calls, fail_seed_names={"PR#1695 - first-thing"})
        self.assertEqual(rc, 1)  # a failure -> nonzero exit
        self.assertNotIn("first-thing", mapping)   # failed seed => no RC, no row
        self.assertIn("second.thing", mapping)     # sibling still raised

    def test_skip_alive_session(self):
        calls = []
        # first-thing already live -> must be skipped (never seeded/re-raised)
        rc, mapping = self._run_main(
            CODE_MD, calls, alive_names={"review-PR1695-first-thing"})
        self.assertEqual(rc, 0)
        seeded_names = [c[c.index("--name") + 1] for c in calls if "-p" in c]
        self.assertNotIn("PR#1695 - first-thing", seeded_names)
        self.assertIn("PR#1695 - second.thing", seeded_names)  # display name = raw slug

    def test_explicit_project_dir_skips_worktree_autodetect(self):
        # --project-dir is the operator overriding where sessions start; it
        # must not be second-guessed by a PR-branch worktree lookup.
        calls = []
        with mock.patch.object(srs, "find_pr_worktree") as fpw:
            rc, _ = self._run_main(CODE_MD, calls)
        self.assertEqual(rc, 0)
        fpw.assert_not_called()
        self.assertFalse(any("--worktree" in c for c in calls if "-p" in c))

    def test_worktree_autodetected_without_project_dir(self):
        calls = []
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = tmp / "comments.md"
            md.write_text(CODE_MD, encoding="utf-8")
            cfg = write_temp_config(tmp)
            argv = ["prog", str(md), "--config", str(cfg)]  # no --project-dir
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(srs.subprocess, "run", make_fake_run(calls)), \
                    mock.patch.object(srs, "git_root", return_value=tmp), \
                    mock.patch.object(srs, "find_pr_worktree",
                                      return_value="pr-1695") as fpw:
                rc = srs.main()
        self.assertEqual(rc, 0)
        fpw.assert_called_once()
        pr_id, repo_dir = fpw.call_args.args
        self.assertEqual(pr_id, "1695")
        self.assertEqual(repo_dir, str(tmp.resolve()))
        seed_cmds = [c for c in calls if "-p" in c]
        self.assertTrue(seed_cmds)
        for c in seed_cmds:
            self.assertEqual(c[c.index("--worktree") + 1], "pr-1695")

    def test_dry_run_writes_no_mapping_and_no_side_effects(self):
        calls = []
        rc, mapping = self._run_main(CODE_MD, calls, argv_extra=("--dry-run",))
        self.assertEqual(rc, 0)
        self.assertEqual(mapping, {})   # nothing persisted
        # has-session probing still runs (idempotency check precedes dry-run gate),
        # but no claude seed (-p) and no tmux new-session are invoked.
        self.assertFalse([c for c in calls if "-p" in c])
        self.assertFalse([c for c in calls if "new-session" in c])

    def test_idempotent_resume_without_reseed(self):
        # Pre-seed a mapping row, tmux dead -> should resume (raise) without seeding.
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = tmp / "comments.md"
            md.write_text(PLAN_MD, encoding="utf-8")
            cfg = write_temp_config(tmp)
            sess = tmp / "sessions"
            sess.mkdir()
            srs.write_mapping(sess / "mapping.tsv", {
                "post-load-name-form": {
                    "slug": "post-load-name-form", "uuid": "kept-uuid",
                    "tmux_session": "review-plan-CIR-post-load-name-form",
                    "name": "chart-implementation-remapping - post-load-name-form",
                    "type": "plan-review"}})
            calls = []
            argv = ["prog", str(md), "--config", str(cfg), "--project-dir", str(tmp)]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(srs.subprocess, "run", make_fake_run(calls)):
                rc = srs.main()
            self.assertEqual(rc, 0)
            self.assertEqual([c for c in calls if "-p" in c], [])  # no re-seed
            new_sess = next(c for c in calls if "new-session" in c)
            self.assertIn("--resume kept-uuid", new_sess[-1])  # reused UUID


class TestShippedTemplates(unittest.TestCase):
    """The shipped templates must carry every placeholder the script fills."""

    def test_placeholders_present(self):
        for name, extra in (("code-review.md", ()),
                            ("plan-review.md", (srs.PLACEHOLDER_PLAN_PATH,))):
            tpl = (srs.SKILL_DIR / "templates" / name).read_text(encoding="utf-8")
            for ph in (srs.PLACEHOLDER_COMMENT, srs.PLACEHOLDER_VERDICT_LANG,
                       srs.PLACEHOLDER_PROJECT_CONTEXT, srs.PLACEHOLDER_SLUG,
                       srs.PLACEHOLDER_COMMENTS_FILE_PATH,
                       srs.PLACEHOLDER_DECISION_PATH, *extra):
                self.assertIn(ph, tpl, f"{name} is missing {ph}")

    def test_shipped_config_defaults(self):
        cfg = json.loads((srs.SKILL_DIR / "config.json").read_text(encoding="utf-8"))
        # binaries unpinned so the skill works on any machine
        self.assertEqual(cfg["claude_path"], "")
        self.assertEqual(cfg["tmux_path"], "")
        self.assertEqual(cfg["verdict_language"], srs.DEFAULT_VERDICT_LANGUAGE)
        self.assertEqual(cfg["project_context"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
