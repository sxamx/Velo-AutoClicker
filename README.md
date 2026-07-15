# Velo AutoClicker

Auto-clicker premium para Windows, con interfaz moderna hecha en **PySide6 (Qt)**.
Genera **un solo `.exe`** portable.

## Cómo obtener el .exe (fácil)

1. Descarga el repositorio como ZIP (botón **Code > Download**) y descomprímelo.
2. Haz **doble clic en `build.bat`**.
   - Si no tienes Python, el `.bat` te avisará con el link para instalarlo
     (marca **"Add Python to PATH"** al instalar). Luego vuelve a ejecutar el `.bat`.
   - La primera compilación tarda 1-3 min (descarga PySide6). Es normal.
3. Cuando termine, tu ejecutable estará en **`dist\VeloAutoClicker.exe`**.
4. Copia ese `.exe` a donde quieras. Funciona con doble clic, sin instalar nada más.

> El `config.json` se guarda junto al `.exe`, así conservas tus ajustes y perfiles.

## Icono opcional

Si quieres un icono propio para el `.exe`, coloca tu archivo en **`icon\app.ico`**
antes de ejecutar `build.bat`. Si no hay icono, se compila sin él (sin problema).

## Funciones

**Modo Simple**
- **CPS configurable** (1-1000 clics por segundo).
- **Modo Toggle**: pulsas la tecla una vez para activar, otra para desactivar.
- **Modo Hold**: clica mientras mantienes la tecla pulsada.
- **Tecla/botón configurable**: pulsa "Cambiar tecla / botón" y presiona la tecla
  o botón del mouse que quieras (incluye botones laterales). Esc cancela.
- **Acción a repetir**: elige qué se spamea (clic izquierdo/derecho/medio/laterales
  o cualquier tecla, ej. la F del juego). Se captura igual que la tecla de activación.
- **Overlay topmost** con icono de la tecla, estado ON/OFF y CPS real / objetivo.
- **Overlay movible** (botón "Mover overlay", con señal visual clara) y ocultable.

**Modo Avanzado** (interruptor que revela más opciones)
- **Perfiles**: crea, elimina y cambia entre configuraciones. El último usado se
  carga al abrir.
- **Jitter**: variación aleatoria del intervalo para un patrón menos robótico.
- **CPS aleatorio** y **rango de CPS** con sliders min/max.

Todo lo relevante se guarda en `config.json` y se restaura al reabrir.

## Actualización automática

El `.exe` que compilas es un **lanzador**: al abrirlo, comprueba el repo y
descarga la última versión del código (`auto_clicker.py`) si hay una más nueva,
mostrando el progreso ("Actualizando vX → vY"). Luego abre el programa.

Esto significa:
- **Compilas el `.exe` una sola vez.** Nunca más.
- Cuando se publica una mejora en el repo, el mismo `.exe` se actualiza **solo**
  la próxima vez que lo abras. No hay que recompilar ni descargar ZIPs.
- Si no hay internet, abre con la última versión guardada (cache) o la embebida.

> El número de versión vive en `version.txt` (repo) y en `__VERSION__`
> dentro de `auto_clicker.py`.

## Sobre la temporización

- Sube la resolución del timer de Windows a ~1 ms (`winmm.timeBeginPeriod`).
- El bucle de clic usa un temporizador de alta precisión (`perf_counter`) con
  clic nativo `SendInput` (down+up en una sola llamada) para una **cadencia estable**
  y CPS real y alto.
- El techo real de clics útiles lo marca el juego, no el clicker:
  pasado cierto CPS, más clics no suman.

## Aviso

El uso de auto-clickers puede infringir los Términos de Servicio de los juegos.
Úselo bajo tu responsabilidad.
