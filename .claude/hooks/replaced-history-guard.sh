#!/bin/sh
# Claude Code PreToolUse hook (Bash): refuse a `git push` that would publish history replaced on
# 2026-10-21. Every replaced commit descends from REPLACED_ROOT, so it is enough to ask whether a
# pushed branch contains that one commit. CI refuses the same on every branch (job "No replaced
# history"); this hook says so before anything leaves the machine.
#
# Checked: every local branch the command names (also as a refspec source, `+src:dst`); with
# --all or --mirror every local branch; when the command names no local branch, the current one.
# The repository is the one given by `git -C <dir>` or a leading `cd <dir>`, else the project.
# A repository without REPLACED_ROOT cannot push it, so the hook lets the command run.
#
# The hook runs before the user approves the command, so it never runs git in a directory the
# command merely names: only the project and directories inside it are checked, everything else is
# let through unchecked (CI still refuses it). Its git calls also refuse lazy fetches and implicit
# bare repositories, so not even a crafted repository inside the project can make git run a command.
#
# Input: the tool call as JSON on stdin. Exit 0 lets the call run; exit 2 blocks it and hands
# stderr to the assistant.

REPLACED_ROOT=1c2098c131ea654c850dccd2c7c627dab2e26f4a

input=$(cat)

# `git push`, also after global options (`git -C dir push`, `git -c k=v push`).
printf '%s' "$input" |
  grep -Eq 'git(([[:space:]]+-[Cc][[:space:]]+[^[:space:]]+)|([[:space:]]+--?[A-Za-z][-A-Za-z]*(=[^[:space:]]+)?))*[[:space:]]+push([[:space:]]|$|["'\'';&|)])' ||
  exit 0

root=$(cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null && pwd -P) || exit 0

# The repository: `git -C <dir>`, else a leading `cd <dir>`, else the project. JSON-escaped
# backslashes (Windows paths) become slashes; paths with spaces are not recognised (-> the project).
dir=$(printf '%s' "$input" | grep -Eo 'git[[:space:]]+-C[[:space:]]+[^[:space:];&|]+' | head -n 1 | sed -E 's/^git[[:space:]]+-C[[:space:]]+//')
[ -n "$dir" ] || dir=$(printf '%s' "$input" | grep -Eo '"command":[[:space:]]*"cd[[:space:]]+[^[:space:];&|]+' | head -n 1 | sed -E 's/^"command":[[:space:]]*"cd[[:space:]]+//')
dir=$(printf '%s' "$dir" | sed 's#\\\\#/#g' | tr -d '"'\')
if [ -n "$dir" ]; then
  dir=$(cd "$dir" 2>/dev/null && pwd -P) || exit 0
  case "$dir/" in
    "$root"/*) ;;
    *) exit 0 ;;
  esac
else
  dir=$root
fi

g() {
  GIT_NO_LAZY_FETCH=1 git -c safe.bareRepository=explicit -C "$dir" "$@"
}

g cat-file -e "$REPLACED_ROOT^{commit}" 2>/dev/null || exit 0

# Each push's own arguments: from `push` to the next `;`, `&`, `|`, line break or end of the command,
# so that names and options of the other commands in a chain do not count.
segments=$(printf '%s' "$input" | grep -Eo '[[:space:]]push([[:space:]][^;&|"]*)?' | sed 's/\\n.*//')

branches=""
set -f
old_ifs=$IFS
IFS='
'
for seg in $segments; do
  IFS=$old_ifs
  # Deleting a remote branch publishes nothing.
  printf '%s' "$seg" | grep -Eq '[[:space:]](--delete|-d)([[:space:]]|$)' && continue
  if printf '%s' "$seg" | grep -Eq '[[:space:]]--(all|mirror)([[:space:]]|$)'; then
    branches="$branches $(g for-each-ref --format='%(refname:short)' refs/heads | tr '\n' ' ')"
    continue
  fi
  named=""
  for tok in $(printf '%s' "$seg" | tr -cs 'A-Za-z0-9._/+:-' '\n'); do
    src=${tok#+}
    src=${src%%:*}
    [ -n "$src" ] && g show-ref --verify --quiet "refs/heads/$src" && named="$named $src"
  done
  # Only tags: origin refuses to move an existing tag without --force, so nothing old gets through.
  [ -n "$named" ] || ! printf '%s' "$seg" | grep -Eq '[[:space:]]--tags([[:space:]]|$)' || continue
  [ -n "$named" ] || named=$(g symbolic-ref --quiet --short HEAD || echo HEAD)
  branches="$branches $named"
done
IFS=$old_ifs
set +f

found=""
for b in $branches; do
  g merge-base --is-ancestor "$REPLACED_ROOT" "$b" 2>/dev/null && found="$found $b"
done
[ -n "$found" ] || exit 0

cat >&2 <<EOF
Push refused:$found still carries history that was replaced on 2026-10-21 to remove internal
project names (it descends from $REPLACED_ROOT). Pushing it would publish those names again, and
CI refuses such a branch anyway.

Tell the user; do not try to get around this. To keep the branch's own work, move its commits onto
the new history -- see "Replaced history" in CLAUDE.md.
EOF
exit 2
