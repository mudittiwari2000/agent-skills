#!/usr/bin/env bash
# Resolve a GitLab MR, branch, or working tree into an isolated review worktree.
set -euo pipefail

REPOS_ROOT="${REPOS_ROOT:-$HOME/dev/repos}"
WT_ROOT="${WT_ROOT:-$HOME/.codex/mr-review/worktrees}"

die() { echo "ERROR: $*" >&2; exit 1; }

remove_review_worktree() {
  local wt="$1" owner repo
  case "$wt" in
    "$WT_ROOT"/*) ;;
    *) die "Refusing to remove path outside WT_ROOT '$WT_ROOT': $wt" ;;
  esac
  owner="$(git -C "$wt" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -n "$owner" ]]; then
    repo="$(dirname "$owner")"
    git -C "$repo" worktree remove --force "$wt" 2>/dev/null || rm -rf -- "$wt"
    git -C "$repo" worktree prune 2>/dev/null || true
  else
    rm -rf -- "$wt"
  fi
  rm -f -- "${wt}.diff"
  rm -f -- "${wt}.description.md"
}

if [[ "${1:-}" == "--cleanup" ]]; then
  wt="${2:?path required}"
  remove_review_worktree "$wt"
  echo "CLEANED=$wt"
  exit 0
fi

REF="${1:?Provide an MR URL, IID, branch, or --working-tree}"
MODE=""; PROJECT=""; IID=""; BRANCH=""
if [[ "$REF" == "--working-tree" ]]; then
  MODE="working-tree"
elif [[ "$REF" =~ ^https?://[^/]+/(.+)/-/merge_requests/([0-9]+) ]]; then
  MODE="mr"; PROJECT="${BASH_REMATCH[1]}"; IID="${BASH_REMATCH[2]}"
elif [[ "$REF" =~ ^!?([0-9]+)$ ]]; then
  MODE="mr"; IID="${BASH_REMATCH[1]}"
else
  MODE="branch"; BRANCH="$REF"
fi

norm_remote() { sed -E 's#^git@[^:]+:##; s#^https?://[^/]+/##; s#\.git$##' <<<"$1"; }

resolve_repo_from_project() {
  local want d url
  want="$(norm_remote "$1")"
  for d in "$REPOS_ROOT"/*/; do
    [[ -d "$d/.git" || -f "$d/.git" ]] || continue
    url="$(git -C "$d" remote get-url origin 2>/dev/null || true)"
    [[ -n "$url" && "$(norm_remote "$url")" == "$want" ]] && { echo "${d%/}"; return 0; }
  done
  return 1
}

if [[ -n "${REPO_DIR:-}" ]]; then
  REPO_DIR="${REPO_DIR%/}"
elif [[ -n "$PROJECT" ]]; then
  REPO_DIR="$(resolve_repo_from_project "$PROJECT")" || \
    die "No local clone under $REPOS_ROOT matches project '$PROJECT'. Set REPO_DIR=..."
else
  REPO_DIR="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  [[ -n "$REPO_DIR" ]] || die "Not inside a git repo and no REPO_DIR set."
fi
[[ -d "$REPO_DIR/.git" || -f "$REPO_DIR/.git" ]] || die "REPO_DIR '$REPO_DIR' is not a git repo."

cd "$REPO_DIR"
mkdir -p "$WT_ROOT"
echo "REPO_DIR=$REPO_DIR"
echo "MODE=$MODE"

repo_name="$(basename "$REPO_DIR")"

if [[ "$MODE" == "working-tree" ]]; then
  BRANCH="$(git symbolic-ref -q --short HEAD || echo HEAD)"
  BASE_SHA="$(git rev-parse HEAD)"
  HEAD_SHA="$BASE_SHA"
  tag="working-tree"
  WT="$WT_ROOT/${repo_name}__${tag}"
  [[ ! -e "$WT" ]] || remove_review_worktree "$WT"
  git worktree add --detach --force "$WT" "$BASE_SHA" >/dev/null 2>&1 || die "Failed to create working-tree snapshot"

  DIFF_FILE="${WT}.diff"
  git diff --binary HEAD > "$DIFF_FILE"
  if [[ -s "$DIFF_FILE" ]]; then
    git -C "$WT" apply "$DIFF_FILE" || die "Failed to apply tracked working-tree changes to snapshot"
  fi

  while IFS= read -r -d '' file; do
    mkdir -p "$WT/$(dirname "$file")"
    cp -Pp -- "$file" "$WT/$file"
    set +e
    git diff --no-index --binary -- /dev/null "$file" >> "$DIFF_FILE"
    status=$?
    set -e
    [[ "$status" -eq 0 || "$status" -eq 1 ]] || \
      die "Failed to create patch for untracked file '$file'"
  done < <(git ls-files --others --exclude-standard -z)

  echo "SOURCE_BRANCH=$BRANCH"
  echo "TARGET_BRANCH=WORKING_TREE"
  echo "BASE_SHA=$BASE_SHA"
  echo "HEAD_SHA=$HEAD_SHA"
  echo "HEAD_LABEL=${HEAD_SHA:0:12}+working-tree"
  echo "TITLE=Working tree: $BRANCH"
  echo "WEB_URL="
  echo "DESCRIPTION_FILE="
  echo "EXTERNAL_POSTING_ALLOWED=false"
  echo "WORKTREE=$WT"
  echo "DIFF_FILE=$DIFF_FILE"
  echo "--- CHANGED FILES ---"
  git -C "$WT" status --porcelain
  echo "--- DIFFSTAT ---"
  git apply --stat "$DIFF_FILE" 2>/dev/null || true
  exit 0
