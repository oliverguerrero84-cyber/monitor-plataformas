#!/usr/bin/env python3
"""Qué se revisa de un sitio y qué cuenta como "roto".

Lo comparten el auditor (`auditar.py`) y la vigilancia continua (`vigilar.py`):
el reporte y las alertas tienen que hablar de lo mismo, o el cliente recibe un
reporte que no coincide con los avisos que le llegan.

La configuración de cada cliente vive en `clientes/<nombre>.json`, así que el
mismo código sirve para cualquier sitio sin tocarlo.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata

import requests

AQUI = os.path.dirname(os.path.abspath(__file__))


def cargar(cliente):
    ruta = os.path.join(AQUI, "clientes", f"{cliente}.json")
    if not os.path.exists(ruta):
        disponibles = [f[:-5] for f in os.listdir(os.path.join(AQUI, "clientes"))
                       if f.endswith(".json")]
        raise SystemExit(f"No existe clientes/{cliente}.json. Hay: {', '.join(disponibles)}")
    with open(ruta, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["paginas"] = [tuple(p) for p in cfg["paginas"]]
    return cfg


def sin_acentos(s):
    """Quita acentos para comparar, así "Página" y "Pagina" empatan."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def revisar(cfg, ruta, timeout=45):
    """Revisa una página y devuelve el veredicto con su detalle.

    SANA = responde 200, es HTML, trae `<title>`, y no contiene ninguna de las
    frases de falla. Cualquier otra cosa es problema.

    Las tres primeras condiciones no bastan por sí solas, y este sitio lo prueba:
    devuelve **HTTP 200 mostrando "Página no encontrada"**. Un monitor que solo
    mire el código de respuesta reporta esas fallas como éxito.
    """
    url = cfg["base"] + ruta
    t0 = time.perf_counter()
    try:
        r = requests.get(url, headers={"User-Agent": cfg["user_agent"]},
                         timeout=timeout, allow_redirects=True)
    except requests.Timeout:
        return {"url": url, "ok": False, "motivo": f"no respondió en {timeout}s",
                "status": None, "segundos": timeout, "titulo": "", "bytes": 0,
                "tipo": "", "headers": {}}
    except Exception as e:
        return {"url": url, "ok": False, "motivo": f"error de red: {e}",
                "status": None, "segundos": None, "titulo": "", "bytes": 0,
                "tipo": "", "headers": {}}
    seg = time.perf_counter() - t0

    ctype = r.headers.get("content-type") or ""
    tipo = ctype.split(";")[0].strip()

    # ⚠️ El sitio no declara charset, y sin eso `requests` decodifica como
    # ISO-8859-1: "Página" se vuelve "PÃ¡gina" y la búsqueda de frases con acento
    # no encuentra nada — o sea, el monitor daría por sanas justo las páginas
    # rotas. WordPress sirve UTF-8, así que se fuerza.
    if "charset" not in ctype.lower():
        r.encoding = "utf-8"

    texto = r.text or ""
    m = re.search(r"<title>([^<]*)</title>", texto, re.I)
    titulo = (m.group(1).strip() if m else "")
    bajo = sin_acentos(texto.lower()) if "html" in tipo else ""

    motivo = None
    if r.status_code != 200:
        motivo = f"HTTP {r.status_code}"
    elif "html" not in tipo:
        # Caso real: una URL de curso devolvía un PNG de 1.4 MB con HTTP 200.
        motivo = f"no devolvió una página, devolvió {tipo} ({len(r.content):,} bytes)"
    elif not titulo:
        motivo = "la página cargó sin título (probablemente incompleta)"
    else:
        for f in cfg["frases_de_falla"]:
            if f in bajo:
                motivo = f"la página dice: “{f}”"
                break

    return {"url": url, "ok": motivo is None, "motivo": motivo,
            "status": r.status_code, "segundos": round(seg, 2), "titulo": titulo,
            "bytes": len(r.content), "tipo": tipo, "headers": dict(r.headers)}
