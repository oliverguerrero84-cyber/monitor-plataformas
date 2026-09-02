#!/usr/bin/env python3
"""Monitoreo continuo de la plataforma. Avisa solo cuando algo CAMBIA.

Por qué avisa solo en los cambios
--------------------------------
Un monitor que grita en cada revisión se vuelve ruido y el equipo deja de leerlo.
Este guarda el estado anterior y avisa dos veces por incidente:

    sano  →  roto   ⚠️  "el catálogo está devolviendo 404"
    roto  →  sano   ✅  "ya se restableció, duró 40 minutos"

Ese segundo aviso es el que da el dato que hoy nadie tiene: **cuánto duró**.

Antes de gritar, confirma
-------------------------
Una falla se reintenta 2 veces antes de darla por buena. Un timeout suelto o un
tropiezo de red no deben despertar a nadie a las 3 de la mañana.

El historial es el producto
---------------------------
Cada incidente se guarda en `monitor/historial.jsonl`. De ahí sale el reporte
semanal —cuántas veces falló, cuánto duró, a qué hora— que es lo que convierte
esto en una conversación con datos en vez de opiniones.

Uso:
    python3 monitor/vigilar.py --cliente ppdg
    python3 monitor/vigilar.py --cliente ppdg --sin-avisar  # sin tocar el CRM
    python3 monitor/vigilar.py --cliente ppdg --probar      # aviso suelto de prueba
    python3 monitor/vigilar.py --cliente ppdg --simulacro   # ensayo del ciclo completo
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sitio import cargar, revisar

BASE_API = "https://services.leadconnectorhq.com"

CLIENTE = "ppdg"
if "--cliente" in sys.argv:
    CLIENTE = sys.argv[sys.argv.index("--cliente") + 1]
CFG = cargar(CLIENTE)
PAGINAS = CFG["paginas"]
UMBRAL_LENTO = CFG["umbral_lento"]
AL = CFG["alerta"]

AQUI = os.path.dirname(os.path.abspath(__file__))
ESTADO = os.path.join(AQUI, "estado", f"{CLIENTE}.json")
HISTORIAL = os.path.join(AQUI, "estado", f"{CLIENTE}-historial.jsonl")
os.makedirs(os.path.dirname(ESTADO), exist_ok=True)

SIN_AVISAR = "--sin-avisar" in sys.argv
PROBAR = "--probar" in sys.argv
SIMULACRO = "--simulacro" in sys.argv
REINTENTOS = 2

# Ruta inexistente a propósito, para el simulacro. Pedirla es una visita más al
# sitio, igual que la de cualquier persona que teclea mal una dirección: no
# escribe nada, no cambia nada y no toca el trabajo de nadie.
RUTA_SIMULACRO = "/esta-pagina-no-existe-prueba-del-monitor/"

# Margen entre el aviso de caída y el de recuperación durante el simulacro. El
# workflow del CRM necesita quitar la etiqueta antes de poder volver a
# dispararse; si los dos avisos salen pegados, el segundo se pierde.
ESPERA_SIMULACRO = 180


def encabezados():
    tok = os.environ.get("GHL_API_KEY")
    if not tok:
        raise SystemExit("Falta GHL_API_KEY en el entorno.")
    return {"Authorization": f"Bearer {tok}", "Version": "2021-07-28",
            "Content-Type": "application/json", "Accept": "application/json"}


def avisar(texto):
    """Escribe el texto en el contacto de alerta y le pone la etiqueta que
    dispara [MON-1]. El workflow manda el WhatsApp y el correo, y se quita la
    etiqueta solo para que la próxima alerta vuelva a dispararlo."""
    if SIN_AVISAR:
        print("  (--sin-avisar: no se tocó el CRM)")
        return True
    h = encabezados()
    try:
        r = requests.put(f"{BASE_API}/contacts/{AL['contacto_id']}", headers=h, timeout=40,
                         json={"customFields": [{"id": AL["campo_id"], "value": texto}]})
        if r.status_code >= 300:
            print(f"  fallo al escribir el detalle: {r.status_code} {r.text[:160]}")
            return False
        # El texto tiene que estar ANTES de la etiqueta: la etiqueta dispara el
        # workflow, y si llega primero el mensaje sale con el detalle anterior.
        time.sleep(2)
        r = requests.post(f"{BASE_API}/contacts/{AL['contacto_id']}/tags", headers=h,
                          json={"tags": [AL["etiqueta"]]}, timeout=40)
        if r.status_code >= 300:
            print(f"  fallo al poner la etiqueta: {r.status_code} {r.text[:160]}")
            return False
        return True
    except Exception as e:
        print(f"  fallo al avisar: {e}")
        return False


def revisar_con_reintento(ruta):
    r = revisar(CFG, ruta)
    for _ in range(REINTENTOS):
        if r["ok"]:
            return r
        time.sleep(4)
        r = revisar(CFG, ruta)
    return r


def cargar_estado():
    if os.path.exists(ESTADO):
        try:
            return json.load(open(ESTADO, encoding="utf-8"))
        except Exception:
            pass
    return {}


def duracion(desde_iso):
    try:
        t0 = datetime.datetime.fromisoformat(desde_iso)
    except Exception:
        return "un rato"
    m = int((datetime.datetime.now(datetime.timezone.utc) - t0).total_seconds() // 60)
    if m < 60:
        return f"{m} minutos"
    return f"{m // 60} h {m % 60} min"


def anotar(registro):
    with open(HISTORIAL, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(registro, ensure_ascii=False) + "\n")


def hora_local(ahora=None):
    ahora = ahora or datetime.datetime.now(datetime.timezone.utc)
    return (ahora - datetime.timedelta(hours=6)).strftime("%H:%M")


def texto_caida(nombre, url, motivo, hora):
    return (f"⚠️ {CFG['nombre']} — falla detectada en la plataforma ({hora} hrs)\n\n"
            f"• {nombre}: {motivo}\n  {url}\n\n"
            "Revisión automática. Se avisa de nuevo cuando se restablezca.")


def simulacro():
    """Ensaya el ciclo completo de aviso: caída y recuperación, con su duración.

    Es la única forma de ver los dos mensajes tal como saldrían de verdad sin
    tener que esperar a que la plataforma se caiga. Pide una dirección que no
    existe —el monitor la ve rota, como debe ser—, avisa, espera unos minutos y
    avisa que se restableció. No toca el estado real ni el sitio del cliente.
    """
    t0 = datetime.datetime.now(datetime.timezone.utc)
    r = revisar(CFG, RUTA_SIMULACRO)
    motivo = r["motivo"] or "respondió distinto a lo esperado"
    print(f"simulacro: {r['url']} → {motivo}")

    aviso = (texto_caida("Página de prueba del monitor", r["url"], motivo, hora_local(t0))
             + "\n\n(SIMULACRO — es un ensayo del sistema de avisos, "
               "la plataforma está funcionando bien.)")
    print("\n--- aviso 1 ---\n" + aviso)
    uno = avisar(aviso)
    print("--- aviso 1", "enviado" if uno else "NO enviado", "---")

    print(f"\nesperando {ESPERA_SIMULACRO}s para el aviso de recuperación...")
    time.sleep(ESPERA_SIMULACRO)

    ahora = datetime.datetime.now(datetime.timezone.utc)
    aviso2 = (f"✅ {CFG['nombre']} — plataforma restablecida ({hora_local(ahora)} hrs)\n\n"
              f"• Página de prueba del monitor ya responde bien. "
              f"Estuvo fallando {duracion(t0.isoformat(timespec='seconds'))}.\n\n"
              "(SIMULACRO — fin del ensayo.)")
    print("\n--- aviso 2 ---\n" + aviso2)
    dos = avisar(aviso2)
    print("--- aviso 2", "enviado" if dos else "NO enviado", "---")

    anotar({"cuando": t0.isoformat(timespec="seconds"), "tipo": "simulacro",
            "avisado": uno and dos, "detalle": aviso + "\n\n" + aviso2})
    if not (uno and dos):
        sys.exit(1)


def main():
    ahora = datetime.datetime.now(datetime.timezone.utc)
    sello = ahora.isoformat(timespec="seconds")
    hora_mx = hora_local(ahora)

    if PROBAR:
        ok = avisar(f"🔧 PRUEBA del monitoreo de {CFG['nombre']} ({hora_mx} hrs).\n\n"
                    "Si estás leyendo esto, el aviso por WhatsApp y correo funciona. "
                    "No hay ninguna falla.")
        print("prueba enviada" if ok else "la prueba no se pudo enviar")
        if not ok:
            sys.exit(1)
        return

    if SIMULACRO:
        return simulacro()

    estado = cargar_estado()
    nuevo, caidas, recuperadas, lentas, cambios_lentitud = {}, [], [], [], []

    print(f"Revisión {sello}\n")
    for clave, ruta, nombre in PAGINAS:
        r = revisar_con_reintento(ruta)
        antes = estado.get(clave, {})
        estaba_ok = antes.get("ok", True)
        era_lenta = antes.get("lenta", False)
        es_lenta = bool(r["ok"] and r["segundos"] and r["segundos"] > UMBRAL_LENTO)

        # Ojo con lo que se guarda aquí: este archivo se commitea en cada corrida,
        # así que todo campo que cambie siempre —los segundos, por ejemplo— genera
        # un commit por revisión y entierra el historial que sí importa. Solo van
        # los datos que definen un cambio de situación.
        nuevo[clave] = {"ok": r["ok"], "motivo": r["motivo"], "lenta": es_lenta,
                        "desde": (antes.get("desde") if r["ok"] == estaba_ok else sello)
                                 or sello}

        marca = "OK " if r["ok"] else "MAL"
        print(f"  {marca} {nombre[:30]:<32} {str(r['status']):>4}  {r['segundos']}s"
              f"  {r['motivo'] or ''}")

        if estaba_ok and not r["ok"]:
            caidas.append((nombre, r))
        elif not estaba_ok and r["ok"]:
            recuperadas.append((nombre, antes.get("desde", sello)))
        if es_lenta:
            lentas.append((nombre, r["segundos"]))
        if es_lenta != era_lenta:
            cambios_lentitud.append((nombre, r["segundos"], es_lenta))

    # ---------- avisar solo si cambió algo
    partes = []
    if caidas:
        partes.append(f"⚠️ {CFG['nombre']} — falla detectada en la plataforma ({hora_mx} hrs)\n")
        for nombre, r in caidas:
            partes.append(f"• {nombre}: {r['motivo']}")
            partes.append(f"  {r['url']}")
        partes.append("\nRevisión automática. Se avisa de nuevo cuando se restablezca.")
    if recuperadas:
        if partes:
            partes.append("")
        partes.append(f"✅ {CFG['nombre']} — plataforma restablecida ({hora_mx} hrs)\n")
        for nombre, desde in recuperadas:
            partes.append(f"• {nombre} ya responde bien. Estuvo fallando {duracion(desde)}.")

    if partes:
        texto = "\n".join(partes)
        print("\n--- aviso ---")
        print(texto)
        enviado = avisar(texto)
        print("--- aviso", "enviado" if enviado else "NO enviado", "---")
        anotar({"cuando": sello, "avisado": enviado,
                "caidas": [n for n, _ in caidas],
                "recuperadas": [n for n, _ in recuperadas], "detalle": texto})
    else:
        print("\nsin cambios respecto a la revisión anterior — no se avisa")

    if lentas:
        print("\nlentas (no generan aviso):")
        for n, s in lentas:
            print(f"  {n}: {s}s")
    # Al historial solo van los cambios. El catálogo lleva meses lento; anotarlo
    # en cada revisión no informa nada y sí ahoga los incidentes reales.
    if cambios_lentitud:
        anotar({"cuando": sello, "tipo": "lentitud",
                "cambios": [{"pagina": n, "segundos": s, "lenta": v}
                            for n, s, v in cambios_lentitud]})

    json.dump(nuevo, open(ESTADO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # Salir con error hace que GitHub Actions marque la corrida como fallida y
    # mande su propio correo. Es un segundo canal, independiente del CRM: si
    # GoGHL o el CRM fallan, este aviso llega igual.
    if caidas:
        sys.exit(1)


if __name__ == "__main__":
    main()
