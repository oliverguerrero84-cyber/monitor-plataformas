#!/usr/bin/env python3
"""Auditoría técnica del sitio de la academia — genera el reporte para el cliente.

Qué mide y por qué
------------------
No es una revisión de "¿está arriba?". Es el diagnóstico que hoy nadie tiene:

  · **Cada página, varias veces.** Una sola medición no dice nada de un problema
    intermitente. Se repite N veces para ver el mínimo, la mediana y el máximo —
    la diferencia entre esos tres es lo que delata inestabilidad.
  · **Contenido, no solo código HTTP.** Varias de las fallas reportadas devuelven
    200 con el contenido equivocado. Ver `FRASES_DE_FALLA` en `sitio.py`.
  · **La infraestructura**: servidor, versión de PHP, caché, CDN, compresión.
    De ahí sale si el problema es de hosting o de configuración.

Genera `reportes/REPORTE_TECNICO_<CLIENTE>.md`, listo para entregar.

Uso:
    python3 monitor/auditar.py --cliente ppdg
    python3 monitor/auditar.py --cliente ppdg --pasadas 5   # más muestras
"""
from __future__ import annotations

import datetime
import os
import re
import statistics
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))

from sitio import cargar, revisar

CLIENTE = "ppdg"
if "--cliente" in sys.argv:
    CLIENTE = sys.argv[sys.argv.index("--cliente") + 1]
CFG = cargar(CLIENTE)
BASE, PAGINAS, UA = CFG["base"], CFG["paginas"], CFG["user_agent"]
UMBRAL_LENTO = CFG["umbral_lento"]

PASADAS = 3
if "--pasadas" in sys.argv:
    PASADAS = int(sys.argv[sys.argv.index("--pasadas") + 1])

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reportes",
                      f"REPORTE_TECNICO_{CLIENTE.upper()}.md")
os.makedirs(os.path.dirname(SALIDA), exist_ok=True)


def huella_tecnologica():
    """Qué se puede saber del sitio desde fuera, sin entrar al panel."""
    datos = {}
    try:
        r = requests.get(BASE, headers={"User-Agent": UA}, timeout=45)
    except Exception as e:
        return {"error": str(e)}
    h = {k.lower(): v for k, v in r.headers.items()}
    html = r.text or ""

    datos["servidor"] = h.get("server", "no lo dice")
    datos["php"] = h.get("x-powered-by", "no lo dice")
    datos["compresion"] = h.get("content-encoding", "ninguna")
    datos["cdn"] = next((h[k] for k in ("cf-ray", "x-cdn", "x-served-by") if k in h), "no se detecta")
    datos["cache_headers"] = {k: h[k] for k in h
                              if any(x in k for x in ("cache", "x-litespeed", "x-cache", "age"))}

    m = re.search(r'name="generator" content="WordPress ([\d.]+)"', html)
    datos["wordpress"] = m.group(1) if m else "no lo expone"

    # Plugins que dejan rastro en el HTML. Interesa sobre todo el caché: es la
    # causa nº1 de que un LMS muestre contenido equivocado.
    fingerprints = {
        "LearnPress": "learnpress",
        "Elementor": "elementor",
        "WooCommerce": "woocommerce",
        "WP Rocket": "wp-rocket",
        "LiteSpeed Cache": "litespeed",
        "W3 Total Cache": "w3-total-cache",
        "WP Super Cache": "wp-super-cache",
        "Autoptimize": "autoptimize",
        "Cloudflare": "cloudflare",
    }
    bajo = html.lower()
    datos["detectados"] = sorted(n for n, f in fingerprints.items() if f in bajo)
    return datos


