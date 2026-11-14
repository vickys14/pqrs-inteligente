"""
Clasificador de PQRS. Modulo intercambiable: se elige con la variable CLASSIFIER.

    CLASSIFIER=ollama  -> modelo local (gratis, funciona sin internet)
    CLASSIFIER=claude  -> API de Claude (requiere ANTHROPIC_API_KEY en el .env)

Devuelve: {"tipo", "tema", "urgencia", "area", "clasificador"}
"""
import json
import os
import unicodedata

import requests

TIPOS = {"peticion", "queja", "reclamo", "sugerencia"}
URGENCIAS = {"baja", "media", "alta"}
AREA_POR_TEMA = {
    "notas": "Registro Académico",
    "finanzas": "Tesorería",
    "infraestructura": "Infraestructura",
    "bienestar": "Bienestar Universitario",
    "docentes": "Decanatura",
    "biblioteca": "Biblioteca",
    "tecnologia": "Soporte TI",
    "servicios": "Servicios Generales",
}
TEMAS = set(AREA_POR_TEMA)

# Red de seguridad: vocabulario general de riesgo, acoso y malestar emocional.
# Si aparece en el mensaje, la urgencia sube a "alta" aunque el modelo diga otra cosa.
# (El error de subir una urgencia de mas es mucho menos grave que dejar pasar un caso critico.)
PALABRAS_ALERTA = [
    "acoso", "acosa", "amenaza", "violencia", "agresion", "abuso",
    "suicid", "hacerme dano", "autolesion", "me siento muy mal", "no puedo mas",
    "crisis", "depresion", "ansiedad",
    "emergencia", "peligro", "riesgo", "urgente", "accidente", "herid",
    "incendio", "electrocut", "intoxic", "me enferme", "inundad",
]


def _escalar_urgencia(texto, urgencia):
    """Devuelve (urgencia, nota). Sube a 'alta' si el texto contiene una palabra de alerta."""
    if os.getenv("URGENCIA_REGLAS", "1") != "1" or urgencia == "alta":
        return urgencia, None
    limpio = _sin_tildes(texto)
    for palabra in PALABRAS_ALERTA:
        if palabra in limpio:
            return "alta", f"escalada a alta por regla ('{palabra}')"
    return urgencia, None


# Valores por defecto si el modelo responde algo invalido
POR_DEFECTO = {"tipo": "peticion", "tema": "servicios", "urgencia": "media"}


def _prompt(texto):
    return f"""Eres un asistente que clasifica PQRS de una universidad en Colombia.
Responde SOLO con un JSON de la forma {{"tipo": "...", "tema": "...", "razon": "...", "urgencia": "..."}}.
En "razon" escribe UNA frase corta que justifique la urgencia (hay riesgo? hay plazo? es solo una consulta?).

TIPO (elige uno):
- "reclamo": algo falló, se cobró mal, hay un error o no se cumplió un servicio (aunque el mensaje pida que lo arreglen).
- "queja": inconformidad con la atención, el trato o el comportamiento de una persona o del servicio.
- "peticion": pide información, un documento o un trámite, sin que algo haya fallado.
- "sugerencia": propone una mejora.

TEMA (elige uno):
- "finanzas": pagos, matrícula, cobros, devoluciones, planes de pago.
- "notas": calificaciones, certificados, homologaciones, inscripción de materias, beca por rendimiento.
- "infraestructura": edificios, salones, baños, ascensores, aire acondicionado, daños físicos.
- "bienestar": salud, psicología, becas de alimentación o transporte, seguridad personal, deportes.
- "docentes": comportamiento o desempeño de profesores.
- "biblioteca": libros, multas, horarios o recursos de la biblioteca.
- "tecnologia": plataformas, aula virtual, contraseñas, software, sistemas caídos.
- "servicios": atención administrativa, cafetería, carné, reciclaje y otros trámites generales.

URGENCIA (elige una; "media" es muy frecuente, no la evites):
- "alta": SOLO si hay riesgo para la salud o la seguridad, acoso, un plazo que vence pronto, bloqueo total de acceso o riesgo de perder el semestre o la beca.
- "media": hay un problema real (un cobro, una nota, un daño, una falla) que afecta al estudiante, pero sin riesgo ni plazo inmediato. Es el nivel de la mayoría de reclamos y quejas.
- "baja": consultas, solicitudes de información y sugerencias.

Ejemplos:
Mensaje: "Me llegó un cobro de intereses por mora aunque pagué a tiempo. Pido que lo anulen."
{{"tipo": "reclamo", "tema": "finanzas", "razon": "es un cobro erróneo que hay que corregir, sin plazo inmediato", "urgencia": "media"}}
Mensaje: "El profesor de Química se burla de los estudiantes que hacen preguntas."
{{"tipo": "queja", "tema": "docentes", "razon": "es una inconformidad por el trato, sin riesgo ni plazo", "urgencia": "media"}}
Mensaje: "¿Dónde puedo consultar el calendario de exámenes finales?"
{{"tipo": "peticion", "tema": "servicios", "razon": "es solo una consulta de información", "urgencia": "baja"}}
Mensaje: "Se desprendió parte del techo del salón 204 y casi cae sobre un compañero."
{{"tipo": "reclamo", "tema": "infraestructura", "razon": "hay riesgo físico para las personas", "urgencia": "alta"}}
Mensaje: "Recomiendo ofrecer cursos de inglés los sábados."
{{"tipo": "sugerencia", "tema": "servicios", "razon": "es una propuesta de mejora", "urgencia": "baja"}}
Mensaje: "El aire de la sala de estudio no funciona hace semanas y hace mucho calor."
{{"tipo": "reclamo", "tema": "infraestructura", "razon": "es una falla que molesta pero no hay riesgo ni plazo", "urgencia": "media"}}

Ahora clasifica este mensaje:
\"\"\"
{texto[:3000]}
\"\"\"
JSON:"""


