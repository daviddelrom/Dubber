# Dubber: visión general

Dubber es una app web local (Python + FastAPI) que combina dos copias de la misma película o serie: la original en inglés (buena calidad) y la doblada al español (normalmente de menor calidad). El resultado es un MKV con el vídeo y el audio originales más las pistas de audio en español.

- **Uso:** personal, un solo usuario, en local. Escucha solo en `127.0.0.1`.
- **Arranque:** `python -m dubber` (puerto 8000, opción `--port`). Entorno en `.venv/`.
- **Tests:** `.venv/bin/python -m pytest` (15 tests; usan `ffmpeg` y `mkvmerge` reales).
- **Origen:** sustituye al script de menú `dubber.py`, retirado en `feat/web-app` (sigue en el historial).
- **Fuera de la v1:** ajuste de offset de audio, login, Docker, búsqueda en TMDb/IMDb.

## Flujo de la app

Ajustes (carpetas esp/eng/dub) → Escanear (job) → Coincidencias (aprobar o descartar las dudosas) → Mezclar (job) → Cola (progreso, log, cancelar).

Se empareja por ID de IMDb (`tt1234567`) y, en series, por `SxxEyy`. Coincidencia *ideal* si la duración difiere 1 s o menos; *dudosa* si difiere o es desconocida (requiere aprobación manual).
