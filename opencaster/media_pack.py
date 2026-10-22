"""
opencaster.media_pack — Download and install the Magic Caster media pack
=========================================================================
The casting sounds and spell videos (see opencaster.spellbook) aren't in the
repository.  This fetches the preserved resource bundle, checks every file
against the bundle's SHA-256 sums (themselves pinned below) and unpacks it:

    media/sounds/*.mp3      casting, house, wand-awake and ambient sounds
    media/*.mp4             spell payoff, Patronus and mishap videos
    media/spellbook.json    only if missing (the repository has its own)

The download waits in the temp folder (not the repository, which may sync)
and resumes if interrupted; files already in place are skipped, so running
it again is cheap.  setup.ps1 / setup.sh and the GUI's first start offer it.

    python -m opencaster.media_pack              install unless already there
    python -m opencaster.media_pack --check      exit code 0 if installed, 1 if not
    python -m opencaster.media_pack --force      install even if already there
    python -m opencaster.media_pack --dest DIR   install into DIR instead of media/
"""

import argparse
import hashlib
import http.client
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

from .paths import MEDIA_DIR

URL = ("https://pub-d3f20a4c06044ebf9c15674bce52959d.r2.dev/2026-10-11/"
       "magic-caster-resources-2026-10-11.zip")
SIZE = 532_675_900          # bytes, for the prompts
# SHA-256 of the bundle's SHA256SUMS.txt, which vouches for every other file
SUMS_SHA256 = "8aee1a66f0f6a2db85c84e29cb84a2ec5590189f6618a4b06d6017a49bacf0f3"
ASSETS = "zz_spell_assets/957/957/assets/"
USER_AGENT = "OpenCaster"   # the host refuses Python's default one
CHUNK = 1 << 20
RETRIES = 4

# progress(stage, done, total): stage "download" or "install", sizes in bytes
Progress = Optional[Callable[[str, int, int], None]]


class Cancelled(Exception):
    pass


class ChecksumError(ValueError):
    pass


def installed(media_dir=MEDIA_DIR) -> bool:
    """True if the casting sounds are there."""
    media_dir = Path(media_dir)
    return media_dir.is_dir() and any(media_dir.rglob("sfx_*_cast_*.mp3"))


def _tick(progress: Progress, cancelled, stage: str, done: int, total: int):
    if cancelled and cancelled():
        raise Cancelled()
    if progress:
        progress(stage, done, total)


def _check_space(folder: Path, need: int):
    while not folder.exists():
        folder = folder.parent
    free = shutil.disk_usage(folder).free
    if free < need + (50 << 20):
        raise OSError(f"not enough disk space in {folder}: {need / 1e6:.0f} MB needed, "
                      f"{free / 1e6:.0f} MB free")


def part_path(url: str = URL) -> Path:
    """Where the download waits (named after the URL, so another URL never resumes it)."""
    tag = hashlib.sha256(url.encode()).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"opencaster-media-{tag}.zip.part"


def download(url: str = URL, progress: Progress = None, cancelled=None) -> Path:
    """Fetch the bundle into part_path(url), resuming what's already there."""
    part = part_path(url)
    for attempt in range(RETRIES + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=30) as r:
                if r.status == 206:
                    total = int(r.headers["Content-Range"].rsplit("/", 1)[1])
                    mode = "ab"
                else:                           # the whole file: start over
                    total = int(r.headers.get("Content-Length") or 0)
                    have, mode = 0, "wb"
                _check_space(part.parent, total - have)
                with open(part, mode) as f:
                    while chunk := r.read(CHUNK):
                        f.write(chunk)
                        have += len(chunk)
                        _tick(progress, cancelled, "download", have, total)
            if not total or have == total:
                return part
        except urllib.error.HTTPError as e:
            if e.code == 416 and have:          # nothing left to fetch
                return part
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            if attempt == RETRIES:
                raise
        time.sleep(2 * (attempt + 1))
    raise OSError("the download keeps stopping short - try again later")


