"""
Spellbook page: a grid of spell cards (tinted with each spell's colour, white
gesture glyph, serif name) and a detail view with pronunciation, lore,
mastery, effect preview and the payoff video, like the original app.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QScrollArea, QStackedLayout, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..settings import HOUSES
from ..spellbook import MASTERY_CASTS
from . import theme as T
from .media import VideoPanel
from .settings_dialog import _chip_icon
from .widgets import FlowLayout, SpellArt, SpellCard, card, section


class SpellbookPage(QWidget):
    def __init__(self, state, practise, parent=None):
        super().__init__(parent)
        self.state = state
        self._practise = practise
        self._cards: dict = {}
        self._current = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        root.addWidget(self.pages)
        self.pages.addWidget(self._build_grid())
        self.pages.addWidget(self._build_detail())

        state.library_changed.connect(self._populate)
        state.progress_changed.connect(self._on_progress)
        state.config_changed.connect(self._config_changed)
        self._populate()

    def _config_changed(self):
        t = self.state.template(self._current)
        if t and self.pages.currentIndex() == 1:
            self._show_choice(t.key)

    # ── grid ──────────────────────────────────────────────────────────────────

    def _build_grid(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        kicker = QLabel("MAGIC CASTER")
        kicker.setObjectName("Section")
        title = QLabel("Spellbook")
        title.setFont(T.font(28, serif=True))
        self.summary = QLabel("")
        self.summary.setObjectName("Dim")
        titles.addWidget(kicker)
        titles.addWidget(title)
        titles.addWidget(self.summary)
        head.addLayout(titles)
        head.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search spells…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self._filter)
        head.addWidget(self.search, 0, Qt.AlignBottom)
        lay.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.flow = FlowLayout(self.grid_host, spacing=16, center=True)
        self.flow.setContentsMargins(2, 2, 2, 12)
        scroll.setWidget(self.grid_host)
        lay.addWidget(scroll, 1)
        return w

    def _populate(self):
        self.flow.clear()
        self._cards = {}
        for t in self.state.templates:
            c = SpellCard(t.name, self.state.color(t.name), t.outline, self.state.mastered(t.name),
                          self.state.icon(t.name))
            c.clicked.connect(self.show_spell)
            self.flow.addWidget(c)
            self._cards[t.key] = c
        self._filter(self.search.text())
        self._update_summary()
        if self._current and not self.state.template(self._current):
            self.pages.setCurrentIndex(0)

    def _filter(self, text: str):
        text = text.strip().lower()
        for t in self.state.templates:
            info = self.state.info(t.name)
            hay = f"{t.name} {info.subtitle if info else ''} {info.spell_type if info else ''}".lower()
            self._cards[t.key].setVisible(not text or text in hay)
        self.flow.invalidate()

    def _update_summary(self):
        n = len(self.state.templates)
        m = sum(self.state.mastered(t.name) for t in self.state.templates)
        self.summary.setText(f"{n} spells  ·  {m} mastered")

    def _on_progress(self, name: str):
        t = self.state.template(name)
        if t and t.key in self._cards:
            self._cards[t.key].mastered = self.state.mastered(name)
            self._cards[t.key].update()
        self._update_summary()
        if self.pages.currentIndex() == 1 and self.state.template(self._current) is t:
            self.show_spell(self._current)

    # ── detail ────────────────────────────────────────────────────────────────

    def _build_detail(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        back = QPushButton("‹  Spellbook")
        back.setObjectName("Ghost")
        back.setFont(T.font(11, serif=True))
        back.clicked.connect(self._back)
        lay.addWidget(back, 0, Qt.AlignLeft)

        body = QHBoxLayout()
        body.setSpacing(24)
        hero = QFrame()
        hero.setFixedWidth(380)
        self.hero_stack = QStackedLayout(hero)
        self.art = SpellArt(glyph_width=4.0)
        self.video = VideoPanel()
        self.video.finished.connect(lambda: self.hero_stack.setCurrentWidget(self.art))
        self.hero_stack.addWidget(self.art)
        self.hero_stack.addWidget(self.video)
        body.addWidget(hero)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        info = QWidget()
        il = QVBoxLayout(info)
        il.setContentsMargins(0, 0, 12, 0)
        il.setSpacing(10)
        self.d_name = QLabel()
        self.d_name.setFont(T.font(32, serif=True))
        self.d_pron = QLabel()
        self.d_pron.setFont(T.font(12, italic=True))
        self.d_pron.setObjectName("Dim")
        self.d_sub = QLabel()
        self.d_sub.setFont(T.font(13, serif=True, italic=True))
        self.d_sub.setStyleSheet(f"color: {T.GOLD};")
        self.d_tags = QLabel()
        self.d_tags.setObjectName("Section")
        for x in (self.d_name, self.d_pron, self.d_sub, self.d_tags):
            il.addWidget(x)

        mastery, ml = card(margins=(18, 14, 18, 14), spacing=6)
        self.m_title = QLabel()
        self.m_title.setFont(T.font(11.5, bold=True))
        self.m_text = QLabel()
        self.m_text.setObjectName("Dim")
        self.m_bar = QProgressBar()
        self.m_bar.setRange(0, MASTERY_CASTS)
        self.m_bar.setTextVisible(False)
        self.m_bar.setFixedHeight(7)
        for x in (self.m_title, self.m_text, self.m_bar):
            ml.addWidget(x)
        il.addWidget(mastery)

        # Expecto Patronum: choose the Patronus; Colovaria: the house colour
        self.choice, cl = card(margins=(18, 12, 18, 12), spacing=6)
        self.choice_label = QLabel()
        self.choice_label.setFont(T.font(11.5, bold=True))
        self.choice_combo = QComboBox()
        self.choice_combo.setMaxVisibleItems(20)
        self.choice_combo.activated.connect(self._choice_made)
        cl.addWidget(self.choice_label)
        cl.addWidget(self.choice_combo)
        self.choice.hide()
        il.addWidget(self.choice)

        self.d_overview_h = section("Overview")
        self.d_overview = QLabel()
        self.d_uses_h = section("Notable uses")
        self.d_uses = QLabel()
        for x in (self.d_overview, self.d_uses):
            x.setWordWrap(True)
            x.setFont(T.font(11))
            x.setStyleSheet(f"color: {T.TEXT}; line-height: 140%;")
        for x in (self.d_overview_h, self.d_overview, self.d_uses_h, self.d_uses):
            il.addWidget(x)
        il.addSpacing(8)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.b_practise = QPushButton("Practise this spell")
        self.b_practise.setObjectName("Primary")
        self.b_practise.clicked.connect(lambda: self._practise(self._current))
        self.b_wand = QPushButton("Play on wand")
        self.b_wand.setToolTip("Play the spell's light and haptic effect on the wand (and box)")
        self.b_wand.clicked.connect(lambda: self.state.bridge.call("preview", self._current))
        self.b_sound = QPushButton("Play sound")
        self.b_sound.clicked.connect(self._play_sound)
        self.b_video = QPushButton("Watch video")
        self.b_video.clicked.connect(self._play_video)
        for b in (self.b_practise, self.b_wand, self.b_sound, self.b_video):
            buttons.addWidget(b)
        buttons.addStretch()
        il.addLayout(buttons)
        il.addStretch()
        scroll.setWidget(info)
        body.addWidget(scroll, 1)
        lay.addLayout(body, 1)
        return w

    def show_spell(self, name: str):
        t = self.state.template(name)
        if t is None:
            return
        self._current = t.name
        info = self.state.info(t.name)
        self.video.stop()
        self.art.set_spell(t.name, self.state.color(t.name), t.outline,
                           info.pronunciation if info else "", self.state.icon(t.name))
        self.d_name.setText(t.name)
        self.d_pron.setText(info.pronunciation if info else "")
        self.d_sub.setText(info.subtitle if info else "")
        self.d_sub.setVisible(bool(info and info.subtitle))
        self.d_tags.setText("  ·  ".join(x for x in (
            info.spell_type.upper() if info else "", info.difficulty_name.upper() if info else "")
            if x) if info else "NOT IN THE SPELLBOOK")

        count = self.state.count(t.name)
        level = f"{info.difficulty_name} Spell" if info else "Spell"
        self.m_title.setText(("★  " if count >= MASTERY_CASTS else "") + level)
        self.m_title.setStyleSheet(f"color: {T.GOLD if count >= MASTERY_CASTS else T.TEXT};")
        self.m_text.setText("You have completed your mastery of this spell!"
                            if count >= MASTERY_CASTS else
                            f"Successfully cast {MASTERY_CASTS} times to master this spell"
                            f"  ({count} / {MASTERY_CASTS})")
        self.m_bar.setValue(min(count, MASTERY_CASTS))

        for head, label, text in ((self.d_overview_h, self.d_overview, info.description if info else ""),
                                  (self.d_uses_h, self.d_uses, info.notable_uses if info else "")):
            label.setText(text)
            head.setVisible(bool(text))
            label.setVisible(bool(text))
        self.b_sound.setEnabled(bool(info and info.sounds))
        self.b_video.setEnabled(bool(info and info.video))
        self._show_choice(t.key)
        self.pages.setCurrentIndex(1)

    def _show_choice(self, key: str):
        cfg, media = self.state.config, self.state.media
        self.choice_combo.clear()
        if key == "expectopatronum" and media.patronuses:
            self.choice_label.setText("Your Patronus")
            self.choice_combo.addItem("Random", "random")
            for name in media.patronuses:
                self.choice_combo.addItem(name, name)
            current = cfg.get("patronus", "random")
        elif key == "colovaria":
            self.choice_label.setText("Your house (Colovaria's colour)")
            self.choice_combo.addItem("No house", "")
            for name, colour in HOUSES.items():
                self.choice_combo.addItem(_chip_icon(colour), name, name)
            current = cfg.get("house", "")
        else:
            self.choice.hide()
            return
        self.choice_combo.setCurrentIndex(max(0, self.choice_combo.findData(current)))
        self.choice.show()

    def _choice_made(self, _i):
        value = self.choice_combo.currentData()
        if self.choice_label.text().startswith("Your Patronus"):
            self.state.bridge.call("set_patronus", value)
        else:
            self.state.bridge.call("set_house", value)
            if value and self.state.flag("sound", True):
                self.state.sound().play(self.state.media.houses.get(value))

    def _back(self):
        self.video.stop()
        self._current = None
        self.pages.setCurrentIndex(0)

    def _play_sound(self):
        info = self.state.info(self._current)
        if info:
            self.state.sound().play(info.sound())

    def _play_video(self):
        info = self.state.info(self._current)
        if info and info.video:
            patronus = None
            if info.key == "expectopatronum":
                patronus = self.state.media.patronus(self.state.config.get("patronus", "random"))
            self.hero_stack.setCurrentWidget(self.video)
            self.video.play(info.video, patronus)
