# Decisiones del proyecto

Las decisiones del harness están en `../harness/decisions.md` (las gestiona rsc y puede sobrescribirlas). Estas son las del producto.

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Mantener SQLite | PostgreSQL | App local de un solo usuario: sin servidor, un archivo, WAL para concurrencia. El problema era el esquema, no el motor. |
| Esquema normalizado con claves | Tablas planas con rutas absolutas | Identidad por `(raíz, ruta relativa)`; permite mover carpetas, reescaneo incremental y limpieza. |
| FastAPI + Jinja + HTMX | SPA en React/Vue; Flask | Sin paso de build de JS; un solo lenguaje. |
| Cola propia con un hilo | Celery/Redis | Uso local. Serializa escaneos y mezclas, y evita dos `mkvmerge` a la vez. |
| Progreso por sondeo HTMX (1 s) | SSE | Más simple; el plan original pedía SSE, queda como mejora posible. |
| Duración del contenedor (`mkvmerge -J`) | Duración de la pista 0 | Más fiable; la duración desconocida nunca es «ideal». |
| Coincidencias dudosas con aprobación manual | Mezclar siempre o preguntar por consola | Evita mezclar audio desincronizado sin que lo veas. |
| Escuchar solo en `127.0.0.1` + control de `Origin` | Abrir a la red | La app ejecuta procesos y escribe archivos en el equipo. |
| `create_all` | Alembic desde el inicio | Pendiente. Desviación respecto al plan aprobado. |
| Sin importar el `mkv.db` antiguo | Migración | Basta con definir carpetas y reescanear. |
