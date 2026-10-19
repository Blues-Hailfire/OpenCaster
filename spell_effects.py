"""
spell_effects.py — Original Magic Caster spell effects (wand light/haptic + audio)
==================================================================================
Plays the original app's per-spell effects when a spell is cast:

  - Wand LED + haptic macro: config_wand.macros_payoff from the recovered
    spellbook.json (uuyyyuu/magic-caster-spellbook), encoded the same way the
    official app's MacroFactory does.
  - Box light macro: config_wandbox.macros_payoff, same command set, sent
    to any connected MCB box (unverified on hardware).
  - Casting sound: an MP3 from the original zz_spell_assets media pack
    (five variants per spell; one is picked at random).

Neither is redistributable, so both live in media/ (gitignored):

    media/spellbook.json
    media/<anything>/...*.mp3      e.g. the unzipped zz_spell_assets-1.7.1-media.zip

Spells are matched by name with spaces/punctuation stripped, so the template
spells/Expelliarmus.svg picks up the spellbook's "Expelliarmus" entry and any
sound file whose name contains "expelliarmus".

Macro commands (MacroFactory.java): durations are seconds in the JSON and
milliseconds on the wire, capped at 32767.
    buzz       0x50 <u16 ms>
    changeled  0x22 <group> <r> <g> <b> <u16 ms>     (fade, runs in parallel)
    delay      0x10 <u16 ms>
    clearleds  → changeled 000000 on all four groups
    setloops N … loop → the enclosed commands repeated N times (expanded here;
               the on-wand loop opcode is unconfirmed)
    waitbusy   → ignored
"""

import asyncio
import ctypes
import json
import os
import random
import re
import struct
import sys
from typing import Optional

from wand import WRITE_UUID, FRAME_START, cmd_changeled, cmd_delay, hex_to_rgb

HERE           = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR      = os.path.join(HERE, "media")
SPELLBOOK_FILE = os.path.join(MEDIA_DIR, "spellbook.json")

OP_BUZZ  = 0x50
MAX_MS   = 32767          # MacroFactory.fromDoubleByteToIntByte cap
ATT_OVERHEAD = 3          # ATT header bytes subtracted from the MTU


