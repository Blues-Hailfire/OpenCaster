#!/usr/bin/env bash
# OpenCaster setup for Raspberry Pi (Raspberry Pi OS):  bash setup-pi.sh
#
#   1. Checks the Pi: 64-bit OS, memory, desktop or Lite.
#   2. Installs the system packages OpenCaster needs (asks for sudo):
#      Python's venv, BlueZ, and the libraries Qt needs for the GUI.
#   3. Turns Bluetooth on and adds you to the bluetooth group.
#   4. Runs setup.sh, holding PySide6 to a version this OS can run
#      (Bookworm's glibc 2.36 stops at PySide6 6.8.0; Trixie takes the latest).
#   5. Turns on passive mode (keep scanning, connect every wand in range).
#   6. Starts OpenCaster at boot: the GUI when the desktop logs in (with
#      desktop auto-login), or headless as the `opencaster` system service.
#
# The GUI needs 64-bit Raspberry Pi OS with the desktop, and a Pi 4 or 5
# (2 GB or more).  Otherwise OpenCaster is set up headless: casting, duels,
# wand lights and buzz, and the local API, run from the terminal.
#
# Safe to run again.  Run it as yourself, not with sudo.
# Options: --gui, --headless (instead of choosing automatically),
#          --no-apt (skip system packages), --no-autostart, --no-passive,
#          and setup.sh's --venv DIR, --no-launcher, --no-media
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/OpenCaster/venv"   # setup.sh's default
MODE=""
APT=1
AUTOSTART=1
PASSIVE=1
PASS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --gui) MODE=gui; shift ;;
        --headless) MODE=headless; shift ;;
        --no-apt) APT=0; shift ;;
        --no-autostart) AUTOSTART=0; shift ;;
        --no-passive) PASSIVE=0; shift ;;
        --venv) VENV="$2"; PASS+=("$1" "$2"); shift 2 ;;
        --no-launcher|--no-media) PASS+=("$1"); shift ;;
        *) echo "unknown option: $1"; exit 2 ;;
    esac
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
fail() { printf '\nSetup stopped: %s\n' "$*" >&2; exit 1; }
ask()  {   # yes unless answered no; no terminal to ask: no
    local answer
    [[ -t 0 ]] || return 1
    read -r -p "$* [Y/n] " answer || return 1
    [[ -z "$answer" || "$answer" =~ ^[Yy] ]]
}
version_ge() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" == "$2" ]]; }

[[ $EUID -ne 0 ]] || fail "run this as your normal user (it uses sudo where it needs to)."
[[ "$(uname)" == "Linux" ]] || fail "this is for Raspberry Pi OS - use setup.sh on other systems."

step "Checking this Raspberry Pi"
MODEL="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)"
# userland, not the kernel: 32-bit Pi OS boots a 64-bit kernel on a Pi 4/5
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
BITS64=0; [[ "$ARCH" == "arm64" || "$ARCH" == "aarch64" ]] && BITS64=1
MEM_MB=$(( $(awk '/^MemTotal:/ {print $2}' /proc/meminfo) / 1024 ))
GLIBC="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')"
OS="$(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}")"
say "  ${MODEL:-not a Raspberry Pi?}"
say "  $OS, $ARCH, ${MEM_MB} MB, glibc ${GLIBC:-?}"
[[ "$MODEL" == *"Raspberry Pi"* ]] || say "  (this doesn't look like a Pi - carrying on anyway)"
CODENAME="$(. /etc/os-release 2>/dev/null && echo "${VERSION_CODENAME:-}")"
if [[ "$CODENAME" == "buster" || "$CODENAME" == "bullseye" ]]; then
    fail "Raspberry Pi OS $CODENAME is too old: OpenCaster needs Python 3.11+, which comes with
Bookworm and later.  Back up anything you need from this card, then flash the current
Raspberry Pi OS (64-bit) with Raspberry Pi Imager and run this again."
fi

DESKTOP=0
[[ "$(systemctl get-default 2>/dev/null || true)" == "graphical.target" ]] && DESKTOP=1
if [[ -z "$MODE" ]]; then
    if [[ $BITS64 -eq 1 && $DESKTOP -eq 1 && $MEM_MB -ge 1800 ]]; then
        MODE=gui
    else
        MODE=headless
    fi
fi
if [[ "$MODE" == "gui" ]]; then
    [[ $BITS64 -eq 1 ]] \
        || fail "the GUI needs 64-bit Raspberry Pi OS (PySide6 has no 32-bit build). Re-run with --headless, or reinstall the 64-bit OS."
    [[ $DESKTOP -eq 1 ]] || say "  No desktop starts at boot (Lite?) - the GUI needs one to show its window."
    [[ $MEM_MB -ge 1800 ]] || say "  Under 2 GB of memory: the GUI may be slow."
    say "Setting up: the GUI"
else
    say "Setting up: headless (the terminal; no GUI)"
    [[ $BITS64 -eq 1 ]] || say "  32-bit OS: headless only."
fi

if [[ $APT -eq 1 ]]; then
    step "Installing system packages (sudo)"
    PKGS=(python3 python3-venv python3-pip bluez rfkill)
    [[ $BITS64 -eq 1 ]] || PKGS+=(libopenblas0-pthread libgfortran5 libatomic1)   # piwheels numpy/scipy link to these
    if [[ "$MODE" == "gui" ]]; then
        # Qt's xcb/wayland platform plugins and Qt Multimedia's sound output
        PKGS+=(libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0
               libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0
               libxcb-xkb1 libpulse0)
    fi
    sudo apt-get update || fail "apt-get update failed - check the network connection."
    sudo apt-get install -y "${PKGS[@]}" || fail "couldn't install the system packages above."
fi

