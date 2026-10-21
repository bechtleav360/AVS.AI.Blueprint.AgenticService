#!/bin/sh
# Claude Code PreToolUse hook (Bash): hold every `git commit` until the assistant has checked the
# commit for project names and says so with PROJECT_NAMES_REVIEWED=1 in front of the command.
#
# There is deliberately no list of forbidden names: such a list in a public repository would publish
# the names it is meant to keep out. The assistant reviews the commit itself and asks the user.
#
# Input: the tool call as JSON on stdin. Exit 0 lets the call run; exit 2 blocks it and hands
# stderr to the assistant.

input=$(cat)

# `git commit`, also after global options (`git -C dir commit`, `git -c k=v commit`); not `commit-tree`.
printf '%s' "$input" |
  grep -Eq 'git(([[:space:]]+-[Cc][[:space:]]+[^[:space:]]+)|([[:space:]]+--?[A-Za-z][-A-Za-z]*(=[^[:space:]]+)?))*[[:space:]]+commit([[:space:]]|$|["'\'';&|)])' ||
  exit 0

printf '%s' "$input" | grep -q 'PROJECT_NAMES_REVIEWED=1' && exit 0

cat >&2 <<'EOF'
Commit held: check it for project names first.

Review the staged diff (`git diff --cached`, new files included) and the commit message for any name
that could be the name of a project, product, customer, team or internal system -- typically the
context in which this change was made. This framework is public and used by many projects; such names
must not end up in its code, comments, tests, docs or commit messages.

- If you find one: stop. Show the user each name and where it occurs, and ask whether this specific
  name may be used. Go on only after an explicit yes; otherwise replace it with a generic description
  and stage the change.
- No new question is needed for a name the user approved explicitly in this conversation or in
  CLAUDE.md, for public open-source projects and libraries, or for this repository's own name.

Then run the same commit again with PROJECT_NAMES_REVIEWED=1 in front of it, for example
`PROJECT_NAMES_REVIEWED=1 git commit -F msg.txt`. Do not add the prefix without doing the review.
EOF
exit 2
