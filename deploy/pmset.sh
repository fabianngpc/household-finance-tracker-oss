#!/usr/bin/env bash
# deploy/pmset.sh — configure macOS power management for 24/7 unattended
# operation. Run once (or after any macOS update resets defaults).
#
# Requires sudo (pmset -a writes system-wide power settings).
set -euo pipefail

echo "Applying no-sleep / wake-on-net / auto-restart power settings..."
sudo pmset -a sleep 0 disksleep 0 womp 1 autorestart 1 powernap 0

# Optional: hard-disable idle sleep entirely. Recommended for a headless
# Mac mini with no local keyboard/mouse interaction expected. Uncomment if
# `pmset -g` still shows sleep triggering (e.g. via lid/display heuristics
# on machines with a display attached).
# sudo pmset -a disablesleep 1

echo
echo "Verifying current power settings:"
pmset -g

echo
echo "Expect to see: sleep 0, disksleep 0, womp 1, autorestart 1, powernap 0."
echo "If 'sleep' is not 0, re-run this script or check for a conflicting"
echo "power-management profile (MDM, third-party tool)."
