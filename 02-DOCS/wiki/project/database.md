# Base de datos (SQLite)

Archivo `dubber.db` en el directorio de trabajo, o la ruta de `DUBBER_DB`. Se crea con `create_all`; **no hay migraciones todavía**: si el esquema cambia hay que añadir Alembic.

| Tabla | Contenido | Clave |
|---|---|---|
| `libraryroot` | carpeta por tipo (`esp`, `eng`, `dub`) | `kind` único |
| `mediafile` | archivo, tamaño, mtime, IMDb, temporada/episodio, duración, error | único `(root_id, relpath)` |
| `track` | pistas de un archivo: tipo, idioma, códec, nombre | FK `file_id` |
| `match` | pareja esp/eng, diferencia de duración, estado, salida, `merged_at` | único `(esp_file_id, eng_file_id)` |
| `job` | tipo (`scan`/`merge`), estado, progreso, parámetros, log, cancelación | — |

Estados de `match`: `ideal`, `doubtful`, `approved`, `discarded`. Al reescanear solo se recalculan `ideal`/`doubtful`; las decisiones manuales se conservan.
Estados de `job`: `queued`, `running`, `done`, `failed`, `cancelled`.

Un archivo solo se reanaliza si cambian `size` o `mtime`, o si falló antes. Un archivo borrado elimina sus pistas y coincidencias.
