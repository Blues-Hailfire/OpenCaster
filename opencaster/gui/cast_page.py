"""
Cast page: one stage per connected wand (live trail, pads, labelling, videos),
the practice target, last spell, history and (optional) diagnostics.  It only
reacts to core events and sends commands through the bridge; all casting
rules live in opencaster.casting.
"""

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QProgressBar,
                               QPushButton, QStackedLayout, QVBoxLayout, QWidget)

from ..casting import NOT_A_SPELL
from ..spellbook import MASTERY_CASTS
from . import theme as T
from .media import VideoPanel
from .trail import TrailCanvas
from .widgets import FlowLayout, SensorPads, SpellArt, StatusDot, card, section

ANY = "Any spell"
VIDEO_DELAY_MS = 1200       # show the spell burst before its video takes over the stage


class ChipButton(QPushButton):
    hovered = Signal(bool)

    def enterEvent(self, e):
        self.hovered.emit(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.hovered.emit(False)
        super().leaveEvent(e)


class WandStage(QFrame):
    """Everything about one wand on the Cast page."""

    def __init__(self, page, address: str):
        super().__init__()
        self.page, self.state, self.address = page, page.state, address
        self.bridge = page.bridge
        self.setObjectName("Stage")
        self._cast_overlay = None
        self._live = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.dot = StatusDot()
        self.name = QLabel(address)
        self.name.setFont(T.font(12.5, serif=True))
        self.battery = QLabel("")
        self.battery.setObjectName("Dim")
        self.status = QLabel("Hold all four pads to cast")
        self.status.setObjectName("Dim")
        self.pads = SensorPads(radius=8)
        self.pads.toggled.connect(lambda i: self.bridge.call("toggle_override", self.address, i))
        for w in (self.dot, self.name, self.battery):
            head.addWidget(w)
        head.addStretch()
        head.addWidget(self.status)
        head.addWidget(self.pads)
        lay.addLayout(head)

        body = QWidget()
        self.stack = QStackedLayout(body)
        self.canvas = TrailCanvas(self.state.sizes.typical)
        self.video = VideoPanel()
        self.video.finished.connect(lambda: self.stack.setCurrentWidget(self.canvas))
        self._video_timer = QTimer(self)            # videos wait for the burst/result to show
        self._video_timer.setSingleShot(True)
        self._video_timer.timeout.connect(lambda: self.play_video(*self._video_queue))
        self._video_queue: tuple = ()
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.video)
        lay.addWidget(body, 1)

        self.label_card, lc = card(margins=(14, 10, 14, 10), spacing=6)
        self.label_prompt = QLabel()
        self.label_prompt.setFont(T.font(11, serif=True))
        chips = QWidget()
        self.chip_flow = FlowLayout(chips, spacing=6)
        lc.addWidget(self.label_prompt)
        lc.addWidget(chips)
        self.label_card.hide()
        lay.addWidget(self.label_card)
        self.set_info(self.state.wands.get(address, {}))

    # ── info ──────────────────────────────────────────────────────────────────

    def set_info(self, info: dict):
        color = info.get("color") or self.state.wand_color(self.address)
        self.name.setText(info.get("label") or self.address)
        self.name.setStyleSheet(f"color: {QColor(color).lighter(150).name()};")
        self.dot.set_color(color if info.get("connected") else T.AMBER)
        pct = info.get("battery")
        self.battery.setText("reconnecting…" if not info.get("connected") else
                             f"▮ {pct}%" if pct is not None else "")
        self.canvas.set_accent(color)

    def set_guide(self, tmpl):
        self.canvas.set_guide(tmpl)
        if not self._live:
            self.clear()

    def clear(self):
        self._cast_overlay = None
        self.canvas.set_overlay(None, None)
        self.canvas.set_trail(None, False)
        self._idle_title()

    def _idle_title(self):
        tmpl = self.canvas.guide
        if tmpl:
            self.canvas.set_title(f"Practise {tmpl.name}", T.BLUE,
                                  "start at the dot - only this spell will be accepted")
        else:
            self.canvas.set_title("", T.TEXT)

    def play_video(self, *paths) -> bool:
        if any(paths) and self.isVisible():        # not with another page in front (it has sound)
            self.stack.setCurrentWidget(self.video)
            return self.video.play(*paths)
        return False

    def play_video_later(self, *paths, delay_ms: int = VIDEO_DELAY_MS):
        """Let the burst / result be seen first; a new cast cancels it."""
        if any(paths):
            self._video_queue = paths
            self._video_timer.start(delay_ms)

    def stop_video(self):
        self._video_timer.stop()
        self.video.stop()

    # ── core events ───────────────────────────────────────────────────────────

    def on_pads(self, mask: int):
        self.pads.set_state(mask)
        if not self._live:
            n = bin(mask).count("1")
            self.status.setText("Hold all four pads to cast" if n == 0 else f"{n} of 4 pads held")

    def on_window_open(self, _target):
        self._live = True
        self.stop_video()
        self._cast_overlay = None
        self.canvas.set_overlay(None, None)
        self.canvas.set_trail(None, True)
        self.canvas.set_title("Casting…", T.GOLD, "release any pad to finish")
        self.status.setText("Casting - draw the spell")
        self.status.setStyleSheet(f"color: {T.GOLD};")
        self.state.cast_loop(self.address, True)

    def on_trail(self, trail):
        self.canvas.set_trail(trail, True)

    def _closed(self):
        self._live = False
        self.status.setStyleSheet("")
        self.state.cast_loop(self.address, False)
        self.on_pads(self.pads.mask)

    def on_tap(self, held: float):
        self._closed()
        self.canvas.set_trail(None, False)
        self.canvas.set_title("", T.TEXT, f"quick tap ({held:.1f} s) - not a cast")

    def on_timeout(self, _p=None):
        self.page.add_log(f"{self.state.wand_label(self.address)}: gesture timeout")

    def on_calibrating(self, _p=None):
        self._closed()
        self.canvas.set_title("Calibrating", T.TEXT_DIM, "spell matching is paused")

    def on_cast(self, r):
        self._closed()
        self.canvas.set_trail(r.trail if len(r.trail) else None, False)
        best = r.best
        tmpl = self.state.template(r.target or (best.spell if best else None))
        kind = None
        if best:
            kind = ("match" if r.accepted else "miss") if r.target else \
                   ("match" if r.accepted else "guess")
        self._cast_overlay = (tmpl, kind) if tmpl and kind else None
        self.canvas.set_overlay(tmpl, kind)
        if not r.accepted:
            self.canvas.set_title(f"✗  {r.message()}", T.RED,
                                  "closest shape shown dashed" if best else "")
            # Not while labelling: the trail and closest shape are needed to answer.
            if (r.gate == "ok" and not self.state.duelling and self.state.flag("video", True)
                    and self.state.flag("mishaps", True) and not self.page.label_box.isChecked()):
                self.play_video_later(self.state.media.mishap())

    def on_spell(self, s: dict, media: bool = True):
        name, info = s["name"], s["info"]
        sub = info.pronunciation if info and info.pronunciation else ""
        if s["source"] == "wand":
            sub = "recognised by the wand" + (f"  ·  {sub}" if sub else "")
        if s.get("mastered_now"):
            sub = "Spell mastered!" + (f"  ·  {sub}" if sub else "")
        self.canvas.set_title(f"✦  {name}", T.VIOLET, sub)
        self.canvas.burst(info.colors if info and info.colors else [self.state.wand_color(self.address)])
        if self.state.flag("sound", True) and info:
            self.state.sound(self.address).play(info.sound())
        if media and self.state.flag("video", True):
            self.play_video_later(info.video if info else None, s.get("patronus_video"),
                                  self.state.media.mastery_video if s.get("mastered_now") else None)

    def on_blocked(self, _p=None):
        self.canvas.set_title("Label the last cast first", T.RED, "")
        self.label_prompt.setStyleSheet(f"color: {T.RED};")

    def on_label_needed(self, record: dict):
        self.chip_flow.clear()
        target = record.get("target")
        guess = record["predicted"] if record["accepted"] else None
        self.label_prompt.setStyleSheet(f"color: {T.GOLD};")
        if target:
            self.label_prompt.setText(f"Was that {target}?")
            self._chip(f"Yes, {target}", target, guess == target)
        else:
            self.label_prompt.setText("What did you cast?")
            ranked = [s for s, _ in record["scores"][:5]]
            for name in ranked:
                self._chip(name, name, name == guess)
            other = QComboBox()
            other.addItem("Other spell…")
            other.addItems([t.name for t in self.state.templates if t.name not in ranked])
            other.activated.connect(lambda i, c=other: i > 0 and self._submit(c.itemText(i)))
            self.chip_flow.addWidget(other)
        self._chip("Not a spell", NOT_A_SPELL, False)
        b = self._chip("Discard", None, False)
        b.setStyleSheet(f"color: {T.RED}; border-radius: 12px; padding: 4px 12px;")
        self.label_card.show()

    def _chip(self, text: str, value, highlighted: bool) -> ChipButton:
        b = ChipButton(text)
        b.setObjectName("ChipGuess" if highlighted else "Chip")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda: self._submit(value))
        tmpl = self.state.template(value) if value not in (None, NOT_A_SPELL) else None
        if tmpl:
            b.hovered.connect(lambda on, t=tmpl: self.canvas.set_overlay(
                *((t, "preview") if on else (self._cast_overlay or (None, None)))))
        self.chip_flow.addWidget(b)
        return b

    def _submit(self, label: Optional[str]):
        self.label_card.hide()
        self.canvas.set_overlay(*(self._cast_overlay or (None, None)))
        self.bridge.call("label", self.address, label)

    def on_labelled(self, payload) -> str:
        label, total, record = payload
        self.label_card.hide()
        if label is not None:
            self.state.sizes.add(dict(record, label=label))
        return ("Cast discarded" if label is None else
                f"Saved as '{'not a spell' if label == NOT_A_SPELL else label}'"
                + (f" - {total} labelled casts" if total else ""))


