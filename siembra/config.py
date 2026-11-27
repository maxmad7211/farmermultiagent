"""Carga, validación y parámetros derivados de la configuración."""

import copy
import json
import math
from pathlib import Path

RUTA_BASE = Path(__file__).resolve().parent.parent / "config" / "parametros.json"
MECANISMOS = ("M0", "M1", "M2")          # los del barrido y los escenarios de la propuesta
MECANISMOS_VALIDOS = MECANISMOS + ("M3",)  # M3 — coordinador supervisor (docs/m3.md)

# Valores por defecto de las secciones de M3. Son opcionales — una configuración sin ellas sigue
# siendo válida y M0, M1 y M2 no las usan mientras los eventos estén apagados.
DEFECTO_COORDINADOR = {
    "periodo_revision": 15, "sectores_revision": 3, "vigencia_vista": 60, "periodo_latido": 5,
    "latidos_perdidos": 3, "radio_percepcion": 2, "prob_no_detectar": 0.1, "tasa_reporte_falso": 0.0,
    "margen_zona": 1, "margen_zona_max": 2, "alcance_pipa": 3, "agua_celdas": 60, "apagado_por_paso": 3, "n_pipas": 1,
    "n_gruas": 1, "enganche_min": 5, "reparacion_min": 60, "paciencia_plan": 40,
    "crecimiento_fuego": 1.5, "peso_tiempo": 1.0, "peso_trabajo": 1.0, "peso_energia": 50.0,
    "peso_riesgo": 30.0,
}
DEFECTO_EVENTOS = {
    "incendio": {"activo": False, "cobertura_disparo": 0.3, "prob_propagacion": 0.02, "duracion_pasos": 60},
    "obstaculo_nuevo": {"activo": False, "cobertura_disparo": 0.4, "ancho": 2, "alto": 2},
}


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

    if cfg.get("mecanismo") not in MECANISMOS_VALIDOS:
        errores.append(f"mecanismo debe ser uno de {MECANISMOS_VALIDOS}, no {cfg.get('mecanismo')!r}")
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

    errores += _errores_m3(cfg)
    if errores:
        raise ErrorConfig("Configuración inválida:\n- " + "\n- ".join(errores))
    return True


REGLAS_COORDINADOR = {
    "periodo_revision": "ent1", "sectores_revision": "ent1", "vigencia_vista": "ent1",
    "periodo_latido": "ent1", "latidos_perdidos": "ent1", "radio_percepcion": "ent1",
    "prob_no_detectar": "frac", "tasa_reporte_falso": "frac", "margen_zona": "ent0",
    "margen_zona_max": "ent0", "alcance_pipa": "ent1", "agua_celdas": "ent1", "apagado_por_paso": "ent1",
    "n_pipas": "ent1",
    "n_gruas": "ent1", "enganche_min": "nneg", "reparacion_min": "nneg", "paciencia_plan": "ent1",
    "crecimiento_fuego": "pos", "peso_tiempo": "nneg", "peso_trabajo": "nneg", "peso_energia": "nneg",
    "peso_riesgo": "nneg",
}
REGLAS_EVENTOS = {
    "incendio": {"cobertura_disparo": "frac", "prob_propagacion": "frac", "duracion_pasos": "ent1"},
    "obstaculo_nuevo": {"cobertura_disparo": "frac", "ancho": "ent1", "alto": "ent1"},
}


def _errores_m3(cfg):
    """Revisa las secciones opcionales `coordinador` y `eventos` (solo si vienen en cfg)."""
    errores = []
    co = cfg.get("coordinador")
    if co is not None:
        if not isinstance(co, dict):
            return ["coordinador debe ser una sección (objeto JSON)"]
        for llave, regla in REGLAS_COORDINADOR.items():
            if llave in co and not _cumple(co[llave], regla):
                errores.append(f"coordinador.{llave} {TEXTO_REGLA[regla]}, no {co[llave]!r}")
        p = parametros_m3(cfg)["coordinador"]
        if _cumple(p["margen_zona"], "ent0") and _cumple(p["margen_zona_max"], "ent0") \
                and p["margen_zona_max"] < p["margen_zona"]:
            errores.append("coordinador.margen_zona_max no puede ser menor que coordinador.margen_zona")
        if _cumple(p["alcance_pipa"], "ent1") and _cumple(p["margen_zona_max"], "ent0") \
                and p["alcance_pipa"] <= p["margen_zona_max"]:
            errores.append("coordinador.alcance_pipa debe ser mayor que coordinador.margen_zona_max "
                           "(la pipa apaga desde fuera de la zona prohibida)")
    ev = cfg.get("eventos")
    if ev is not None:
        if not isinstance(ev, dict):
            return errores + ["eventos debe ser una sección (objeto JSON)"]
        for nombre, reglas in REGLAS_EVENTOS.items():
            sub = ev.get(nombre)
            if sub is None:
                continue
            if not isinstance(sub, dict):
                errores.append(f"eventos.{nombre} debe ser una sección (objeto JSON)")
                continue
            if "activo" in sub and not isinstance(sub["activo"], bool):
                errores.append(f"eventos.{nombre}.activo debe ser true o false")
            for llave, regla in reglas.items():
                if llave in sub and not _cumple(sub[llave], regla):
                    errores.append(f"eventos.{nombre}.{llave} {TEXTO_REGLA[regla]}, no {sub[llave]!r}")
    return errores


def parametros_m3(cfg):
    """Secciones `coordinador` y `eventos` completas (los valores que falten toman el defecto)."""
    co = dict(DEFECTO_COORDINADOR)
    co.update(cfg.get("coordinador") or {})
    ev = {}
    for nombre, defecto in DEFECTO_EVENTOS.items():
        ev[nombre] = dict(defecto)
        ev[nombre].update((cfg.get("eventos") or {}).get(nombre) or {})
    return {"coordinador": co, "eventos": ev}


def derivados_m3(cfg):
    """Tiempos de M3 en pasos (aparte de `derivados` para no cambiar su contrato)."""
    d = derivados(cfg)
    co = parametros_m3(cfg)["coordinador"]
    a_pasos = lambda minutos: max(1, int(round(minutos * 60 / d["paso_s"])))
    return {"pasos_enganche": a_pasos(co["enganche_min"]), "pasos_reparacion": a_pasos(co["reparacion_min"])}


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
