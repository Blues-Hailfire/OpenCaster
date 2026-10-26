"""
opencaster.wand.effects — Light/haptic effects as playable step lists
=====================================================================
An effect is a tuple of (bytes, wait_seconds) steps: write the bytes, then
wait before the next write.  The device plays one effect at a time and a new
one cancels the old, so effects never interleave.

Animation rule: the tip (group 0) glows only for a successful cast – the
spell's payoff (`success`, spellbook macros), what it leaves lit (the
Wingardium steering `glow`, a clash's `locked_in`) – and for the connect
`welcome`.  Every other cue lights the body (groups 1-3) with `_body`, which
also fades the tip out: a new effect doesn't reset LEDs it never sets, so a
cue that merely skipped the tip would leave the last spell's glow on it.
Direct control (`light`, `glow`, `solid` from the API/CLI) is exempt.

Two sources:
  - Built-in animations (connect, cast window, success, fail, clear).
  - Original-app macros (spellbook.json `macros_payoff`), encoded the same
    way as the official app's MacroFactory:

        buzz       0x50 <u16 ms>
        changeled  0x22 <group> <r> <g> <b> <u16 ms>   (fade, runs in parallel)
        delay      0x10 <u16 ms>
        clearleds  → changeled 000000 on all four groups
        setloops N … loop → expanded here (the on-wand loop opcode is unconfirmed)
        waitbusy, smart-lamp commands → ignored

    JSON durations are seconds; the wire carries ms capped at 32767.
    Colours may name a variable such as "$house_color" (Colovaria).
"""

from typing import Iterable, Optional

from . import protocol as p

MAX_MS = 32767                  # MacroFactory.fromDoubleByteToIntByte cap
ATT_OVERHEAD = 3                # ATT header bytes subtracted from the MTU
DEFAULT_VARIABLES = {"house_color": "D4AF37"}

Effect = tuple                  # ((bytes, wait_s), ...)


# ── Built-in animations ────────────────────────────────────────────────────────

def _prefixed(frame: bytes, wait: float = 0.0) -> list:
    return [(p.EFFECT_PREFIX, 0.0), (frame, wait)]


# Colours are (r, g, b) tuples.  Groups run 0..3 from tip to handle.
BLUE = (0, 0, 255)
GOLD = (255, 180, 0)
WHITE = (255, 255, 255)
TIP_TO_HANDLE = (0, 1, 2, 3)
BODY = (1, 2, 3)                # every group but the tip


def _scale(rgb: tuple, k: float) -> tuple:
    return tuple(max(0, min(255, int(c * k))) for c in rgb)


def _body(rgb: tuple, ms: int, groups=BODY) -> bytes:
    """One frame: `groups` (body groups) fade to rgb, the tip fades out."""
    return p.frame(p.changeled(0, 0, 0, 0, ms), *(p.changeled(g, *rgb, ms) for g in groups))


def _buzz_pulse(intensity: int, on_s: float, off_s: float = 0.0) -> list:
    """The proven haptic pattern: 0x60, buzz frame, then 0x40 to stop the
    motor (0x40 also turns the LEDs off)."""
    gap = p.HW_INIT_GAP_S
    return [(p.EFFECT_PREFIX, gap), (p.frame(p.buzz(intensity)), gap + on_s),
            (p.LIGHTS_OFF, gap + off_s)]


def _wave(rgb: tuple, order=TIP_TO_HANDLE, fade_ms: int = 120, step_s: float = 0.06) -> list:
    out = []
    for g in order:
        out += _prefixed(p.frame(p.changeled(g, *rgb, fade_ms)), step_s)
    return out


def clear() -> Effect:
    """Fade every group to black over 0.5 s."""
    return ((p.all_groups(0, 0, 0, 500), 0.0),)


def glow(r: int = 0, g: int = 0, b: int = 255, fade_ms: int = 2000) -> Effect:
    """Steady colour on the whole wand."""
    return tuple(_prefixed(p.all_groups(r, g, b, fade_ms)))


def breathe(rgb: tuple = BLUE, seconds: float = 9.0, period: float = 1.6) -> Effect:
    """Cast-window glow on the body: a quick bloom to full colour, then a
    slow breath between full and 35% brightness until cancelled (or
    `seconds` pass).  The tip stays dark until the spell succeeds."""
    dim, half = _scale(rgb, 0.35), period / 2
    out = _prefixed(_body(rgb, 150), 0.25)
    for _ in range(max(1, int(seconds / period))):
        out += _prefixed(_body(dim, int(half * 1000)), half)
        out += _prefixed(_body(rgb, int(half * 1000)), half)
    return tuple(out)


