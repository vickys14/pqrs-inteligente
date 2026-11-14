"""
Generador de datos sinteticos de PQRS.

Crea casos ficticios en tres formatos y los sube al data lake (bucket pqrs-raw):
  - textos/  -> correos en .txt
  - audios/  -> llamadas simuladas en .mp3 (voz sintetica con gTTS)
  - fotos/   -> formularios "escaneados" en .png (para probar OCR)

Tambien escribe etiquetas.csv con la clasificacion correcta de cada caso,
para poder medir despues que tan bien clasifica el modelo.

Uso:
    python generar_datos.py                 # 30 casos, genera y sube
    python generar_datos.py --casos 60      # mas casos (repite plantillas)
    python generar_datos.py --solo-local    # no sube, solo genera archivos
    python generar_datos.py --sin-audio     # omite audios (no requiere internet)

Todos los nombres y casos son ficticios.
"""
import argparse
import csv
import os
import random
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent
SALIDA = RAIZ / "output"
BUCKET_RAW = "pqrs-raw"
BUCKET_REPORTES = "pqrs-reportes"
SEMILLA = 42
CANALES = ["texto", "audio", "foto"]

NOMBRES = ["Laura", "Camilo", "Valentina", "Andrés", "Daniela", "Santiago", "Mariana",
           "Juan David", "Paula", "Felipe", "Sofía", "Sebastián", "Carolina", "Mateo"]
APELLIDOS = ["Gómez", "Rodríguez", "Martínez", "López", "Ramírez", "Torres", "Herrera",
             "Castro", "Vargas", "Moreno", "Rojas", "Pardo", "Ortiz", "Suárez"]
PROGRAMAS = ["Ingeniería de Sistemas", "Administración de Empresas", "Derecho", "Psicología",
             "Ingeniería Industrial", "Contaduría Pública", "Medicina", "Diseño Gráfico"]

