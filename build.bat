@echo off
setlocal
title Velo AutoClicker - Compilador

echo ============================================================
echo   Velo AutoClicker - Generador de .exe
echo ============================================================
echo.

REM --- Buscar Python de sistema (no el venv de Hermes u otros) ---
REM Intentamos "py" (Python Launcher, viene con la instalacion oficial)
REM y fallamos a "python" solo si py no existe.
set "PYCMD="

py --version >nul 2>&1
if not errorlevel 1 (
    set "PYCMD=py"
    goto :found
)

REM Fallback: python, pero verificar que tenga pip (no sea un venv sin pip)
python --version >nul 2>&1
if not errorlevel 1 (
    python -m pip --version >nul 2>&1
    if not errorlevel 1 (
        set "PYCMD=python"
        goto :found
    )
)

echo [ERROR] No se encontro Python con pip.
echo.
echo Tienes Python instalado pero "python" apunta a un entorno virtual
echo sin pip (posiblemente el de Hermes). Necesitas el Python de sistema.
echo.
echo Opciones:
echo   1. Instala Python desde: https://www.python.org/downloads/
echo      IMPORTANTE: marca "Add Python to PATH" al instalar.
echo   2. Si ya lo tienes, abre el menu Inicio y busca "Python" -
echo      usa la consola que viene con el Python de sistema, no la de Hermes.
echo.
pause
exit /b 1

:found
echo [OK] Python detectado: %PYCMD%
%PYCMD% --version
echo.

echo Instalando dependencias (pynput, PySide6, pyinstaller)...
%PYCMD% -m pip install --upgrade pip >nul 2>&1
%PYCMD% -m pip install -r requirements.txt
%PYCMD% -m pip install pyinstaller
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)

echo.
REM --- Detectar icono opcional en icon\app.ico ---
set ICON_ARG=
if exist "icon\app.ico" (
    echo [OK] Icono encontrado: icon\app.ico
    set ICON_ARG=--icon=icon\app.ico
) else (
    echo [i] Sin icono ^(icon\app.ico no existe^). Se compilara sin icono.
)

echo.
echo Compilando el ejecutable (esto puede tardar 1-3 min la primera vez)...
REM Se compila el LANZADOR (launcher.py). Incluye auto_clicker.py como respaldo
REM embebido, pero al abrirse descarga la version mas nueva desde el repo.
REM --collect-all / --hidden-import aseguran que las dependencias del clicker
REM (que se carga como texto) queden dentro del .exe.
%PYCMD% -m PyInstaller --onefile --noconsole --name VeloAutoClicker %ICON_ARG% --add-data "auto_clicker.py;." --add-data "version.txt;." --hidden-import=ctypes --hidden-import=pynput.keyboard --hidden-import=pynput.mouse --collect-all pynput --collect-all PySide6 launcher.py
if errorlevel 1 (
    echo [ERROR] Fallo la compilacion.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   LISTO! Tu ejecutable esta en:  dist\VeloAutoClicker.exe
echo ============================================================
echo.
echo Puedes copiar ese .exe a donde quieras y usarlo con doble clic.
echo.
pause