def welcome(rgb: tuple = BLUE) -> Effect:
    """Connect animation: colour sweeps handle → tip, two buzzes, then the
    whole wand glows in its colour and slowly fades out."""
    out = _wave(rgb, order=(3, 2, 1, 0), fade_ms=140, step_s=0.11)
    out += _prefixed(p.frame(p.changeled(0, *WHITE, 80)), 0.12)
    out += _prefixed(p.frame(p.changeled(0, *rgb, 200)), 0.25)
    out += _buzz_pulse(100, 0.15, 0.25) + _buzz_pulse(100, 0.4, 0.25)
    out += _prefixed(p.all_groups(*rgb, 300), 0.9)
    out.append((p.all_groups(0, 0, 0, 1200), 0.0))
    return tuple(out)


def success(rgb: tuple = GOLD) -> Effect:
    """Generic recognised spell: short buzz, colour wave tip → handle, white
    flash, fade."""
    return tuple(
        _buzz_pulse(200, 0.12, 0.05)
        + _wave(rgb, fade_ms=120, step_s=0.07)
        + [(p.EFFECT_PREFIX, 0.0), (p.all_groups(*rgb, 100), 0.15)]
        + _prefixed(p.all_groups(*WHITE, 150), 0.2)
        + [(p.all_groups(0, 0, 0, 600), 0.0)])


def fail() -> Effect:
    """Faint red wash on groups 1-3, no buzz: cast not recognised."""
    return tuple(_prefixed(_body((45, 0, 0), 150), 0.18)
                 + [(p.all_groups(0, 0, 0, 500), 0.0)])


def display(rgb: tuple) -> Effect:
    """Display mode: the body glows steadily in the wand's colour until its
    pads are pressed (the tip stays dark)."""
    return tuple(_prefixed(_body(rgb, 1000)))


def color_preview(rgb: tuple) -> Effect:
    """A wand's colour was changed: show it on the body for a moment."""
    return tuple(_prefixed(_body(rgb, 250), 1.2) + [(p.all_groups(0, 0, 0, 250), 0.0)])


def solid(color: str) -> Effect:
    """'#RRGGBB' on every group (CLI testing)."""
    return glow(*p.hex_to_rgb(color), fade_ms=300)


# Duel cues --------------------------------------------------------------------

def countdown_tick(rgb: tuple = BLUE) -> Effect:
    """One countdown beat: a soft pulse in the player's colour."""
    return tuple(_prefixed(_body(_scale(rgb, 0.6), 80), 0.22)
                 + [(p.all_groups(0, 0, 0, 250), 0.0)])


def go(rgb: tuple = BLUE) -> Effect:
    """'Cast!': a white flash just below the tip that runs down the body
    into the player's colour."""
    return tuple(_prefixed(_body(WHITE, 60, groups=(1,)), 0.08)
                 + _wave(rgb, order=BODY, fade_ms=100, step_s=0.04)
                 + [(p.EFFECT_PREFIX, 0.6), (p.all_groups(0, 0, 0, 900), 0.0)])


def locked_in(rgb: tuple = BLUE) -> Effect:
    """Clash: spell chosen.  One buzz, then a steady half-bright glow in the
    player's own colour, which gives nothing away until the reveal."""
    return tuple(_buzz_pulse(150, 0.12, 0.05)
                 + _prefixed(p.all_groups(*_scale(rgb, 0.5), 150), 2.5)
                 + [(p.all_groups(0, 0, 0, 600), 0.0)])


def round_lost() -> Effect:
    """The other player got there first: a red fade up from the handle."""
    return tuple(_prefixed(_body((120, 0, 0), 200, groups=(3,)), 0.08)
                 + _wave((120, 0, 0), order=(2, 1), fade_ms=200, step_s=0.08)
                 + [(p.EFFECT_PREFIX, 0.4), (p.all_groups(0, 0, 0, 800), 0.0)])


