"""
Harness: lee las PQRS del data lake, extrae el texto de cada una
(texto directo, transcripcion de audio u OCR de foto), las clasifica
y guarda el resultado en PostgreSQL.

Los archivos originales del data lake NUNCA se modifican (solo se leen).

Uso (dentro de Docker):
    docker compose run --rm harness                  # procesa todo lo pendiente
    docker compose run --rm harness python main.py --limite 3   # prueba rapida
"""
import argparse
import io
import os
import tempfile
import time
from collections import Counter

import boto3
import psycopg2
import pytesseract
from botocore.config import Config
from PIL import Image

from clasificador import clasificar

BUCKET_RAW = "pqrs-raw"
PREFIJOS = {"textos/": "texto", "audios/": "audio", "fotos/": "foto"}

_whisper = None


# ------------------------------------------------------------- conexiones
def conectar_s3():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "admin"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", ""),
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def conectar_db(intentos=20):
    for i in range(intentos):
        try:
            return psycopg2.connect(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                dbname=os.getenv("POSTGRES_DB", "pqrs"),
                user=os.getenv("POSTGRES_USER", "pqrs"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
        except psycopg2.OperationalError:
            print(f"Esperando a PostgreSQL ({i + 1}/{intentos}) ...")
            time.sleep(3)
    raise SystemExit("No se pudo conectar a PostgreSQL. Revisa 'docker compose ps' y el .env")


def preparar_esquema(conn):
    """Agrega la columna de fecha si la base se creo con la version inicial del esquema."""
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE pqrs_casos ADD COLUMN IF NOT EXISTS fecha_recepcion DATE")
    conn.commit()


# ------------------------------------------------------ extraccion de texto
def leer_texto(datos):
    return datos.decode("utf-8", errors="replace")


def transcribir_audio(datos):
    global _whisper
    from faster_whisper import WhisperModel

    if _whisper is None:
        modelo = os.getenv("WHISPER_MODEL", "small")
        print(f"  Cargando modelo Whisper '{modelo}' (la primera vez descarga el modelo) ...")
        _whisper = WhisperModel(modelo, device="cpu", compute_type="int8")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(datos)
        ruta = f.name
    try:
        segmentos, _ = _whisper.transcribe(ruta, language="es")
        return " ".join(s.text.strip() for s in segmentos)
    finally:
        os.remove(ruta)


def leer_foto(datos):
    imagen = Image.open(io.BytesIO(datos))
    return pytesseract.image_to_string(imagen, lang="spa").strip()


EXTRACTORES = {"texto": leer_texto, "audio": transcribir_audio, "foto": leer_foto}


# ------------------------------------------------------------------ main
def listar_objetos(s3):
    for prefijo, canal in PREFIJOS.items():
        paginas = s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET_RAW, Prefix=prefijo)
        for pagina in paginas:
            for obj in pagina.get("Contents", []):
                if not obj["Key"].endswith("/"):
                    yield obj["Key"], canal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=0, help="procesar solo N archivos (prueba)")
    args = ap.parse_args()

    s3 = conectar_s3()
    conn = conectar_db()
    preparar_esquema(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT archivo_origen FROM pqrs_casos")
        ya_procesados = {fila[0] for fila in cur.fetchall()}

    pendientes = [(k, c) for k, c in listar_objetos(s3) if f"{BUCKET_RAW}/{k}" not in ya_procesados]
    if args.limite:
        pendientes = pendientes[: args.limite]
    print(f"Archivos pendientes: {len(pendientes)} (ya procesados: {len(ya_procesados)})")

    nuevos, errores = Counter(), 0
    for n, (clave, canal) in enumerate(pendientes, start=1):
        print(f"[{n}/{len(pendientes)}] {clave}")
        try:
            objeto = s3.get_object(Bucket=BUCKET_RAW, Key=clave)
            datos = objeto["Body"].read()
            fecha = objeto.get("Metadata", {}).get("fecha")

            texto = EXTRACTORES[canal](datos)
            if not texto.strip():
                raise ValueError("no se pudo extraer texto del archivo")
            resultado = clasificar(texto)

            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO pqrs_casos
                       (archivo_origen, canal, texto_extraido, tipo, tema, urgencia,
                        area_destino, clasificador, fecha_recepcion)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (archivo_origen) DO NOTHING""",
                    (f"{BUCKET_RAW}/{clave}", canal, texto, resultado["tipo"], resultado["tema"],
                     resultado["urgencia"], resultado["area"], resultado["clasificador"], fecha),
                )
            conn.commit()
            nuevos[canal] += 1
            print(f"    -> {resultado['tipo']} / {resultado['tema']} / urgencia {resultado['urgencia']}"
                  f" / {resultado['area']}")
            if resultado.get("nota"):
                print(f"       ({resultado['nota']})")
        except Exception as e:  # un archivo con error no detiene al resto
            conn.rollback()
            errores += 1
            print(f"    ERROR: {e}")

    print(f"\nListo. Procesados: {sum(nuevos.values())} {dict(nuevos)} | Errores: {errores}")
    conn.close()


if __name__ == "__main__":
    main()
