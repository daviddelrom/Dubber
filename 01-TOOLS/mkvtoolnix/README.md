# MKVToolNix y ffmpeg (herramientas locales)

Dubber no usa servicios externos ni credenciales. Depende de dos binarios locales.

| Binario | Uso | Obligatorio |
|---|---|---|
| `mkvmerge` | analizar (`-J`) y mezclar pistas | sí, en la app |
| `ffmpeg` | generar MKV de prueba en los tests | solo para tests (se omiten sin él) |

Instalación: `sudo pacman -S mkvtoolnix-cli ffmpeg` (Arch) o `sudo apt install mkvtoolnix ffmpeg` (Debian/Ubuntu).

Comprobación: `./test_connection.sh`. La pantalla Ajustes de la app también avisa si falta `mkvmerge`.
