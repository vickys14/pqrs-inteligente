"""
Reporte mensual de PQRS para las directivas (PDF).

Lee los casos clasificados de PostgreSQL, genera graficos y una tabla con los casos
de urgencia alta, guarda el PDF en reports/ y lo sube al bucket pqrs-reportes del data lake.

Uso (dentro de Docker):
    docker compose run --rm harness python reporte.py                 # mes mas reciente
    docker compose run --rm harness python reporte.py --mes 2026-10   # un mes concreto
    docker compose run --rm harness python reporte.py --sin-subir     # no sube al data lake
"""
import argparse
import io
import os
import re
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,  # noqa: E402
                                Table, TableStyle)

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
ETIQ_TIPO = {"peticion": "Petición", "queja": "Queja", "reclamo": "Reclamo",
             "sugerencia": "Sugerencia"}
ETIQ_TEMA = {"notas": "Notas", "finanzas": "Finanzas", "infraestructura": "Infraestructura",
             "bienestar": "Bienestar", "docentes": "Docentes", "biblioteca": "Biblioteca",
             "tecnologia": "Tecnología", "servicios": "Servicios"}
ETIQ_CANAL = {"texto": "Texto", "audio": "Audio", "foto": "Foto"}
COLOR_URG = {"alta": "#c0392b", "media": "#e1a100", "baja": "#2e8b57"}
AZUL = "#1f4e79"


# ----------------------------------------------------------------- utilidades
def pct(n, total):
    return f"{100 * n / total:.0f} %" if total else "0 %"


def extracto(texto, n=150):
    """Resumen corto del caso, sin encabezados ni firma (mejor esfuerzo, para no mostrar datos personales)."""
    lineas = []
    for linea in texto.splitlines():
        l = linea.strip()
        bajo = l.lower()
        if bajo.startswith(("atentamente", "firma:")):
            break
        if not l or bajo.startswith(("de:", "para:", "fecha:", "asunto:", "nombre:", "programa:",
                                     "buen día", "universidad - formulario", "descripción:")):
            continue
        lineas.append(l)
    plano = " ".join(lineas)
    plano = re.sub(r"^Hola, buenas tardes\.\s*Mi nombre es .+? y estudio .+?\.\s*", "", plano)
    plano = re.sub(r"\s*Muchas gracias por su atención\.?$", "", plano)
    if len(plano) > n:
        plano = plano[:n].rsplit(" ", 1)[0] + "..."
    return plano


