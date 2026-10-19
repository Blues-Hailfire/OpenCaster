"""Calibration dialog: a view over casting.calibration.MotionCalibrator state."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout)

from . import theme as T

STEP_COLORS = {"rest": T.TEXT_DIM, "tipup": T.TEAL, "swipe_up": T.BLUE,
               "swipe_right": T.BLUE, "done": T.TEAL, "intro": T.GOLD}
STATUS_COLORS = {"info": T.TEXT_DIM, "ok": T.TEAL, "error": T.RED, "ready": T.BLUE}


class CalibrationDialog(QDialog):
    """Begin → four self-advancing steps → Save.  The core does the work;
    this dialog sends start/finish and renders "calibration" events."""

    def __init__(self, bridge, address: str, label: str = "", parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.address = address
        self._started = self._finished = False
        self.setWindowTitle(f"Calibrate {label or address}")
        self.setModal(True)
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 20)
        lay.setSpacing(8)

        head = QLabel(f"✦  Calibrating {label or address}")
        head.setFont(T.font(17, serif=True))
        head.setStyleSheet(f"color: {T.GOLD};")
        head.setAlignment(Qt.AlignCenter)
        self.steps = QLabel("")
        self.steps.setObjectName("Section")
        self.steps.setAlignment(Qt.AlignCenter)
        self.icon = QLabel("✦")
        self.icon.setFont(T.font(44))
        self.icon.setAlignment(Qt.AlignCenter)
        self.title = QLabel("Motion calibration")
        self.title.setFont(T.font(15, serif=True))
        self.title.setAlignment(Qt.AlignCenter)
        self.instruction = QLabel("Four quick steps, about 30 seconds.\n"
                                  "Each step advances on its own once the wand is held right.")
        self.instruction.setAlignment(Qt.AlignCenter)
        self.instruction.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setFont(T.font(9))

        buttons = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.next_btn = QPushButton("Begin  →")
        self.next_btn.setObjectName("Primary")
        self.cancel_btn.clicked.connect(self.reject)
        self.next_btn.clicked.connect(self._next)
        buttons.addStretch()
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.next_btn)

        for w in (head, self.steps, self.icon, self.title, self.instruction):
            lay.addWidget(w)
        lay.addSpacing(6)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addSpacing(8)
        lay.addLayout(buttons)

    def _next(self):
        if not self._started:
            self._started = True
            self.next_btn.setEnabled(False)
            self.next_btn.setText("Waiting…")
            self.bridge.call("start_calibration", self.address)
        else:
            self._finish(save=True)
            self.accept()

    def show_state(self, s: dict):
        colour = STEP_COLORS.get(s["id"], T.TEXT)
        self.icon.setText(s["icon"])
        self.icon.setStyleSheet(f"color: {colour};")
        self.title.setText(s["title"])
        self.instruction.setText(s["instruction"])
        self.progress.setValue(int(s["progress"] * 100))
        self.status.setText(s["status"])
        self.status.setStyleSheet(f"color: {STATUS_COLORS.get(s['status_kind'], T.TEXT_DIM)};")
        if 0 <= s["step"] < s["steps"] and not s["done"]:
            self.steps.setText(f"Step {s['step'] + 1} of {s['steps']}")
        if s["done"]:
            self.steps.setText("All steps done")
            self.next_btn.setEnabled(True)
            self.next_btn.setText("Save  ✓")

    def _finish(self, save: bool):
        if self._started and not self._finished:
            self._finished = True
            self.bridge.call("finish_calibration", self.address, save)

    def reject(self):
        self._finish(save=False)
        super().reject()
