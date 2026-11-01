# Dubber

Dubber es una aplicación web local para organizar y consolidar copias de películas y episodios en una sola biblioteca. Analiza una carpeta mixta, busca coincidencias por nombres y metadatos locales y crea un MKV en el que conserva el mejor vídeo, las pistas de audio seleccionadas y los subtítulos disponibles.

La aplicación no consulta TMDb, IMDb ni otros servicios en línea. Los archivos fuente nunca se modifican ni se borran.

## Requisitos

- Python 3.11 o superior
- `mkvmerge`, incluido en [MKVToolNix](https://mkvtoolnix.download/)
- `ffprobe`, incluido en FFmpeg, para leer metadatos de color HDR
- `ffmpeg` para ejecutar la suite de pruebas, que genera archivos multimedia de prueba

En Arch Linux:

```bash
sudo pacman -S mkvtoolnix-cli ffmpeg
```

En Debian/Ubuntu:

```bash
sudo apt install mkvtoolnix ffmpeg
```

## Instalación y arranque

```bash
git clone https://github.com/daviddelrom/dubber.git
cd dubber
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m dubber
```

Abre <http://127.0.0.1:8000>. La aplicación escucha solo en `127.0.0.1`; puedes elegir otro puerto con `--port N`.

## Uso

1. En **Ajustes**, elige una única carpeta raíz que contenga películas y episodios en cualquier idioma. El resultado se guarda dentro de esa carpeta, en `dub/`.
2. Deja **Todos los idiomas detectados** o selecciona los códigos de audio que quieres conservar, por ejemplo `eng, spa`.
3. Pulsa **Escanear y consolidar**. Dubber recorre la carpeta, excluye `dub/`, analiza archivos `.mkv`, `.mp4` y `.avi`, agrupa copias probables y procesa automáticamente los grupos de alta confianza.
4. Los grupos ambiguos aparecen en **Trabajos y revisión**. Puedes confirmar que sus archivos son el mismo elemento o separarlos. La decisión se aplica solo al lote actual; cada escaneo posterior vuelve a evaluar los nombres y los metadatos desde cero.
5. Consulta el progreso, los resultados y los errores en **Trabajos**. Se pueden cancelar los trabajos en curso. Una salida solo se publica después de terminar correctamente la mezcla; cada error se informa y no impide procesar otros grupos.

El planificador selecciona un vídeo según resolución, HDR positivo y eficiencia del códec; conserva como máximo una pista de audio por idioma seleccionado y todas las pistas de subtítulos disponibles. Si el idioma no está etiquetado y es la única pista de audio, se considera español; varias pistas sin etiqueta requieren revisión.

## Datos y límites

- La base nueva predeterminada es `dubber-v2.db`; puedes cambiar la ruta mediante `DUBBER_DB`.
- Dubber rechaza bases de datos heredadas o de esquema desconocido antes de modificarlas. No migra ni altera la base antigua.
- La carpeta `dub/` está reservada para resultados y nunca se analiza como fuente.
- Entre escaneos, no se guardan las decisiones de revisión.
- El emparejado es local y conservador. No hay búsqueda en TMDb/IMDb, corrección de desfase de audio, inicio de sesión ni borrado de fuentes.

## Estructura

```text
dubber/
  core/   metadatos, agrupación local, planificación y ejecución de muxing
  db/     modelos SQLModel y sesión SQLite
  jobs/   escaneo incremental y trabajos por lote
  web/    FastAPI, plantillas Jinja y HTMX
tests/    pytest; varias pruebas generan MKV reales con ffmpeg/mkvmerge
```

## Pruebas

Con `ffmpeg`, `ffprobe` y `mkvmerge` instalados:

```bash
.venv/bin/python -m pytest -q
```