def grafico_resumen(filas):
    """Cuatro graficos en una sola imagen: tipo, urgencia, canal y tema."""
    fig, ejes = plt.subplots(2, 2, figsize=(10, 7))

    def barras(ax, conteo, etiquetas, titulo, colores=None, horizontal=False):
        claves = list(conteo)
        valores = [conteo[k] for k in claves]
        nombres = [etiquetas.get(k, k) for k in claves]
        cols = colores or [AZUL] * len(claves)
        if horizontal:
            bars = ax.barh(nombres[::-1], valores[::-1], color=cols[::-1])
            ax.bar_label(bars, padding=3)
            ax.set_xlim(0, max(valores) * 1.2)
        else:
            bars = ax.bar(nombres, valores, color=cols)
            ax.bar_label(bars, padding=2)
            ax.set_ylim(0, max(valores) * 1.2)
        ax.set_title(titulo, fontsize=12, fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)

    tipos = Counter(f["tipo"] for f in filas)
    urg = Counter(f["urgencia"] for f in filas)
    canal = Counter(f["canal"] for f in filas)
    tema = Counter(f["tema"] for f in filas)

    barras(ejes[0][0], dict(tipos.most_common()), ETIQ_TIPO, "Casos por tipo")
    orden = [u for u in ("alta", "media", "baja") if u in urg]
    barras(ejes[0][1], {u: urg[u] for u in orden}, {u: u.capitalize() for u in orden},
           "Casos por urgencia", [COLOR_URG[u] for u in orden])
    barras(ejes[1][0], dict(canal.most_common()), ETIQ_CANAL, "Casos por canal de entrada")
    barras(ejes[1][1], dict(tema.most_common()), ETIQ_TEMA, "Casos por tema", horizontal=True)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def hallazgos(filas):
    total = len(filas)
    tema, n_tema = Counter(f["tema"] for f in filas).most_common(1)[0]
    tipo, n_tipo = Counter(f["tipo"] for f in filas).most_common(1)[0]
    altas = [f for f in filas if f["urgencia"] == "alta"]
    area_tema = Counter(f["area_destino"] for f in filas if f["tema"] == tema).most_common(1)[0][0]

    lineas = [
        f"Se recibieron <b>{total}</b> PQRS: "
        + ", ".join(f"{n} por {ETIQ_CANAL[c].lower()}" for c, n in Counter(f['canal'] for f in filas).most_common())
        + ".",
        f"El tema más frecuente fue <b>{ETIQ_TEMA.get(tema, tema)}</b> ({n_tema} casos, {pct(n_tema, total)}).",
        f"El tipo más frecuente fue <b>{ETIQ_TIPO.get(tipo, tipo)}</b> ({n_tipo} casos, {pct(n_tipo, total)}).",
        f"Hay <b>{len(altas)}</b> casos de urgencia alta ({pct(len(altas), total)}).",
    ]
    if altas:
        areas = Counter(f["area_destino"] for f in altas).most_common(3)
        lineas.append("Áreas con más casos urgentes: "
                      + ", ".join(f"{a} ({n})" for a, n in areas) + ".")

    recomendaciones = []
    if altas:
        recomendaciones.append(f"Atender primero los {len(altas)} casos de urgencia alta de la tabla siguiente.")
    recomendaciones.append(f"Revisar el proceso relacionado con <b>{ETIQ_TEMA.get(tema, tema)}</b>, "
                           f"tema más frecuente, con el área de {area_tema}.")
    return lineas, recomendaciones


# ------------------------------------------------------------------------ PDF
def construir_pdf(filas, mes, ruta, clasificador):
    anio, num = mes.split("-")
    titulo_mes = f"{MESES[int(num) - 1].capitalize()} de {anio}"

    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Title"], textColor=colors.HexColor(AZUL), fontSize=20,
                        alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], textColor=colors.HexColor(AZUL),
                        spaceBefore=12, spaceAfter=6)
    normal = ParagraphStyle("n", parent=base["BodyText"], fontSize=10, leading=14)
    pequeno = ParagraphStyle("p", parent=normal, fontSize=8, leading=10)
    nota = ParagraphStyle("nota", parent=normal, fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(2 * cm, 1.2 * cm, f"Reporte generado automáticamente - clasificador: {clasificador}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(ruta), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.8 * cm, bottomMargin=2 * cm,
                            title=f"Reporte PQRS {titulo_mes}", author="Sistema Inteligente de Análisis de PQRS")
    e = []
    e.append(Paragraph("Reporte mensual de PQRS", h1))
    e.append(Paragraph(f"Peticiones, quejas, reclamos y sugerencias - {titulo_mes}", normal))

    lineas, recomendaciones = hallazgos(filas)
    e.append(Paragraph("Resumen del mes", h2))
    for l in lineas:
        e.append(Paragraph("• " + l, normal))

    e.append(Spacer(1, 8))
    e.append(Image(grafico_resumen(filas), width=17 * cm, height=17 * cm * 0.7))

    e.append(Paragraph("Recomendaciones", h2))
    for r in recomendaciones:
        e.append(Paragraph("• " + r, normal))

    # --- casos por area
    e.append(Paragraph("Casos por área responsable", h2))
    por_area = Counter(f["area_destino"] for f in filas)
    altas_area = Counter(f["area_destino"] for f in filas if f["urgencia"] == "alta")
    datos = [["Área", "Casos", "Urgencia alta"]]
    for area, n in por_area.most_common():
        datos.append([area, str(n), str(altas_area.get(area, 0))])
    t = Table(datos, colWidths=[9 * cm, 3.5 * cm, 4.5 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(AZUL)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f6fa")]),
    ]))
    e.append(t)

    # --- casos urgentes
    altas = sorted((f for f in filas if f["urgencia"] == "alta"), key=lambda f: str(f["fecha_recepcion"]))
    e.append(Paragraph(f"Casos de urgencia alta ({len(altas)})", h2))
    if altas:
        datos = [["Fecha", "Canal", "Área", "Tipo / Tema", "Resumen del caso"]]
        for f in altas:
            datos.append([
                Paragraph(str(f["fecha_recepcion"]), pequeno),
                Paragraph(ETIQ_CANAL.get(f["canal"], f["canal"]), pequeno),
                Paragraph(escape(f["area_destino"]), pequeno),
                Paragraph(f"{ETIQ_TIPO.get(f['tipo'], f['tipo'])} / {ETIQ_TEMA.get(f['tema'], f['tema'])}", pequeno),
                Paragraph(escape(extracto(f["texto_extraido"])), pequeno),
            ])
        t = Table(datos, colWidths=[1.9 * cm, 1.4 * cm, 2.9 * cm, 3.3 * cm, 7.5 * cm], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLOR_URG["alta"])),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fbf1f0")]),
        ]))
        e.append(t)
    else:
        e.append(Paragraph("No hubo casos de urgencia alta en este periodo.", normal))

    e.append(Spacer(1, 14))
    e.append(Paragraph(
        "<b>Nota:</b> la clasificación (tipo, tema y urgencia) la realiza un modelo de inteligencia "
        "artificial y puede contener errores. Se recomienda que una persona verifique los casos antes de "
        "actuar, en especial los de urgencia media y baja, que el sistema puede subestimar. "
        "Los datos de este reporte son sintéticos.", nota))
    doc.build(e, onFirstPage=pie, onLaterPages=pie)


