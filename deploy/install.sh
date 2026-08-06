#!/usr/bin/env bash
# deploy/install.sh — install or uninstall the five com.finance.* LaunchAgents.
#
# Usage:
#   deploy/install.sh install     # (default) copy plists + bootstrap all five
#   deploy/install.sh uninstall   # bootout all five, leave copied plists in place
#
# Idempotent: re-running `install` first boots out any already-loaded agent
# (ignoring "not found" errors) then bootstraps fresh — safe to re-run after
# editing a plist (e.g. after filling secrets or relocating the DB).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_SRC_DIR="$REPO_ROOT/deploy/launchd"
PLIST_DST_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/finance"
UID_GID="gui/$(id -u)"

AGENTS=(
  com.finance.web
  com.finance.bot
  com.finance.worker
  com.finance.ollama
  com.finance.scheduler
)

action="${1:-install}"

check_no_placeholder_secrets() {
  local found=0
  for name in "${AGENTS[@]}"; do
    local plist="$PLIST_SRC_DIR/${name}.plist"
    if [[ -f "$plist" ]] && grep -q "__FILL_ME__" "$plist"; then
      echo "ERROR: $plist still contains __FILL_ME__ — fill in real secrets before installing." >&2
      found=1
    fi
  done
  if [[ "$found" -eq 1 ]]; then
    echo "Refusing to install with placeholder secrets present. See DEPLOY.md 'One-time setup'." >&2
    exit 1
  fi
}

do_uninstall() {
  echo "Booting out all com.finance.* LaunchAgents..."
  for name in "${AGENTS[@]}"; do
    launchctl bootout "$UID_GID/$name" 2>/dev/null || echo "  (not loaded: $name)"
  done
}

do_install() {
  check_no_placeholder_secrets

  echo "Creating log directory: $LOG_DIR"
  mkdir -p "$LOG_DIR"

  echo "Creating LaunchAgents directory: $PLIST_DST_DIR"
  mkdir -p "$PLIST_DST_DIR"

  echo "Copying plists into $PLIST_DST_DIR ..."
  for name in "${AGENTS[@]}"; do
    cp "$PLIST_SRC_DIR/${name}.plist" "$PLIST_DST_DIR/${name}.plist"
  done

  echo "Bootout-then-bootstrap each agent (idempotent)..."
  for name in "${AGENTS[@]}"; do
    launchctl bootout "$UID_GID/$name" 2>/dev/null || true
    echo "  bootstrap $name"
    launchctl bootstrap "$UID_GID" "$PLIST_DST_DIR/${name}.plist"
  done

  echo
  echo "Installed. Verify each agent with:"
  for name in "${AGENTS[@]}"; do
    echo "  launchctl print $UID_GID/$name | head -5"
  done
  echo
  echo "To uninstall: deploy/install.sh uninstall"
}

case "$action" in
  install)
    do_install
    ;;
  uninstall)
    do_uninstall
    ;;
  *)
    echo "Usage: $0 [install|uninstall]" >&2
    exit 1
    ;;
esac
