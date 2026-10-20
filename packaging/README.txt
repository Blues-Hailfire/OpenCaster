OpenCaster - Windows release
============================

An unofficial, open-source app for the Warner Bros. Magic Caster wand.
Source, documentation and updates: https://github.com/Blues-Hailfire/OpenCaster

Start
-----
1. Unzip this folder anywhere you can write to (Desktop, Downloads, ...).
   Avoid very deeply nested folders: Windows can't load some of the
   Bluetooth files if the folder path is longer than about 160 characters.
2. Turn on Bluetooth.
3. Double-click OpenCaster.exe.  Your wand connects automatically.
4. Cast: hold all four touch pads, draw the spell, release.

Windows SmartScreen may say "Windows protected your PC" because this build
isn't code-signed: click "More info", then "Run anyway".

If it doesn't start, run "OpenCaster (debug).exe": it opens a console
window that shows the error.  Please include that text in a bug report.

Spell effects
-------------
media\spellbook.json (included) gives every spell its own wand light and
haptics.  For sounds and videos, add the media pack's files to that same
"media" folder (sounds in media\sounds).  Casting works without them.

Your files
----------
OpenCaster keeps these next to OpenCaster.exe:
  casts\casts.jsonl     your labelled casts
  wand_profiles.json    wand colours, nicknames, calibration
  progress.json         spell mastery
  settings.json         settings
Keep them when you update: unzip the new version and copy them across.
(If this folder isn't writable they go to %LOCALAPPDATA%\OpenCaster.)

Help improve recognition
------------------------
Keep "Label casts" on and label what you meant to cast.  Then share your
casts\casts.jsonl in a pull request (or an issue) on GitHub - see
"Contributing" in the project README.  Each record holds the gesture
trail, labels, scores, a timestamp and your wand's Bluetooth address.

Licences of the bundled components: THIRD_PARTY_NOTICES.txt.
Magic Caster is a Warner Bros. product; OpenCaster is not affiliated with
or endorsed by Warner Bros.
