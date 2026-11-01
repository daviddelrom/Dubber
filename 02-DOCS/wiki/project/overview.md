# Dubber: visión general

Dubber es una aplicación web local (Python + FastAPI) que convierte una carpeta mixta de películas y episodios en una biblioteca consolidada. Agrupa copias mediante nombres y metadatos locales, conserva el vídeo de mayor prioridad y reúne las pistas de audio y subtítulos elegidas en un MKV bajo `dub/`.

- **Uso:** personal, una persona usuaria, ejecución local; escucha solo en `127.0.0.1`.
- **Arranque:** `python -m dubber` (puerto 8000, opción `--port`).
- **Datos:** SQLite/SQLModel en `dubber-v2.db` por defecto; `DUBBER_DB` permite elegir otra ruta. La base heredada no se migra ni se modifica.
- **Herramientas locales:** `mkvmerge` y `ffprobe` son necesarios para la aplicación; `ffmpeg` se usa para generar archivos en pruebas.
- **Red:** el emparejado es local; no consulta TMDb, IMDb ni otros servicios de metadatos.
- **Pruebas:** `.venv/bin/python -m pytest -q`.

## Flujo de la aplicación

Ajustes (un solo directorio y selección de idiomas) → escaneo incremental → agrupación local → consolidación automática de coincidencias seguras y revisión no bloqueante de las ambiguas → resultados en `dub/`.

Se reconocen películas mediante título/año y duración y episodios mediante la serie y numeración normalizada (`SxxEyy` o `NxNN`). Una coincidencia ambigua requiere confirmación. Las decisiones de revisión solo se aplican al lote actual y **cada escaneo vuelve a evaluar** los nombres y metadatos; no se guardan para uso futuro.

Los archivos de `dub/` se excluyen del escaneo. Las fuentes permanecen intactas. Los trabajos exponen progreso, resultados, errores y cancelación.

## Límites de producto

La app no busca datos en TMDb/IMDb, no corrige desfases de audio, no borra archivos fuente y no requiere login, Docker ni servicios externos.