# (tipo, tema, urgencia, area_destino, texto)
CASOS_BASE = [
    ("reclamo", "finanzas", "alta", "Tesorería",
     "Pagué la matrícula del semestre el 2 de octubre por PSE y en el sistema sigue apareciendo como pendiente. Ya me bloquearon el acceso a la plataforma y mañana tengo parcial. Necesito que lo solucionen hoy, por favor."),
    ("peticion", "notas", "media", "Registro Académico",
     "Solicito amablemente un certificado de notas del semestre anterior para presentarlo en una convocatoria de beca. ¿Cuánto tarda el trámite y cuánto cuesta?"),
    ("queja", "docentes", "media", "Decanatura",
     "Quiero poner una queja sobre el profesor de Cálculo II. Llega veinte minutos tarde casi todas las clases y no responde las dudas de los estudiantes. Somos muchos los inconformes."),
    ("reclamo", "infraestructura", "alta", "Infraestructura",
     "Hay una fuga de agua en el baño del tercer piso del bloque C y el piso está inundado. Ya una persona se resbaló. Por favor envíen a alguien urgente."),
    ("sugerencia", "biblioteca", "baja", "Biblioteca",
     "Sería muy bueno que la biblioteca abriera los domingos en época de parciales. Muchos trabajamos entre semana y solo podemos estudiar los fines de semana."),
    ("reclamo", "notas", "media", "Registro Académico",
     "Mi nota de Física Mecánica aparece como 2.8 en el sistema, pero el profesor me dijo en clase que había sacado 3.4. Pido que revisen y corrijan antes de que cierre el plazo de reclamos."),
    ("queja", "bienestar", "alta", "Bienestar Universitario",
     "Fui a pedir cita con psicología porque estoy pasando por una situación muy difícil y me dijeron que no hay cupos hasta dentro de dos meses. Necesito que me atiendan más pronto, me siento muy mal."),
    ("peticion", "servicios", "baja", "Registro Académico",
     "Quisiera saber cuándo abren las inscripciones para el próximo semestre y qué documentos debo presentar para el reintegro."),
    ("reclamo", "tecnologia", "media", "Soporte TI",
     "Desde hace una semana no puedo ingresar al aula virtual. Me dice usuario o contraseña incorrecta aunque ya la restablecí dos veces. Tengo entregas pendientes."),
    ("sugerencia", "infraestructura", "baja", "Infraestructura",
     "Propongo instalar más tomacorrientes en la biblioteca y en la cafetería. Casi no hay dónde cargar el portátil y toca pelear por un enchufe."),
    ("queja", "servicios", "alta", "Servicios Generales",
     "La comida de la cafetería del bloque B estaba fría y con mal olor ayer. Me enfermé del estómago después de almorzar. Pido que revisen la higiene del lugar."),
    ("reclamo", "finanzas", "media", "Tesorería",
     "Me cobraron dos veces el recibo de la carnetización. Tengo el comprobante de pago. Solicito la devolución del valor duplicado."),
    ("peticion", "bienestar", "baja", "Bienestar Universitario",
     "Quiero información sobre las becas de alimentación y transporte para el próximo semestre. ¿Cuáles son los requisitos y hasta qué fecha puedo aplicar?"),
    ("queja", "docentes", "alta", "Decanatura",
     "Un profesor del departamento hizo comentarios ofensivos hacia una compañera frente a todo el salón. Fue una situación de acoso y varias personas la presenciamos. Pedimos que se abra una investigación."),
    ("sugerencia", "tecnologia", "baja", "Soporte TI",
     "Sería muy útil tener una aplicación móvil para consultar horarios y notas. Hoy toca entrar desde el computador y la página se ve muy mal en el celular."),
    ("reclamo", "infraestructura", "media", "Infraestructura",
     "El aire acondicionado del laboratorio de sistemas dos lleva un mes dañado. Hace muchísimo calor y los equipos se sobrecalientan en plena práctica."),
    ("peticion", "notas", "media", "Registro Académico",
     "Pido la homologación de dos materias que cursé en otra universidad. Ya tengo los contenidos programáticos. ¿A quién debo enviarlos?"),
    ("queja", "servicios", "baja", "Registro Académico",
     "La atención en la ventanilla de Registro es muy lenta. Hice fila una hora y media para un trámite que tomó cinco minutos. Faltan más personas atendiendo."),
    ("reclamo", "tecnologia", "alta", "Soporte TI",
     "El sistema de inscripción de materias se cayó justo cuando abrió mi turno y ya no hay cupos en las materias que necesito. Pierdo el semestre si no me solucionan esto hoy."),
    ("sugerencia", "bienestar", "baja", "Bienestar Universitario",
     "Podrían organizar talleres de manejo del estrés antes de los exámenes finales. Creo que ayudaría a muchos estudiantes."),
    ("reclamo", "biblioteca", "media", "Biblioteca",
     "Devolví un libro hace dos semanas y el sistema todavía me muestra una multa. Tengo el recibo de entrega. Por favor, retiren la sanción."),
    ("peticion", "finanzas", "media", "Tesorería",
     "Quisiera solicitar un plan de pagos para la matrícula porque mi familia tuvo una dificultad económica. ¿Se puede pagar en cuotas?"),
    ("queja", "infraestructura", "alta", "Infraestructura",
     "Los ascensores del bloque A casi nunca funcionan y para quienes tenemos movilidad reducida es imposible llegar a las clases del quinto piso. Es un problema de accesibilidad."),
    ("sugerencia", "servicios", "baja", "Servicios Generales",
     "Recomiendo poner más canecas de reciclaje en los pasillos y dar información sobre cómo separar los residuos."),
    ("reclamo", "notas", "alta", "Registro Académico",
     "El semestre pasado aprobé una materia y ahora el sistema dice que la perdí, y por eso me quitaron la beca. Necesito que lo revisen urgente porque se me vence el plazo para renovarla."),
    ("peticion", "tecnologia", "baja", "Soporte TI",
     "Solicito acceso a las licencias de software de la universidad, como Office y MATLAB. No sé cómo activarlas con mi correo institucional."),
    ("queja", "bienestar", "media", "Bienestar Universitario",
     "En las instalaciones deportivas el vestier de mujeres no tiene puertas ni casilleros con llave. No nos sentimos seguras dejando nuestras cosas."),
    ("sugerencia", "docentes", "baja", "Decanatura",
     "Sería bueno que los profesores publicaran el programa y las fechas de evaluación desde la primera semana. Así podemos organizarnos mejor."),
    ("peticion", "biblioteca", "baja", "Biblioteca",
     "Quiero pedir que compren la edición más reciente del libro de Ingeniería de Software de Sommerville, porque solo hay una copia y todos lo necesitamos."),
    ("reclamo", "servicios", "media", "Servicios Generales",
     "Perdí mi carné estudiantil y pagué el duplicado hace un mes, pero todavía no me lo entregan y sin carné no me dejan entrar a la biblioteca."),
]