def _sin_tildes(valor):
    valor = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode()
    return valor.strip().lower()


def _llamar_ollama(prompt):
    url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    modelo = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    r = requests.post(
        f"{url}/api/chat",
        json={"model": modelo, "stream": False, "format": "json",
              "messages": [{"role": "user", "content": prompt}],
              "options": {"temperature": 0}},
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


def _llamar_claude(prompt):
    clave = os.getenv("ANTHROPIC_API_KEY", "")
    if not clave:
        raise RuntimeError("CLASSIFIER=claude pero ANTHROPIC_API_KEY esta vacia en el .env")
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": clave, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": os.getenv("CLAUDE_MODEL", "claude-haiku-5-5"), "max_tokens": 200,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def _extraer_json(texto):
    """Toma el primer objeto JSON que aparezca en la respuesta del modelo."""
    ini, fin = texto.find("{"), texto.rfind("}")
    if ini == -1 or fin == -1:
        raise ValueError("la respuesta no contiene JSON")
    return json.loads(texto[ini:fin + 1])


def _normalizar(datos):
    tipo = _sin_tildes(datos.get("tipo", ""))
    tema = _sin_tildes(datos.get("tema", ""))
    urgencia = _sin_tildes(datos.get("urgencia", ""))
    for campo, valor, validos in (("tipo", tipo, TIPOS), ("tema", tema, TEMAS),
                                  ("urgencia", urgencia, URGENCIAS)):
        if valor not in validos:
            print(f"    aviso: '{campo}' invalido ({valor!r}); se usa '{POR_DEFECTO[campo]}'")
    tipo = tipo if tipo in TIPOS else POR_DEFECTO["tipo"]
    tema = tema if tema in TEMAS else POR_DEFECTO["tema"]
    urgencia = urgencia if urgencia in URGENCIAS else POR_DEFECTO["urgencia"]
    return {"tipo": tipo, "tema": tema, "urgencia": urgencia, "area": AREA_POR_TEMA[tema]}


def _finalizar(resultado, texto, modo):
    resultado["urgencia"], resultado["nota"] = _escalar_urgencia(texto, resultado["urgencia"])
    reglas_activas = os.getenv("URGENCIA_REGLAS", "1") == "1"
    resultado["clasificador"] = f"{modo}+reglas" if reglas_activas else modo
    return resultado


def clasificar(texto):
    modo = os.getenv("CLASSIFIER", "ollama").lower()
    llamar = _llamar_claude if modo == "claude" else _llamar_ollama
    prompt = _prompt(texto)

    ultimo_error = None
    for _ in range(2):  # un reintento si el modelo devuelve JSON roto
        try:
            respuesta = llamar(prompt)
            if os.getenv("CLASSIFIER_DEBUG"):
                print(f"    respuesta cruda: {respuesta!r}")
            resultado = _normalizar(_extraer_json(respuesta))
            return _finalizar(resultado, texto, modo)
        except (ValueError, json.JSONDecodeError) as e:
            ultimo_error = e
    print(f"    aviso: respuesta invalida del modelo ({ultimo_error}); se usan valores por defecto")
    resultado = {**POR_DEFECTO, "area": AREA_POR_TEMA[POR_DEFECTO["tema"]]}
    return _finalizar(resultado, texto, modo)
