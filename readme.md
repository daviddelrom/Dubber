# Dubber

App web local (Python + FastAPI) para combinar vídeos en diferentes idiomas con `mkvmerge`. Tienes una película o serie en versión original y buena calidad, y otra copia doblada al español (normalmente de menor calidad). Dubber las empareja por ID de IMDb y genera un MKV con el **vídeo y audio original** más las **pistas de audio en español**.

## Requisitos

- Python 3.11 o superior
- `mkvmerge` ([MKVToolNix](https://mkvtoolnix.download/))

```bash
sudo pacman -S mkvtoolnix-cli  # Arch Linux
sudo apt install mkvtoolnix    # Debian/Ubuntu
```

## Instalación y arranque

```bash
git clone https://github.com/daviddelrom/dubber.git
cd dubber
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m dubber            # http://127.0.0.1:8000
```

La app solo escucha en `127.0.0.1`. Opción: `--port N`. La base de datos SQLite se guarda en `./dubber.db` (o en la ruta de la variable `DUBBER_DB`).

## Uso

1. **Ajustes**: indica las carpetas de español, inglés y salida.
2. **Biblioteca** → *Escanear carpetas*: analiza recursivamente `.mkv`, `.mp4` y `.avi`. Los reescaneos son incrementales (solo se reanalizan archivos cambiados) y se limpian los archivos borrados.
3. **Coincidencias**: empareja por ID de IMDb (`tt1234567`) y, en series, por temporada y episodio (`S01E02`). Si la duración difiere en 1 s o menos, la coincidencia es *ideal*; si difiere o es desconocida, queda *dudosa* y hay que aprobarla a mano. Tus decisiones se conservan al reescanear.
4. **Mezclar seleccionadas**: crea un trabajo en segundo plano. El resultado va a la carpeta de salida con la misma ruta relativa y nombre que el archivo en inglés (siempre como `.mkv`). Si el archivo ya existe se omite, salvo que marques *Sobrescribir*.
5. **Cola**: progreso en vivo, registro y cancelación de cada trabajo. Los escaneos y las mezclas se ejecutan de uno en uno.

Los archivos deben llevar el ID de IMDb en el nombre, por ejemplo `tt1234567_pelicula.mkv`.

## Estructura

```
dubber/
  core/   lógica pura: nombres, emparejado, wrapper de mkvmerge
  db/     modelos SQLModel y sesión SQLite (WAL)
  jobs/   cola en segundo plano y tareas de escaneo/mezcla
  web/    FastAPI, plantillas Jinja y HTMX
tests/    pytest (usan ffmpeg y mkvmerge para generar MKV reales)
```

## Tests

```bash
pytest
```

## Migración desde el script antiguo

El script de menú (`dubber.py`) y su base `mkv.db` ya no se usan. Define las carpetas en Ajustes y escanea de nuevo.
