#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/bin/clipboard-manager"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
PID_FILE="/tmp/clipboard-manager.pid"

# ─────────────────────────────────────────────
# 1. Detect desktop environment
# ─────────────────────────────────────────────

detect_de() {
    if [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
        echo "hyprland"
    elif [ "${XDG_CURRENT_DESKTOP:-}" = "GNOME" ]; then
        echo "gnome"
    elif [ -n "${WAYLAND_DISPLAY:-}" ]; then
        echo "wayland-other"
    else
        echo "x11"
    fi
}

DE=$(detect_de)
echo "Detected environment: $DE"

# ─────────────────────────────────────────────
# 2. Python validation
# ─────────────────────────────────────────────

echo ""
echo "Checking Python runtime..."

if ! "$PYTHON_BIN" -c "import gi" 2>/dev/null; then
    echo "✗ PyGObject missing in $PYTHON_BIN"
    exit 1
fi

echo "✓ Python OK"

# ─────────────────────────────────────────────
# 3. System dependencies
# ─────────────────────────────────────────────

echo ""
echo "Checking dependencies..."

if [ "$DE" = "hyprland" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
    command -v wl-paste &>/dev/null && echo "✓ wl-paste" || echo "✗ wl-paste"
    command -v wl-copy  &>/dev/null && echo "✓ wl-copy"  || echo "✗ wl-copy"
    command -v ydotool  &>/dev/null && echo "✓ ydotool"  || echo "✗ ydotool (optional)"
else
    command -v xclip   &>/dev/null && echo "✓ xclip"   || echo "✗ xclip"
    command -v xdotool &>/dev/null && echo "✓ xdotool" || echo "✗ xdotool"
fi

# ─────────────────────────────────────────────
# 4. Install files
# ─────────────────────────────────────────────

echo ""
echo "Installing to $INSTALL_DIR ..."

mkdir -p "$INSTALL_DIR"

cp -r "$SCRIPT_DIR/clipboard" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/ui" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/main.py" "$INSTALL_DIR/"

mkdir -p "$HOME/.config/clipboard-manager/themes"

THEME_DIR="$SCRIPT_DIR/ui/themes"

if ls "$THEME_DIR"/*.css >/dev/null 2>&1; then
    for f in "$THEME_DIR"/*.css; do
        cp "$f" "$HOME/.config/clipboard-manager/themes/" || true
    done
fi

echo "✓ Files installed"

# ─────────────────────────────────────────────
# 5. Autostart (GNOME/XDG)
# ─────────────────────────────────────────────

echo ""
echo "Setting up autostart..."

mkdir -p "$HOME/.config/autostart"

cat > "$HOME/.config/autostart/clipboard-manager.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Clipboard Manager
Exec="$PYTHON_BIN" $INSTALL_DIR/main.py
Icon=edit-paste
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "✓ Autostart configured"

# ─────────────────────────────────────────────
# 6. Desktop-specific setup
# ─────────────────────────────────────────────

echo ""

if [ "$DE" = "gnome" ]; then
    echo "GNOME detected → running gnome-setup.sh"
    export PYTHON_BIN INSTALL_DIR
    bash "$SCRIPT_DIR/shortcuts/gnome-setup.sh"

elif [ "$DE" = "hyprland" ]; then
    echo "Hyprland detected"

    HYPR_CONF="$HOME/.config/hypr/hyprland.conf"

    if [ -f "$HYPR_CONF" ]; then
        if ! grep -q "clipboard-manager" "$HYPR_CONF"; then
            {
                echo ""
                echo "# Clipboard Manager"
                echo "exec-once = $PYTHON_BIN $INSTALL_DIR/main.py"
                echo "bind = SUPER, V, exec, kill -USR1 \$(cat $PID_FILE)"
            } >> "$HYPR_CONF"

            echo "✓ Hyprland config updated"
        else
            echo "✓ Hyprland already configured"
        fi
    else
        echo "! Hyprland config not found"
    fi

else
    echo "Manual setup required:"
    echo "Bind SUPER+V → kill -USR1 \$(cat $PID_FILE)"
fi

# ─────────────────────────────────────────────
# 7. IMPORTANT: DO NOT START DAEMON HERE
# ─────────────────────────────────────────────

echo ""
echo "────────────────────────────────────────────"
echo " Clipboard Manager installed ✓"
echo ""
echo " IMPORTANT:"
echo " - Daemon is NOT started by installer"
echo " - Use autostart OR keybind OR manual run"
echo " - This prevents duplicate instances"
echo ""
echo " Install dir : $INSTALL_DIR"
echo " PID file    : $PID_FILE"
echo "────────────────────────────────────────────"