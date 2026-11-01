#!/usr/bin/env bash
set -u
status=0
for bin in mkvmerge ffprobe; do
  if command -v "$bin" >/dev/null 2>&1; then
    echo "OK   $bin: $("$bin" --version 2>&1 | head -n1)"
  else
    echo "FALTA $bin"
    status=1
  fi
done
if command -v ffmpeg >/dev/null 2>&1; then
  echo "OK   ffmpeg: $(ffmpeg -version 2>&1 | head -n1) (solo necesario para pruebas)"
else
  echo "INFO ffmpeg no encontrado (solo necesario para pruebas)"
fi
exit $status
