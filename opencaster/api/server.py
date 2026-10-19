"""
opencaster.api.server — Local control API (HTTP + Server-Sent Events)
======================================================================
Lets other programs light and buzz the wands and hear about casts, without
any extra dependencies.  Runs on the core's asyncio loop.

    GET  /api                 endpoint list
    GET  /api/status          wands, duel, settings
    GET  /api/wands           connected wands
    GET  /api/spells          spells with colours, difficulty, mastery count
    GET  /api/events          Server-Sent Events stream (?include=imu,trail for extras)
    POST /api/light           {"wand": "all", "color": "#FF8800", "fade_ms": 300,
                               "hold_ms": 0, "groups": [0, 1, 2, 3]}
    POST /api/vibrate         {"wand": "all", "duration_ms": 200}
    POST /api/clear           {"wand": "all"}
    POST /api/effect          {"wand": "all", "name": "success"} | {"spell": "Lumos"}
                              | {"macro": [spellbook-format commands]}

`wand` is "all" (default), an address, a wand name (MCW-F108) or a nickname.
Each wand plays one effect at a time: an API effect replaces whatever was
playing (including the cast glow).

Security: binds to 127.0.0.1 by default.  Requests carrying an Origin header
(i.e. from a web page) are refused unless the origin is listed in
settings.json api.allow_origins, and POST bodies must be JSON, so a web page
can't drive the wand behind your back.  Set api.token to also require
"Authorization: Bearer <token>" (or ?token=).
"""

import asyncio
import json
import logging
from urllib.parse import parse_qs, urlsplit

from ..settings import normalise_color
from ..wand.effects import MAX_MS

log = logging.getLogger(__name__)

VERSION = 1
MAX_BODY = 64 * 1024
MAX_STREAMS = 16
STREAM_QUEUE = 256
KEEPALIVE_S = 15.0

