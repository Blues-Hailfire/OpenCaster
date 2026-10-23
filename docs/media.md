# Spell effects and media

[← OpenCaster](../README.md) · [Documentation](README.md)

`opencaster/spellbook.py` reads the original app's data from `media/`.
`spellbook.json` and OpenCaster's logo (`media/Logo/`) are tracked; the rest
of `media/` is gitignored.  Everything is optional; missing files are simply
skipped.

**The media pack** (`opencaster/media_pack.py`) downloads the preserved
Magic Caster resource bundle (2026-10-11, 533 MB), checks every file against
the bundle's SHA-256 sums (whose own hash is pinned in the code) and unpacks
the sounds into `media/sounds/` and the videos into `media/`, keeping the
tracked `spellbook.json`.  The download waits in the temp folder and resumes
if interrupted; files already in place are skipped.  `setup.ps1` /
`setup.sh` offer it, the GUI asks once on first start and keeps a button in
Settings → Media, and `python -m opencaster.media_pack` does it by hand
(`--check`, `--force`, `--dest DIR`).  Your own copy works too: put the files
anywhere under `media/`.

| Media | Source | Used for |
|-------|--------|----------|
| Wand lights + haptics | `config_wand.macros_payoff` in `media/spellbook.json` | A recognised spell's effect on the wand, encoded like the app's `MacroFactory` (see [Lights and haptics](protocol.md#lights-and-haptics)) |
| Box lights | `config_wandbox.macros_payoff` | Sent to every connected box; **not yet verified on hardware** |
| Card colours | the colours in each wand macro | Spellbook cards, duel cards and the cast burst (weighted by duration × brightness) |
| Lore | `pronunciation`, `description`, `notable_uses`, `spell_type`, `difficulty` | The Spellbook |
| Casting sound | `sfx_<spell>_cast_01..05.mp3` | One at random per cast |
| Payoff video | `<spell>_video_payoff.mp4` | After a successful cast; each duel round's winning spell |
| Patronus videos | `sfx_patronus_<animal>.mp4` (69) | After Expecto Patronum; the Patronus picker |
| Mishap videos | `spellcasting_mishap_N.mp4` | After a failed cast |
| Celebration | `payoff_maxlevel.mp4` | Mastering a spell; winning a duel |
| Duel intro | `tutorial_end_transition.mp4` | Opening a duel |
| Wand awake | `sfx_wandawake_long.mp3` | A wand connects |
| Wand movement | `sfx_wandmovement_generalloop.mp3` | Looped while a cast window is open |
| House sounds | `ui_choose_house_*.mp3` | Choosing a house in Settings |

Media is matched to spells by file name, ignoring spaces and punctuation
(`sfx_lumos_cast_01.mp3` → Lumos); each sound goes to the longest spell name
it contains, so Lumos doesn't pick up Lumos Maxima's sounds.  Spells without
a wand macro fall back to a generic pulse in the wand's colour.  Colovaria's
`$house_color` is your house's colour (gold without a house).

## Built-in wand animations (`opencaster/wand/effects.py`)

| Effect | When |
|--------|------|
| `welcome` | Connect: the wand's colour sweeps handle → tip, two buzzes, a glow that fades out |
| `breathe` | Cast window open: a bloom, then a slow breath in the wand's colour (body only) |
| `success` | Spell without its own macro: buzz, colour wave tip → handle, white flash |
| `fail` | Failed cast: a faint red wash on the body, no buzz |
| `countdown`, `go`, `round_lost`, `duel_won` | Duel cues (body only) |
| `locked_in` | Clash pick made: one buzz and a dim glow in the wand's own colour, giving nothing away |

**The tip only glows for a successful cast** (the spell's own light, the
Wingardium steering glow, a clash pick) and for the connect animation.
Every other cue lights the body (groups 1–3) and fades the tip out, so a
spell's leftover glow never sits on the tip through the next cast window.
The API's direct `light`/`glow` commands are exempt.

They use only commands already proven on the wand (`0x60` prefix, `changeled`
fades, host-timed waits, the existing buzz pattern).
