"""
opencaster.api.client — Tiny Python client for the OpenCaster API (stdlib only)
================================================================================
    from opencaster.api.client import OpenCasterClient

    oc = OpenCasterClient()                       # http://127.0.0.1:8765
    oc.light("#FF8800", hold_ms=1500)             # every wand, 1.5 s
    oc.vibrate(300, wand="MCW-F108")
    for event in oc.events():                     # blocks, yields dicts
        if event["type"] == "spell":
            print(event["wand"]["label"], "cast", event["spell"])

Copy this file into another project to use it there; it needs nothing but
the standard library.
"""

import json
import urllib.error
import urllib.request
from typing import Iterator, Optional


class OpenCasterError(RuntimeError):
    pass


class OpenCasterClient:
    def __init__(self, base: str = "http://127.0.0.1:8765", token: str = "", timeout: float = 5.0):
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Optional[dict] = None, timeout=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error", e.reason)
            except Exception:
                msg = e.reason
            raise OpenCasterError(f"{e.code}: {msg}") from None
        except urllib.error.URLError as e:
            raise OpenCasterError(f"OpenCaster isn't reachable at {self.base} ({e.reason})") from None

    def _json(self, method: str, path: str, body: Optional[dict] = None):
        with self._request(method, path, body) as r:
            return json.loads(r.read() or b"null")

    # ── queries ───────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return self._json("GET", "/api/status")

    def wands(self) -> list:
        return self._json("GET", "/api/wands")

    def spells(self) -> list:
        return self._json("GET", "/api/spells")

    # ── commands ──────────────────────────────────────────────────────────────

    def light(self, color: str, wand: str = "all", fade_ms: int = 300, hold_ms: int = 0,
              groups: Optional[list] = None) -> dict:
        body = {"wand": wand, "color": color, "fade_ms": fade_ms, "hold_ms": hold_ms}
        if groups is not None:
            body["groups"] = groups
        return self._json("POST", "/api/light", body)

    def vibrate(self, duration_ms: int = 200, wand: str = "all") -> dict:
        return self._json("POST", "/api/vibrate", {"wand": wand, "duration_ms": duration_ms})

    def clear(self, wand: str = "all") -> dict:
        return self._json("POST", "/api/clear", {"wand": wand})

    def effect(self, name: Optional[str] = None, spell: Optional[str] = None,
               macro: Optional[list] = None, wand: str = "all") -> dict:
        body = {"wand": wand}
        body.update({k: v for k, v in (("name", name), ("spell", spell), ("macro", macro))
                     if v is not None})
        return self._json("POST", "/api/effect", body)

    # ── events ────────────────────────────────────────────────────────────────

    def events(self, include=()) -> Iterator[dict]:
        """Yield events as they happen (blocks).  include=("imu", "trail")
        adds raw motion events."""
        path = "/api/events" + (f"?include={','.join(include)}" if include else "")
        with self._request("GET", path, timeout=60) as r:
            data = []
            for raw in r:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    yield json.loads("\n".join(data))
                    data = []