def duel_won(rgb: tuple = GOLD) -> Effect:
    """Victory: three buzzes and a rainbow cascade down the body, ending in
    the player's colour."""
    out = _buzz_pulse(150, 0.12, 0.08) + _buzz_pulse(150, 0.12, 0.08) + _buzz_pulse(200, 0.3, 0.1)
    for i in range(16):
        out += _prefixed(p.frame(p.changeled(0, 0, 0, 0, 90),
                                 *(p.changeled(grp, *p.hue_to_rgb((i + grp * 2) / 16), 90)
                                   for grp in BODY)), 0.09)
    out += _prefixed(_body(rgb, 300), 1.2)
    out.append((p.all_groups(0, 0, 0, 1500), 0.0))
    return tuple(out)


# Direct control (API / CLI) ---------------------------------------------------

def light(rgb: tuple, fade_ms: int = 300, hold_ms: int = 0, groups=range(4)) -> Effect:
    """Set groups to a colour.  hold_ms > 0 fades back out after that long;
    0 leaves the colour on."""
    out = _prefixed(p.all_groups(*rgb, fade_ms, groups=groups), hold_ms / 1000 if hold_ms else 0.0)
    if hold_ms:
        out.append((p.all_groups(0, 0, 0, fade_ms, groups=groups), 0.0))
    return tuple(out)


def vibrate(duration_ms: int) -> Effect:
    """Buzz for duration_ms, using the official app's encoding (duration in
    ms; the LEDs are left as they are)."""
    return ((p.EFFECT_PREFIX, 0.0), (p.frame(p.buzz(min(max(int(duration_ms), 0), MAX_MS))), 0.0))


BUILTIN = {"welcome": welcome, "success": success, "fail": fail, "glow": glow,
           "breathe": breathe, "clear": clear, "countdown": countdown_tick, "go": go,
           "locked_in": locked_in, "round_lost": round_lost, "duel_won": duel_won}


# ── Spellbook macros ───────────────────────────────────────────────────────────

def _ms(seconds) -> int:
    return max(0, min(int(float(seconds) * 1000), MAX_MS))


def expand_loops(macro: Iterable[dict]) -> list:
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


def _color(value: str, variables: dict) -> Optional[tuple]:
    value = str(value)
    if value.startswith("$"):
        value = variables.get(value[1:], "")
    try:
        return p.hex_to_rgb(value)
    except ValueError:
        return None


def encode_command(c: dict, variables: dict) -> tuple:
    """One macro command → (wire bytes, seconds the wand spends on it)."""
    cmd = c.get("command")
    if cmd == "buzz":
        return p.buzz(_ms(c["duration"])), 0.0
    if cmd == "changeled":
        rgb = _color(c.get("color", ""), variables)
        if rgb is None:
            return b"", 0.0
        return p.changeled(int(c["group"]), *rgb, _ms(c["duration"])), 0.0
    if cmd == "delay":
        ms = _ms(c["duration"])
        return p.delay(ms), ms / 1000
    if cmd == "clearleds":
        return b"".join(p.changeled(g, 0, 0, 0, 0) for g in range(4)), 0.0
    return b"", 0.0


def macro_to_frames(macro: Iterable[dict], max_len: int,
                    variables: Optional[dict] = None) -> list:
    """Encode a macro as [(frame, wait_s), ...], each frame ≤ max_len bytes.

    Frames split only at command boundaries; each frame's delays are waited
    before the next is sent, so timing holds whether the wand queues or
    replaces frames.
    """
    variables = {**DEFAULT_VARIABLES, **(variables or {})}
    frames, body, wait = [], b"", 0.0
    for c in expand_loops(macro):
        data, secs = encode_command(c, variables)
        if not data:
            continue
        if body and 1 + len(body) + len(data) > max_len:
            frames.append((bytes([p.Msg.FRAME_START]) + body, wait))
            body, wait = b"", 0.0
        body += data
        wait += secs
    if body:
        frames.append((bytes([p.Msg.FRAME_START]) + body, wait))
    return frames


def macro_effect(macro: Iterable[dict], mtu: Optional[int] = None,
                 variables: Optional[dict] = None) -> Effect:
    """A spellbook macro as a playable effect for a link with this MTU."""
    max_len = max(20, (mtu or 23) - ATT_OVERHEAD)
    return ((p.EFFECT_PREFIX, 0.0),) + tuple(macro_to_frames(macro, max_len, variables))
