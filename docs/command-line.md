# Running headless

[← OpenCaster](../README.md) · [Documentation](README.md)

The wand link and spell assessment are separate packages, and each runs
without the GUI:

```bash
# Wand only (opencaster.wand, needs bleak)
python -m opencaster.wand scan                  # list nearby wands and boxes
python -m opencaster.wand monitor               # connect and print every event
python -m opencaster.wand record capture.csv    # raw IMU + pad state to CSV
python -m opencaster.wand effect success        # a built-in effect, or a #RRGGBB colour

# Spell assessment only (opencaster.casting, needs numpy + scipy)
python -m opencaster.casting list               # spell templates
python -m opencaster.casting evaluate           # score the matcher on labelled casts
python -m opencaster.casting replay capture.csv # replay a recorded capture through casting

# Everything together, in the terminal (every connected wand casts)
python -m opencaster [--target Lumos] [--duel | --clash | --club [N] [--random-order]] [--npc [LEVEL]]
```

`python -m opencaster` reads the same `settings.json` and
`wand_profiles.json` as the GUI, so passive mode and each wand's display
mode apply headless too.

`--address AA:BB:...` picks a wand for the wand commands; `replay --wand
ADDRESS` uses that wand's calibration.
