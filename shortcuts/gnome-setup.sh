#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${INSTALL_DIR:-$HOME/.local/bin/clipboard-manager}"

# Respect PYTHON_BIN if the caller (install.sh) already exported it.
# Previously this line unconditionally overwrote it with `command -v python3`,
# which could silently resolve to a different interpreter (e.g. linuxbrew's)
# than the one install.sh validated `gi` against.
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"

SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
ENTRY_SCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
NAME="Clipboard Manager"
BINDING="<Super>v"
COMMAND="bash -c 'pgrep -f main.py | xargs -r kill -USR1'"

################################################################################
# SYSTEMD USER SERVICE (replaces autostart .desktop)
################################################################################
echo "✓ Installing systemd user service..."

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"

SERVICE_FILE="$SYSTEMD_USER_DIR/clipboard-manager.service"
SERVICE_TEMPLATE="$(dirname "${BASH_SOURCE[0]}")/clipboard-manager.service"

sed \
    -e "s|__PYTHON_BIN__|$PYTHON_BIN|g" \
    -e "s|__INSTALL_DIR__|$APP_DIR|g" \
    "$SERVICE_TEMPLATE" > "$SERVICE_FILE"

# Remove the old autostart .desktop entry if present, to avoid a second
# instance racing the systemd-managed one at login.
rm -f "$HOME/.config/autostart/clipboard-manager.desktop"

systemctl --user daemon-reload
systemctl --user enable clipboard-manager.service

# Stop any manually-started instance and any stale lock before (re)starting
# under systemd, so we don't get "already running" from the old process.
pkill -f "$APP_DIR/main.py" 2>/dev/null || true
rm -f /tmp/clipboard-manager.lock
sleep 0.5

systemctl --user restart clipboard-manager.service
echo "✓ Service enabled and started"

################################################################################
# READ CURRENT KEYBINDINGS (SAFE)
################################################################################
CURRENT=$(gsettings get "$SCHEMA" custom-keybindings 2>/dev/null || echo "@as []")
if [[ "$CURRENT" == "@as []" ]]; then
    CURRENT=""
fi

################################################################################
# FIND EXISTING ENTRY
################################################################################
FOUND_PATH=""
PATHS=$(echo "$CURRENT" | grep -o "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom[0-9]\+/" || true)
for path in $PATHS; do
    name=$(gsettings get "${ENTRY_SCHEMA}:${path}" name 2>/dev/null || true)
    name="${name//\'/}"
    name="${name//\"/}"
    if [[ "$name" == "$NAME" ]]; then
        FOUND_PATH="$path"
        break
    fi
done

################################################################################
# CREATE ENTRY IF NEEDED
################################################################################
if [[ -z "$FOUND_PATH" ]]; then
    INDEX=0
    while :; do
        TEST="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom${INDEX}/"
        if ! echo "$PATHS" | grep -q "$TEST"; then
            FOUND_PATH="$TEST"
            break
        fi
        INDEX=$((INDEX + 1))
    done
    if [[ -z "$CURRENT" ]]; then
        NEW="['$FOUND_PATH']"
    else
        CLEAN="$CURRENT"
        CLEAN="${CLEAN%]}"
        NEW="$CLEAN, '$FOUND_PATH']"
    fi
    gsettings set "$SCHEMA" custom-keybindings "$NEW"
    echo "✓ Created shortcut entry"
else
    echo "✓ Existing shortcut found"
fi

################################################################################
# CONFIGURE KEYBINDING
################################################################################
BASE="${ENTRY_SCHEMA}:${FOUND_PATH}"
gsettings set "$BASE" name "$NAME"
gsettings set "$BASE" command "$COMMAND"
gsettings set "$BASE" binding "$BINDING"

################################################################################
# DONE
################################################################################
echo ""
echo "----------------------------------------"
echo " GNOME Clipboard Manager configured"
echo ""
echo " Python    : $PYTHON_BIN"
echo " Service   : systemctl --user status clipboard-manager.service"
echo " Shortcut  : $BINDING"
echo " Command   : $COMMAND"
echo " Path      : $FOUND_PATH"
echo "----------------------------------------"
