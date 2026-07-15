@echo off
setlocal
title Velo AutoClicker - Compilador

echo ============================================================
echo   Velo AutoClicker - Generador de .exe
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python.
    echo.
    echo Instala Python 3 desde: https://www.python.org/downloads/
    echo IMPORTANTE: marca la casilla "Add Python to PATH" al instalar.
    echo.
    echo Cuando lo instales, vuelve a ejecutar este archivo.
    pause
    exit /b 1
)

echo [OK] Python detectado.
echo.
echo Instalando dependencias (pynput, PySide6, pyinstaller)...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
python -m pip install pyinstaller
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
python -m PyInstaller --onefile --noconsole --name VeloAutoClicker %ICON_ARG% --add-data "auto_clicker.py;." --add-data "version.txt;." --hidden-import=ctypes --hidden-import=pynput.keyboard --hidden-import=pynput.mouse --collect-all pynput --collect-all PySide6 launcher.py
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
