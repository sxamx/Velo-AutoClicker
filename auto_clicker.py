"""
Velo AutoClicker
----------------
Auto-clicker preciso para Windows con interfaz premium (PySide6 / Qt).

Logica de clic (probada y estable):
- Clic nativo via SendInput (down+up en una sola llamada) => CPS real y alto.
- Timer de alta precision (busy-wait + timeBeginPeriod) => cadencia estable.
- Modos toggle (on/off) y hold (mantener pulsado). Control SOLO por hotkey.
- Jitter, CPS aleatorio y rango (avanzado). Perfiles con guardado en config.json.

Capa visual (nueva, Qt):
- Ventana frameless con esquinas redondeadas, sombra y barra de titulo propia.
- Switches animados, segmented control, sliders y tarjetas con estilo QSS.
- Overlay topmost frameless con feedback visual al moverlo.
"""

import ctypes
from ctypes import wintypes
import json
import os
import random
import sys
import threading
import time

from PySide6.QtCore import (Qt, QTimer, QPoint, QRect, QSize, QPropertyAnimation,
                            QEasingCurve, Property, Signal, QObject)
from PySide6.QtGui import (QColor, QPainter, QBrush, QPen, QFont, QFontDatabase,
                           QCursor, QGuiApplication)
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
                               QHBoxLayout, QFrame, QLineEdit, QGraphicsDropShadowEffect,
                               QComboBox, QSlider, QSizePolicy)

from pynput import mouse
from pynput.mouse import Button
from pynput.keyboard import Listener as KeyListener, Key

# Version del codigo del clicker. El lanzador la compara contra version.txt
# del repo para decidir si hay una actualizacion disponible.
__VERSION__ = "1.3.0"


# ==========================================================================
#  Clic nativo Windows (SendInput)
# ==========================================================================
user32 = ctypes.WinDLL("user32", use_last_error=True)
try:
    winmm = ctypes.WinDLL("winmm")
    winmm.timeBeginPeriod(1)
except Exception:
    winmm = None

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


INPUT_MOUSE = 0
_extra = ctypes.c_ulong(0)
_extra_ptr = ctypes.cast(ctypes.pointer(_extra), ULONG_PTR)
_CLICK_ARRAY = (INPUT * 2)(
    INPUT(INPUT_MOUSE, _INPUTunion(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, _extra_ptr))),
    INPUT(INPUT_MOUSE, _INPUTunion(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, _extra_ptr))),
)
_INPUT_SIZE = ctypes.sizeof(INPUT)


def native_click():
    user32.SendInput(2, _CLICK_ARRAY, _INPUT_SIZE)


# --- Accionar una TECLA del teclado o un BOTON del mouse (down+up) ----------
# Codigos de mouse extra para SendInput
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

# Teclado via SendInput (keybd)
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class _INPUTunion2(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT2(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion2)]


INPUT_KEYBOARD = 1
MapVirtualKeyW = user32.MapVirtualKeyW

# Mapa de nombres de tecla (pynput) -> Virtual-Key code de Windows
VK_MAP = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "esc": 0x1B,
    "shift": 0xA0, "shift_r": 0xA1, "ctrl_l": 0xA2, "ctrl_r": 0xA3,
    "alt_l": 0xA4, "alt_r": 0xA5, "caps_lock": 0x14,
}


def _vk_for(value):
    v = str(value)
    if v in VK_MAP:
        return VK_MAP[v]
    if len(v) == 1:
        vk = user32.VkKeyScanW(ord(v.upper())) & 0xFF
        return vk
    return None


def make_action_clicker(action):
    """Devuelve una funcion sin argumentos que ejecuta la accion configurada
    (clic de mouse o pulsacion de tecla) mediante SendInput, precomputando
    los arrays de INPUT para maxima velocidad y cadencia estable."""
    if action["type"] == "mouse":
        val = action["value"]
        if val == "left":
            return native_click
        pairs = {
            "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
            "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
            "x1": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1),
            "x2": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2),
        }
        down, up, data = pairs.get(val, (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0))
        arr = (INPUT2 * 2)(
            INPUT2(INPUT_MOUSE, _INPUTunion2(mi=MOUSEINPUT(0, 0, data, down, 0, _extra_ptr))),
            INPUT2(INPUT_MOUSE, _INPUTunion2(mi=MOUSEINPUT(0, 0, data, up, 0, _extra_ptr))),
        )
        size = ctypes.sizeof(INPUT2)

        def _do():
            user32.SendInput(2, arr, size)
        return _do

    # teclado
    vk = _vk_for(action["value"])
    if vk is None:
        return native_click  # respaldo seguro
    scan = MapVirtualKeyW(vk, 0)
    arr = (INPUT2 * 2)(
        INPUT2(INPUT_KEYBOARD, _INPUTunion2(ki=KEYBDINPUT(vk, scan, KEYEVENTF_SCANCODE, 0, _extra_ptr))),
        INPUT2(INPUT_KEYBOARD, _INPUTunion2(ki=KEYBDINPUT(vk, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0, _extra_ptr))),
    )
    size = ctypes.sizeof(INPUT2)

    def _do():
        user32.SendInput(2, arr, size)
    return _do


# ==========================================================================
#  Config / Perfiles
# ==========================================================================
CONFIG_PATH = os.path.join(
    os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
    "config.json",
)

DEFAULT_PROFILE = {
    "cps": 14,
    "mode": "toggle",
    "key": {"type": "keyboard", "value": "f"},
    "action": {"type": "mouse", "value": "left"},
    "jitter": 0,
    "random_cps": False,
    "range_enabled": False,
    "cps_min": 10,
    "cps_max": 18,
}

