# Control API

[← OpenCaster](../README.md) · [Documentation](README.md)

While OpenCaster runs (GUI or `python -m opencaster`), other programs can
light and buzz the wands and hear about casts, over plain HTTP + JSON at
`http://127.0.0.1:8765/api`.  Events stream as
[Server-Sent Events](https://developer.mozilla.org/docs/Web/API/Server-sent_events).

| Request | Body / notes |
|---------|--------------|
| `GET /api/status` | wands, duel state, settings |
| `GET /api/wands` | connected wands: address, name, nickname, colour, battery |
| `GET /api/spells` | spells: name, cast colours, difficulty, mastery count |
| `GET /api/events` | event stream (`?include=imu,trail` adds raw motion) |
| `POST /api/light` | `{"wand": "all", "color": "#FF8800", "fade_ms": 300, "hold_ms": 0, "groups": [0,1,2,3]}` — `hold_ms` 0 leaves it on; groups run tip (0) to handle (3) |
| `POST /api/vibrate` | `{"wand": "all", "duration_ms": 200}` |
| `POST /api/clear` | `{"wand": "all"}` |
| `POST /api/effect` | `{"name": "success"}` (success, fail, welcome, glow, breathe, clear, countdown, go, locked_in, round_lost, duel_won), `{"spell": "Lumos"}`, or `{"macro": [...]}` in the spellbook's command format |

`wand` is `"all"` (the default), an address, a wand name (`MCW-F108`) or a
nickname.  Each wand plays one effect at a time, so an API effect replaces
whatever was playing (including the cast glow).

Events: `spell` (wand, spell, colours, mastery count), `cast` (accepted or
not, best match), `casting`, `tap`, `pads`, `wand_connected`, `wand_ready`,
`wand_disconnected`, `wand_info`, `battery`, `duel`, `settings`, `status`.
`duel` snapshots carry `mode` (`race`, `clash` or `club`); the NPC plays as
the player `"npc"` (its `player_info` has `"npc": true` and its `level`, and
the snapshot `npc_level`).  A clash adds
`window_s`, `locked` (who has picked), and after each round `picks`,
`elements` and `line` ("Aguamenti douses Incendio").  Duelling Club adds
`order` (`in_order` or `random`), `turn`, `turn_kind` (`attack` or
`counter`), `turn_no`, `window_s`, `incoming` (the spell to answer), `chain`
(the rally's moves), and once somebody slips up `loser` and `line`; it has a
single round, so `result` is followed by `finished`.

```bash
curl http://127.0.0.1:8765/api/wands
curl -X POST http://127.0.0.1:8765/api/light -H "Content-Type: application/json" \
     -d '{"color": "#FF8800", "hold_ms": 1500}'
curl -N http://127.0.0.1:8765/api/events
```

```python
from opencaster.api.client import OpenCasterClient   # stdlib only: copy the file anywhere

oc = OpenCasterClient()
oc.vibrate(300, wand="MCW-F108")
for event in oc.events():
    if event["type"] == "spell":
        print(event["wand"]["label"], "cast", event["spell"])
        oc.light("#00FF00", hold_ms=1000)
```

Or from the terminal: `python -m opencaster.api light red --hold 1500`,
`... vibrate 300`, `... spell Lumos`, `... listen`.

**Configuration** (`settings.json` → `"api"`): `enabled` (default true),
`host` (default `127.0.0.1`: this computer only), `port` (8765), `token`
(if set, requests need `Authorization: Bearer <token>` or `?token=`), and
`allow_origins` (web pages allowed to call the API; requests from any other
web origin are refused, and POST bodies must be JSON, so a website can't
drive your wand).