# ---------------------------------------------------------------- utilidades
def cargar_fuente(tamano):
    candidatas = [
        "C:/Windows/Fonts/arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arial.ttf",
        "DejaVuSans.ttf",
    ]
    for ruta in candidatas:
        try:
            return ImageFont.truetype(ruta, tamano)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=tamano)
    except TypeError:
        return ImageFont.load_default()


def ajustar_texto(texto, fuente, ancho_max):
    """Parte el texto en lineas que quepan en ancho_max pixeles."""
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}".strip()
        if fuente.getlength(prueba) <= ancho_max:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def correo_desde_nombre(nombre):
    """'Sofía Rodríguez' -> 'sofia.rodriguez' (sin tildes, como un correo real)."""
    sin_tildes = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return sin_tildes.lower().replace(" ", ".")


# ------------------------------------------------------------ generadores
def generar_texto(caso, ruta):
    contenido = (
        f"De: {correo_desde_nombre(caso['nombre'])}@estudiantes.universidad.edu.co\n"
        f"Para: pqrs@universidad.edu.co\n"
        f"Fecha: {caso['fecha']}\n"
        f"Asunto: Solicitud PQRS\n\n"
        f"Buen día,\n\n{caso['texto']}\n\n"
        f"Atentamente,\n{caso['nombre']}\n{caso['programa']}\n"
    )
    ruta.write_text(contenido, encoding="utf-8")


def generar_audio(caso, ruta):
    from gtts import gTTS  # se importa aqui para poder usar --sin-audio sin la libreria

    guion = (
        f"Hola, buenas tardes. Mi nombre es {caso['nombre']} y estudio {caso['programa']}. "
        f"{caso['texto']} Muchas gracias por su atención."
    )
    gTTS(text=guion, lang="es", tld="com.mx").save(str(ruta))


def generar_foto(caso, ruta):
    ancho, alto = 900, 1200
    img = Image.new("RGB", (ancho, alto), "white")
    d = ImageDraw.Draw(img)
    f_titulo, f_normal = cargar_fuente(34), cargar_fuente(26)

    d.rectangle([30, 30, ancho - 30, alto - 30], outline="black", width=3)
    d.text((60, 60), "UNIVERSIDAD - FORMULARIO PQRS", font=f_titulo, fill="black")
    d.line([60, 115, ancho - 60, 115], fill="black", width=2)

    y = 145
    for etiqueta, valor in [("Fecha", caso["fecha"]), ("Nombre", caso["nombre"]),
                            ("Programa", caso["programa"])]:
        d.text((60, y), f"{etiqueta}: {valor}", font=f_normal, fill="black")
        y += 48

    y += 20
    d.text((60, y), "Descripción:", font=f_normal, fill="black")
    y += 50
    for linea in ajustar_texto(caso["texto"], f_normal, ancho - 140):
        d.text((60, y), linea, font=f_normal, fill="black")
        y += 40

    d.text((60, alto - 120), f"Firma: {caso['nombre']}", font=f_normal, fill="black")
    img.save(ruta)


