# Arquitectura

```text
dubber/
  core/    lógica de dominio: metadatos, normalización, agrupación,
           revisión en memoria y planificación/ejecución de consolidación
  db/      modelos SQLModel, base SQLite v2 y protección del esquema heredado
  jobs/    escaneo incremental de una carpeta y trabajos por lote
  web/     FastAPI, páginas Jinja/HTMX, rutas y validación de origen
tests/     pytest con MKV reales generados por ffmpeg/mkvmerge
```

## Flujo de datos

```text
Ajustes web → escaneo recursivo → mkvmerge -J + ffprobe
            → agrupación local → revisión del lote actual
            → plan de pistas → mkvmerge → <origen>/dub/
```

La aplicación de arranque usa la biblioteca v2. El flujo web legado se conserva solo para compatibilidad con las rutas de construcción que reciben explícitamente un motor o runner antiguo; no es la experiencia normal de `python -m dubber`.

## Límites y garantías

- `core/` no importa `db/`, `jobs/` ni `web/`.
- Los ejecutables externos se invocan con listas de argumentos, nunca mediante shell.
- Las tareas de fondo usan sesiones de base de datos propias; no comparten objetos ORM entre sesiones.
- `mkvmerge` construye un archivo parcial junto al destino. Solo una ejecución correcta publica la salida; el error o la cancelación elimina el parcial y conserva un resultado previo.
- Cada salida se publica por grupo, no por lote. Los errores se registran y el procesamiento continúa con otros grupos.
- `dub/` está reservado para resultados y queda fuera del escaneo de fuentes.
- La base `dubber-v2.db` se separa de la heredada; el preflight rechaza esquemas heredados o desconocidos antes de crear tablas.
- Las decisiones de revisión no se guardan para escaneos posteriores.
- Al reiniciar, los trabajos `queued` o `running` se marcan como fallidos por interrupción.
- Las peticiones POST con un encabezado `Origin` de otro host se rechazan.
- El servidor solo escucha en `127.0.0.1`.
