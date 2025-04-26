# MKV Analyzer

Este es un programa interactivo en Python diseñado para combinar vídeos en diferentes idiomas (español e inglés) usando `mkvmerge`. El programa analiza archivos de vídeo, detecta coincidencias basadas en el ID de IMDb y combina las pistas deseadas en una carpeta final.

## Requisitos

- Python 3.x
- `mkvmerge` (parte de [MKVToolNix](https://mkvtoolnix.download/))
- `sqlite3` (incluido con Python)

## Instalación

1. Asegúrate de tener `mkvmerge` disponible en tu sistema:

```bash
sudo pacman -S mkvtoolnix-cli  # En Arch Linux
sudo apt install mkvtoolnix    # En Debian/Ubuntu
```

2. Clona este repositorio y entra en la carpeta:

```bash
git clone https://github.com/tuusuario/mkv-analyzer.git
cd mkv-analyzer
```

3. Ejecuta el script principal:

```bash
python3 main.py
```

## Estructura del proyecto

- `esp/` → Carpeta con los vídeos en español
- `eng/` → Carpeta con los vídeos en inglés
- `dub/` → Carpeta donde se generarán los vídeos combinados

## Uso

El programa muestra un menú interactivo con las siguientes opciones:

```
1 - Definir carpetas
2 - Analizar carpetas
3 - Buscar coincidencias
4 - Generar combinaciones (mkvmerge)
5 - Vaciar base de datos
0 - Salir
```

### 1 - Definir carpetas

Permite definir manualmente las rutas de las carpetas `esp`, `eng` y `dub`. Si no se definen, se usan por defecto `./esp`, `./eng` y `./dub`.

### 2 - Analizar carpetas

Escanea recursivamente las carpetas `esp` y `eng` buscando archivos `.mkv`, `.mp4` o `.avi`, y extrae información de las pistas con `mkvmerge`.

### 3 - Buscar coincidencias

Busca coincidencias entre archivos en `esp` y `eng` basadas en el ID IMDb (`tt...`) contenido en el nombre del archivo. Verifica que la duración del video coincida (tolerancia de 1 segundo). Guarda las coincidencias en la base de datos.

### 4 - Generar combinaciones

Combina las coincidencias ideales usando `mkvmerge`. El archivo generado irá a la carpeta `dub`, con el mismo nombre del archivo de inglés. Solo se combinan las pistas de audio en español (`es`).

### 5 - Vaciar base de datos

Elimina todas las pistas y coincidencias guardadas. Las carpetas definidas se conservan.

## Notas

- Los archivos deben contener un ID IMDb en su nombre, por ejemplo: `tt1234567_pelicula.mkv`.
- Soporta subdirectorios anidados.
- El programa guarda toda la información en una base de datos SQLite (`mkv.db`).

## Licencia

MIT