# ---------------------------------------------------------------- data lake
def conectar_s3():
    import boto3
    from botocore.config import Config

    try:
        from dotenv import load_dotenv
        load_dotenv(RAIZ.parent / ".env")
    except ImportError:
        pass

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "admin"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", ""),
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def asegurar_bucket(s3, nombre):
    from botocore.exceptions import ClientError

    try:
        s3.head_bucket(Bucket=nombre)
    except ClientError:
        s3.create_bucket(Bucket=nombre)
        print(f"  Bucket creado: {nombre}")


def subir_al_data_lake(casos):
    s3 = conectar_s3()
    asegurar_bucket(s3, BUCKET_RAW)
    asegurar_bucket(s3, BUCKET_REPORTES)
    for c in casos:
        clave = f"{c['carpeta']}/{c['archivo']}"
        with open(SALIDA / c["carpeta"] / c["archivo"], "rb") as f:
            s3.put_object(Bucket=BUCKET_RAW, Key=clave, Body=f.read(),
                          Metadata={"fecha": c["fecha"], "caso-id": c["caso_id"]})
    print(f"  {len(casos)} archivos subidos a s3://{BUCKET_RAW}/")


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Generador de PQRS sinteticas")
    ap.add_argument("--casos", type=int, default=30, help="cantidad de casos (default 30)")
    ap.add_argument("--solo-local", action="store_true", help="no subir al data lake")
    ap.add_argument("--sin-audio", action="store_true", help="omitir audios (sin internet)")
    args = ap.parse_args()

    rng = random.Random(SEMILLA)
    carpetas = {"texto": "textos", "audio": "audios", "foto": "fotos"}
    extensiones = {"texto": "txt", "audio": "mp3", "foto": "png"}
    for c in carpetas.values():
        (SALIDA / c).mkdir(parents=True, exist_ok=True)

    casos = []
    for i in range(args.casos):
        tipo, tema, urgencia, area, texto = CASOS_BASE[i % len(CASOS_BASE)]
        canal = CANALES[i % 3]
        if canal == "audio" and args.sin_audio:
            continue
        cid = f"caso_{i + 1:03d}"
        casos.append({
            "caso_id": cid,
            "canal": canal,
            "carpeta": carpetas[canal],
            "archivo": f"{cid}.{extensiones[canal]}",
            "nombre": f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)}",
            "programa": rng.choice(PROGRAMAS),
            "fecha": (date(2026, 10, 1) + timedelta(days=rng.randint(0, 30))).isoformat(),
            "tipo": tipo, "tema": tema, "urgencia": urgencia, "area": area, "texto": texto,
        })

    print(f"Generando {len(casos)} casos en {SALIDA} ...")
    for c in casos:
        ruta = SALIDA / c["carpeta"] / c["archivo"]
        if c["canal"] == "texto":
            generar_texto(c, ruta)
        elif c["canal"] == "audio":
            generar_audio(c, ruta)
        else:
            generar_foto(c, ruta)

    campos = ["caso_id", "canal", "archivo", "fecha", "tipo", "tema", "urgencia", "area", "texto"]
    with open(RAIZ / "etiquetas.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(casos)
    print("  etiquetas.csv escrito (clasificacion correcta de cada caso)")

    if args.solo_local:
        print("Listo (modo local, no se subio nada).")
        return
    try:
        subir_al_data_lake(casos)
    except Exception as e:
        print(f"\nNo se pudo subir al data lake: {e}")
        print("Revisa que 'docker compose up -d' este corriendo y que el .env tenga")
        print("MINIO_ROOT_USER y MINIO_ROOT_PASSWORD correctos.")
        raise SystemExit(1)
    print("Listo.")


if __name__ == "__main__":
    main()