def _extract(zpath: Path, dest: Path, progress: Progress, cancelled) -> dict:
    counts = {"installed": 0, "unchanged": 0}
    with zipfile.ZipFile(zpath) as z:
        raw = z.read("SHA256SUMS.txt")
        if hashlib.sha256(raw).hexdigest() != SUMS_SHA256:
            raise ChecksumError("the bundle's SHA256SUMS.txt isn't the expected one")
        sums = {}
        for line in raw.decode("utf-8").splitlines():
            digest, _, name = line.strip().partition("  ")
            if name:
                sums[name] = digest
        picks = []                              # (member, target)
        for info in z.infolist():
            name = info.filename[len(ASSETS):]
            low = name.lower()
            if (info.filename.startswith(ASSETS) and name and "/" not in name and "\\" not in name
                    and low.endswith((".mp3", ".mp4"))):
                picks.append((info, (dest / "sounds" if low.endswith(".mp3") else dest) / name))
        if not (dest / "spellbook.json").exists():
            picks.append((z.getinfo("spellbook.json"), dest / "spellbook.json"))

        todo = []
        for info, target in picks:
            want = sums.get(info.filename)
            if not want:
                raise ChecksumError(f"{info.filename} has no checksum")
            if target.is_file() and target.stat().st_size == info.file_size:
                h = hashlib.sha256()
                with open(target, "rb") as f:
                    while chunk := f.read(CHUNK):
                        h.update(chunk)
                if h.hexdigest() == want:
                    counts["unchanged"] += 1
                    continue
            todo.append((info, target, want))
        total = sum(info.file_size for info, _t, _w in todo)
        _check_space(dest, total)
        done = 0
        for info, target, want in todo:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".part")
            h = hashlib.sha256()
            try:
                with z.open(info) as src, open(tmp, "wb") as out:
                    while chunk := src.read(CHUNK):
                        h.update(chunk)
                        out.write(chunk)
                        done += len(chunk)
                        _tick(progress, cancelled, "install", done, total)
                if h.hexdigest() != want:
                    raise ChecksumError(f"{info.filename} is damaged")
                tmp.replace(target)
            finally:
                tmp.unlink(missing_ok=True)
            counts["installed"] += 1
    return counts


def install(dest=MEDIA_DIR, url: str = URL, progress: Progress = None, cancelled=None) -> dict:
    """Download (or resume) the bundle, check it and unpack it into dest.
    Returns {"installed": n, "unchanged": n}.  Raises Cancelled, OSError
    (network, disk), ChecksumError or zipfile.BadZipFile; a cancelled or
    failed download is kept to resume, a damaged one is deleted."""
    dest = Path(dest)
    zpath = download(url, progress, cancelled)
    try:
        counts = _extract(zpath, dest, progress, cancelled)
    except (ChecksumError, zipfile.BadZipFile):
        zpath.unlink(missing_ok=True)
        raise
    zpath.unlink(missing_ok=True)
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencaster.media_pack", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", type=Path, default=MEDIA_DIR, help=f"default: {MEDIA_DIR}")
    ap.add_argument("--url", default=URL)
    ap.add_argument("--check", action="store_true", help="only report whether it's installed")
    ap.add_argument("--force", action="store_true",
                    help="install even if already there (checks and repairs every file)")
    args = ap.parse_args(argv)
    if args.check:
        ok = installed(args.dest)
        print(f"The media pack is {'' if ok else 'not '}installed in {args.dest}")
        return 0 if ok else 1
    if installed(args.dest) and not args.force:
        print(f"The media pack is already installed in {args.dest} (--force checks every file).")
        return 0
    print(f"Downloading the media pack ({SIZE / 1e6:.0f} MB) into {args.dest}")
    shown = [None]

    def show(stage, done, total):
        pct = int(100 * done / total) if total else 0
        if (stage, pct) != shown[0]:
            shown[0] = (stage, pct)
            word = "Downloading" if stage == "download" else "Installing "
            print(f"\r  {word} {pct:3d}%  ({done / 1e6:.0f} of {total / 1e6:.0f} MB)",
                  end="", flush=True)

    try:
        counts = install(args.dest, args.url, show)
    except KeyboardInterrupt:
        print("\nStopped - run it again to resume the download.")
        return 1
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        print(f"\nThe media pack wasn't installed: {e}")
        return 1
    print(f"\nDone: {counts['installed']} files installed, {counts['unchanged']} already there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
