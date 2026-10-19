"""Sounds and videos through Qt Multimedia (cross-platform).  Every call
accepts None for a missing file and does nothing, so the app runs without
the media pack."""

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget


class SoundPlayer:
    def __init__(self, volume: float = 0.9, loop: bool = False):
        self._out = QAudioOutput()
        self._out.setVolume(volume)
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._out)
        if loop:
            self._player.setLoops(QMediaPlayer.Infinite)

    def play(self, path) -> bool:
        if not path:
            return False
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        return True

    def stop(self):
        if self._player.playbackState() != QMediaPlayer.StoppedState:
            self._player.stop()


class VideoPanel(QVideoWidget):
    """Plays a video, or several back to back; emits finished at the end, on
    error, or when clicked (a click skips the rest)."""
    finished = Signal()

    def __init__(self, parent=None, volume: float = 0.7):
        super().__init__(parent)
        self.setAspectRatioMode(Qt.KeepAspectRatio)
        self.setStyleSheet("background: black;")
        self.setToolTip("Click to close")
        self._queue: list = []
        self._out = QAudioOutput()
        self._out.setVolume(volume)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._out)
        self._player.setVideoOutput(self)
        self._player.mediaStatusChanged.connect(self._status)
        self._player.errorOccurred.connect(lambda *_: self._advance())

    def play(self, *paths) -> bool:
        """Play these files in order (None entries are skipped)."""
        self._queue = [p for p in paths if p]
        if not self._queue:
            return False
        self._advance()
        return True

    def stop(self):
        self._queue = []
        if self._player.playbackState() != QMediaPlayer.StoppedState:
            self._player.stop()
        self.finished.emit()

    @property
    def playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlayingState

    def mousePressEvent(self, _e):
        self.stop()

    def _advance(self):
        if not self._queue:
            self.stop()
            return
        self._player.setSource(QUrl.fromLocalFile(str(self._queue.pop(0))))
        self._player.play()

    def _status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self._advance()
