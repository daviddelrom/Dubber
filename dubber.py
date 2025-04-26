import os
import sqlite3
import subprocess
import json
import sys
import re

def crear_bd():
    with sqlite3.connect("mkv.db") as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS carpetas (
                tipo TEXT PRIMARY KEY,
                ruta TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS pistas (
                archivo TEXT,
                ruta TEXT,
                pista INTEGER,
                tipo TEXT,
                duracion REAL,
                idioma TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS coincidencias (
                archivo_esp TEXT,
                ruta_esp TEXT,
                archivo_eng TEXT,
                ruta_eng TEXT,
                coincidenciaideal INTEGER
            )
        """)
        # Valores por defecto
        for tipo, ruta in [("esp", "./esp"), ("eng", "./eng"), ("dub", "./dub")]:
            c.execute("INSERT OR IGNORE INTO carpetas (tipo, ruta) VALUES (?, ?)", (tipo, ruta))
        conn.commit()

def definir_carpetas():
    rutas = {}
    for tipo in ["esp", "eng", "dub"]:
        ruta = input(f"Ruta para carpeta {tipo}: ").strip()
        rutas[tipo] = ruta
    with sqlite3.connect("mkv.db") as conn:
        c = conn.cursor()
        for tipo, ruta in rutas.items():
            c.execute("REPLACE INTO carpetas (tipo, ruta) VALUES (?, ?)", (tipo, ruta))
        conn.commit()

def vaciar_base_de_datos():
    with sqlite3.connect("mkv.db") as conn:
        c = conn.cursor()
        c.execute("DELETE FROM pistas")
        c.execute("DELETE FROM coincidencias")
        conn.commit()
        print("Base de datos vaciada.")

def obtener_ruta(tipo):
    with sqlite3.connect("mkv.db") as conn:
        c = conn.cursor()
        c.execute("SELECT ruta FROM carpetas WHERE tipo = ?", (tipo,))
        resultado = c.fetchone()
        return resultado[0] if resultado else None

def cargar_info_mkv(archivo_mkv):
    try:
        resultado = subprocess.run(
            ["mkvmerge", "-J", archivo_mkv],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return json.loads(resultado.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error al ejecutar mkvmerge: {e.stderr}")
        return None

def analizar_carpeta(tipo):
    ruta = obtener_ruta(tipo)
    if not ruta:
        print(f"No se ha definido la carpeta '{tipo}'")
        return

    for root, _, files in os.walk(ruta):
        for file in files:
            if file.lower().endswith((".mkv", ".mp4", ".avi")):
                archivo_completo = os.path.join(root, file)
                info = cargar_info_mkv(archivo_completo)
                if not info:
                    continue
                for track in info.get("tracks", []):
                    numero = track.get("id", 0)
                    tipo_pista = track.get("type", "")
                    duracion_str = track.get("properties", {}).get("tag_duration", "0:00:00.000")
                    idioma = track.get("properties", {}).get("language_ietf", "und")
                    duracion = convertir_a_segundos(duracion_str)
                    with sqlite3.connect("mkv.db") as conn:
                        c = conn.cursor()
                        c.execute("INSERT INTO pistas VALUES (?, ?, ?, ?, ?, ?)",
                                  (file, archivo_completo, numero, tipo_pista, duracion, idioma))
                        conn.commit()

def convertir_a_segundos(tiempo):
    if not tiempo:
        return 0.0
    partes = tiempo.split(":")
    if len(partes) != 3:
        return 0.0
    h, m, s = partes
    return int(h) * 3600 + int(m) * 60 + float(s)

def extraer_info_nombre(archivo):
    imdb_match = re.search(r"(tt\d+)", archivo)
    serie_match = re.search(r"S(\d{2})E(\d{2})", archivo, re.IGNORECASE)
    imdb_id = imdb_match.group(1) if imdb_match else None
    serie_info = serie_match.group(0).upper() if serie_match else None
    return imdb_id, serie_info

def buscar_coincidencias():
    with sqlite3.connect("mkv.db") as conn:
        c = conn.cursor()
        c.execute("SELECT archivo, ruta FROM pistas WHERE tipo = 'video'")
        datos = c.fetchall()

        esp_map = {}
        eng_map = {}

        for archivo, ruta in datos:
            imdb_id, serie_info = extraer_info_nombre(archivo)
            if not imdb_id:
                continue
            clave = (imdb_id, serie_info)
            if obtener_ruta("esp") in ruta:
                esp_map[clave] = (archivo, ruta)
            elif obtener_ruta("eng") in ruta:
                eng_map[clave] = (archivo, ruta)

        for clave in esp_map:
            if clave in eng_map:
                archivo_esp, ruta_esp = esp_map[clave]
                archivo_eng, ruta_eng = eng_map[clave]

                c.execute("SELECT duracion FROM pistas WHERE ruta = ? AND pista = 0", (ruta_esp,))
                d1 = c.fetchone()
                c.execute("SELECT duracion FROM pistas WHERE ruta = ? AND pista = 0", (ruta_eng,))
                d2 = c.fetchone()
                if d1 and d2:
                    dur1, dur2 = d1[0], d2[0]
                    diferencia = abs(dur1 - dur2)
                    ideal = int(diferencia <= 1.0)
                    if ideal:
                        print(f"Coincidencia ideal: {archivo_esp} <-> {archivo_eng}")
                    else:
                        print(f"Coincidencia encontrada pero diferencia de duración: {archivo_esp} <-> {archivo_eng}")
                    c.execute("INSERT INTO coincidencias VALUES (?, ?, ?, ?, ?)",
                              (archivo_esp, ruta_esp, archivo_eng, ruta_eng, ideal))
        conn.commit()

def combinar_archivos():
    with sqlite3.connect("mkv.db") as conn:
        c = conn.cursor()
        c.execute("SELECT archivo_esp, ruta_esp, archivo_eng, ruta_eng FROM coincidencias WHERE coincidenciaideal = 1")
        coincidencias = c.fetchall()
        ruta_dub = obtener_ruta("dub")

        for archivo_esp, ruta_esp, archivo_eng, ruta_eng in coincidencias:
            info = cargar_info_mkv(ruta_esp)
            pistas_audio_es = []
            for track in info.get("tracks", []):
                if track.get("type") == "audio" and track.get("properties", {}).get("language_ietf") == "es":
                    pistas_audio_es.append(str(track.get("id")))

            salida = ruta_eng.replace(obtener_ruta("eng"), ruta_dub)
            os.makedirs(os.path.dirname(salida), exist_ok=True)

            comando = ["mkvmerge", "-o", salida, "-D"]
            if pistas_audio_es:
                comando += ["-a", ",".join(pistas_audio_es)]
            comando += [ruta_esp, ruta_eng]

            print("Ejecutando:", " ".join(comando))
            resultado = subprocess.run(comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            print(resultado.stdout)

def menu():
    while True:
        print("\n1 - Definir carpetas")
        print("2 - Analizar carpetas")
        print("3 - Buscar coincidencias")
        print("4 - Vaciar base de datos")
        print("5 - Combinar archivos")
        print("0 - Salir")
        opcion = input("Elige una opción: ").strip()

        if opcion == "1":
            definir_carpetas()
        elif opcion == "2":
            analizar_carpeta("esp")
            analizar_carpeta("eng")
        elif opcion == "3":
            buscar_coincidencias()
        elif opcion == "4":
            vaciar_base_de_datos()
        elif opcion == "5":
            combinar_archivos()
        elif opcion == "0":
            break
        else:
            print("Opción inválida")

if __name__ == "__main__":
    crear_bd()
    menu()

