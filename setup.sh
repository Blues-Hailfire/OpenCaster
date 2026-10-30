#!/usr/bin/env bash
# OpenCaster setup for macOS and Linux:  bash setup.sh
#
#   1. Finds Python 3.11 or newer.
#   2. Creates a private environment outside this folder:
#        macOS  ~/Library/Application Support/OpenCaster/venv
#        Linux  ${XDG_DATA_HOME:-~/.local/share}/OpenCaster/venv
#   3. Installs (or updates) the packages in requirements.txt.
#   4. Adds an `opencaster` launcher (and an app-menu entry on Linux).
#   5. Offers to download the media pack (each spell's sounds and videos) into
#      media/, if it isn't there yet.
#
# Safe to run again (an interrupted media download resumes).
# Options: --venv DIR, --no-launcher, --no-media,
#          --headless (no GUI: skips PySide6; the launcher runs `python -m opencaster`)
# Raspberry Pi: use setup-pi.sh, which prepares Bluetooth and then runs this.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(uname)" == "Darwin" ]]; then
    BASE="$HOME/Library/Application Support/OpenCaster"
else
    BASE="${XDG_DATA_HOME:-$HOME/.local/share}/OpenCaster"
fi
VENV="$BASE/venv"
LAUNCHER=1
MEDIA=1
HEADLESS=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --venv) VENV="$2"; shift 2 ;;
        --no-launcher) LAUNCHER=0; shift ;;
        --no-media) MEDIA=0; shift ;;
        --headless) HEADLESS=1; shift ;;
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

step "Looking for Python 3.11 or newer"
PY=""
for cand in python3.13 python3.12 python3.14 python3.11 python3 python; do
    if command -v "$cand" >/dev/null 2>&1 &&
       "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        PY="$(command -v "$cand")"; break
    fi
done
if [[ -z "$PY" ]]; then
    if [[ "$(uname)" == "Darwin" ]]; then
        say "Install Python from https://www.python.org/downloads/ (or: brew install python@3.13)."
    else
        say "Install Python 3.11+ and its venv module, e.g. sudo apt install python3 python3-venv"
    fi
    fail "Python 3.11 or newer is needed."
fi
say "Using $("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])') at $PY"

step "Preparing the OpenCaster environment"
if [[ -x "$VENV/bin/python" ]] && ! "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    say "The existing environment is broken or too old; rebuilding it."
    rm -rf "$VENV"
fi
if [[ ! -x "$VENV/bin/python" ]]; then
    mkdir -p "$(dirname "$VENV")"
    "$PY" -m venv "$VENV" || fail "couldn't create $VENV (on Debian/Ubuntu: sudo apt install python3-venv)."
fi

step "Installing packages (the first time downloads a few hundred MB)"
"$VENV/bin/python" -m pip install --upgrade pip --disable-pip-version-check --quiet
REQS="$REPO/requirements.txt"
IMPORTS='import bleak, numpy, scipy, PySide6.QtMultimedia, PySide6.QtSvg'
if [[ $HEADLESS -eq 1 ]]; then
    REQS="$(mktemp)"
    trap 'rm -f "$REQS"' EXIT
    grep -vi '^pyside6' "$REPO/requirements.txt" > "$REQS"
    IMPORTS='import bleak, numpy, scipy'
fi
"$VENV/bin/python" -m pip install --upgrade --disable-pip-version-check -r "$REQS" \
    || fail "package installation failed - see the messages above."
"$VENV/bin/python" -c "$IMPORTS" \
    || fail "the packages installed but don't import - try running setup again."

RUN="$BASE/opencaster"
if [[ $HEADLESS -eq 1 ]]; then
    START="-m opencaster"
else
    START="\"$REPO/OpenCaster_GUI.py\""
fi
if [[ $LAUNCHER -eq 1 ]]; then
    step "Adding a launcher"
    mkdir -p "$BASE"
    cat > "$RUN" <<EOF
#!/usr/bin/env bash
cd "$REPO" && exec "$VENV/bin/python" $START "\$@"
EOF
    chmod +x "$RUN"
    say "  $RUN"
    if [[ "$(uname)" != "Darwin" ]]; then
        mkdir -p "$HOME/.local/bin"
        ln -sf "$RUN" "$HOME/.local/bin/opencaster"
        say "  ~/.local/bin/opencaster"
    fi
    if [[ "$(uname)" != "Darwin" && $HEADLESS -eq 0 ]]; then
        mkdir -p "$HOME/.local/share/applications"
        cat > "$HOME/.local/share/applications/opencaster.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=OpenCaster
Comment=Cast spells with your Magic Caster wand
Exec="$RUN"
Icon=$REPO/opencaster/gui/assets/opencaster-icon-1c-dark.svg
Terminal=false
Categories=Game;
EOF
        say "  an OpenCaster entry in your app menu"
    fi
fi

if [[ $MEDIA -eq 1 ]]; then
    step "Media pack (each spell's sounds and videos)"
    # from the repository, so -m finds the opencaster package
    if ! (cd "$REPO" && "$VENV/bin/python" -m opencaster.media_pack --check); then
        if ask "Download the media pack now (about 530 MB)?"; then
            (cd "$REPO" && "$VENV/bin/python" -m opencaster.media_pack) || {
                say "The media pack isn't installed yet - run setup again to resume, or use"
                say "Settings in OpenCaster.  Casting works without it."
            }
        else
            say "Skipped - OpenCaster offers it on first start (and in Settings)."
        fi
    fi
fi
say ""
say "Setup complete. Start OpenCaster with:"
if [[ $LAUNCHER -eq 1 ]]; then say "  \"$RUN\""; else say "  cd \"$REPO\" && \"$VENV/bin/python\" $START"; fi
if [[ $HEADLESS -eq 1 ]]; then say "(headless: same options as python -m opencaster, e.g. --duel)"; fi