DEFAULT_CONFIG = {
    "advanced": False,
    "overlay": True,
    "ovx": 12,
    "ovy": 12,
    "winx": None,
    "winy": None,
    "last_profile": "Predeterminado",
    "profiles": {"Predeterminado": dict(DEFAULT_PROFILE)},
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    if not cfg.get("profiles"):
        cfg["profiles"] = {"Predeterminado": dict(DEFAULT_PROFILE)}
    for name, p in cfg["profiles"].items():
        merged = dict(DEFAULT_PROFILE)
        merged.update(p)
        cfg["profiles"][name] = merged
    if cfg["last_profile"] not in cfg["profiles"]:
        cfg["last_profile"] = next(iter(cfg["profiles"]))
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


MOUSE_ICON = "\U0001F5B1"
KEY_ICON = "\u2328"
MOUSE_NAMES = {"left": "Click Izq", "right": "Click Der", "middle": "Click Medio",
               "x1": "Lateral 1", "x2": "Lateral 2"}
SPECIAL_KEY_NAMES = {"space": "ESPACIO", "shift": "SHIFT", "shift_r": "SHIFT",
                     "ctrl_l": "CTRL", "ctrl_r": "CTRL", "alt_l": "ALT", "alt_r": "ALT",
                     "tab": "TAB", "caps_lock": "CAPS"}


def key_icon(key):
    return MOUSE_ICON if key["type"] == "mouse" else KEY_ICON


def key_name(key):
    if key["type"] == "mouse":
        return MOUSE_NAMES.get(key["value"], key["value"])
    v = str(key["value"])
    return SPECIAL_KEY_NAMES.get(v, v.upper())


def key_display(key):
    return f"{key_icon(key)}  {key_name(key)}"


# ==========================================================================
#  Tema (paleta premium)
# ==========================================================================
C_BG = "#0d0f16"
C_TITLEBAR = "#12141d"
C_CARD = "#161925"
C_FIELD = "#0b0d14"
C_ACCENT = "#6d8bff"
C_ACCENT_H = "#8098ff"
C_TXT = "#f4f6fb"
C_SUB = "#7a8194"
C_MUTED = "#9aa1b4"
C_ON = "#3ddc97"
C_OFF = "#ff6b6b"
C_BORDER = "#232838"
C_WARN = "#ffd166"
RADIUS = 18


# ==========================================================================
#  Puente de senales (los listeners corren en otros hilos)
# ==========================================================================
class Bridge(QObject):
    key_captured = Signal(dict)
    capture_cancelled = Signal()
    activate = Signal()      # toggle / start
    deactivate = Signal()    # hold release / stop
    hold_start = Signal()
    real_cps = Signal(float)
    state_changed = Signal(bool)


# ==========================================================================
#  Interruptor tipo pastilla animado
# ==========================================================================
class Switch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked=False):
        super().__init__()
        self._checked = checked
        self._offset = 1.0 if checked else 0.0
        self.setFixedSize(46, 26)
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def isChecked(self):
        return self._checked

    def setChecked(self, value, emit=False):
        value = bool(value)
        if value == self._checked:
            return
        self._checked = value
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if value else 0.0)
        self._anim.start()
        if emit:
            self.toggled.emit(value)

    def getOffset(self):
        return self._offset

    def setOffset(self, v):
        self._offset = v
        self.update()

    offset = Property(float, getOffset, setOffset)

    def mousePressEvent(self, e):
        self.setChecked(not self._checked, emit=True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track_off = QColor("#2a3042")
        track_on = QColor(C_ACCENT)
        r = self._offset
        track = QColor(
            int(track_off.red() + (track_on.red() - track_off.red()) * r),
            int(track_off.green() + (track_on.green() - track_off.green()) * r),
            int(track_off.blue() + (track_on.blue() - track_off.blue()) * r),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 13, 13)
        knob = 20
        margin = 3
        x = margin + (self.width() - knob - 2 * margin) * self._offset
        p.setBrush(QColor("white"))
        p.drawEllipse(int(x), margin, knob, knob)


# ==========================================================================
#  Segmented control (mejor que un combobox para 2-3 opciones)
# ==========================================================================
class Segmented(QWidget):
    changed = Signal(str)

    def __init__(self, options, value):
        super().__init__()
        self._options = options
        self._value = value
        self._btns = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(3)
        self.setObjectName("segmented")
        for opt, label in options:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setObjectName("segbtn")
            b.clicked.connect(lambda _=False, o=opt: self._select(o))
            self._btns[opt] = b
            lay.addWidget(b)
        self._refresh()

    def _select(self, opt):
        if opt == self._value:
            self._btns[opt].setChecked(True)
            return
        self._value = opt
        self._refresh()
        self.changed.emit(opt)

    def setValue(self, opt):
        self._value = opt
        self._refresh()

    def value(self):
        return self._value

    def _refresh(self):
        for opt, b in self._btns.items():
            b.setChecked(opt == self._value)


# ==========================================================================
#  Fila etiqueta + control
# ==========================================================================
def make_row(label_text, widget):
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    lbl = QLabel(label_text)
    lbl.setObjectName("rowlabel")
    lay.addWidget(lbl)
    lay.addStretch(1)
    lay.addWidget(widget)
    return row


# ==========================================================================
#  Overlay topmost
# ==========================================================================
class Overlay(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.movable = False
        self._drag = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._pulse_on = False

        self.box = QFrame(self)
        self.box.setObjectName("overlaybox")
        lay = QVBoxLayout(self.box)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(2)

        self.hint = QLabel("\u2725  arrastra para mover")
        self.hint.setObjectName("ovhint")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.hide()
        lay.addWidget(self.hint)

        self.key_lbl = QLabel("")
        self.key_lbl.setObjectName("ovkey")
        lay.addWidget(self.key_lbl)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        self.state_lbl = QLabel("OFF")
        self.state_lbl.setObjectName("ovstate")
        self.cps_lbl = QLabel("0 CPS")
        self.cps_lbl.setObjectName("ovcps")
        bottom.addWidget(self.state_lbl)
        bottom.addStretch(1)
        bottom.addWidget(self.cps_lbl)
        lay.addLayout(bottom)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.box)

        self._apply_style(C_ACCENT)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse)

    def _apply_style(self, border):
        self.box.setStyleSheet(f"""
            #overlaybox {{
                background: rgba(6,8,13,235);
                border: 2px solid {border};
                border-radius: 12px;
            }}
            #ovkey {{ color: white; font: 600 12px 'Segoe UI'; }}
            #ovstate {{ color: {C_OFF}; font: 800 13px 'Segoe UI'; }}
            #ovcps {{ color: #7cc4ff; font: bold 12px 'Consolas'; }}
            #ovhint {{ color: {C_WARN}; font: bold 9px 'Segoe UI'; }}
        """)

    def set_key(self, key):
        self.key_lbl.setText(key_display(key))
        self.adjustSize()

    def set_state(self, on, target=""):
        self.state_lbl.setText("ON" if on else "OFF")
        self.state_lbl.setStyleSheet(f"color: {C_ON if on else C_OFF};"
                                     " font: 800 13px 'Segoe UI';")
        if not on:
            self.cps_lbl.setText("0 CPS")
        elif target:
            self.cps_lbl.setText(f"-- / {target} CPS")

    def set_cps_text(self, txt):
        self.cps_lbl.setText(txt)

    def set_movable(self, movable):
        self.movable = movable
        if movable:
            self.hint.show()
            self.setCursor(Qt.SizeAllCursor)
            self._pulse_timer.start(420)
        else:
            self.hint.hide()
            self.setCursor(Qt.ArrowCursor)
            self._pulse_timer.stop()
            self._apply_style(C_ACCENT)
        self.adjustSize()

    def _pulse(self):
        self._pulse_on = not self._pulse_on
        self._apply_style(C_WARN if self._pulse_on else "#7a5f1f")

    def mousePressEvent(self, e):
        if self.movable and e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.movable and self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