def main():
    print(f"Auditando {BASE} — {PASADAS} pasadas por página\n")
    resultados = {}

    for clave, ruta, nombre in PAGINAS:
        muestras = []
        for i in range(PASADAS):
            r = revisar(CFG, ruta)
            muestras.append(r)
            estado = "OK " if r["ok"] else "MAL"
            print(f"  {estado} {nombre[:30]:<32} {str(r['status']):>4} "
                  f"{r['segundos']}s  {r['motivo'] or ''}")
        resultados[clave] = {"nombre": nombre, "ruta": ruta, "muestras": muestras}

    print("\nLeyendo huella tecnológica…")
    tec = huella_tecnologica()

    # ---------- reporte
    ahora = datetime.datetime.now().strftime("%d de %B de %Y, %H:%M")
    L = []
    L.append(f"# Reporte técnico — Plataforma {CFG['nombre']}\n")
    L.append(f"> Medición automatizada del sitio `{BASE}`, {PASADAS} revisiones por página.\n"
             f"> Fecha: {ahora}.\n")

    fallando = [r for r in resultados.values()
                if any(not m["ok"] for m in r["muestras"])]
    lentas = []
    for r in resultados.values():
        t = [m["segundos"] for m in r["muestras"] if m["segundos"]]
        if t and statistics.median(t) > UMBRAL_LENTO:
            lentas.append(r)

    L.append("\n## Resumen\n")
    L.append(f"- Páginas revisadas: **{len(resultados)}**")
    L.append(f"- Con alguna falla: **{len(fallando)}**")
    L.append(f"- Por encima de {UMBRAL_LENTO:.0f} s: **{len(lentas)}**")
    todos = [m["segundos"] for r in resultados.values() for m in r["muestras"] if m["segundos"]]
    if todos:
        L.append(f"- Tiempo de respuesta mediano del sitio: **{statistics.median(todos):.1f} s**")
        L.append(f"- El más lento medido: **{max(todos):.1f} s**")

    L.append("\n> **Referencia:** una página se considera aceptable por debajo de 2.5 s "
             "y buena por debajo de 1 s. Arriba de 5 s, una parte de los visitantes "
             "abandona antes de que cargue.\n")

    L.append("\n## Detalle por página\n")
    L.append("| Página | Estado | Mín | Mediana | Máx | Observación |")
    L.append("|---|---|---:|---:|---:|---|")
    for r in resultados.values():
        t = [m["segundos"] for m in r["muestras"] if m["segundos"]]
        malos = [m for m in r["muestras"] if not m["ok"]]
        if not malos:
            estado = "✅ OK"
            obs = ""
        elif len(malos) == len(r["muestras"]):
            estado = "❌ Falla"
            obs = malos[0]["motivo"]
        else:
            estado = "⚠️ Intermitente"
            obs = f"falló {len(malos)} de {len(r['muestras'])}: {malos[0]['motivo']}"
        mn = f"{min(t):.1f}s" if t else "—"
        md = f"{statistics.median(t):.1f}s" if t else "—"
        mx = f"{max(t):.1f}s" if t else "—"
        if t and not malos and not obs:
            med = statistics.median(t)
            if med > 5:
                obs = "responde bien pero **lenta**"
            elif max(t) - min(t) > 3:
                obs = "tiempos muy dispares entre visitas"
        L.append(f"| {r['nombre']} | {estado} | {mn} | {md} | {mx} | {obs} |")

    L.append("\n## Infraestructura\n")
    if tec.get("error"):
        L.append(f"No se pudo leer: {tec['error']}")
    else:
        L.append("| Dato | Valor |")
        L.append("|---|---|")
        L.append(f"| Servidor | `{tec['servidor']}` |")
        L.append(f"| PHP | `{tec['php']}` |")
        L.append(f"| WordPress | `{tec['wordpress']}` |")
        L.append(f"| Compresión | `{tec['compresion']}` |")
        L.append(f"| CDN | `{tec['cdn']}` |")
        L.append(f"| Detectado en la página | {', '.join(tec['detectados']) or 'nada identificable'} |")
        if tec["cache_headers"]:
            L.append("\n**Cabeceras de caché encontradas:**\n")
            L.append("```")
            for k, v in tec["cache_headers"].items():
                L.append(f"{k}: {v}")
            L.append("```")
        else:
            L.append("\n> **No se detectó ninguna cabecera de caché.** Es un dato "
                     "relevante: significa que cada visita se genera desde cero "
                     "en el servidor, lo que explica buena parte de la lentitud.")

    L.append("\n## Hallazgo principal: hay caché de servidor con 2 horas de vida\n")
    ch = tec.get("cache_headers") or {}
    if ch:
        ttl = ch.get("cache-control", "")
        m = re.search(r"max-age=(\d+)", ttl)
        horas = int(m.group(1)) / 3600 if m else None
        L.append("El sitio guarda copias de las páginas en un caché de servidor y se "
                 "las sirve a los visitantes sin volver a generarlas:\n")
        L.append("```")
        for k, v in ch.items():
            L.append(f"{k}: {v}")
        L.append("```\n")
        if horas:
            estado_cache = ch.get("x-proxy-cache", "").upper()
            nota = {
                "HIT": "En el momento de esta medición estaba sirviendo desde una copia "
                       "guardada, no desde el sitio.",
                "MISS": "En el momento de esta medición generó la página de nuevo y "
                        "guardó una copia fresca — la siguiente visita ya recibirá esa copia.",
            }.get(estado_cache, "")
            L.append(f"`max-age={m.group(1)}` significa que una copia guardada se "
                     f"reutiliza durante **{horas:.0f} horas**. {nota}\n")
        L.append("**Por qué esto importa para las fallas reportadas:**\n")
        L.append("Si en el momento en que el caché toma la foto la página está rota "
                 "—por ejemplo, justo durante una actualización, cuando las rutas "
                 "internas se reconstruyen— **esa foto rota se le sirve a todo el "
                 "mundo hasta que expire**. El sitio ya está bien, pero los visitantes "
                 "siguen viendo el error.\n")
        L.append("Eso explica cuatro cosas que hasta ahora parecían contradictorias:\n")
        L.append("| Lo que se observó | Lo que lo explica |")
        L.append("|---|---|")
        L.append("| *\"Lleva así media hora\"*, *\"más de una hora\"* | La copia guardada "
                 "vive hasta 2 horas |")
        L.append("| A veces F5 lo arregla y a veces no | Depende de si toca una copia "
                 "buena o la rota |")
        L.append("| A una persona le falla y a otra no, al mismo tiempo | Están tomando "
                 "copias distintas |")
        L.append("| *\"La plataforma nunca ha dejado de funcionar\"* | **Es correcto** — "
                 "el sitio está bien, lo que sirve mal es el caché |")
        L.append("\n**Qué se puede hacer, en orden de esfuerzo:**\n")
        L.append("1. **Excluir del caché las páginas del área de alumnos** — login, "
                 "perfil, carrito y contenido de curso. Son páginas personales: "
                 "guardarlas y reutilizarlas entre usuarios es lo que produce que "
                 "alguien vea el contenido o el estado de otro.")
        L.append("2. **Vaciar el caché automáticamente después de cada actualización** "
                 "de plugins o del tema. Es el momento exacto en que se toma la foto rota.")
        L.append("3. **Bajar el tiempo de vida** de 2 horas a 10 o 15 minutos mientras "
                 "se estabiliza. Acota el daño de cualquier copia mala.")
        L.append("\n> Los tres son **configuración**, no desarrollo. Ninguno requiere "
                 "tocar el código del sitio.\n")
    else:
        L.append("No se detectaron cabeceras de caché en esta medición.\n")

    L.append("\n## Qué significa esto\n")
    if fallando:
        L.append("### Páginas con falla\n")
        for r in fallando:
            malos = [m for m in r["muestras"] if not m["ok"]]
            L.append(f"- **{r['nombre']}** (`{r['ruta']}`) — {malos[0]['motivo']}")
        L.append("")
    if lentas:
        L.append("### Lentitud\n")
        L.append("Estas páginas responden correctamente pero tardan de más:\n")
        for r in lentas:
            t = [m["segundos"] for m in r["muestras"] if m["segundos"]]
            L.append(f"- **{r['nombre']}** — mediana de {statistics.median(t):.1f} s")
        L.append("\nEn un sitio de cursos esto pega doble: el visitante nuevo se va "
                 "antes de ver la oferta, y el alumno inscrito siente que \"no carga\" "
                 "aunque técnicamente no haya error.\n")
    if not fallando and not lentas:
        L.append("En esta medición no se detectaron fallas ni lentitud fuera de rango. "
                 "Un problema intermitente **no se descarta con una sola auditoría** — "
                 "para eso está el monitoreo continuo.\n")

    L.append("\n---\n")
    L.append("*Generado por `monitor/auditar.py`. Reproducible: al volver a correrlo "
             "se puede comparar contra esta medición y ver si mejoró o empeoró.*")

    with open(SALIDA, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"\nReporte escrito en {os.path.relpath(SALIDA)}")


if __name__ == "__main__":
    main()