fi

TITLE=""; TARGET=""; WEB_URL=""; DESCRIPTION=""; json=""
RARG=(); [[ -n "$PROJECT" ]] && RARG=(-R "$PROJECT")
if [[ "$MODE" == "mr" ]]; then
  json="$(glab mr view "$IID" "${RARG[@]}" -F json 2>/dev/null)" || \
    die "glab could not read MR !$IID (project='${PROJECT:-<repo default>}'). Check 'glab auth status'."
elif [[ "$MODE" == "branch" ]]; then
  json="$(glab mr view "$BRANCH" -F json 2>/dev/null || true)"
fi

if [[ -n "$json" ]]; then
  IID="$(jq -r '.iid // .id // empty' <<<"$json")"
  BRANCH="$(jq -r '.source_branch' <<<"$json")"
  TARGET="$(jq -r '.target_branch' <<<"$json")"
  TITLE="$(jq -r '.title' <<<"$json")"
  WEB_URL="$(jq -r '.web_url' <<<"$json")"
  DESCRIPTION="$(jq -r '.description // empty' <<<"$json")"
elif [[ "$MODE" == "branch" ]]; then
  TITLE="$BRANCH"
fi

if git fetch --quiet origin "$BRANCH" 2>/dev/null; then
  HEAD_SHA="$(git rev-parse FETCH_HEAD)"
elif [[ -n "$IID" ]] && git fetch --quiet origin "refs/merge-requests/$IID/head" 2>/dev/null; then
  HEAD_SHA="$(git rev-parse FETCH_HEAD)"
elif git rev-parse --verify --quiet "$BRANCH^{commit}" >/dev/null; then
  HEAD_SHA="$(git rev-parse "$BRANCH^{commit}")"
else
  die "Could not resolve source branch '$BRANCH'."
fi

if [[ -z "$TARGET" ]]; then
  TARGET="${TARGET_BRANCH_OVERRIDE:-}"
fi
if [[ -z "$TARGET" ]]; then
  origin_head="$(git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  TARGET="${origin_head#origin/}"
fi
if [[ -z "$TARGET" ]]; then
  TARGET="$(git remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p')"
fi
if [[ -z "$TARGET" ]]; then
  if git show-ref --verify --quiet refs/remotes/origin/main; then TARGET="main"
  elif git show-ref --verify --quiet refs/remotes/origin/master; then TARGET="master"
  else die "Could not determine target branch; set TARGET_BRANCH_OVERRIDE."; fi
fi

git fetch --quiet origin "$TARGET" 2>/dev/null || true
if git rev-parse --verify --quiet "origin/$TARGET^{commit}" >/dev/null; then
  target_ref="origin/$TARGET"
elif git rev-parse --verify --quiet "$TARGET^{commit}" >/dev/null; then
  target_ref="$TARGET"
else
  die "Could not resolve target branch '$TARGET'."
fi
BASE_SHA="$(git merge-base "$HEAD_SHA" "$target_ref")" || die "Source and target have no merge base."

echo "MR_IID=$IID"
echo "TITLE=$TITLE"
echo "WEB_URL=$WEB_URL"
echo "SOURCE_BRANCH=$BRANCH"
echo "TARGET_BRANCH=$TARGET"
echo "BASE_SHA=$BASE_SHA"
echo "HEAD_SHA=$HEAD_SHA"
echo "HEAD_LABEL=${HEAD_SHA:0:12}"
[[ -n "$WEB_URL" && -n "$IID" ]] && echo "EXTERNAL_POSTING_ALLOWED=true" || echo "EXTERNAL_POSTING_ALLOWED=false"

tag="${IID:-$(echo "$BRANCH" | tr '/ ' '__')}"
WT="$WT_ROOT/${repo_name}__${tag}"
[[ ! -e "$WT" ]] || remove_review_worktree "$WT"
git worktree prune 2>/dev/null || true
git worktree add --detach --force "$WT" "$HEAD_SHA" >/dev/null 2>&1 || die "Failed to create worktree at $WT"
echo "WORKTREE=$WT"

DESCRIPTION_FILE="${WT}.description.md"
printf '%s\n' "$DESCRIPTION" > "$DESCRIPTION_FILE"
echo "DESCRIPTION_FILE=$DESCRIPTION_FILE"

DIFF_FILE="${WT}.diff"
git diff --binary "$BASE_SHA" "$HEAD_SHA" > "$DIFF_FILE"
echo "DIFF_FILE=$DIFF_FILE"
echo "--- CHANGED FILES ---"
git diff --name-status "$BASE_SHA" "$HEAD_SHA"
echo "--- DIFFSTAT ---"
git diff --stat "$BASE_SHA" "$HEAD_SHA"