# ----------------------------------------------------------------------- main
def main():
    import boto3
    import psycopg2
    from botocore.config import Config

    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", help="mes del reporte, formato AAAA-MM (por defecto el mas reciente)")
    ap.add_argument("--sin-subir", action="store_true", help="no subir el PDF al data lake")
    args = ap.parse_args()

    conn = psycopg2.connect(host=os.getenv("POSTGRES_HOST", "localhost"),
                            dbname=os.getenv("POSTGRES_DB", "pqrs"),
                            user=os.getenv("POSTGRES_USER", "pqrs"),
                            password=os.getenv("POSTGRES_PASSWORD", ""))
    with conn.cursor() as cur:
        cur.execute("SELECT to_char(MAX(fecha_recepcion), 'YYYY-MM') FROM pqrs_casos")
        mes = args.mes or cur.fetchone()[0]
        if not mes:
            raise SystemExit("No hay casos con fecha en la base. Corre primero el harness.")
        cur.execute("""SELECT canal, texto_extraido, tipo, tema, urgencia, area_destino,
                              fecha_recepcion, clasificador
                       FROM pqrs_casos WHERE to_char(fecha_recepcion, 'YYYY-MM') = %s""", (mes,))
        columnas = ["canal", "texto_extraido", "tipo", "tema", "urgencia", "area_destino",
                    "fecha_recepcion", "clasificador"]
        filas = [dict(zip(columnas, r)) for r in cur.fetchall()]
    conn.close()
    if not filas:
        raise SystemExit(f"No hay casos para el mes {mes}.")

    clasificador = Counter(f["clasificador"] for f in filas).most_common(1)[0][0]
    Path("reports").mkdir(exist_ok=True)
    ruta = Path("reports") / f"reporte_{mes}.pdf"
    construir_pdf(filas, mes, ruta, clasificador)
    print(f"Reporte generado con {len(filas)} casos: {ruta}")

    if args.sin_subir:
        return
    s3 = boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT", "http://localhost:9000"),
                      aws_access_key_id=os.getenv("MINIO_ROOT_USER", "admin"),
                      aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", ""),
                      region_name="us-east-1",
                      config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
    s3.put_object(Bucket="pqrs-reportes", Key=ruta.name, Body=ruta.read_bytes(),
                  ContentType="application/pdf")
    print(f"Subido al data lake: s3://pqrs-reportes/{ruta.name}")


if __name__ == "__main__":
    main()
