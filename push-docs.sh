#!/bin/bash
# Push the new docs/ files to GitHub and clean up the now-unused setup-github.sh.
# Run from the repo root: bash push-docs.sh
#
# Auth: the Mac Keychain should have saved your token after the initial push,
# so this should not prompt for credentials.

set -e

echo "==> Removing one-shot setup-github.sh (it served its purpose)"
git rm -f setup-github.sh 2>/dev/null || rm -f setup-github.sh

echo ""
echo "==> Staging all changes (docs/, README updates, push-docs.sh, anything else not gitignored)"
git add -A

echo ""
echo "==> Files about to be committed:"
git diff --cached --name-status

echo ""
echo "==> Safety check: verifying .env is NOT being committed"
if git diff --cached --name-only | grep -E "(^|/)\.env$" >/dev/null; then
  echo "    XX FAILED: .env file is staged for commit. ABORTING."
  exit 1
fi
echo "    .env correctly excluded."

echo ""
echo "==> Committing"
git commit -q -m "docs: add full docs/ suite (INSTALL, AWS_KUBECOST_SETUP, CONFIGURATION, ARCHITECTURE, OPERATIONS, SECURITY, TROUBLESHOOTING, LIMITATIONS); link from README; remove one-shot setup script"
echo "    $(git log -1 --oneline)"

echo ""
echo "==> Pushing to GitHub"
git push

echo ""
echo "==> Done. The 7 README documentation links should now resolve."
echo "==> Visit: https://github.com/moizl599/Steward"
