"""Carga, validación y parámetros derivados de la configuración."""

import copy
import json
import math
from pathlib import Path

RUTA_BASE = Path(__file__).resolve().parent.parent / "config" / "parametros.json"
MECANISMOS = ("M0", "M1", "M2")


class ErrorConfig(ValueError):
    """La configuración no es válida; el mensaje lista cada problema."""


def _fusionar(base, cambios):
    for k, v in cambios.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _fusionar(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def aplicar(cfg, cambios):
    """Devuelve una copia de cfg con cambios en notación de puntos: {"campo.hectareas": 40}."""
    nuevo = copy.deepcopy(cfg)
    for clave, valor in (cambios or {}).items():
        partes = clave.split(".")
        destino = nuevo
        for p in partes[:-1]:
            destino = destino.setdefault(p, {})
        destino[partes[-1]] = copy.deepcopy(valor)
    return nuevo


def cargar_config(ruta=None, cambios=None):
    with open(ruta or RUTA_BASE, encoding="utf-8") as f:
        cfg = json.load(f)
    if cambios:
        cfg = aplicar(cfg, cambios)
    validar(cfg)
    return cfg


def lado_campo(cfg):
    c = cfg["campo"]
    celdas = c["hectareas"] * 10000 / c["celda_m"] ** 2
    return max(4, int(round(math.sqrt(celdas))))


SECCIONES = ("campo", "flota", "escala_tiempo", "agente", "comunicacion", "economia",
             "agronomia", "falla", "simulacion")

# (ruta, regla): "pos" > 0, "nneg" >= 0, "frac" en [0, 1], "fracpos" en (0, 1], "ent1" entero >= 1,
# "ent0" entero >= 0
REGLAS = [
    ("campo.hectareas", "pos"), ("campo.celda_m", "pos"), ("campo.n_obstaculos", "ent0"),
    ("flota.n_tractores", "ent1"),
    ("escala_tiempo.ancho_trabajo_m", "pos"), ("escala_tiempo.velocidad_kmh", "pos"),
    ("escala_tiempo.jornada_h", "pos"), ("escala_tiempo.dias_laborables", "fracpos"),
    ("agente.tolva_ha", "pos"), ("agente.tanque_l", "pos"), ("agente.consumo_lh", "pos"),
    ("agente.consumo_ralenti_frac", "frac"), ("agente.reserva_diesel_frac", "frac"),
    ("agente.recarga_semilla_min", "nneg"), ("agente.recarga_diesel_min", "nneg"),
    ("agente.cambio_implemento_min", "nneg"), ("agente.variacion_servicio", "frac"),
    ("agente.paciencia_pasos", "ent1"),
    ("comunicacion.perdida_mensajes", "frac"), ("comunicacion.retraso_max", "ent0"),
    ("comunicacion.timeout_ofertas", "ent1"), ("comunicacion.reintento_cfp", "ent1"),
    ("comunicacion.holgura_tell", "pos"), ("comunicacion.valor_hilera", "nneg"),
    ("comunicacion.costo_celda", "pos"), ("comunicacion.ventana_reservas", "ent1"),
    ("comunicacion.margen_recarga_hileras", "ent0"),
    ("economia.precio_tractor", "pos"), ("economia.temporadas_vida", "pos"), ("economia.vida_h", "pos"),
    ("economia.reparacion_frac", "nneg"), ("economia.precio_diesel", "nneg"),
    ("economia.rendimiento_t_ha", "nneg"), ("economia.precio_maiz", "nneg"),
    ("economia.penaliza_colision", "nneg"), ("economia.perdida_no_sembrada_frac", "frac"),
    ("agronomia.perdida_dia", "frac"), ("agronomia.ventana_dias", "pos"),
    ("falla.cobertura_disparo", "frac"),
    ("simulacion.max_estancado_pasos", "ent1"), ("simulacion.max_pasos_factor", "pos"),
]
TEXTO_REGLA = {
    "pos": "debe ser un número positivo", "nneg": "no puede ser negativo",
    "frac": "es una probabilidad o fracción y debe estar entre 0 y 1",
    "fracpos": "es una fracción: debe estar entre 0 y 1 y ser mayor que 0",
    "ent1": "debe ser un entero >= 1", "ent0": "debe ser un entero y no puede ser negativo",
}


def _es_numero(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v  # descarta NaN


def _cumple(v, regla):
    if regla in ("ent1", "ent0"):
        if not (isinstance(v, int) and not isinstance(v, bool)):
            return False
        return v >= (1 if regla == "ent1" else 0)
    if not _es_numero(v):
        return False
    return {"pos": v > 0, "nneg": v >= 0, "frac": 0 <= v <= 1, "fracpos": 0 < v <= 1}[regla]


def validar(cfg):
    """Revisa secciones, tipos y rangos. Lanza ErrorConfig con la lista completa de problemas."""
    faltan = [s for s in SECCIONES if not isinstance(cfg.get(s), dict)]
    if faltan:
        raise ErrorConfig("Configuración inválida:\n- faltan las secciones " + ", ".join(faltan))
    errores = []
    for ruta, regla in REGLAS:
        seccion, llave = ruta.split(".")
        if llave not in cfg[seccion]:
            errores.append(f"falta el parámetro {ruta}")
            continue
        v = cfg[seccion][llave]
        if not _es_numero(v):
            errores.append(f"{ruta} debe ser un número ({TEXTO_REGLA[regla].replace('debe ser ', '')}), no {v!r}")
        elif not _cumple(v, regla):
            errores.append(f"{ruta} {TEXTO_REGLA[regla]}, no {v!r}")

    if cfg.get("mecanismo") not in MECANISMOS:
        errores.append(f"mecanismo debe ser uno de {MECANISMOS}, no {cfg.get('mecanismo')!r}")
    if not (isinstance(cfg.get("semilla"), int) and not isinstance(cfg.get("semilla"), bool)):
        errores.append(f"semilla debe ser un entero, no {cfg.get('semilla')!r}")
    if not isinstance(cfg["falla"].get("activa"), bool):
        errores.append(f"falla.activa debe ser true o false, no {cfg['falla'].get('activa')!r}")
    if not isinstance(cfg["comunicacion"].get("oferta_anticipada"), bool):
        errores.append("comunicacion.oferta_anticipada debe ser true o false")

    f = cfg["flota"]
    n, nf = f.get("n_tractores"), f.get("n_surcadores")
    if nf is not None:
        if not _cumple(nf, "ent1"):
            errores.append(f"flota.n_surcadores debe ser un entero >= 1 o null, no {nf!r}")
        elif _cumple(n, "ent1") and n >= 2 and not (1 <= nf <= n - 1):
            errores.append(f"flota.n_surcadores debe estar entre 1 y {n - 1} cuando hay {n} tractores")
        elif n == 1 and nf != 1:
            errores.append("con 1 tractor, flota.n_surcadores debe ser null o 1 (surca y luego siembra)")

    c = cfg["campo"]
    if _cumple(c.get("hectareas"), "pos") and _cumple(c.get("celda_m"), "pos"):
        lado = lado_campo(cfg)
        dx = c.get("deposito_x")
        if dx is not None and not (_cumple(dx, "ent0") and dx < lado):
            errores.append(f"campo.deposito_x={dx!r} queda fuera del campo: debe ser una columna entera "
                           f"entre 0 y {lado - 1}, o null")
        alto_trabajo = (2, lado + 1)
        for i, ob in enumerate(c.get("obstaculos") or []):
            try:
                x, y = ob["x"], ob["y"]
                w, h = ob.get("ancho", 1), ob.get("alto", 1)
            except (TypeError, KeyError):
                errores.append(f"obstáculo {i} debe tener x, y (y opcionalmente ancho, alto)")
                continue
            enteros = all(isinstance(v, int) and not isinstance(v, bool) for v in (x, y, w, h))
            if not enteros or w < 1 or h < 1:
                errores.append(f"obstáculo {i}: x, y, ancho y alto deben ser enteros (ancho y alto >= 1)")
                continue
            if x < 0 or x + w > lado:
                errores.append(f"obstáculo {i} queda fuera del campo en x")
            if y < alto_trabajo[0] or y + h - 1 > alto_trabajo[1]:
                errores.append(f"obstáculo {i} cae en una cabecera o en el patio del depósito "
                               f"(filas de trabajo {alto_trabajo[0]} a {alto_trabajo[1]})")

    if errores:
        raise ErrorConfig("Configuración inválida:\n- " + "\n- ".join(errores))
    return True


def derivados(cfg):
    """Escala de tiempo y capacidades en unidades de la simulación (pasos y celdas)."""
    e, a = cfg["escala_tiempo"], cfg["agente"]
    celda_ha = cfg["campo"]["celda_m"] ** 2 / 10000
    cap_ha_h = e["velocidad_kmh"] * e["ancho_trabajo_m"] / 10  # ASABE D497, capacidad teórica
    paso_s = celda_ha / cap_ha_h * 3600
    a_pasos = lambda minutos: max(1, int(round(minutos * 60 / paso_s)))
    return {
        "celda_ha": celda_ha,
        "capacidad_teorica_ha_h": cap_ha_h,
        "paso_s": paso_s,
        "paso_h": paso_s / 3600,
        "pasos_dia": e["jornada_h"] * 3600 / paso_s,
        "diesel_paso_l": a["consumo_lh"] * paso_s / 3600,
        "tolva_celdas": max(1, int(round(a["tolva_ha"] / celda_ha))),
        "pasos_recarga_semilla": a_pasos(a["recarga_semilla_min"]),
        "pasos_recarga_diesel": a_pasos(a["recarga_diesel_min"]),
        "pasos_cambio": a_pasos(a["cambio_implemento_min"]),
    }
