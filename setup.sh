#!/usr/bin/env bash
# OpenCaster setup for macOS and Linux:  bash setup.sh
#
#   1. Finds Python 3.11 or newer.
#   2. Creates a private environment outside this folder:
#        macOS  ~/Library/Application Support/OpenCaster/venv
#        Linux  ${XDG_DATA_HOME:-~/.local/share}/OpenCaster/venv
#   3. Installs (or updates) the packages in requirements.txt.
#   4. Adds an `opencaster` launcher (and an app-menu entry on Linux).
#
# Safe to run again.  Options: --venv DIR, --no-launcher
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(uname)" == "Darwin" ]]; then
    BASE="$HOME/Library/Application Support/OpenCaster"
else
    BASE="${XDG_DATA_HOME:-$HOME/.local/share}/OpenCaster"
fi
VENV="$BASE/venv"
LAUNCHER=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --venv) VENV="$2"; shift 2 ;;
        --no-launcher) LAUNCHER=0; shift ;;
        *) echo "unknown option: $1"; exit 2 ;;
    esac
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
fail() { printf '\nSetup stopped: %s\n' "$*" >&2; exit 1; }

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
"$VENV/bin/python" -m pip install --upgrade --disable-pip-version-check -r "$REPO/requirements.txt" \
    || fail "package installation failed - see the messages above."
"$VENV/bin/python" -c 'import bleak, numpy, scipy, PySide6.QtMultimedia, PySide6.QtSvg' \
    || fail "the packages installed but don't import - try running setup again."

RUN="$BASE/opencaster"
if [[ $LAUNCHER -eq 1 ]]; then
    step "Adding a launcher"
    mkdir -p "$BASE"
    cat > "$RUN" <<EOF
#!/usr/bin/env bash
cd "$REPO" && exec "$VENV/bin/python" "$REPO/OpenCaster_GUI.py" "\$@"
EOF
    chmod +x "$RUN"
    say "  $RUN"
    if [[ "$(uname)" != "Darwin" ]]; then
        mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
        ln -sf "$RUN" "$HOME/.local/bin/opencaster"
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
        say "  ~/.local/bin/opencaster and an OpenCaster entry in your app menu"
    fi
fi

if [[ ! -f "$REPO/media/spellbook.json" ]]; then
    say ""
    say "Optional: put spellbook.json and the media pack in $REPO/media for each spell's"
    say "own light, sounds and videos (casting works without them)."
fi
say ""
say "Setup complete. Start OpenCaster with:"
if [[ $LAUNCHER -eq 1 ]]; then say "  \"$RUN\""; else say "  \"$VENV/bin/python\" \"$REPO/OpenCaster_GUI.py\""; fi
