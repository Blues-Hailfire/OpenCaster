# OpenCaster

<a href="https://www.buymeacoffee.com/hailfire"><img src="https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20coffee&emoji=&slug=hailfire&button_colour=FFDD00&font_colour=000000&font_family=Cookie&outline_colour=000000&coffee_colour=ffffff" alt="Buy me a coffee" height="42"></a>

## 🎃 Happy Halloween – the first release!

Hi everyone, happy Halloween!  This is the first release of this project,
and there's a lot of cool stuff to unpack here.  For starters, it's a
toolkit to build your own stuff with the Magic Caster wand: OpenCaster is
broken down into [separate modules](docs/architecture.md) so other applications
can use and reuse parts of it.  Not to mention a
[Claude skills package](.claude/skills/opencaster/SKILL.md) to make life
easy.  It's my hope we'll add support for things like TVs and smart home
devices, but if you beat me to it, there's an [API](docs/api.md) – go wild!

Some of the coolest features include the return of [duelling](docs/duel.md)!
Duel your friends!  Or an NPC if you need people, I'm sorry.  There are
three duel modes, with Duelling Club supporting up to 5 players.  (Yes, you
can connect more than one wand.)  The Spellbook is back, sounds and videos
included – setup (or the app's first start) downloads the media pack.
I've also added a fun [environment mode](docs/environment.md): cast spells
and blow up some pumpkins!  I highly recommend giving Wingardium Leviosa a
go.

What I could really use from all of you is to download the application and
cast some spells!  Then put in a pull request with the training data you've
gathered ([here's how](CONTRIBUTING.md)) – the more I get, the better
detection will be.

Lastly, I love contributions, and not just money: feel free to bolt some
stuff on, make a pull request, and we can build a better application
together!

---

An unofficial, open-source reimplementation of the Warner Bros. Magic Caster
Wand experience.  OpenCaster talks to the wand directly over Bluetooth LE: it
tracks your gesture with the wand's gyro, recognises it against 52 spell
shapes, and plays that spell's original light, haptic, sound and video
effects (on the wand, and on a Magic Caster box if one is nearby).  Several
wands can cast at once, wizards can duel (a quick-draw race or a clash of
spell elements for two, or a Duelling Club rally for up to five), an
enchanted jack-o'-lantern on screen reacts to every spell, and other
programs can drive the wands through a local API.  Leave it running in
passive mode to connect every wand that comes into range, and put a wand in
display mode to have it glow in its colour until someone picks it up and
presses its pads.

## Credits

- **Spell data and audio/visual media:** credit to **uuyyyuu** and
  [uuyyyuu/magic-caster-spellbook](https://github.com/uuyyyuu/magic-caster-spellbook),
  which recovered and preserved the original Magic Caster app's spell
  definitions (`spellbook.json`: wand and box lighting/haptic effects) and its
  `zz_spell_assets` media pack (casting sounds, spell videos), which OpenCaster
  plays when you cast.  These files belong to their original owners.  The
  spell manifest, `media/spellbook.json`, is included in this repository;
  the media pack is **not committed**: setup or the app downloads it into
  your local `media/` folder (see [Spell effects and media](docs/media.md)).
- **Spell gesture SVGs:** all 52 templates in `spells/` were traced from the
  gesture diagrams by **eigger** in
  [eigger/hass-magic-caster-wand](https://github.com/eigger/hass-magic-caster-wand/tree/master/docs/gestures)
  (MIT licence); each traced SVG names its source image.  The spell icons in
  `spells/icons/` are those original PNGs, unmodified (licence alongside).

Magic Caster is a Warner Bros. product.  OpenCaster is an unofficial project
and is not affiliated with or endorsed by Warner Bros.

---

## Quick start

**Windows, no Python needed:** download `OpenCaster-<version>-windows.zip`
from [Releases](https://github.com/Blues-Hailfire/OpenCaster/releases),
unzip it and run **OpenCaster.exe** (the zip's README.txt has the details;
SmartScreen may ask you to click *More info → Run anyway*, as the build
isn't code-signed).

**Windows, from source:** double-click **`setup.bat`**.  It finds (or
offers to install) Python, installs everything OpenCaster needs into
`%LOCALAPPDATA%\OpenCaster`, and adds **OpenCaster** to your Desktop and
Start Menu.  It also offers to download the media pack (each spell's
sounds and videos, about 530 MB).  Run it again any time to update.  If
the app doesn't start, use the **OpenCaster (troubleshoot)** shortcut to see the error.

**macOS / Linux:** `bash setup.sh` does the same and creates an
`opencaster` launcher (plus an app-menu entry on Linux).  Skip the media
download with `setup.ps1 -NoMedia` / `setup.sh --no-media`.

**By hand:**

```bash
pip install -r requirements.txt
python OpenCaster_GUI.py
```

1. **Effects:** `media/spellbook.json` (included) gives every spell its own
   wand light and haptics.  Sounds and videos come in the media pack: setup
   offers it, the app offers it on first start (and in Settings), or run
   `python -m opencaster.media_pack`.  Without it the spellbook shows
   shapes only.
2. **Launch:** the app scans for wands and boxes and connects automatically.
   Turn on **Passive mode** in Settings to keep scanning and connect every
   wand in range.
3. **Calibrate (optional):** press **Calibrate** once per wand to measure its gyro bias.
4. **Cast:** hold all four touch pads, draw the spell, release.

Requires Python 3.11+.  Sounds and videos play through Qt Multimedia, so
they work on every platform PySide6 supports.

---

## Documentation

- [Using the GUI](docs/gui.md) – connecting wands (and passive mode),
  casting, practising, labelling casts, the Spellbook, Settings, display
  mode and calibration
- [Wizard's duel](docs/duel.md) – quick-draw, clash, the Duelling Club and
  the NPC opponent
- [Environment: the enchanted jack-o'-lantern](docs/environment.md)
- [Spell effects and media](docs/media.md) – the media pack and built-in wand
  animations
- [Running headless](docs/command-line.md) and the [Control API](docs/api.md)
- [Spells](docs/spells.md) – adding spells, tuning and how recognition works
- [Architecture](docs/architecture.md) and the
  [protocol reference](docs/protocol.md)

---

## Contributing

**Share your casts – it's the most useful thing you can do.**  Keep **Label
casts** on, cast some spells, and send `casts/casts.jsonl` in a pull request.
[CONTRIBUTING.md](CONTRIBUTING.md) has the details, plus how to build the
Windows release.
