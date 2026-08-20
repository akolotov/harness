#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Create a fresh timestamped comments directory for save-review-comments.
# Every run gets its own new timestamped directory; nothing from a previous
# run is deleted or touched. Timestamp is `date +%y%m%d-%H%M`.
#
# Two modes, because the two review types have two different natural anchors:
#
#   --plan-file <path>   Implementation-plan review. For a plan file at
#                        <dir>/<stem>.<ext>, creates and prints
#                        <dir>/<stem>/comments/<timestamp>/ -- i.e. next to
#                        the plan itself, alongside the scratchpads directory
#                        made by implementation-plan-review. The plan file
#                        does NOT need to live under .ai/impl_plans; any local
#                        path works. This mode does not require git.
#
#   --pr-id <n>          Code review. Creates and prints
#                        <repo-root>/.ai/pr-review/<n>/comments/<timestamp>/.
#                        A numeric GitHub PR id has no filesystem anchor of its
#                        own, so this mode resolves the project root with
#                        `git rev-parse --show-toplevel` and therefore behaves
#                        the same in the principal checkout and in a linked
#                        git worktree. Override the base with --pr-review-dir.
#
# Usage: new_comments_dir.sh --plan-file <path>
#        new_comments_dir.sh --pr-id <numeric-id> [--pr-review-dir <path>]
# Output on success: absolute path of the new directory on stdout, nothing else.
# Output on failure: "error: <message>" on stderr.
# Exit codes: 2 = bad usage, or an invalid plan-file / pr-id
#             3 = plan file (or its parent directory) does not exist
#             4 = target directory path exists but is not a directory, or
#                 could not be created
#             5 = not inside a git repository (--pr-id mode only)

set -euo pipefail

lib_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../_lib" && pwd)"
source "$lib_dir/report_dir.sh"

usage="usage: $(basename "$0") --plan-file <path> | --pr-id <numeric-id> [--pr-review-dir <path>]"

plan_file=""
pr_id=""
pr_review_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan-file)
      [[ $# -ge 2 ]] || report_dir::die 2 "$1 requires a value"
      plan_file="$2"
      shift 2
      ;;
    --pr-id)
      [[ $# -ge 2 ]] || report_dir::die 2 "$1 requires a value"
      pr_id="$2"
      shift 2
      ;;
    --pr-review-dir)
      [[ $# -ge 2 ]] || report_dir::die 2 "$1 requires a value"
      pr_review_dir="$2"
      shift 2
      ;;
    *)
      report_dir::die 2 "$usage"
      ;;
  esac
done

if [[ -n "$plan_file" && -n "$pr_id" ]]; then
  report_dir::die 2 "--plan-file and --pr-id are mutually exclusive"
fi

if [[ -z "$plan_file" && -z "$pr_id" ]]; then
  report_dir::die 2 "$usage"
fi

if [[ -n "$pr_review_dir" && -z "$pr_id" ]]; then
  report_dir::die 2 "--pr-review-dir applies only to --pr-id mode"
fi

if [[ -n "$plan_file" ]]; then
  plan_dir="$(dirname -- "$plan_file")"
  plan_base="$(basename -- "$plan_file")"

  if [[ "$plan_base" == "" || "$plan_base" == "." || "$plan_base" == ".." ]]; then
    report_dir::die 2 "unsafe plan filename: $plan_file"
  fi

  if [[ ! -d "$plan_dir" ]]; then
    report_dir::die 3 "plan parent directory does not exist or is not a directory: $plan_dir"
  fi

  if [[ ! -f "$plan_file" ]]; then
    report_dir::die 3 "plan file does not exist or is not a file: $plan_file"
  fi

  plan_stem="$plan_base"
  if [[ "$plan_stem" == *.* && "$plan_stem" != .* ]]; then
    plan_stem="${plan_stem%.*}"
  fi

  if [[ -z "$plan_stem" || "$plan_stem" == "." || "$plan_stem" == ".." ]]; then
    report_dir::die 2 "unsafe comments base name derived from: $plan_base"
  fi

  report_dir::new "$plan_dir/$plan_stem" "comments"
  exit 0
fi

if [[ ! "$pr_id" =~ ^[0-9]+$ ]]; then
  report_dir::die 2 "invalid pr id '$pr_id' (expected a numeric GitHub PR id like '1695')"
fi

if [[ -z "$pr_review_dir" ]]; then
  if ! repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    report_dir::die 5 "not inside a git repository (run within the project checkout or a git worktree)"
  fi
  pr_review_dir="$repo_root/.ai/pr-review"
fi

report_dir::new "$pr_review_dir/$pr_id" "comments"