ENDPOINTS = {
    "GET /api/status": "wands, duel state and settings",
    "GET /api/wands": "connected wands",
    "GET /api/spells": "spells: name, colours, difficulty, mastery count",
    "GET /api/events": "Server-Sent Events: spell, cast, casting, pads, wand_connected, "
                       "wand_disconnected, wand_ready, battery, duel, settings, status "
                       "(?include=imu,trail adds raw motion)",
    "POST /api/light": '{"wand":"all","color":"#FF8800","fade_ms":300,"hold_ms":0,"groups":[0,1,2,3]}',
    "POST /api/vibrate": '{"wand":"all","duration_ms":200}',
    "POST /api/clear": '{"wand":"all"}',
    "POST /api/effect": '{"wand":"all","name":"success"} or {"spell":"Lumos"} or {"macro":[...]}',
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _ms(value, default: int = 0) -> int:
    try:
        return max(0, min(int(value if value is not None else default), MAX_MS))
    except (TypeError, ValueError):
        raise ApiError(400, f"not a duration in ms: {value!r}")


class ApiServer:
    def __init__(self, core, enabled: bool = True, host: str = "127.0.0.1", port: int = 8765,
                 token: str = "", allow_origins=(), **_ignored):
        self.core = core
        self.host, self.port = host, int(port)
        self.token = token or ""
        self.allow_origins = {o.rstrip("/") for o in (allow_origins or ())}
        self.server = None
        self._streams: set = set()          # (queue, include set)
        self._writers: set = set()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/api"

    async def start(self):
        try:
            self.server = await asyncio.start_server(self._handle, self.host, self.port)
        except OSError as e:
            self.core.events.emit("status", f"API not started: port {self.port} unavailable ({e})")
            return
        self.core.events.on("*", self._on_event)
        self.core.events.emit("status", f"API listening on {self.url}")

    async def close(self):
        if self.server is None:
            return
        self.core.events.off("*", self._on_event)
        self.server.close()
        for q, _ in tuple(self._streams):
            q.put_nowait(None)
        for w in tuple(self._writers):
            w.close()
        try:
            await asyncio.wait_for(self.server.wait_closed(), 2.0)
        except (asyncio.TimeoutError, Exception):
            pass

    # ── events → SSE ──────────────────────────────────────────────────────────

    def _wand(self, address: str) -> dict:
        return self.core.wand_info(address)

    def serialise(self, name: str, args: tuple):
        """A core event as a JSON-able dict, or None for events not exposed."""
        if name in ("connected", "disconnected", "ready"):
            info = args[0]
            if info.kind == "box":
                return {"type": f"box_{name}", "box": {"name": info.name, "address": info.address}}
            return {"type": f"wand_{name}", "wand": self._wand(info.address)}
        if name == "spell":
            s = args[0]
            return {"type": "spell", "spell": s["name"], "wand": self._wand(s["wand"]),
                    "source": s["source"], "count": s["count"], "mastered_now": s["mastered_now"],
                    "colors": list(s["info"].colors) if s.get("info") else []}
        if name == "cast":
            a, r = args
            return {"type": "cast", "wand": self._wand(a), "accepted": r.accepted,
                    "spell": r.spell, "message": r.message(), "gate": r.gate,
                    "target": r.target,
                    "best": {"spell": r.best.spell, "score": r.best.score} if r.best else None}
        if name == "window_open":
            return {"type": "casting", "wand": self._wand(args[0]), "target": args[1]}
        if name == "tap":
            return {"type": "tap", "wand": self._wand(args[0])}
        if name == "pads":
            return {"type": "pads", "wand": args[0], "pads": [bool(args[1] & (1 << i)) for i in range(4)]}
        if name == "battery":
            return {"type": "battery", "wand": args[0], "percent": args[1]}
        if name == "wand_info":
            return {"type": "wand_info", "wand": args[0]}
        if name == "duel":
            return {"type": "duel", "duel": {k: v for k, v in args[0].items()}}
        if name == "settings":
            s = dict(args[0])
            s.pop("api", None)
            return {"type": "settings", "settings": s}
        if name == "status":
            return {"type": "status", "text": args[0]}
        if name == "imu":
            return {"type": "imu", "wand": args[0], "sample": list(args[1])}
        if name == "trail":
            return {"type": "trail", "wand": args[0], "points": args[1].round(2).tolist()}
        return None

    def _on_event(self, name: str, *args):
        if not self._streams:
            return
        try:
            ev = self.serialise(name, args)
        except Exception:
            log.exception("cannot serialise %s", name)
            return
        if ev is None:
            return
        for q, include in tuple(self._streams):
            if ev["type"] in ("imu", "trail") and ev["type"] not in include:
                continue
            if q.full():                   # slow client: drop its oldest event
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(ev)

    # ── HTTP ──────────────────────────────────────────────────────────────────

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._writers.add(writer)
        origin = None
        try:
            line = await asyncio.wait_for(reader.readline(), 10)
            if not line:
                return
            try:
                method, target, _ = line.decode("latin-1").split()
            except ValueError:
                raise ApiError(400, "bad request line")
            headers = {}
            while True:
                h = await asyncio.wait_for(reader.readline(), 10)
                if h in (b"\r\n", b"\n", b""):
                    break
                if b":" in h:
                    k, v = h.decode("latin-1").split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            url = urlsplit(target)
            path = url.path.rstrip("/") or "/"
            query = parse_qs(url.query)
            origin = headers.get("origin")
            if origin is not None and origin.rstrip("/") not in self.allow_origins:
                raise ApiError(403, "origin not allowed (add it to api.allow_origins)")
            if method == "OPTIONS":
                return await self._send(writer, 204, None, origin)
            if self.token:
                auth = headers.get("authorization", "")
                if auth != f"Bearer {self.token}" and query.get("token", [""])[0] != self.token:
                    raise ApiError(401, "missing or wrong token")
            body = {}
            if method == "POST":
                body = await self._read_body(reader, headers)
            if method == "GET" and path == "/api/events":
                include = {x for v in query.get("include", []) for x in v.split(",")}
                return await self._stream(writer, include, origin)
            result = self._route(method, path, body)
            await self._send(writer, 200, result, origin)
        except ApiError as e:
            await self._send(writer, e.status, {"error": str(e)}, origin)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
            pass
        except Exception as e:
            log.exception("API request failed")
            await self._send(writer, 500, {"error": str(e)}, origin)
        finally:
            self._writers.discard(writer)
            try:
                writer.close()
            except Exception:
                pass

    async def _read_body(self, reader, headers) -> dict:
        if "transfer-encoding" in headers:
            raise ApiError(411, "send a Content-Length body (chunked is not supported)")
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            raise ApiError(400, "bad Content-Length")
        if length > MAX_BODY:
            raise ApiError(413, "body too large")
        if length and not headers.get("content-type", "").startswith("application/json"):
            raise ApiError(415, "POST bodies must be application/json")
        if not length:
            return {}
        raw = await asyncio.wait_for(reader.readexactly(length), 10)
        try:
            body = json.loads(raw)
        except ValueError:
            raise ApiError(400, "body is not valid JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")
        return body

    async def _send(self, writer, status: int, payload, origin):
        reason = {200: "OK", 204: "No Content", 400: "Bad Request", 401: "Unauthorized",
                  403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
                  411: "Length Required", 413: "Payload Too Large",
                  415: "Unsupported Media Type", 500: "Internal Server Error"}.get(status, "")
        body = b"" if payload is None else json.dumps(payload).encode()
        head = [f"HTTP/1.1 {status} {reason}", "Connection: close",
                f"Content-Length: {len(body)}"]
        if payload is not None:
            head.append("Content-Type: application/json")
        head += self._cors(origin)
        try:
            writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + body)
            await writer.drain()
        except ConnectionError:
            pass

    def _cors(self, origin) -> list:
        if origin is None or origin.rstrip("/") not in self.allow_origins:
            return []
        return [f"Access-Control-Allow-Origin: {origin}",
                "Access-Control-Allow-Methods: GET, POST, OPTIONS",
                "Access-Control-Allow-Headers: Content-Type, Authorization"]

    async def _stream(self, writer, include: set, origin):
        if len(self._streams) >= MAX_STREAMS:
            raise ApiError(503, "too many event streams")
        q: asyncio.Queue = asyncio.Queue(STREAM_QUEUE)
        entry = (q, frozenset(include))
        self._streams.add(entry)
        head = ["HTTP/1.1 200 OK", "Content-Type: text/event-stream", "Cache-Control: no-cache",
                "Connection: close"] + self._cors(origin)
        try:
            writer.write(("\r\n".join(head) + "\r\n\r\n").encode())
            hello = {"type": "hello", "version": VERSION, "wands": self.core.wand_list()}
            writer.write(f"event: hello\ndata: {json.dumps(hello)}\n\n".encode())
            await writer.drain()
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), KEEPALIVE_S)
                except asyncio.TimeoutError:
                    writer.write(b": keepalive\n\n")
                    await writer.drain()
                    continue
                if ev is None:
                    break
                writer.write(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode())
                await writer.drain()
        except ConnectionError:
            pass
        finally:
            self._streams.discard(entry)

    # ── routes ────────────────────────────────────────────────────────────────

    def _route(self, method: str, path: str, body: dict):
        core = self.core
        if method == "GET":
            if path in ("/", "/api"):
                return {"name": "OpenCaster", "version": VERSION, "endpoints": ENDPOINTS}
            if path == "/api/status":
                settings = core.settings.snapshot()
                settings.pop("api", None)
                return {"version": VERSION, "wands": core.wand_list(),
                        "duel": core.duel.snapshot() if core.duel else None,
                        "target": core.target, "settings": settings}
            if path == "/api/wands":
                return core.wand_list()
            if path == "/api/spells":
                out = []
                for t in core.library.templates:
                    i = core.spellbook.get(t.name)
                    out.append({"name": t.name, "colors": list(i.colors) if i else [],
                                "difficulty": i.difficulty_name if i else None,
                                "type": i.spell_type if i else None,
                                "pronunciation": i.pronunciation if i else None,
                                "has_effect": bool(i and i.wand_macros),
                                "count": core.progress.count(t.name)})
                return out
            if path.startswith("/api/") and path[5:] in ("light", "vibrate", "clear", "effect"):
                raise ApiError(405, f"use POST {path}")
            raise ApiError(404, f"no such endpoint: {path}")
        if method != "POST":
            raise ApiError(405, "use GET or POST")
        wand = body.get("wand", "all")
        try:
            if path == "/api/light":
                groups = body.get("groups")
                if groups is not None:
                    if not isinstance(groups, list) or not all(g in (0, 1, 2, 3) for g in groups):
                        raise ApiError(400, "groups must be a list of 0-3 (tip to handle)")
                try:
                    color = normalise_color(body.get("color", ""))
                except ValueError as e:
                    raise ApiError(400, str(e))
                targets = core.resolve(wand)
                core.light(wand, color, _ms(body.get("fade_ms"), 300), _ms(body.get("hold_ms")), groups)
                return {"ok": True, "wands": targets}
            if path == "/api/vibrate":
                targets = core.resolve(wand)
                core.vibrate(wand, _ms(body.get("duration_ms"), 200))
                return {"ok": True, "wands": targets}
            if path == "/api/clear":
                targets = core.resolve(wand)
                core.clear(wand)
                return {"ok": True, "wands": targets}
            if path == "/api/effect":
                spell, macro, name = body.get("spell"), body.get("macro"), body.get("name")
                if spell and not core.library.get(spell) and not core.spellbook.get(spell):
                    raise ApiError(404, f"unknown spell {spell!r}")
                if macro is not None and not (isinstance(macro, list)
                                              and all(isinstance(c, dict) for c in macro)):
                    raise ApiError(400, "macro must be a list of command objects")
                if not (spell or macro is not None or name):
                    raise ApiError(400, "give name, spell or macro")
                targets = core.resolve(wand)
                core.play_effect(wand, name=name, spell=spell, macro=macro)
                return {"ok": True, "wands": targets}
        except KeyError as e:
            raise ApiError(404, str(e).strip("'\""))
        raise ApiError(404, f"no such endpoint: {path}")
