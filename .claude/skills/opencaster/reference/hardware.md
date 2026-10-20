# The wand: hardware and protocol facts

Full tables: README.md → "Protocol reference" and "How recognition works".
`opencaster.wand.protocol` and `.effects` implement all of this; prefer them
to raw bytes.

## Devices
- Wand `MCW-###` (nRF52832); optional box `MCB-###` (nRF52810).  Windows/macOS/Linux via bleak.
- Writes go to `57420002-…` (write without response); notifications come
  on `57420003-…`; battery on the standard `2a19`.
- Keepalive: the wand sends `0x01` challenges and drops the link if they
  aren't answered – the Device layer answers them for you.  Never block
  the loop thread for long or links die.

## Inputs
- **Touch pads**: `0x10 [mask]`, bit 0..3 = pads 1..4 from tip to handle.
  OpenCaster's convention: **all four held (0x0F) opens a cast window**,
  releasing closes it (held < 0.5 s is a "tap", > 8 s a timeout).
- **IMU**: `0x2C [seq u16 LE][count]` + count × 12 bytes (`gx gy gz ax ay az`,
  int16 LE).  220 Hz, 19 samples/packet, one arrival time per packet (use
  dt = 1/220).  Accel 2048 counts/g (±16 g); gyro 0.0625 °/s per count
  (±2000 °/s).  Gyro bias ≈1 °/s.  Starts with `0x31` then `0x30 00 80`
  (the manager does this) and **streams continuously** until disconnect.
- **Axes**: the tip points along sensor +y on every wand, and left/right
  never needs flipping.  Calibration measures only gyro bias; its swipes
  confirm tracking and are retried, never "fixed", when they read wrong.
  A saved tip more than 25° off +y (older calibrators) is ignored at load
  (`tracker.tip_offset_deg`).
  Level wand, tip forward: accel ≈ (0, 0, 1) g.
  Tip right = negative gz; tip up = positive gx.  Prefer
  `GestureTracker` (world-up aware, roll-free) to raw gyro maths.
- **Firmware spells**: `0x24 00 00 [len] name` – the wand recognises some
  spells itself; the core treats them like its own matches.

## Outputs
- Frames: `0x68` + commands; OpenCaster writes `0x60` before each frame.
- `0x22 changeled [group][r][g][b][ms u16 LE]` – a fade, **non-blocking**;
  consecutive changeleds run together.  Groups 0..3 = tip → handle.
- `0x10 delay [ms u16 LE]` – waits.  `0x50 buzz [ms u16 LE]` – haptic.
- `0x40` turns the LEDs off.  Durations are **little-endian ms, max 32767**.
- Haptics need `protocol.HW_INIT` once per connection (the manager sends it).
- Frames are split at command boundaries to fit the BLE MTU (macro_effect does it).
- **One effect at a time per device**: `play()` cancels the running effect.
  The core relies on this (cast glow → spell payoff).  If you want a
  colour to persist after a payoff, start it when the payoff ends (see
  `OpenCaster.set_aim` / `_payoff_until`).

## Timing to design around
- A cast: press all pads, ~1–2 s gesture, release; recognition takes ~35 ms.
- Packets arrive ~every 86 ms, so motion-driven UI updates at ~12 Hz – smooth it.
- Connect + init + welcome animation takes ~3–4 s per wand; BLE operations
  run one at a time (concurrent WinRT connects fail).