class CastPage(QWidget):
    HISTORY_MAX = 40
    LOG_MAX = 400

    def __init__(self, state, open_calibration, parent=None):
        super().__init__(parent)
        self.state = state
        self.bridge = state.bridge
        self._open_calibration = open_calibration
        self.stages: dict = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(self._build_left())
        root.addLayout(self._build_centre(), 1)
        root.addWidget(self._build_diagnostics())
        self._refresh_targets()
        state.library_changed.connect(self._refresh_targets)
        state.wands_changed.connect(self._wands_changed)

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_left(self) -> QWidget:
        col = QWidget()
        col.setFixedWidth(280)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        last, ll = card("Last spell")
        self.last_art = SpellArt(glyph_width=3.0)
        self.last_art.setMinimumHeight(250)
        self.last_art.set_spell("", "#2a1f4a", None)
        self.last_by = QLabel("")
        self.last_by.setObjectName("Dim")
        self.mastery = QLabel("Cast a spell to begin")
        self.mastery.setObjectName("Dim")
        self.mastery_bar = QProgressBar()
        self.mastery_bar.setRange(0, MASTERY_CASTS)
        self.mastery_bar.setTextVisible(False)
        self.mastery_bar.setFixedHeight(6)
        self.mastery_bar.hide()
        for w in (self.last_art, self.last_by, self.mastery, self.mastery_bar):
            ll.addWidget(w, 1 if w is self.last_art else 0)
        lay.addWidget(last, 3)
        hist, hl = card("Recent casts", spacing=4)
        self.history = QListWidget()
        self.history.setFocusPolicy(Qt.NoFocus)
        hl.addWidget(self.history)
        lay.addWidget(hist, 2)
        return col

    def _build_centre(self) -> QVBoxLayout:
        lay = QVBoxLayout()
        lay.setSpacing(12)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        bar.addWidget(section("Practise"))
        self.target = QComboBox()
        self.target.setMinimumWidth(220)
        self.target.setMaxVisibleItems(18)
        self.target.currentTextChanged.connect(self._on_target_changed)
        bar.addWidget(self.target)
        bar.addStretch()
        self.label_box = self._toggle(bar, "Label casts", "label_casts", True,
                                      "Ask what each cast was and save it for tuning",
                                      lambda on: self.bridge.call("set_label_casts", on))
        self.sound_box = self._toggle(bar, "Sound", "sound", True, "Casting sounds")
        self.video_box = self._toggle(bar, "Video", "video", True,
                                      "Spell videos after successful casts (and mishaps)")
        lay.addLayout(bar)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.placeholder = QFrame()
        self.placeholder.setObjectName("Stage")
        pl = QVBoxLayout(self.placeholder)
        empty = TrailCanvas(self.state.sizes.typical)
        empty.hint = "Connect a wand to start casting"
        pl.addWidget(empty)
        lay.addWidget(self.grid_host, 1)
        self._relayout()

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.cal_btn = QPushButton("Calibrate")
        self.cal_btn.setToolTip("Measure a wand's tip axis and gyro bias (30 s)")
        self.cal_btn.clicked.connect(self._calibrate_clicked)
        tools.addWidget(self.cal_btn)
        for text, tip, fn in (
                ("Reload spells", "Reload spells/ and media/ without restarting",
                 lambda: self.bridge.call("reload")),
                ("Clear", "Clear the trails", self.clear)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            tools.addWidget(b)
        tools.addStretch()
        self.diag_btn = QPushButton("Diagnostics")
        self.diag_btn.setCheckable(True)
        self.diag_btn.setChecked(self.state.flag("diagnostics", False))
        self.diag_btn.toggled.connect(self._toggle_diagnostics)
        tools.addWidget(self.diag_btn)
        lay.addLayout(tools)
        return lay

    def _build_diagnostics(self) -> QWidget:
        self.diag = QWidget()
        self.diag.setFixedWidth(300)
        lay = QVBoxLayout(self.diag)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        scores, sl = card("Match scores")
        self.scores = QLabel("—")
        self.scores.setTextFormat(Qt.RichText)
        self.scores.setWordWrap(True)
        sl.addWidget(self.scores)
        lay.addWidget(scores)
        imu, il = card("Last IMU sample")
        self.imu = QLabel("—")
        self.imu.setStyleSheet(f"font-family: Consolas; font-size: 8.5pt; color: {T.BLUE};")
        il.addWidget(self.imu)
        lay.addWidget(imu)
        log, gl = card("Events", spacing=4)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(self.LOG_MAX)
        gl.addWidget(self.log)
        lay.addWidget(log, 1)
        self.diag.setVisible(self.diag_btn.isChecked())
        self._imu_rows: dict = {}
        return self.diag

    def _toggle(self, bar, text, key, default, tip, on_change=None) -> QCheckBox:
        box = QCheckBox(text)
        box.setToolTip(tip)
        box.setChecked(self.state.flag(key, default))

        def changed(on):
            self.state.set_flag(key, on)
            if on_change:
                on_change(on)
        box.toggled.connect(changed)
        bar.addWidget(box)
        return box

    def _toggle_diagnostics(self, on: bool):
        self.diag.setVisible(on)
        self.state.set_flag("diagnostics", on)

    # ── stages ────────────────────────────────────────────────────────────────

    def stage(self, address: str) -> WandStage:
        if address not in self.stages:
            st = WandStage(self, address)
            st.set_guide(self._target_template())
            self.stages[address] = st
            self._relayout()
        return self.stages[address]

    def remove_stage(self, address: str):
        st = self.stages.pop(address, None)
        if st:
            st.stop_video()
            self.state.cast_loop(address, False)
            st.setParent(None)
            st.deleteLater()
            self._relayout()

    def _relayout(self):
        while self.grid.count():
            self.grid.takeAt(0)
        widgets = list(self.stages.values()) or [self.placeholder]
        self.placeholder.setVisible(not self.stages)
        cols = 1 if len(widgets) == 1 else 2 if len(widgets) <= 4 else 3
        for i, w in enumerate(widgets):
            self.grid.addWidget(w, i // cols, i % cols)
        for c in range(3):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)

    def _wands_changed(self):
        for a, st in self.stages.items():
            st.set_info(self.state.wands.get(a, {}))

    def wand_event(self, name: str, address: str, payload):
        """Route a per-wand session event to that wand's stage."""
        st = self.stage(address)
        handler = getattr(st, f"on_{name}", None)
        result = handler(payload) if handler else None
        if name == "cast":
            if not payload.accepted:
                self._add_history(payload.message(), address, ok=False)
            self._show_scores(payload, address)
        return result

    # ── commands ──────────────────────────────────────────────────────────────

    def start(self):
        """Push GUI settings into the core once it is running."""
        self.bridge.call("set_label_casts", self.label_box.isChecked())
        self._on_target_changed(self.target.currentText())

    def practise(self, name: str):
        self.target.setCurrentText(name)

    def clear(self):
        for st in self.stages.values():
            st.clear()

    def _calibrate_clicked(self):
        wands = self.state.connected_wands()
        if len(wands) <= 1:
            self._open_calibration(wands[0] if wands else None)
            return
        menu = QMenu(self)
        for a in wands:
            menu.addAction(self.state.wand_label(a), lambda a=a: self._open_calibration(a))
        menu.exec(self.cal_btn.mapToGlobal(self.cal_btn.rect().topLeft()))

    def _refresh_targets(self):
        current = self.target.currentText() or ANY
        self.target.blockSignals(True)
        self.target.clear()
        self.target.addItems([ANY] + [t.name for t in self.state.templates])
        self.target.setCurrentText(current if self.target.findText(current) >= 0 else ANY)
        self.target.blockSignals(False)
        self._on_target_changed(self.target.currentText())

    def _target_template(self):
        name = self.target.currentText()
        return None if name in (ANY, "") else self.state.template(name)

    def _on_target_changed(self, _text):
        tmpl = self._target_template()
        self.bridge.call("set_target", tmpl.name if tmpl else None)
        for st in self.stages.values():
            st.set_guide(tmpl)

    # ── page-level events ─────────────────────────────────────────────────────

    def on_spell(self, s: dict, media: bool = True):
        name, info, count = s["name"], s["info"], s["count"]
        tmpl = self.state.template(name)
        self.last_art.set_spell(name, self.state.color(name), tmpl.outline if tmpl else None,
                                info.pronunciation if info else "", self.state.icon(name))
        self.last_by.setText(f"by {s['wand_label']}" if len(self.stages) > 1 else "")
        self.mastery_bar.show()
        self.mastery_bar.setValue(min(count, MASTERY_CASTS))
        self.mastery.setText(f"Mastered - cast {count} times" if count >= MASTERY_CASTS
                             else f"Cast {count} of {MASTERY_CASTS} to master")
        self._add_history(name, s["wand"], ok=True)
        self.stage(s["wand"]).on_spell(s, media)

    def on_imu(self, address: str, sample):
        if not self.diag.isVisible():
            return
        ax, ay, az, gx, gy, gz = sample
        k = 57.29578
        self._imu_rows[address] = (f"{self.state.wand_label(address)}\n"
                                   f"a  {ax:+.2f} {ay:+.2f} {az:+.2f}  g\n"
                                   f"ω  {gx * k:+5.0f} {gy * k:+5.0f} {gz * k:+5.0f}  °/s")
        self.imu.setText("\n".join(self._imu_rows.values()))

    def add_log(self, text: str, colour: Optional[str] = None):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.appendHtml(f"<span style='color:{T.TEXT_FAINT}'>{ts}</span>&nbsp; "
                            f"<span style='color:{colour or T.TEXT_DIM}'>{text}</span>")

    def _add_history(self, text: str, address: str, ok: bool):
        who = f"   ({self.state.wand_label(address)})" if len(self.stages) > 1 else ""
        item = QListWidgetItem(f"{datetime.now().strftime('%H:%M')}   "
                               f"{'✦' if ok else '✗'}  {text}{who}")
        item.setForeground(QColor(T.VIOLET if ok else T.TEXT_FAINT))
        if ok:
            item.setFont(T.font(10.5, serif=True))
        self.history.insertItem(0, item)
        while self.history.count() > self.HISTORY_MAX:
            self.history.takeItem(self.history.count() - 1)

    def _show_scores(self, r, address: str):
        head = (f"<div style='color:{T.TEXT_FAINT}; margin-bottom:3px'>"
                f"{self.state.wand_label(address)}</div>") if len(self.stages) > 1 else ""
        if not r.ranked:
            self.scores.setText(head + f"<span style='color:{T.TEXT_FAINT}'>{r.message()}</span>")
            return
        rows = list(r.ranked[:5])
        tgt = r.score_of(r.target) if r.target else None
        if tgt and tgt not in rows:
            rows.append(tgt)
        html = head + "<table width='100%' cellspacing='0' cellpadding='2'>"
        for m in rows:
            colour = T.TEAL if m.success else (T.BLUE if tgt is m else T.TEXT_DIM)
            mark = "✓" if m.success else ("◎" if tgt is m else "")
            html += (f"<tr><td style='color:{colour}' width='14'>{mark}</td>"
                     f"<td style='color:{colour}'>{m.spell}</td>"
                     f"<td align='right' style='color:{colour}; font-family:Consolas'>{m.score:.3f}</td>"
                     f"<td align='right' style='color:{T.TEXT_FAINT}; font-family:Consolas'>"
                     f"/{m.threshold:.2f}</td></tr>")
        html += "</table>"
        if r.best and r.best.margin != float("inf"):
            html += (f"<div style='color:{T.TEXT_FAINT}; margin-top:4px'>"
                     f"margin ×{r.best.margin:.2f}</div>")
        self.scores.setText(html)
