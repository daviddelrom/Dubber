#!/usr/bin/env bash
set -u
status=0
for bin in mkvmerge ffmpeg; do
  if command -v "$bin" >/dev/null 2>&1; then
    echo "OK   $bin: $("$bin" --version 2>&1 | head -n1)"
  else
    echo "FALTA $bin"
    [ "$bin" = "mkvmerge" ] && status=1
  fi
done
exit $status
