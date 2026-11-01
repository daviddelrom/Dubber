# Arquitectura

```
dubber/
  core/    lógica pura, sin E/S de usuario ni base de datos
    naming.py    ID IMDb, temporada/episodio, extensiones de vídeo
    matching.py  emparejado y estado ideal/dudosa por duración
    mkv.py       wrapper de mkvmerge: probe, comando de mezcla, ejecución con progreso
  db/
    models.py    SQLModel: LibraryRoot, MediaFile, Track, Match, Job
    session.py   motor SQLite con WAL, foreign_keys y busy_timeout
  jobs/
    runner.py    JobRunner: un solo hilo, así escaneos y mezclas se serializan
    tasks.py     escaneo incremental, reconstrucción de coincidencias, mezcla
  web/
    app.py       FastAPI, rutas y comprobación de origen
    templates/   Jinja; HTMX local en static/ (sin CDN)
tests/           pytest con MKV reales generados por ffmpeg
```

## Reglas que el código cumple

- `core/` no importa de `db/`, `jobs/` ni `web/`.
- Los comandos externos se lanzan siempre con lista de argumentos, nunca con shell.
- Las tareas de fondo abren sesiones propias; no pasan objetos ORM entre sesiones (provocó un bug real: usar solo IDs).
- La mezcla escribe en `<salida>.partial` y hace `os.replace` al terminar; una cancelación o un error borran el parcial.
- Al arrancar, los jobs que quedaron `queued` o `running` se marcan `failed` (la app se cerró).
- Las peticiones POST con cabecera `Origin` de otro host se rechazan con 403.
- La carpeta `dub` puede no existir (se crea); `esp` y `eng` deben existir.
- Las fechas son con zona horaria (UTC); esta versión de SQLModel lo exige.
