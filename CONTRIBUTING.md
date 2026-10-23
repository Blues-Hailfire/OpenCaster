# Contributing

**Share your casts – it's the most useful thing you can do.**  Recognition
gets better with every honestly labelled cast from different people and
wands.

1. Keep **Label casts** on (the default) and cast spells.  After each cast,
   pick the spell you *meant* to cast – even when OpenCaster guessed wrong –
   or **Not a spell** for a fumble.  That's what makes the data useful.
2. Your casts are appended to `casts/casts.jsonl` (in the Windows release,
   the `casts` folder next to OpenCaster.exe).
3. Fork this repository, add your casts to `casts/casts.jsonl`, and open a
   pull request – or attach the file to an issue if pull requests are new
   to you.  Each record holds the gesture trail, the labels and scores, a
   timestamp and your wand's Bluetooth address – nothing else.  Casts also
   keep the wand's raw motion (1 s before the window opens, then the whole
   gesture), so tracker improvements can be re-run on them later
   (`python -m opencaster.casting evaluate --retrack`); that's about
   10–30 KB per cast.

**Code, spells and ideas** are just as welcome: bolt something on and open
a pull request.  [Architecture](docs/architecture.md) shows how the pieces fit,
and the Claude skill in `.claude/skills/opencaster/` describes how
features, spells and effects are built and tested without a wand.

## Building the Windows release

`packaging\build.ps1 -Version v1.0.0` makes a one-folder PyInstaller build
(`OpenCaster.exe`, plus `OpenCaster (debug).exe` with a console for error
messages) and zips it, in `%LOCALAPPDATA%\OpenCaster\release` so OneDrive
doesn't sync the build.  `OpenCaster.exe --smoke-test` checks a build
(spells, assets, Bluetooth backend, Qt Multimedia, the window) without
touching Bluetooth.

Pushing a version tag (`git tag v1.0.0 && git push origin v1.0.0`) runs
the same build on GitHub Actions (`.github/workflows/release.yml`), smoke
tests it, and attaches the zip to a GitHub release.  The release ships
`media/spellbook.json` next to the exe but never the media pack (the app
offers to download it on first start); user files
(casts, profiles, progress, settings, `media/`) live next to the exe.
