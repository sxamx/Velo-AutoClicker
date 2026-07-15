"""
Velo AutoClicker - Lanzador con auto-actualizacion
--------------------------------------------------
Este es el UNICO archivo que se compila a .exe (una sola vez).

Que hace al abrirse:
  1. Muestra una pantalla de carga (para que no parezca congelado).
  2. Consulta el repo publico si hay una version mas nueva del codigo.
  3. Si la hay: descarga auto_clicker.py (texto) y lo guarda en cache local.
     Muestra feedback: "Actualizando vX -> vY".
  4. Ejecuta el codigo del clicker (el descargado, o la cache, o el embebido).

Asi, cuando se mejora auto_clicker.py en el repo, el .exe ya compilado se
actualiza SOLO al abrirse. Nadie tiene que recompilar ni subir binarios.

Estrategia de resiliencia (siempre abre, aunque falle la red):
  - Con internet y version nueva  -> usa el codigo descargado (y lo cachea).
  - Con internet y misma version   -> usa la cache si existe, si no el embebido.
  - Sin internet                   -> usa la cache si existe, si no el embebido.
"""

import os
import sys
import time
import traceback
import urllib.request

# --------------------------------------------------------------------------
# IMPORTANTE (empaquetado): el codigo del clicker se carga dinamicamente como
# texto, asi que PyInstaller NO detecta sus dependencias por si solo. Las
# importamos aqui para forzar que queden incluidas dentro del .exe. Sin esto,
# el clicker descargado falla con "ModuleNotFoundError: No module named ctypes"
# (u otros). No se usan directamente aqui; solo se anclan para el empaquetado.
# --------------------------------------------------------------------------
import ctypes                       # noqa: F401
import ctypes.wintypes              # noqa: F401
import json                         # noqa: F401
import random                       # noqa: F401
import threading                    # noqa: F401
try:
    import pynput                   # noqa: F401
    import pynput.mouse             # noqa: F401
    import pynput.keyboard          # noqa: F401
except Exception:
    pass
try:
    import PySide6.QtCore           # noqa: F401
    import PySide6.QtGui            # noqa: F401
    import PySide6.QtWidgets        # noqa: F401
except Exception:
    pass

# --------------------------------------------------------------------------
# Configuracion del repo (publico). Si cambia el repo, solo se edita aqui.
# --------------------------------------------------------------------------
RAW_BASE = "https://raw.githubusercontent.com/sxamx/velo-autoclicker/main"
VERSION_URL = f"{RAW_BASE}/version.txt"
CODE_URL = f"{RAW_BASE}/auto_clicker.py"
HTTP_TIMEOUT = 4  # chequeo de version: archivo diminuto, respuesta rapida

# Carpeta de datos junto al .exe (o al script en desarrollo).
# Aqui se guardan la cache del codigo y la version, junto al .exe.
APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)
CACHE_CODE = os.path.join(APP_DIR, "auto_clicker_cache.py")
CACHE_VERSION = os.path.join(APP_DIR, "version_cache.txt")


def embedded_path():
    """Ruta al auto_clicker.py incluido en el .exe.
    PyInstaller (--onefile) extrae los datos a sys._MEIPASS, NO a la carpeta
    del .exe. En desarrollo, esta junto al script."""
    base = getattr(sys, "_MEIPASS", APP_DIR)
    return os.path.join(base, "auto_clicker.py")


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def _write(path, text):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except Exception:
        return False


def _http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "VeloAutoClicker"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read().decode("utf-8")


def _version_tuple(v):
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except Exception:
        return (0,)


def embedded_version_file():
    base = getattr(sys, "_MEIPASS", APP_DIR)
    return os.path.join(base, "version.txt")


