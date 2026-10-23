# Using the GUI

[← OpenCaster](../README.md) · [Documentation](README.md)

Four pages: **Cast**, **Spellbook**, **Duel** and **Environment**.  The header shows a pill
for every connected wand (its colour, nickname and battery) and any boxes;
**⚙** opens Settings.

## Connecting (one wand or several)

- **Automatic:** on launch the wands that were connected last time are
  reconnected whenever they're in range; with none of those around, the
  first wand found is connected.  While nothing is found it rescans every
  10 s, and a dropped link is reconnected automatically.
- **More wands:** **Scan**, pick a wand under *Found wands*, **Connect**.
  Every connected wand casts independently, each in its own stage.
- **A wand's settings:** click its pill for its nickname, colour,
  **Calibrate…** and **Disconnect** (a disconnected wand isn't reconnected
  automatically again).
- **Boxes:** every box (`MCB-*`) found is connected too.

## Casting

- **Start:** hold all four touch pads.  The wand's body breathes in its
  colour while the gesture window is open (the tip stays dark until a spell
  succeeds), the trail is drawn live with sparkles
  at the tip, and a soft wand sound plays.
- **End:** release any pad (or wait 8 s).  The trail is then matched.
- **Quick taps:** releasing within 0.5 s isn't counted as a cast.
- **Result:** a recognised spell bursts in its colours, plays its
  light/haptic effect on the wand (and box), its casting sound and its
  payoff video (Expecto Patronum is followed by your Patronus).  A failed
  cast plays a dim red flash, shows the closest shape dashed over your
  trail, and a short mishap video (not while **Label casts** is on, so the
  trail stays visible while you answer).  Videos start a moment after the
  spell's burst, and a new cast stops them.
- **Pads:** the orbs in each stage's header mirror its touch pads.  Click
  one to force it on, as a workaround for a faulty sensor (gold ring).
- **Mastery:** every successful cast counts towards mastering that spell
  (10 casts, as in the original app), kept in `progress.json`; mastering a
  spell plays the celebration video.

## Practising one spell

**Practise** defaults to **Any spell**.  Pick a spell, or press **Practise
this spell** in the Spellbook, and its shape is drawn as a guide, starting
where your stroke starts, at the size you usually cast it.  Only that spell
can then be cast; a cast that looks more like another spell is rejected with
"not X (closest: Y)".

## Labelling casts

With **Label casts** on (the default), each cast must be labelled before the
next one can start on that wand: one of the closest spells, any other spell,
*Not a spell*, or *Discard*.  Starting a calibration discards a cast still
waiting for its label.  Hovering a spell previews its shape on the
trail.  While practising, the question is just "Was that Lumos?".  Labelled
trails go to `casts/casts.jsonl` for tuning (see
[Tuning recognition](spells.md#tuning-recognition)).

## Spellbook

A card for every spell template, coloured with the light colours the spell
plays on the wand and showing its original gesture icon (`spells/icons/`,
falling back to the SVG shape).  The small icon in each card's top left is
the spell's duelling type (Fire, Explosive, Binding, Locomotive, Water/Ice or
Protection, as on the duel wheel); utility spells, which take no part in
clashes or the Duelling Club, have none.  Hovering a card names the type and
what it beats.  Open one for its pronunciation, lore and
mastery progress, with buttons to practise it, play its effect on the wands,
play its sound or watch its video.  Expecto Patronum's page has a **Patronus**
picker and Colovaria's a **house** picker.

## Settings (⚙)

| Setting | What it does |
|---------|--------------|
| Default wand colour | The breathing cast glow and connect animation of wands without their own colour (blue until changed).  A wand's own colour is set by clicking its pill. |
| Hogwarts house | Gryffindor, Hufflepuff, Ravenclaw or Slytherin: plays the house's sound and fills Colovaria's house colour |
| Patronus | Random, or any of the 69 Patronuses that have a video; shown after Expecto Patronum (with a preview) |
| Media | Casting sounds, spell videos, mishap videos, ambient casting sound, wand-connect sound |
| Control API | Shows the API address (configured in `settings.json`) |

Core settings live in `settings.json` (shared with the headless runner and
the API); per-wand colour and nickname in `wand_profiles.json`.

## Calibration

Press **Calibrate** (or **Calibrate…** in a wand's settings) while
connected.  Three self-advancing steps, about 20 s:

1. Lay the wand flat → gyro bias and noise
2. Swipe up → confirms tracking reads up
3. Swipe right → confirms it reads right

The tip axis and left/right sign are the same on every wand, so the swipes
only confirm them: one that reads the wrong way (or too small or crooked)
is asked for again.  The result is saved as a `motion` block for that wand
in `wand_profiles.json` (keyed by MAC address) and loaded on every connect.
Without it, defaults are used (tip +y, bias learned on the fly), so
calibrating is optional.  A tip more than 25° off +y, saved by an older
calibration with the wand held wrong, is ignored at load: only its gyro
bias is used.

**Diagnostics** shows match scores, the live IMU samples and an event log.
