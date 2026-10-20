"""
OpenCaster — an open-source host for the Magic Caster Wand.

    opencaster.wand       BLE connection and protocol (bleak only)
    opencaster.casting    gesture tracking and spell assessment (numpy/scipy only)
    opencaster.spellbook  original spell data and media lookup
    opencaster.core       wires the wand to casting and effects
    opencaster.gui        PySide6 interface (run OpenCaster_GUI.py)

Each of wand, casting and the core runs headless:
    python -m opencaster.wand --help
    python -m opencaster.casting --help
    python -m opencaster
"""
