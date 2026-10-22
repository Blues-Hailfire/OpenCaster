"""Download the media pack (opencaster.media_pack) from the GUI: offered once
on first start when the casting sounds are missing, and from Settings."""

import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from .. import media_pack, paths

DECLINED = "media_pack_declined"        # QSettings key: "Not now" on the first-start offer


def target(media_dir: Path) -> Path:
    """Where to install: the spellbook's media folder, or – an exe in a
    read-only folder – the user's data folder, which is preferred from the
    next start on (opencaster.paths)."""
    if paths._writable(media_dir):
        return media_dir
    return paths.ROOT / "media"


def missing(state) -> bool:
    media_dir = state.spellbook.media_dir
    return not (media_pack.installed(media_dir) or media_pack.installed(target(media_dir)))


class _Relay(QObject):
    progress = Signal(str, float)       # stage, fraction
    finished = Signal(object)           # counts dict, or the exception


def offer_on_start(parent, state):
    """First start without the media pack: ask once."""
    if not missing(state) or state.prefs.value(DECLINED, False, type=bool):
        return
    box = QMessageBox(QMessageBox.Question, "Media pack",
                      "Each spell has its own casting sounds and video in the media pack, "
                      f"a {media_pack.SIZE / 1e6:.0f} MB download.\n\nDownload it now?  "
                      "(You can also do it later from Settings.)", parent=parent)
    yes = box.addButton("Download", QMessageBox.AcceptRole)
    box.addButton("Not now", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is yes:
        download(parent, state)
    else:
        state.prefs.setValue(DECLINED, True)


def download(parent, state):
    media_dir = state.spellbook.media_dir
    dest = target(media_dir)
    dlg = QProgressDialog("Connecting…", "Cancel", 0, 1000, parent)
    dlg.setWindowTitle("Media pack")
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.setMinimumWidth(420)
    stop = threading.Event()
    relay = _Relay(dlg)
    shown = [None]

    def progress(stage, done, total):           # worker thread: only report changes
        step = (stage, int(1000 * done / total) if total else 0)
        if step != shown[0]:
            shown[0] = step
            relay.progress.emit(stage, step[1] / 1000)

    def run():
        try:
            if dest != media_dir and (media_dir / "spellbook.json").is_file() \
                    and not (dest / "spellbook.json").exists():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(media_dir / "spellbook.json", dest / "spellbook.json")
            relay.finished.emit(media_pack.install(dest, progress=progress, cancelled=stop.is_set))
        except Exception as e:                  # reported in the dialog
            relay.finished.emit(e)

    def on_progress(stage, fraction):
        size = media_pack.SIZE / 1e6
        dlg.setLabelText(f"Downloading the media pack… {fraction * size:.0f} of {size:.0f} MB"
                         if stage == "download" else "Installing sounds and videos…")
        dlg.setValue(int(fraction * 1000))

    def on_finished(result):
        dlg.close()
        dlg.deleteLater()
        if isinstance(result, media_pack.Cancelled):
            QMessageBox.information(parent, "Media pack", "Download paused.  Start it again from "
                                    "Settings and it carries on where it stopped.")
        elif isinstance(result, Exception):
            QMessageBox.warning(parent, "Media pack", f"The media pack wasn't installed:\n{result}"
                                "\n\nTry again from Settings; a download in progress resumes.")
        elif dest != media_dir:
            QMessageBox.information(parent, "Media pack", f"Installed in {dest}.\n"
                                    "Restart OpenCaster to hear and see the spells.")
        else:
            state.bridge.call("reload")
            QMessageBox.information(parent, "Media pack", "Installed – every spell now has its "
                                    "sounds and video.")

    relay.progress.connect(on_progress)
    relay.finished.connect(on_finished)
    dlg.canceled.connect(stop.set)
    dlg.show()
    threading.Thread(target=run, name="opencaster-media-pack", daemon=True).start()
