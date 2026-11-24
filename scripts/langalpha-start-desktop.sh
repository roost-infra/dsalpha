#!/bin/bash
set -euo pipefail

export DISPLAY=:99
state_dir="${XDG_RUNTIME_DIR:-$HOME/.cache}/langalpha-desktop"
install -d -m 700 "$state_dir"
exec 9>"$state_dir/start.lock"
flock -w 8 9
if xdpyinfo >/dev/null 2>&1; then
    exit 0
fi

nohup Xvfb "$DISPLAY" -screen 0 1280x800x24 -nolisten tcp </dev/null >"$state_dir/xvfb.log" 2>&1 9>&- &
for _ in {1..40}; do
    if xdpyinfo >/dev/null 2>&1; then
        nohup dbus-run-session -- openbox-session </dev/null >"$state_dir/desktop.log" 2>&1 9>&- &
        nohup tint2 </dev/null >"$state_dir/panel.log" 2>&1 9>&- &
        nohup xterm -title 'LangAlpha Linux' </dev/null >"$state_dir/terminal.log" 2>&1 9>&- &
        exit 0
    fi
    sleep 0.1
done
exit 1