# --------------------------------------------------------------------------
# Pantalla de carga / feedback (PySide6). Si PySide6 no esta, seguimos igual.
# --------------------------------------------------------------------------
class Splash:
    def __init__(self):
        self.app = None
        self.win = None
        self.label = None
        try:
            from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QColor
            from PySide6.QtWidgets import QGraphicsDropShadowEffect, QFrame

            self.app = QApplication.instance() or QApplication(sys.argv)
            self.win = QWidget()
            self.win.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.win.setAttribute(Qt.WA_TranslucentBackground)
            self.win.setFixedSize(340, 150)

            root = QVBoxLayout(self.win)
            root.setContentsMargins(14, 14, 14, 14)
            card = QFrame()
            card.setObjectName("card")
            sh = QGraphicsDropShadowEffect(blurRadius=40, xOffset=0, yOffset=10)
            sh.setColor(QColor(0, 0, 0, 180))
            card.setGraphicsEffect(sh)
            root.addWidget(card)
            lay = QVBoxLayout(card)
            lay.setContentsMargins(24, 24, 24, 24)

            title = QLabel("\u25C9  Velo AutoClicker")
            title.setObjectName("title")
            title.setAlignment(Qt.AlignCenter)
            self.label = QLabel("Iniciando...")
            self.label.setObjectName("msg")
            self.label.setAlignment(Qt.AlignCenter)
            lay.addStretch(1)
            lay.addWidget(title)
            lay.addSpacing(8)
            lay.addWidget(self.label)
            lay.addStretch(1)

            self.win.setStyleSheet("""
                #card { background: #0d0f16; border: 1px solid #232838;
                        border-radius: 16px; }
                #title { color: #6d8bff; font: 600 13px 'Segoe UI'; }
                #msg { color: #9aa1b4; font: 10px 'Segoe UI'; }
            """)
            # centrar
            from PySide6.QtGui import QGuiApplication
            scr = QGuiApplication.primaryScreen().geometry()
            self.win.move((scr.width() - 340) // 2, (scr.height() - 150) // 3)
            self.win.show()
            self._pump()
        except Exception:
            self.app = None  # sin GUI de splash; el updater sigue en modo silencioso

    def _pump(self):
        if self.app:
            self.app.processEvents()

    def set(self, text):
        if self.label:
            self.label.setText(text)
            self._pump()

    def hold_min(self, start_time, min_seconds):
        """Mantiene el splash visible al menos min_seconds desde start_time,
        procesando eventos para que se vea fluido. Asi el usuario siempre
        alcanza a leer la version / el mensaje de actualizacion."""
        remaining = min_seconds - (time.time() - start_time)
        end = time.time() + max(0.0, remaining)
        while time.time() < end:
            self._pump()
            time.sleep(0.03)

    def close(self):
        if self.win:
            self.win.close()
            self._pump()


# --------------------------------------------------------------------------
# Determina que codigo ejecutar (descargado / cache / embebido)
# --------------------------------------------------------------------------
def resolve_code(splash):
    """Devuelve la ruta a un archivo .py listo para ejecutar.

    Optimizacion de arranque: solo se descarga el codigo completo cuando la
    version remota es MAS NUEVA que la local (o no hay cache). Si ya estamos
    al dia, abre desde la cache al instante (no vuelve a descargar todo).

    El splash se muestra un tiempo minimo para que el usuario alcance a ver
    la version actual y si hubo actualizacion.
    """
    embedded = embedded_path()  # respaldo incluido en el .exe (sys._MEIPASS)
    local_version = _read(CACHE_VERSION) or _read(embedded_version_file()) or "0.0.0"
    t0 = time.time()

    splash.set(f"v{local_version}  \u00b7  buscando actualizaciones...")
    try:
        remote_version = _http_get(VERSION_URL).strip()
    except Exception:
        remote_version = None

    # Sin internet -> lo que tengamos local
    if not remote_version:
        splash.set(f"v{local_version}  \u00b7  sin conexion")
        splash.hold_min(t0, 1.6)
        return CACHE_CODE if os.path.exists(CACHE_CODE) else embedded

    hay_update = _version_tuple(remote_version) > _version_tuple(local_version)

    # Al dia y con cache -> abrir directo (rapido, sin descargar el codigo)
    if not hay_update and os.path.exists(CACHE_CODE):
        splash.set(f"v{local_version}  \u00b7  al dia \u2713")
        splash.hold_min(t0, 1.5)
        return CACHE_CODE

    # Hay update, o no hay cache todavia -> descargar codigo
    if hay_update:
        splash.set(f"Actualizando  v{local_version}  \u2192  v{remote_version}...")
    else:
        splash.set(f"v{remote_version}  \u00b7  preparando...")
    try:
        code = _http_get(CODE_URL)
        if code and "AutoClicker" in code:
            _write(CACHE_CODE, code)
            _write(CACHE_VERSION, remote_version)
            if hay_update:
                splash.set(f"\u2713  Actualizado a v{remote_version}")
                splash.hold_min(t0, 2.2)
            else:
                splash.hold_min(t0, 1.5)
            return CACHE_CODE
    except Exception:
        pass
    # fallo la descarga: usar lo mejor disponible
    splash.set(f"v{local_version}  \u00b7  abriendo...")
    splash.hold_min(t0, 1.4)
    if os.path.exists(CACHE_CODE):
        return CACHE_CODE
    return embedded


def run_code(path):
    """Ejecuta el codigo del clicker con acceso completo a los modulos
    estandar (ctypes, threading, etc.).

    Se usa exec() en un namespace propio en vez de importlib con un spec
    artificial: asi el codigo corre como un modulo __main__ normal y ve
    todos los modulos que PyInstaller empaqueto, evitando el
    'ModuleNotFoundError: No module named ctypes'.
    """
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    ns = {"__name__": "auto_clicker", "__file__": path}
    exec(compile(source, path, "exec"), ns)
    ns["AutoClicker"]().run()


def _show_error(msg):
    """Muestra el error en una ventana (no hay consola con --noconsole)."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "Velo AutoClicker", msg)
    except Exception:
        pass


def main():
    splash = Splash()
    try:
        code_path = resolve_code(splash)
    except Exception:
        code_path = embedded_path()
    splash.close()

    # Orden de intentos: codigo resuelto -> cache -> embebido.
    candidates = []
    for c in (code_path, CACHE_CODE, embedded_path()):
        if c and c not in candidates and os.path.exists(c):
            candidates.append(c)

    last_err = None
    for path in candidates:
        try:
            run_code(path)
            return
        except Exception:
            last_err = traceback.format_exc()
            continue

    _show_error("No se pudo iniciar el programa.\n\n"
                + (last_err or "Sin detalles disponibles."))


if __name__ == "__main__":
    main()
