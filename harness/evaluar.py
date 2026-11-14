"""
Evalua la precision del clasificador comparando lo guardado en PostgreSQL
contra las etiquetas correctas (etiquetas.csv, generado junto con los datos sinteticos).

Uso (dentro de Docker):
    docker compose run --rm harness python evaluar.py

Guarda un resumen en reports/evaluacion_<clasificador>.json para poder comparar
modelos (por ejemplo ollama vs claude) en el articulo.
"""
import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

CAMPOS = ["tipo", "tema", "urgencia"]


def cargar_etiquetas(ruta):
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        return {fila["archivo"]: fila for fila in csv.DictReader(f)}


def calcular(etiquetas, filas):
    """filas: lista de dicts con archivo, canal, tipo, tema, urgencia (lo que predijo el modelo)."""
    total = 0
    aciertos = Counter()
    por_canal = defaultdict(lambda: Counter())
    totales_canal = Counter()
    errores = []
    alta_real = alta_detectada = 0

    for fila in filas:
        real = etiquetas.get(fila["archivo"])
        if not real:
            continue
        total += 1
        totales_canal[fila["canal"]] += 1
        todo_ok = True
        for campo in CAMPOS:
            ok = fila[campo] == real[campo]
            aciertos[campo] += ok
            por_canal[fila["canal"]][campo] += ok
            todo_ok &= ok
        aciertos["exacto"] += todo_ok
        por_canal[fila["canal"]]["exacto"] += todo_ok
        if real["urgencia"] == "alta":
            alta_real += 1
            alta_detectada += fila["urgencia"] == "alta"
        if not todo_ok:
            errores.append({
                "archivo": fila["archivo"],
                "real": f'{real["tipo"]}/{real["tema"]}/{real["urgencia"]}',
                "modelo": f'{fila["tipo"]}/{fila["tema"]}/{fila["urgencia"]}',
            })

    pct = lambda a, n: round(100 * a / n, 1) if n else 0.0
    return {
        "casos_evaluados": total,
        "precision": {c: pct(aciertos[c], total) for c in CAMPOS + ["exacto"]},
        "recall_urgencia_alta": pct(alta_detectada, alta_real),
        "por_canal": {
            canal: {c: pct(por_canal[canal][c], n) for c in CAMPOS + ["exacto"]} | {"casos": n}
            for canal, n in totales_canal.items()
        },
        "errores": errores,
    }


def imprimir(res, nombre):
    print(f"\n=== Evaluacion del clasificador: {nombre} ===")
    print(f"Casos evaluados: {res['casos_evaluados']}\n")
    p = res["precision"]
    print(f"Precision tipo:      {p['tipo']}%")
    print(f"Precision tema:      {p['tema']}%")
    print(f"Precision urgencia:  {p['urgencia']}%")
    print(f"Los tres campos bien: {p['exacto']}%")
    print(f"Urgencias altas detectadas: {res['recall_urgencia_alta']}%\n")
    print("Por canal:")
    for canal, m in res["por_canal"].items():
        print(f"  {canal:6s} ({m['casos']} casos): tipo {m['tipo']}% | tema {m['tema']}% | "
              f"urgencia {m['urgencia']}% | todo {m['exacto']}%")
    if res["errores"]:
        print(f"\nCasos con algun error ({len(res['errores'])}):")
        for e in res["errores"]:
            print(f"  {e['archivo']}: real {e['real']}  ->  modelo {e['modelo']}")


def main():
    import psycopg2

    ruta = os.getenv("ETIQUETAS", "/app/etiquetas.csv")
    if not Path(ruta).is_file():
        raise SystemExit(f"No encuentro {ruta}. Revisa que synthetic_data/etiquetas.csv exista.")
    etiquetas = cargar_etiquetas(ruta)

    conn = psycopg2.connect(host=os.getenv("POSTGRES_HOST", "localhost"),
                            dbname=os.getenv("POSTGRES_DB", "pqrs"),
                            user=os.getenv("POSTGRES_USER", "pqrs"),
                            password=os.getenv("POSTGRES_PASSWORD", ""))
    with conn.cursor() as cur:
        cur.execute("SELECT archivo_origen, canal, tipo, tema, urgencia, clasificador FROM pqrs_casos")
        filas = [{"archivo": r[0].split("/")[-1], "canal": r[1], "tipo": r[2], "tema": r[3],
                  "urgencia": r[4], "clasificador": r[5]} for r in cur.fetchall()]
    conn.close()

    if not filas:
        raise SystemExit("La tabla pqrs_casos esta vacia. Corre primero el harness.")
    nombre = Counter(f["clasificador"] for f in filas).most_common(1)[0][0]
    res = calcular(etiquetas, filas)
    imprimir(res, nombre)

    Path("reports").mkdir(exist_ok=True)
    salida = Path("reports") / f"evaluacion_{nombre}.json"
    salida.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResumen guardado en {salida}")


if __name__ == "__main__":
    main()