step "Bluetooth"
sudo rfkill unblock bluetooth 2>/dev/null || true
sudo systemctl enable --now bluetooth >/dev/null 2>&1 || say "  couldn't start the bluetooth service."
if id -nG "$USER" | tr ' ' '\n' | grep -qx bluetooth; then
    say "  $USER is in the bluetooth group"
else
    sudo usermod -aG bluetooth "$USER" && say "  added $USER to the bluetooth group (takes effect at your next login)"
fi
if compgen -G "/sys/class/bluetooth/hci*" >/dev/null; then
    for hci in /sys/class/bluetooth/hci*; do say "  adapter: ${hci##*/}"; done
else
    say "  No Bluetooth adapter found.  Pi 3, 4, 5, 400 and Zero W/2 W have one built in;"
    say "  otherwise plug in a USB Bluetooth 4.0+ adapter.  Setup carries on."
fi

# PySide6 >= 6.8.1 needs glibc 2.39 on 64-bit ARM; Bookworm has 2.36.
if [[ "$MODE" == "gui" && -n "$GLIBC" ]] && ! version_ge "$GLIBC" 2.39; then
    CONSTRAINTS="$(mktemp)"
    trap 'rm -f "$CONSTRAINTS"' EXIT
    printf '%s\n' 'PySide6<6.8.1' 'PySide6-Essentials<6.8.1' 'PySide6-Addons<6.8.1' > "$CONSTRAINTS"
    export PIP_CONSTRAINT="$CONSTRAINTS"
    say ""
    say "glibc $GLIBC: holding PySide6 below 6.8.1 (the newest build this OS can run)."
fi

if [[ "$MODE" == "headless" ]]; then
    PASS+=(--headless)
    # headless OpenCaster plays no sounds on Linux, so the media pack would sit unused
    [[ " ${PASS[*]} " == *" --no-media "* ]] || PASS+=(--no-media)
fi
bash "$REPO/setup.sh" "${PASS[@]}"
PY="$VENV/bin/python"

if [[ $PASSIVE -eq 1 ]]; then
    step "Passive mode"
    (cd "$REPO" && "$PY" -c 'from opencaster import paths
from opencaster.settings import Settings
Settings(paths.SETTINGS_FILE).passive_mode = True
print("  on: OpenCaster keeps scanning and connects every wand in range")')
fi

SERVICE=/etc/systemd/system/opencaster.service
AUTOSTART_FILE="$HOME/.config/autostart/opencaster.desktop"
step "Start at boot"
# only one copy may hold the wands: clear whichever kind this mode doesn't use
if [[ "$MODE" == "gui" || $AUTOSTART -eq 0 ]] && [[ -f "$SERVICE" ]]; then
    sudo systemctl disable --now opencaster >/dev/null 2>&1 || true
    sudo rm -f "$SERVICE" && sudo systemctl daemon-reload
    say "  removed the headless service"
fi
if [[ "$MODE" == "headless" || $AUTOSTART -eq 0 ]] && [[ -f "$AUTOSTART_FILE" ]]; then
    rm -f "$AUTOSTART_FILE"
    say "  removed the desktop autostart entry"
fi
# a headless install has no app-menu entry (one left from a GUI install would start nothing visible)
[[ "$MODE" == "gui" ]] || rm -f "$HOME/.local/share/applications/opencaster.desktop"

if [[ $AUTOSTART -eq 0 ]]; then
    say "  off (--no-autostart)"
elif [[ "$MODE" == "gui" ]]; then
    mkdir -p "$(dirname "$AUTOSTART_FILE")"
    cat > "$AUTOSTART_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=OpenCaster
Comment=Cast spells with your Magic Caster wand
Exec="$PY" "$REPO/OpenCaster_GUI.py"
Path=$REPO
Icon=$REPO/opencaster/gui/assets/opencaster-icon-1c-dark.svg
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    say "  the GUI opens when the desktop logs in ($AUTOSTART_FILE)"
    if command -v raspi-config >/dev/null 2>&1 && \
       ! grep -qs '^autologin-user=' /etc/lightdm/lightdm.conf; then
        say "  The desktop doesn't log in by itself, so OpenCaster would wait for you to log in."
        if ask "  Log in to the desktop automatically at boot?"; then
            sudo raspi-config nonint do_boot_behaviour B4 && say "  desktop auto-login on"
        fi
    fi
else
    sudo tee "$SERVICE" >/dev/null <<EOF
[Unit]
Description=OpenCaster (Magic Caster wands, headless)
Wants=bluetooth.target
After=bluetooth.target

[Service]
User=$USER
WorkingDirectory=$REPO
ExecStart="$PY" -m opencaster
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable --now opencaster >/dev/null 2>&1 \
        && say "  the opencaster service is running, and starts at every boot" \
        || say "  couldn't start the opencaster service - see: systemctl status opencaster"
fi

say ""
if [[ "$MODE" == "headless" ]]; then
    if [[ $AUTOSTART -eq 1 ]]; then
        say "Watch it:  journalctl -u opencaster -f   (hold all four pads, draw a spell, release)"
        say "Stop it:   sudo systemctl stop opencaster   (before running ~/.local/bin/opencaster by hand,"
        say "           e.g. --duel; only one copy can hold the wands)"
    else
        say "Try it:  ~/.local/bin/opencaster        (hold all four pads, draw a spell, release)"
        say "         ~/.local/bin/opencaster --duel  (two wands)"
    fi
else
    say "If the window doesn't open under Wayland, try:  QT_QPA_PLATFORM=xcb ~/.local/bin/opencaster"
fi
if ! id -nG | tr ' ' '\n' | grep -qx bluetooth; then
    say "Log out and back in (or reboot) first, so the bluetooth group applies."
fi
