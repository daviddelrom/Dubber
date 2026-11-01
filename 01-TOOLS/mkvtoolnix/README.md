# MKVToolNix y FFmpeg (herramientas locales)

Dubber no usa servicios externos ni credenciales. Analiza y consolida los archivos con ejecutables locales:

| Binario | Uso | Requerido |
|---|---|---|
| `mkvmerge` | Leer metadatos de pistas (`-J`) y crear el MKV consolidado | Sí, en la aplicación |
| `ffprobe` | Leer transferencia de color HDR que no expone `mkvmerge -J` | Sí, en la aplicación |
| `ffmpeg` | Crear archivos multimedia temporales para las pruebas | Solo para la suite de pruebas |

`ffprobe` se instala como parte de FFmpeg. Instalación en Arch: `sudo pacman -S mkvtoolnix-cli ffmpeg`. En Debian/Ubuntu: `sudo apt install mkvtoolnix ffmpeg`.

Ejecuta `./test_connection.sh` para comprobar los ejecutables requeridos de la aplicación. La pantalla Ajustes también muestra si falta `mkvmerge` o `ffprobe`; en ese caso el escaneo se deshabilita.