# ==========================================================================
#  Ventana principal
# ==========================================================================
class MainWindow(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.c = controller
        self._drag = None
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(430)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)  # espacio para la sombra

        self.container = QFrame()
        self.container.setObjectName("container")
        shadow = QGraphicsDropShadowEffect(blurRadius=40, xOffset=0, yOffset=10)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.container.setGraphicsEffect(shadow)
        root.addWidget(self.container)

        self.v = QVBoxLayout(self.container)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(0)

        self._build_titlebar()
        self._build_body()
        self.setStyleSheet(self._qss())

    # ------------------------------------------------------------------
    def _build_titlebar(self):
        bar = QFrame()
        bar.setObjectName("titlebar")
        bar.setFixedHeight(46)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 10, 0)
        dot = QLabel("\u25C9")
        dot.setObjectName("logo")
        title = QLabel("Velo AutoClicker")
        title.setObjectName("title")
        lay.addWidget(dot)
        lay.addSpacing(8)
        lay.addWidget(title)
        lay.addStretch(1)
        self.mini = QPushButton("\u2013")
        self.mini.setObjectName("winbtn")
        self.mini.setCursor(Qt.PointingHandCursor)
        self.mini.clicked.connect(self.showMinimized)
        self.close_b = QPushButton("\u2715")
        self.close_b.setObjectName("winclose")
        self.close_b.setCursor(Qt.PointingHandCursor)
        self.close_b.clicked.connect(self.c.quit)
        lay.addWidget(self.mini)
        lay.addWidget(self.close_b)
        self.v.addWidget(bar)
        self._titlebar = bar

    def _build_body(self):
        body = QWidget()
        b = QVBoxLayout(body)
        b.setContentsMargins(20, 16, 20, 20)
        b.setSpacing(14)
        self.v.addWidget(body)

        # --- Estado ---
        state_card = QFrame()
        state_card.setObjectName("statecard")
        sl = QHBoxLayout(state_card)
        sl.setContentsMargins(16, 14, 16, 14)
        self.state_dot = QLabel("\u2B24")
        self.state_dot.setObjectName("statedot_off")
        self.state_txt = QLabel("DETENIDO")
        self.state_txt.setObjectName("statetxt_off")
        self.hint_txt = QLabel("")
        self.hint_txt.setObjectName("hint")
        sl.addWidget(self.state_dot)
        sl.addSpacing(8)
        sl.addWidget(self.state_txt)
        sl.addStretch(1)
        sl.addWidget(self.hint_txt)
        b.addWidget(state_card)

        # --- Tarjeta ajustes ---
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 8, 16, 16)
        cl.setSpacing(10)
        b.addWidget(card)

        cl.addWidget(self._label_section("AJUSTES"))

        # CPS
        self.cps_edit = QLineEdit(str(self.c.p["cps"]))
        self.cps_edit.setObjectName("field")
        self.cps_edit.setFixedWidth(70)
        self.cps_edit.setAlignment(Qt.AlignCenter)
        self.cps_edit.editingFinished.connect(self.c.on_cps_commit)
        cl.addWidget(make_row("Clics por segundo", self.cps_edit))

        # Modo
        self.mode_seg = Segmented([("toggle", "Toggle"), ("hold", "Hold")], self.c.p["mode"])
        self.mode_seg.changed.connect(self.c.on_mode_change)
        cl.addWidget(make_row("Modo de activacion", self.mode_seg))

        # Tecla
        self.key_lbl = QLabel(key_display(self.c.p["key"]))
        self.key_lbl.setObjectName("keyval")
        cl.addWidget(make_row("Tecla de activacion", self.key_lbl))
        self.capture_btn = QPushButton("Cambiar tecla / boton")
        self.capture_btn.setObjectName("primary")
        self.capture_btn.setCursor(Qt.PointingHandCursor)
        self.capture_btn.clicked.connect(self.c.start_capture)
        cl.addWidget(self.capture_btn)

        # Accion a repetir (que se spamea)
        self.action_lbl = QLabel(key_display(self.c.p.get("action", {"type": "mouse", "value": "left"})))
        self.action_lbl.setObjectName("keyval")
        cl.addWidget(make_row("Accion a repetir", self.action_lbl))
        self.action_btn = QPushButton("Cambiar accion")
        self.action_btn.setObjectName("ghost")
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.clicked.connect(self.c.start_capture_action)
        cl.addWidget(self.action_btn)

        # --- Avanzado (contenedor colapsable) ---
        self.adv = QWidget()
        av = QVBoxLayout(self.adv)
        av.setContentsMargins(0, 4, 0, 0)
        av.setSpacing(10)
        av.addWidget(self._divider())
        av.addWidget(self._label_section("AVANZADO"))

        # Perfiles
        self.profile_box = QComboBox()
        self.profile_box.setObjectName("combo")
        self.profile_box.addItems(list(self.c.cfg["profiles"].keys()))
        self.profile_box.setCurrentText(self.c.cfg["last_profile"])
        self.profile_box.currentTextChanged.connect(self.c.on_profile_switch)
        av.addWidget(make_row("Perfil", self.profile_box))
        prow = QHBoxLayout()
        newb = QPushButton("+ Nuevo")
        newb.setObjectName("ghost")
        newb.setCursor(Qt.PointingHandCursor)
        newb.clicked.connect(self.c.new_profile)
        delb = QPushButton("Eliminar")
        delb.setObjectName("ghostdanger")
        delb.setCursor(Qt.PointingHandCursor)
        delb.clicked.connect(self.c.delete_profile)
        prow.addWidget(newb)
        prow.addWidget(delb)
        pr_w = QWidget()
        pr_w.setLayout(prow)
        av.addWidget(pr_w)

        # Jitter
        self.jitter_box = QComboBox()
        self.jitter_box.setObjectName("combo")
        self.jitter_box.addItems(["0", "5", "10", "15", "20", "30"])
        self.jitter_box.setCurrentText(str(self.c.p["jitter"]))
        self.jitter_box.currentTextChanged.connect(self.c.on_jitter_change)
        av.addWidget(make_row("Jitter (variacion %)", self.jitter_box))

        # CPS aleatorio
        self.random_switch = Switch(self.c.p["random_cps"])
        self.random_switch.toggled.connect(self.c.on_random_toggle)
        av.addWidget(make_row("CPS aleatorio", self.random_switch))

        # Rango
        self.range_switch = Switch(self.c.p["range_enabled"])
        self.range_switch.toggled.connect(self.c.on_range_toggle)
        av.addWidget(make_row("Usar rango de CPS", self.range_switch))

        self.range_box = QWidget()
        rb = QVBoxLayout(self.range_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(4)
        self.min_lbl = QLabel(f"Min: {self.c.p['cps_min']}")
        self.min_lbl.setObjectName("slidelbl")
        self.min_slider = QSlider(Qt.Horizontal)
        self.min_slider.setRange(1, 100)
        self.min_slider.setValue(self.c.p["cps_min"])
        self.min_slider.valueChanged.connect(self.c.on_min_change)
        self.max_lbl = QLabel(f"Max: {self.c.p['cps_max']}")
        self.max_lbl.setObjectName("slidelbl")
        self.max_slider = QSlider(Qt.Horizontal)
        self.max_slider.setRange(1, 100)
        self.max_slider.setValue(self.c.p["cps_max"])
        self.max_slider.valueChanged.connect(self.c.on_max_change)
        rb.addWidget(self.min_lbl)
        rb.addWidget(self.min_slider)
        rb.addWidget(self.max_lbl)
        rb.addWidget(self.max_slider)
        av.addWidget(self.range_box)

        cl.addWidget(self.adv)

        # --- General ---
        cl.addWidget(self._divider())
        cl.addWidget(self._label_section("GENERAL"))
        self.overlay_switch = Switch(self.c.cfg["overlay"])
        self.overlay_switch.toggled.connect(self.c.on_overlay_toggle)
        cl.addWidget(make_row("Mostrar overlay", self.overlay_switch))
        self.lock_btn = QPushButton("Mover overlay")
        self.lock_btn.setObjectName("ghost")
        self.lock_btn.setCursor(Qt.PointingHandCursor)
        self.lock_btn.clicked.connect(self.c.toggle_lock)
        cl.addWidget(self.lock_btn)

        self.adv_switch = Switch(self.c.cfg["advanced"])
        self.adv_switch.toggled.connect(self.c.on_advanced_toggle)
        cl.addWidget(make_row("Modo avanzado", self.adv_switch))

        b.addStretch(1)

    # ------------------------------------------------------------------
    def _label_section(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("section")
        return lbl

    def _divider(self):
        d = QFrame()
        d.setObjectName("divider")
        d.setFixedHeight(1)
        return d

    def set_advanced_visible(self, visible):
        self.adv.setVisible(visible)
        self.range_box.setVisible(visible and self.c.p["range_enabled"])
        self._refit()

    def set_range_visible(self, visible):
        self.range_box.setVisible(visible)
        self._refit()

    def _refit(self):
        """Reajusta la ALTURA de la ventana Y del container a su contenido real.
        La ventana es frameless y de ancho fijo; solo debe cambiar el alto.
        Hay que encoger tambien el container (la tarjeta con sombra): si solo
        se ajusta la ventana externa, el container conserva su alto anterior y
        queda un espacio de fondo abajo al contraer el modo avanzado.
        Se aplica tras dos ciclos de evento para que Qt recalcule la
        visibilidad de los widgets."""
        def _apply():
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.container.setMinimumHeight(0)
            self.container.setMaximumHeight(16777215)
            self.container.adjustSize()
            ch = self.container.layout().sizeHint().height()
            self.container.setFixedHeight(ch)
            h = self.layout().sizeHint().height()
            self.setFixedHeight(h)
        QTimer.singleShot(0, lambda: QTimer.singleShot(0, _apply))

    def refresh_profile_widgets(self):
        p = self.c.p
        self.cps_edit.setText(str(p["cps"]))
        self.mode_seg.setValue(p["mode"])
        self.key_lbl.setText(key_display(p["key"]))
        self.action_lbl.setText(key_display(p.get("action", {"type": "mouse", "value": "left"})))
        self.jitter_box.setCurrentText(str(p["jitter"]))
        self.random_switch.setChecked(p["random_cps"])
        self.range_switch.setChecked(p["range_enabled"])
        self.min_slider.setValue(p["cps_min"])
        self.max_slider.setValue(p["cps_max"])
        self.min_lbl.setText(f"Min: {p['cps_min']}")
        self.max_lbl.setText(f"Max: {p['cps_max']}")

    def set_state(self, on):
        self.state_dot.setObjectName("statedot_on" if on else "statedot_off")
        self.state_txt.setObjectName("statetxt_on" if on else "statetxt_off")
        self.state_txt.setText("ACTIVO" if on else "DETENIDO")
        self.state_dot.style().unpolish(self.state_dot)
        self.state_dot.style().polish(self.state_dot)
        self.state_txt.style().unpolish(self.state_txt)
        self.state_txt.style().polish(self.state_txt)

    def set_hint(self, text):
        self.hint_txt.setText(text)

    def set_capturing(self, capturing, target="key"):
        if target == "action":
            lbl = self.action_lbl
            current = key_display(self.c.p.get("action", {"type": "mouse", "value": "left"}))
        else:
            lbl = self.key_lbl
            current = key_display(self.c.p["key"])
        if capturing:
            lbl.setText("presiona... (Esc)")
            lbl.setStyleSheet(f"color: {C_WARN};")
        else:
            lbl.setText(current)
            lbl.setStyleSheet(f"color: {C_ACCENT};")

    # arrastre por la barra de titulo
    def mousePressEvent(self, e):
        # Al hacer clic en cualquier parte de la ventana que no sea el campo CPS,
        # quitamos el foco del campo para que deje de "escribir" (evita que la
        # tecla de activacion o cualquier tecla siga entrando en el input).
        self._defocus_cps()
        if e.button() == Qt.LeftButton and self._titlebar.geometry().contains(
                self.container.mapFromParent(e.position().toPoint())):
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _defocus_cps(self):
        try:
            if self.cps_edit.hasFocus():
                self.cps_edit.clearFocus()
                self.setFocus()
        except Exception:
            pass

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.c.save_window_pos()

    def moveEvent(self, e):
        # Guardar posicion cuando el usuario mueve la ventana.
        if getattr(self, "_ready", False):
            self.c.save_window_pos()
        super().moveEvent(e)

    # ------------------------------------------------------------------
    def _qss(self):
        return f"""
        #container {{
            background: {C_BG};
            border-radius: {RADIUS}px;
            border: 1px solid {C_BORDER};
        }}
        #titlebar {{
            background: {C_TITLEBAR};
            border-top-left-radius: {RADIUS}px;
            border-top-right-radius: {RADIUS}px;
            border-bottom: 1px solid {C_BORDER};
        }}
        #logo {{ color: {C_ACCENT}; font: 15px 'Segoe UI'; }}
        #title {{ color: {C_TXT}; font: 600 11px 'Segoe UI'; }}
        #winbtn, #winclose {{
            background: transparent; color: {C_MUTED};
            border: none; font: 13px 'Segoe UI'; padding: 6px 12px; border-radius: 8px;
        }}
        #winbtn:hover {{ background: #232838; color: {C_TXT}; }}
        #winclose:hover {{ background: {C_OFF}; color: white; }}
        #statecard {{
            background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 14px;
        }}
        #statedot_on {{ color: {C_ON}; font: 12px 'Segoe UI'; }}
        #statedot_off {{ color: {C_OFF}; font: 12px 'Segoe UI'; }}
        #statetxt_on {{ color: {C_ON}; font: 800 13px 'Segoe UI'; }}
        #statetxt_off {{ color: {C_OFF}; font: 800 13px 'Segoe UI'; }}
        #hint {{ color: {C_SUB}; font: 9px 'Segoe UI'; }}
        #card {{
            background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 16px;
        }}
        #section {{ color: {C_SUB}; font: bold 8px 'Segoe UI'; letter-spacing: 1px; }}
        #rowlabel {{ color: {C_TXT}; font: 10px 'Segoe UI'; }}
        #keyval {{ color: {C_ACCENT}; font: 600 12px 'Segoe UI'; }}
        #slidelbl {{ color: {C_MUTED}; font: 9px 'Segoe UI'; }}
        #divider {{ background: {C_BORDER}; border: none; }}
        #field {{
            background: {C_FIELD}; color: {C_TXT}; border: 1px solid {C_BORDER};
            border-radius: 8px; padding: 6px; font: 600 12px 'Segoe UI';
        }}
        #field:focus {{ border: 1px solid {C_ACCENT}; }}
        #primary {{
            background: {C_ACCENT}; color: white; border: none; border-radius: 10px;
            padding: 10px; font: 600 10px 'Segoe UI';
        }}
        #primary:hover {{ background: {C_ACCENT_H}; }}
        #primary:pressed {{ background: #5a76e6; }}
        #ghost {{
            background: #1c2130; color: {C_TXT}; border: 1px solid {C_BORDER};
            border-radius: 9px; padding: 8px; font: 9px 'Segoe UI';
        }}
        #ghost:hover {{ background: #232a3c; }}
        #ghostdanger {{
            background: #1c2130; color: {C_OFF}; border: 1px solid {C_BORDER};
            border-radius: 9px; padding: 8px; font: 9px 'Segoe UI';
        }}
        #ghostdanger:hover {{ background: #2a1c22; }}
        #segmented {{ background: {C_FIELD}; border-radius: 10px; }}
        #segbtn {{
            background: transparent; color: {C_MUTED}; border: none;
            border-radius: 8px; padding: 6px 14px; font: 600 10px 'Segoe UI';
        }}
        #segbtn:checked {{ background: {C_ACCENT}; color: white; }}
        #combo {{
            background: {C_FIELD}; color: {C_TXT}; border: 1px solid {C_BORDER};
            border-radius: 8px; padding: 5px 10px; font: 10px 'Segoe UI'; min-width: 120px;
        }}
        #combo::drop-down {{ border: none; width: 20px; }}
        #combo QAbstractItemView {{
            background: {C_CARD}; color: {C_TXT}; border: 1px solid {C_BORDER};
            selection-background-color: {C_ACCENT}; outline: none;
        }}
        QSlider::groove:horizontal {{
            height: 5px; background: {C_FIELD}; border-radius: 3px;
        }}
        QSlider::sub-page:horizontal {{ background: {C_ACCENT}; border-radius: 3px; }}
        QSlider::handle:horizontal {{
            background: white; width: 15px; height: 15px; margin: -6px 0; border-radius: 8px;
        }}
        """


# ==========================================================================
#  Controlador (logica + puente entre listeners e interfaz)
# ==========================================================================
class AutoClicker:
    def __init__(self):
        self.cfg = load_config()
        self.p = self.cfg["profiles"][self.cfg["last_profile"]]
        self.active = False
        self.capturing = False
        self.overlay_locked = True
        self._lock = threading.Lock()

        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.bridge = Bridge()
        self.bridge.key_captured.connect(self._set_key)
        self.bridge.capture_cancelled.connect(self._cancel_capture)
        self.bridge.activate.connect(self.toggle_clicking)
        self.bridge.hold_start.connect(self.start_clicking)
        self.bridge.deactivate.connect(self.stop_clicking)
        self.bridge.real_cps.connect(self._on_real_cps)

        self.win = MainWindow(self)
        self.overlay = Overlay(self.app)
        self.overlay.set_key(self.p["key"])
        x, y = self._clamp_overlay(self.cfg["ovx"], self.cfg["ovy"])
        self.overlay.move(x, y)

        self.win.set_advanced_visible(self.cfg["advanced"])
        self._update_hint()
        if self.cfg["overlay"]:
            self.overlay.show()

        self._restore_window_pos()
        self.start_listeners()

    # ---------------------------- helpers ------------------------------
    def _clamp_overlay(self, x, y):
        scr = QGuiApplication.primaryScreen().geometry()
        return max(0, min(x, scr.width() - 150)), max(0, min(y, scr.height() - 80))

    def _visible_area(self):
        """Rectangulo que une todas las pantallas conectadas ahora mismo.
        Sirve para validar si una posicion guardada sigue siendo visible
        (por si se desconecto un monitor o cambio la resolucion)."""
        area = None
        for scr in QGuiApplication.screens():
            g = scr.geometry()
            area = g if area is None else area.united(g)
        return area or QGuiApplication.primaryScreen().geometry()

    def _restore_window_pos(self):
        """Restaura la posicion guardada si sigue siendo visible; si no,
        centra en la pantalla principal. Luego trae la ventana al frente.
        La ventana SIEMPRE se abre visible y al frente (nunca minimizada),
        aunque se haya cerrado minimizada la vez anterior."""
        wx, wy = self.cfg.get("winx"), self.cfg.get("winy")
        self.win.setWindowState(Qt.WindowNoState)  # forzar NO minimizado
        self.win.show()
        w = self.win.frameGeometry().width()
        h = self.win.frameGeometry().height()
        area = self._visible_area()

        use_saved = (isinstance(wx, int) and isinstance(wy, int) and
                     area.contains(QPoint(wx + 40, wy + 20)))
        if use_saved:
            self.win.move(wx, wy)
        else:
            prim = QGuiApplication.primaryScreen().availableGeometry()
            self.win.move(prim.x() + (prim.width() - w) // 2,
                          prim.y() + (prim.height() - h) // 3)
        # Traer al frente de forma robusta (evita que quede minimizada o detras).
        self.win.setWindowState(Qt.WindowActive)
        self.win.show()
        self.win.raise_()
        self.win.activateWindow()
        self.win._ready = True

    def save_window_pos(self):
        try:
            self.cfg["winx"] = self.win.x()
            self.cfg["winy"] = self.win.y()
            save_config(self.cfg)
        except Exception:
            pass

    def _update_hint(self):
        m = "Manten" if self.p["mode"] == "hold" else "Pulsa"
        self.win.set_hint(f"{m}  {key_name(self.p['key'])}")

    def _target_cps(self):
        if self.cfg["advanced"] and self.p["range_enabled"]:
            return f"{self.p['cps_min']}-{self.p['cps_max']}"
        return self.p["cps"]

    # ---------------------------- eventos UI ---------------------------
    def on_cps_commit(self):
        raw = "".join(ch for ch in self.win.cps_edit.text() if ch.isdigit())
        val = max(1, min(1000, int(raw))) if raw else self.p["cps"]
        self.win.cps_edit.setText(str(val))
        self.p["cps"] = val
        self._save_profile()

    def on_mode_change(self, mode):
        self.p["mode"] = mode
        self._save_profile()
        self._update_hint()

    def on_jitter_change(self, val):
        self.p["jitter"] = int(val)
        self._save_profile()

    def on_random_toggle(self, val):
        self.p["random_cps"] = val
        self._save_profile()

    def on_range_toggle(self, val):
        self.p["range_enabled"] = val
        self.win.set_range_visible(val and self.cfg["advanced"])
        self._save_profile()

    def on_min_change(self, val):
        self.p["cps_min"] = int(val)
        self.win.min_lbl.setText(f"Min: {int(val)}")
        self._save_profile()

    def on_max_change(self, val):
        self.p["cps_max"] = int(val)
        self.win.max_lbl.setText(f"Max: {int(val)}")
        self._save_profile()

    def on_overlay_toggle(self, val):
        self.cfg["overlay"] = val
        self.overlay.show() if val else self.overlay.hide()
        save_config(self.cfg)

    def on_advanced_toggle(self, val):
        self.cfg["advanced"] = val
        self.win.set_advanced_visible(val)
        save_config(self.cfg)

    def toggle_lock(self):
        self.overlay_locked = not self.overlay_locked
        if not self.overlay_locked:
            self.win.lock_btn.setText("Fijar overlay aqui")
            self.overlay.set_movable(True)
        else:
            self.win.lock_btn.setText("Mover overlay")
            self.overlay.set_movable(False)
            self.cfg["ovx"], self.cfg["ovy"] = self.overlay.x(), self.overlay.y()
            save_config(self.cfg)

    # ---------------------------- captura ------------------------------
    def start_capture(self):
        self.capturing = "key"
        self.win.set_capturing(True, "key")

    def start_capture_action(self):
        self.capturing = "action"
        self.win.set_capturing(True, "action")

    def _set_key(self, key_dict):
        target = self.capturing
        self.capturing = False
        if target == "action":
            self.p["action"] = key_dict
            self.win.set_capturing(False, "action")
        else:
            self.p["key"] = key_dict
            self.win.set_capturing(False, "key")
            self.overlay.set_key(key_dict)
            self._update_hint()
        self._save_profile()

    def _cancel_capture(self):
        target = self.capturing
        self.capturing = False
        self.win.set_capturing(False, target if target in ("key", "action") else "key")

    # ---------------------------- perfiles -----------------------------
    def _save_profile(self):
        name = self.win.profile_box.currentText() if hasattr(self.win, "profile_box") \
            else self.cfg["last_profile"]
        self.cfg["profiles"][name] = self.p
        save_config(self.cfg)

    def on_profile_switch(self, name):
        if name not in self.cfg["profiles"]:
            return
        self.cfg["last_profile"] = name
        self.p = self.cfg["profiles"][name]
        self.win.refresh_profile_widgets()
        self.overlay.set_key(self.p["key"])
        self._update_hint()
        self.win.set_range_visible(self.cfg["advanced"] and self.p["range_enabled"])
        save_config(self.cfg)

    def new_profile(self):
        i = 1
        name = f"Perfil {i}"
        while name in self.cfg["profiles"]:
            i += 1
            name = f"Perfil {i}"
        self.cfg["profiles"][name] = dict(DEFAULT_PROFILE)
        self.cfg["last_profile"] = name
        self.p = self.cfg["profiles"][name]
        self.win.profile_box.blockSignals(True)
        self.win.profile_box.addItem(name)
        self.win.profile_box.setCurrentText(name)
        self.win.profile_box.blockSignals(False)
        self.win.refresh_profile_widgets()
        self.overlay.set_key(self.p["key"])
        self._update_hint()
        save_config(self.cfg)

    def delete_profile(self):
        if len(self.cfg["profiles"]) <= 1:
            return
        name = self.win.profile_box.currentText()
        self.cfg["profiles"].pop(name, None)
        new = next(iter(self.cfg["profiles"]))
        self.cfg["last_profile"] = new
        self.p = self.cfg["profiles"][new]
        self.win.profile_box.blockSignals(True)
        self.win.profile_box.clear()
        self.win.profile_box.addItems(list(self.cfg["profiles"].keys()))
        self.win.profile_box.setCurrentText(new)
        self.win.profile_box.blockSignals(False)
        self.win.refresh_profile_widgets()
        self.overlay.set_key(self.p["key"])
        self._update_hint()
        save_config(self.cfg)

    # ---------------------------- listeners ----------------------------
    def start_listeners(self):
        self.kb_listener = KeyListener(on_press=self.on_key_press, on_release=self.on_key_release)
        self.kb_listener.start()
        self.ms_listener = mouse.Listener(on_click=self.on_mouse_click)
        self.ms_listener.start()

    def _key_to_str(self, key):
        try:
            return key.char.lower()
        except AttributeError:
            return str(key).replace("Key.", "")

    def _matches(self, key_str=None, mouse_btn=None):
        k = self.p["key"]
        if k["type"] == "keyboard" and key_str is not None:
            return k["value"] == key_str
        if k["type"] == "mouse" and mouse_btn is not None:
            return k["value"] == mouse_btn
        return False

    def on_key_press(self, key):
        ks = self._key_to_str(key)
        if self.capturing:
            if key == Key.esc:
                self.bridge.capture_cancelled.emit()
            else:
                self.bridge.key_captured.emit({"type": "keyboard", "value": ks})
            return
        if self._matches(key_str=ks):
            if self.p["mode"] == "hold":
                self.bridge.hold_start.emit()
            else:
                self.bridge.activate.emit()

    def on_key_release(self, key):
        if self.capturing:
            return
        ks = self._key_to_str(key)
        if self.p["mode"] == "hold" and self._matches(key_str=ks):
            self.bridge.deactivate.emit()

    def _mouse_name(self, button):
        mapping = {Button.left: "left", Button.right: "right", Button.middle: "middle"}
        name = mapping.get(button)
        if name:
            return name
        s = str(button)
        if "x1" in s:
            return "x1"
        if "x2" in s:
            return "x2"
        return s

    def on_mouse_click(self, x, y, button, pressed):
        name = self._mouse_name(button)
        if self.capturing and pressed:
            self.bridge.key_captured.emit({"type": "mouse", "value": name})
            return
        if self._matches(mouse_btn=name):
            if self.p["mode"] == "hold":
                self.bridge.hold_start.emit() if pressed else self.bridge.deactivate.emit()
            elif pressed:
                self.bridge.activate.emit()

    # ---------------------------- clic loop ----------------------------
    def toggle_clicking(self):
        self.stop_clicking() if self.active else self.start_clicking()

    def start_clicking(self):
        with self._lock:
            if self.active:
                return
            self.active = True
        self.win.set_state(True)
        self.overlay.set_state(True, str(self._target_cps()))
        threading.Thread(target=self._click_loop, daemon=True).start()

    def stop_clicking(self):
        with self._lock:
            self.active = False
        self.win.set_state(False)
        self.overlay.set_state(False)

    def _pick_cps(self):
        if self.cfg["advanced"] and self.p["range_enabled"]:
            lo, hi = sorted((self.p["cps_min"], self.p["cps_max"]))
            return random.randint(max(1, lo), max(1, hi))
        return max(1, int(self.p["cps"]))

    def _click_loop(self):
        advanced = self.cfg["advanced"]
        jitter = (self.p.get("jitter", 0) / 100.0) if advanced else 0.0
        random_cps = advanced and self.p.get("random_cps", False)
        use_range = advanced and self.p.get("range_enabled", False)

        # Accion a repetir (clic de mouse o tecla), precomputada para velocidad.
        do_action = make_action_clicker(self.p.get("action", {"type": "mouse", "value": "left"}))

        perf = time.perf_counter
        sleep = time.sleep

        cur_cps = self._pick_cps()
        base = 1.0 / cur_cps
        dynamic = jitter > 0 or random_cps or use_range

        start = perf()
        clicks = 0
        win_start = start
        win_clicks = 0
        recompute_at = start + 1.0

        while True:
            with self._lock:
                if not self.active:
                    break

            do_action()
            clicks += 1
            win_clicks += 1
            now = perf()

            if (random_cps or use_range) and now >= recompute_at:
                cur_cps = self._pick_cps()
                base = 1.0 / cur_cps
                recompute_at = now + 1.0

            if dynamic:
                factor = 1.0 + random.uniform(-jitter, jitter) if jitter > 0 else 1.0
                next_time = now + base * factor
            else:
                next_time = start + clicks * base

            elapsed = now - win_start
            if elapsed >= 0.5:
                self.bridge.real_cps.emit(win_clicks / elapsed)
                win_start = now
                win_clicks = 0

            remaining = next_time - perf()
            if remaining <= 0:
                continue
            if remaining > 0.003:
                sleep(remaining - 0.002)
            while perf() < next_time:
                pass

    def _on_real_cps(self, real):
        if self.active:
            self.overlay.set_cps_text(f"{round(real)} / {self._target_cps()} CPS")

    # ---------------------------- salir --------------------------------
    def quit(self):
        self.active = False
        try:
            self.kb_listener.stop()
            self.ms_listener.stop()
        except Exception:
            pass
        if winmm:
            try:
                winmm.timeEndPeriod(1)
            except Exception:
                pass
        self.app.quit()

    def run(self):
        # La ventana ya se muestra y se posiciona en _restore_window_pos().
        self.app.exec()


if __name__ == "__main__":
    AutoClicker().run()