def spell_key(name: str) -> str:
    """'Wingardium Leviosa' / 'wingardium_leviosa' → 'wingardiumleviosa'."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _ms(seconds: float) -> int:
    return max(0, min(int(seconds * 1000), MAX_MS))


# ── Macro → BLE frames ─────────────────────────────────────────────────────────

def _expand_loops(macro: list) -> list:
    """Inline setloops N … loop blocks (nesting allowed)."""
    out, stack = [], []
    for c in macro:
        cmd = c.get("command")
        if cmd == "setloops":
            stack.append((max(1, int(c.get("loops", 1))), out))
            out = []
        elif cmd == "loop" and stack:
            n, parent = stack.pop()
            parent.extend(out * n)
            out = parent
        else:
            out.append(c)
    while stack:                          # unterminated setloops: play once
        _, parent = stack.pop()
        parent.extend(out)
        out = parent
    return out


def _encode(c: dict) -> tuple:
    """One macro command → (wire bytes, seconds the wand spends on it)."""
    cmd = c.get("command")
    if cmd == "buzz":
        return struct.pack("<BH", OP_BUZZ, _ms(c["duration"])), 0.0
    if cmd == "changeled":
        return cmd_changeled(int(c["group"]), *hex_to_rgb(c["color"]), _ms(c["duration"])), 0.0
    if cmd == "delay":
        return cmd_delay(_ms(c["duration"])), _ms(c["duration"]) / 1000
    if cmd == "clearleds":
        return b"".join(cmd_changeled(g, 0, 0, 0, 0) for g in range(4)), 0.0
    return b"", 0.0                       # waitbusy / unknown


def macro_to_frames(macro: list, max_len: int) -> list:
    """Encode a macro as [(frame, delay_seconds), ...], each frame ≤ max_len.

    Frames are split only at command boundaries; the caller waits each
    frame's delay total before sending the next so timing is kept whether the
    wand queues or replaces frames.
    """
    frames, body, wait = [], b"", 0.0
    for c in _expand_loops(macro):
        data, secs = _encode(c)
        if not data:
            continue
        if body and 1 + len(body) + len(data) > max_len:
            frames.append((bytes([FRAME_START]) + body, wait))
            body, wait = b"", 0.0
        body += data
        wait += secs
    if body:
        frames.append((bytes([FRAME_START]) + body, wait))
    return frames


async def play_wand_macro(client, macro: list) -> None:
    """Send an original-app wand macro over BLE."""
    mtu = getattr(client, "mtu_size", None) or 23
    frames = macro_to_frames(macro, max(20, mtu - ATT_OVERHEAD))
    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
    for frame, wait in frames:
        await client.write_gatt_char(WRITE_UUID, frame, response=False)
        if wait:
            await asyncio.sleep(wait)


# ── Audio ──────────────────────────────────────────────────────────────────────

class _MciPlayer:
    """MP3 playback through the Windows MCI API (no extra dependencies)."""
    ALIAS = "opencaster_sfx"

    def __init__(self):
        self._send = ctypes.windll.winmm.mciSendStringW if sys.platform == "win32" else None

    def play(self, path: str) -> bool:
        if self._send is None:
            return False
        self._send(f"close {self.ALIAS}", None, 0, 0)
        if self._send(f'open "{path}" type mpegvideo alias {self.ALIAS}', None, 0, 0):
            return False
        return self._send(f"play {self.ALIAS}", None, 0, 0) == 0

    def stop(self):
        if self._send is not None:
            self._send(f"close {self.ALIAS}", None, 0, 0)


# ── Library ────────────────────────────────────────────────────────────────────

class SpellEffects:
    """Original wand macros + casting sounds, keyed by spell_key()."""

    def __init__(self, media_dir: str = MEDIA_DIR):
        self._media_dir = media_dir
        self._macros: dict = {}
        self._box_macros: dict = {}
        self._sounds: dict = {}
        self._mp3s: list = []
        self._player = _MciPlayer()
        self.reload()

    def reload(self):
        self._macros.clear()
        self._box_macros.clear()
        self._sounds.clear()
        book = os.path.join(self._media_dir, "spellbook.json")
        if os.path.exists(book):
            with open(book, encoding="utf-8") as f:
                for s in json.load(f).get("spells", []):
                    alts = (s.get("config_wand") or {}).get("macros_payoff") or []
                    if alts:
                        self._macros[spell_key(s["spell_name"])] = alts
                    box = (s.get("config_wandbox") or {}).get("macros_payoff") or []
                    if box:
                        self._box_macros[spell_key(s["spell_name"])] = box
        self._mp3s = []
        for root, _dirs, files in os.walk(self._media_dir):
            self._mp3s += [os.path.join(root, f) for f in files if f.lower().endswith(".mp3")]
        self._index_sounds()
        print(f"  [effects] {len(self._macros)} wand macro(s), {len(self._mp3s)} sound file(s)")

    def wand_macro(self, spell: str) -> Optional[list]:
        """A random alternative of the spell's original wand macro, or None."""
        alts = self._macros.get(spell_key(spell))
        return random.choice(alts) if alts else None

    def box_macro(self, spell: str) -> Optional[list]:
        """A random alternative of the spell's original box (MCB) macro, or None."""
        alts = self._box_macros.get(spell_key(spell))
        return random.choice(alts) if alts else None

    def _index_sounds(self):
        """Give each MP3 to the longest spellbook name inside its filename, so
        'Lumos' doesn't also collect 'Lumos Maxima' sounds."""
        for p in self._mp3s:
            fname = spell_key(os.path.splitext(os.path.basename(p))[0])
            hits = [k for k in self._macros if k in fname]
            if hits:
                self._sounds.setdefault(max(hits, key=len), []).append(p)

    def sounds(self, spell: str) -> list:
        key = spell_key(spell)
        if key not in self._sounds:       # spell not in the spellbook: plain match
            self._sounds[key] = [p for p in self._mp3s
                                 if key in spell_key(os.path.basename(p))]
        return self._sounds[key]

    def play_sound(self, spell: str) -> bool:
        files = self.sounds(spell)
        return self._player.play(random.choice(files)) if files else False

    def stop_sound(self):
        self._player.stop()

    def summary(self, spells: list) -> dict:
        """{spell: (has_macro, n_sounds)} for the given spell names."""
        return {s: (spell_key(s) in self._macros, len(self.sounds(s))) for s in spells}
