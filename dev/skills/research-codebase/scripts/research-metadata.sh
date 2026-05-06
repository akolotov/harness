#!/bin/bash
set -euo pipefail

slug=""
research_target_root=""
research_dir=""
invocation_root="$(pwd)"
workspace_root="$invocation_root"
researcher="${RESEARCHER:-AI Agent}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --topic)
      echo "Unknown argument: --topic" >&2
      echo "Use --slug with a short 2-4 word filename slug instead." >&2
      exit 1
      ;;
    --slug)
      slug="${2:-}"
      shift 2
      ;;
    --research-target-root)
      research_target_root="${2:-}"
      shift 2
      ;;
    --research-dir)
      research_dir="${2:-}"
      shift 2
      ;;
    --researcher)
      researcher="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$research_target_root" ]]; then
  research_target_root="$invocation_root"
fi

if git -C "$invocation_root" rev-parse --show-toplevel >/dev/null 2>&1; then
  workspace_root="$(git -C "$invocation_root" rev-parse --show-toplevel)"
fi

research_target_root="$(cd "$research_target_root" && pwd)"

if [[ -z "$research_dir" ]]; then
  research_dir="$workspace_root/.ai/research"
fi

case "$research_dir" in
  /*) ;;
  ~/*)
    research_dir="${HOME}/${research_dir#~/}"
    ;;
  *)
    research_dir="${workspace_root}/${research_dir#./}"
    ;;
esac

if [[ -n "$slug" ]]; then
  slug="$(
    printf '%s' "$slug" \
      | tr '[:upper:]' '[:lower:]' \
      | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-{2,}/-/g'
  )"
else
  slug="research"
fi

if [[ -z "$slug" ]]; then
  slug="research"
fi

timestamp_raw="$(date '+%Y-%m-%dT%H:%M:%S%z')"
timestamp_iso="$(printf '%s' "$timestamp_raw" | sed -E 's/([+-][0-9]{2})([0-9]{2})$/\1:\2/')"
today="$(date '+%Y-%m-%d')"
time_slug="$(date '+%H-%M')"

target_git_available="false"
target_git_root=""
target_git_commit=""
target_git_branch=""
target_git_remote=""

if git -C "$research_target_root" rev-parse --show-toplevel >/dev/null 2>&1; then
  target_git_available="true"
  target_git_root="$(git -C "$research_target_root" rev-parse --show-toplevel)"
  target_git_commit="$(git -C "$research_target_root" rev-parse HEAD)"
  target_git_branch="$(git -C "$research_target_root" branch --show-current)"
  target_git_remote="$(git -C "$research_target_root" remote get-url origin 2>/dev/null || true)"
fi

target_project_name="$(basename "$research_target_root")"
note_basename="${today}-${time_slug}-${slug}.md"
note_path="${research_dir}/${note_basename}"

cat <<EOF
DATE_ISO=${timestamp_iso}
DATE=${today}
RESEARCHER=${researcher}
TARGET_PROJECT_NAME=${target_project_name}
TARGET_PROJECT_ROOT=${research_target_root}
WORKSPACE_ROOT=${workspace_root}
RESEARCH_DIR=${research_dir}
SLUG=${slug}
NOTE_BASENAME=${note_basename}
NOTE_PATH=${note_path}
TARGET_GIT_AVAILABLE=${target_git_available}
TARGET_GIT_ROOT=${target_git_root}
TARGET_GIT_COMMIT=${target_git_commit}
TARGET_GIT_BRANCH=${target_git_branch}
TARGET_GIT_REMOTE=${target_git_remote}
EOF
