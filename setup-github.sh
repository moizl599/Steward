#!/bin/bash
# One-shot script to push Steward to GitHub.
# Run from the repo root: bash setup-github.sh
#
# It will:
#   1. Clean up any half-initialized git state.
#   2. Re-init git fresh, configure user, stage everything.
#   3. Verify .env is excluded from the commit (refuses to push if .env would leak).
#   4. Commit with a sensible message.
#   5. Force-push to your GitHub repo, replacing whatever's there now.
#
# Edit the REMOTE_URL below if your GitHub repo is at a different path.

set -e

REMOTE_URL="https://github.com/moizl599/steward.git"
COMMIT_MSG="Initial commit: Steward v0.1.0 research preview"

echo "==> Step 1/6 — Cleaning up any half-initialized git state"
rm -rf .git
echo "    .git removed (or didn't exist)"

echo ""
echo "==> Step 2/6 — Initializing fresh git repo"
git init -q
git branch -M main
git config user.email "moizlakdawala97@gmail.com"
git config user.name "Moiz Lakdawala"
echo "    initialized as user: $(git config user.name) <$(git config user.email)>"

echo ""
echo "==> Step 3/6 — Staging files (respecting .gitignore)"
git add .
STAGED_COUNT=$(git diff --cached --name-only | wc -l | tr -d ' ')
echo "    $STAGED_COUNT files staged"

echo ""
echo "==> Step 4/6 — Safety check: verifying .env is NOT being committed"
if git diff --cached --name-only | grep -E "(^|/)\.env$" >/dev/null; then
  echo "    XX FAILED: .env file is staged for commit. ABORTING."
  echo "    Check your .gitignore and unstage with: git reset .env"
  exit 1
fi
echo "    .env correctly excluded — your encryption key is safe."

echo ""
echo "==> Step 5/6 — Committing"
git commit -q -m "$COMMIT_MSG"
echo "    committed: $(git log -1 --oneline)"

echo ""
echo "==> Step 6/6 — Pushing to GitHub (force, to replace existing repo state)"
echo "    Remote: $REMOTE_URL"
echo "    Note: this will overwrite the current GitHub state. The screenshots"
echo "    you uploaded via the web UI will be replaced with the same files at"
echo "    the correct path (docs/screenshots/) from your local copy."
echo ""
git remote add origin "$REMOTE_URL"
git push -u origin main --force

echo ""
echo "==> Done. Visit your repo: ${REMOTE_URL%.git}"
echo "==> The README should now render with all five screenshots inline."
