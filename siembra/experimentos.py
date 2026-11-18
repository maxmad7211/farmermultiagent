"""Experimentos de la propuesta y su ejecución en paralelo.

- barrido: hectáreas × tractores (1 a 4) × mecanismo × semillas -> `barrido.csv`
- escenarios: 9 escenarios × mecanismo × semillas -> `escenarios.csv` y `curvas.csv`
- sens: sensibilidad de la arquitectura (20 ha, 4 tractores) -> `sens_arquitectura.csv`
- detalladas: corridas con `detalle=True`, semilla 0 -> `corridas/<escenario>_<mecanismo>_s0/`

Uso (siempre desde la raíz del proyecto, con el entorno virtual):

    python -m siembra.experimentos --modo rapido
    python -m siembra.experimentos --modo completo --solo barrido escenarios --nucleos 6
    python -m siembra.experimentos --solo detalladas --salida resultados_prueba

Las semillas son 0..S-1 y son las mismas para los tres mecanismos, así que las corridas se
pueden comparar con pruebas pareadas. Si una corrida falla, el error (id, cambios y
traceback) se agrega a `<salida>/errores.log` y las demás siguen.
"""

import argparse
import importlib
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import metricas, telemetria
from .config import MECANISMOS, aplicar, cargar_config, validar

RAIZ = Path(__file__).resolve().parent.parent
SALIDA_POR_DEFECTO = RAIZ / "resultados"
SIMULADOR = "siembra.modelo:simular"
EXPERIMENTOS = ("barrido", "escenarios", "sens", "detalladas")
N_TRACTORES = (1, 2, 3, 4)
MAX_PUNTOS_CURVA = 200
COLUMNAS_CURVAS = ("grupo", "escenario", "mecanismo", "semilla", "t", "t_h", "sembrado_frac", "surcado_frac")

MODOS = {
    "rapido": {
        "hectareas": (10, 20, 40, 80),
        "semillas_barrido": 5,
        "semillas_escenarios": 5,
        "semillas_sens": 5,
        "semillas_por_escenario": {"limite_1t_160ha_lluvia": 2},
    },
    "completo": {
        "hectareas": (10, 20, 40, 80, 160),
        "semillas_barrido": 20,
        "semillas_escenarios": 20,
        "semillas_sens": 10,
        "semillas_por_escenario": {},
    },
}

# Sensibilidad de la arquitectura (propuesta, p. 19): (ruta, valores, mecanismos).
BASE_SENS = {"campo.hectareas": 20, "flota.n_tractores": 4}
SENS_ARQ = (
    ("comunicacion.timeout_ofertas", (1, 3, 5, 10), ("M1", "M2")),
    ("comunicacion.perdida_mensajes", (0.0, 0.1, 0.2, 0.3, 0.5), ("M0", "M1", "M2")),
    ("comunicacion.ventana_reservas", (5, 10, 20), ("M2",)),
    ("comunicacion.margen_recarga_hileras", (0, 1, 2), ("M2",)),
)

# Corridas detalladas (semilla 0): (escenario, mecanismos).
DETALLADAS = (
    ("normal_20ha_2t", ("M0", "M1", "M2")),
    ("falla_20ha_4t", ("M0", "M1", "M2")),
    ("normal_40ha_3t_obst", ("M2",)),
    ("perdida30_20ha_4t", ("M1",)),
)


def escenarios(cfg_base):
    """Escenarios de la propuesta (p. 14) más el de lluvia: {id: (nombre legible, cambios)}."""
    base_20_4 = {"campo.hectareas": 20, "flota.n_tractores": 4}
    return {
        "normal_20ha_2t": ("Normal: 20 ha, 2 tractores, sin obstáculos",
                           {"campo.hectareas": 20, "flota.n_tractores": 2}),
        "normal_40ha_3t_obst": ("Normal: 40 ha, 3 tractores, 2 obstáculos",
                                {"campo.hectareas": 40, "flota.n_tractores": 3, "campo.n_obstaculos": 2}),
        "falla_20ha_4t": ("Adverso: falla de un tractor a media siembra (20 ha, 4 tractores)",
                          {**base_20_4, "falla.activa": True}),
        "perdida10_20ha_4t": ("Adverso: 10 % de mensajes perdidos (20 ha, 4 tractores)",
                              {**base_20_4, "comunicacion.perdida_mensajes": 0.10}),
        "perdida30_20ha_4t": ("Adverso: 30 % de mensajes perdidos (20 ha, 4 tractores)",
                              {**base_20_4, "comunicacion.perdida_mensajes": 0.30}),
        "tolva_mitad_20ha_4t": ("Adverso: tolva con la mitad de capacidad (20 ha, 4 tractores)",
                                {**base_20_4, "agente.tolva_ha": cfg_base["agente"]["tolva_ha"] / 2}),
        "limite_1t_80ha": ("Límite: 1 tractor en 80 ha",
                           {"campo.hectareas": 80, "flota.n_tractores": 1}),
        "limite_1t_160ha_lluvia": ("Límite: 1 tractor en 160 ha con lluvia (60 % de días laborables)",
                                   {"campo.hectareas": 160, "flota.n_tractores": 1,
                                    "escala_tiempo.dias_laborables": 0.6}),
        "limite_4t_10ha": ("Límite: 4 tractores en 10 ha",
                           {"campo.hectareas": 10, "flota.n_tractores": 4}),
    }


@dataclass
class Tarea:
    """Una corrida: grupo, id, cambios de cfg (notación de puntos), semilla y detalle.

    `etiquetas` son las columnas extra que se agregan al resumen (escenario, parámetro, valor).
    `carpeta` (solo detalladas) es donde se guarda la corrida con `telemetria.guardar_corrida`.
    `curva` pide devolver la serie reducida para `curvas.csv`.
    """
    grupo: str
    id: str
    cambios: dict
    semilla: int
    detalle: bool = False
    etiquetas: dict = field(default_factory=dict)
    carpeta: str | None = None
    curva: bool = False
    simulador: str = SIMULADOR
    ruta_config: str | None = None


# ---------------------------------------------------------------------------
# Armado de tareas
# ---------------------------------------------------------------------------

def _texto_valor(v):
    return f"{v:g}" if isinstance(v, float) else str(v)


def armar_tareas(experimento, modo="rapido", semillas=None, cfg_base=None, salida=None,
                 simulador=SIMULADOR, ruta_config=None):
    """Lista de `Tarea` de un experimento ("barrido", "escenarios", "sens" o "detalladas").

    `semillas` sobrescribe el número de semillas del modo (para todos los experimentos y
    escenarios, salvo las detalladas, que siempre usan la semilla 0).
    """
    if modo not in MODOS:
        raise ValueError(f"modo debe ser uno de {tuple(MODOS)}, no {modo!r}")
    m = MODOS[modo]
    cfg_base = cfg_base if cfg_base is not None else cargar_config(ruta_config)
    salida = Path(salida) if salida is not None else SALIDA_POR_DEFECTO
    comun = {"simulador": simulador, "ruta_config": None if ruta_config is None else str(ruta_config)}
    tareas = []

    if experimento == "barrido":
        for ha in m["hectareas"]:
            for n in N_TRACTORES:
                for mec in MECANISMOS:
                    for s in range(semillas or m["semillas_barrido"]):
                        tareas.append(Tarea(
                            grupo="barrido", id=f"barrido_{ha}ha_{n}t_{mec}_s{s}",
                            cambios={"campo.hectareas": ha, "flota.n_tractores": n, "mecanismo": mec},
                            semilla=s, **comun))

    elif experimento == "escenarios":
        for esc, (nombre, cambios) in escenarios(cfg_base).items():
            n_sem = semillas or m["semillas_por_escenario"].get(esc, m["semillas_escenarios"])
            for mec in MECANISMOS:
                for s in range(n_sem):
                    tareas.append(Tarea(
                        grupo="escenario", id=f"{esc}_{mec}_s{s}",
                        cambios={**cambios, "mecanismo": mec}, semilla=s,
                        etiquetas={"escenario": esc, "escenario_nombre": nombre}, curva=True, **comun))

    elif experimento == "sens":
        for ruta, valores, mecs in SENS_ARQ:
            corto = ruta.split(".")[-1]
            for valor in valores:
                for mec in mecs:
                    for s in range(semillas or m["semillas_sens"]):
                        tareas.append(Tarea(
                            grupo="sens_arq", id=f"sens_{corto}_{_texto_valor(valor)}_{mec}_s{s}",
                            cambios={**BASE_SENS, ruta: valor, "mecanismo": mec}, semilla=s,
                            etiquetas={"parametro": ruta, "valor": valor}, **comun))

    elif experimento == "detalladas":
        esc_def = escenarios(cfg_base)
        for esc, mecs in DETALLADAS:
            nombre, cambios = esc_def[esc]
            for mec in mecs:
                id_ = f"{esc}_{mec}_s0"
                tareas.append(Tarea(
                    grupo="detallada", id=id_, cambios={**cambios, "mecanismo": mec}, semilla=0,
                    detalle=True, etiquetas={"escenario": esc, "escenario_nombre": nombre},
                    carpeta=str(salida / "corridas" / id_), **comun))
    else:
        raise ValueError(f"experimento desconocido {experimento!r}; usa uno de {EXPERIMENTOS}")
    return tareas


# ---------------------------------------------------------------------------
# Ejecución de una corrida (en el proceso trabajador)
# ---------------------------------------------------------------------------

def resolver_simulador(ruta):
    """'modulo:funcion' -> función. Se resuelve en cada proceso (Windows usa spawn)."""
    modulo, _, funcion = ruta.partition(":")
    return getattr(importlib.import_module(modulo), funcion or "simular")


def _aplanar(resumen):
    fila = {}
    for k, v in resumen.items():
        if isinstance(v, (list, tuple, dict, np.ndarray)):
            v = json.dumps(telemetria.a_json(v), ensure_ascii=False)
        elif isinstance(v, np.generic):
            v = v.item()
        fila[k] = v
    return fila


def _curva(res, tarea, resumen):
    serie = pd.DataFrame(res["serie"])
    if len(serie) > MAX_PUNTOS_CURVA:
        idx = np.unique(np.linspace(0, len(serie) - 1, MAX_PUNTOS_CURVA).round().astype(int))
        serie = serie.iloc[idx]
    paso_s = float(resumen.get("paso_s", res.get("derivados", {}).get("paso_s", np.nan)))
    t = serie["t"].to_numpy()
    return pd.DataFrame({
        "grupo": tarea.grupo,
        "escenario": tarea.etiquetas.get("escenario", ""),
        "mecanismo": tarea.cambios.get("mecanismo", resumen.get("mecanismo", "")),
        "semilla": tarea.semilla,
        "t": t,
        "t_h": t * paso_s / 3600,
        "sembrado_frac": serie["sembrado_frac"].to_numpy(),
        "surcado_frac": serie["surcado_frac"].to_numpy(),
    }, columns=list(COLUMNAS_CURVAS))


def correr_tarea(tarea):
    """Corre una tarea y devuelve {"ok", "fila", "curva", "segundos"} o {"ok": False, "error"}.

    Nunca lanza excepciones: así una corrida que falla no tumba el pool de procesos.
    """
    inicio = time.perf_counter()
    try:
        simular = resolver_simulador(tarea.simulador)
        cfg = aplicar(cargar_config(tarea.ruta_config), {**tarea.cambios, "semilla": tarea.semilla})
        validar(cfg)
        res = simular(cfg, detalle=tarea.detalle)
        resumen = dict(res["resumen"])
        if any(k not in resumen for k in metricas.LLAVES_COSTO):
            resumen.update(metricas.costos(resumen, cfg))
            res["resumen"] = resumen
        if tarea.carpeta:
            telemetria.guardar_corrida(res, tarea.carpeta)
        fila = {"grupo": tarea.grupo, **tarea.etiquetas, **_aplanar(resumen)}
        curva = _curva(res, tarea, resumen) if tarea.curva else None
        return {"ok": True, "fila": fila, "curva": curva, "segundos": time.perf_counter() - inicio}
    except Exception:
        return {"ok": False, "error": traceback.format_exc(), "segundos": time.perf_counter() - inicio}


# ---------------------------------------------------------------------------
# Ejecución de muchas corridas
# ---------------------------------------------------------------------------

def _costo_estimado(tarea):
    """Para repartir mejor la carga: las corridas grandes se mandan primero."""
    ha = tarea.cambios.get("campo.hectareas", 20)
    return ha * (3 if tarea.detalle else 1)


def _formato_tiempo(s):
    if not np.isfinite(s):
        return "?"
    s = int(round(s))
    h, resto = divmod(s, 3600)
    m, s = divmod(resto, 60)
    return f"{h} h {m:02d} min" if h else (f"{m} min {s:02d} s" if m else f"{s} s")


class _Progreso:
    def __init__(self, total, etiqueta, verbose):
        self.total, self.etiqueta, self.verbose = total, etiqueta, verbose
        self.hechas = self.errores = 0
        self.inicio = self.ultimo = time.perf_counter()
        self.cada = max(1, total // 20)

    def avanzar(self, ok):
        self.hechas += 1
        self.errores += 0 if ok else 1
        ahora = time.perf_counter()
        if not self.verbose:
            return
        if self.hechas == self.total or self.hechas % self.cada == 0 or ahora - self.ultimo > 15:
            self.ultimo = ahora
            trans = ahora - self.inicio
            falta = trans / self.hechas * (self.total - self.hechas)
            print(f"[{self.etiqueta}] {self.hechas}/{self.total} ({100 * self.hechas / self.total:.0f} %)"
                  f" | {_formato_tiempo(trans)} | faltan ~{_formato_tiempo(falta)}"
                  f" | errores {self.errores}", flush=True)


def _registrar_error(ruta_log, tarea, error):
    if ruta_log is None:
        return
    ruta_log = Path(ruta_log)
    ruta_log.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_log, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {tarea.grupo} {tarea.id} (semilla {tarea.semilla})\n")
        f.write(f"cambios: {json.dumps(telemetria.a_json(tarea.cambios), ensure_ascii=False)}\n")
        f.write(error.rstrip() + "\n" + "-" * 72 + "\n")


def ejecutar(tareas, nucleos=1, etiqueta="corridas", ruta_errores=None, verbose=True):
    """Corre las tareas (en paralelo si `nucleos` > 1) y devuelve sus resultados en el mismo orden.

    Cada resultado es el dict de `correr_tarea`. Los errores se escriben en `ruta_errores`.
    """
    resultados = [None] * len(tareas)
    if not tareas:
        return resultados
    progreso = _Progreso(len(tareas), etiqueta, verbose)
    orden = sorted(range(len(tareas)), key=lambda i: -_costo_estimado(tareas[i]))

    def guardar(i, r):
        resultados[i] = r
        if not r["ok"]:
            _registrar_error(ruta_errores, tareas[i], r["error"])
        progreso.avanzar(r["ok"])

    if nucleos <= 1 or len(tareas) == 1:
        for i in orden:
            guardar(i, correr_tarea(tareas[i]))
    else:
        with ProcessPoolExecutor(max_workers=min(nucleos, len(tareas), 61)) as pool:
            futuros = {pool.submit(correr_tarea, tareas[i]): i for i in orden}
            for futuro in as_completed(futuros):
                i = futuros[futuro]
                try:
                    r = futuro.result()
                except Exception:  # el proceso trabajador murió (memoria, Ctrl+C...)
                    r = {"ok": False, "error": traceback.format_exc(), "segundos": np.nan}
                guardar(i, r)
    return resultados


def _escribir(df, ruta, verbose):
    if df.empty:
        if verbose:
            print(f"  (sin corridas exitosas: no se escribió {ruta.name})", flush=True)
        return
    df.to_csv(ruta, index=False, encoding="utf-8")
    if verbose:
        print(f"  -> {ruta} ({len(df)} filas)", flush=True)


def correr(experimentos=EXPERIMENTOS, modo="rapido", semillas=None, nucleos=None, salida=None,
           simulador=SIMULADOR, ruta_config=None, verbose=True):
    """Corre los experimentos pedidos y escribe sus CSV en `salida` (por defecto `resultados/`).

    Devuelve un dict con los DataFrames escritos (`barrido`, `escenarios`, `curvas`,
    `sens_arq`, `detalladas`, según lo que se haya corrido) y `n_errores`.
    """
    salida = Path(salida) if salida is not None else SALIDA_POR_DEFECTO
    salida.mkdir(parents=True, exist_ok=True)
    nucleos = nucleos or max(1, (os.cpu_count() or 2) - 1)
    cfg_base = cargar_config(ruta_config)
    ruta_errores = salida / "errores.log"
    pedidos = [e for e in EXPERIMENTOS if e in set(experimentos)]
    desconocidos = set(experimentos) - set(EXPERIMENTOS)
    if desconocidos:
        raise ValueError(f"experimentos desconocidos: {sorted(desconocidos)}")

    with open(ruta_errores, "a", encoding="utf-8") as f:
        f.write(f"=== Sesión {datetime.now():%Y-%m-%d %H:%M:%S} | modo {modo} | {', '.join(pedidos)} ===\n")

    salidas, n_errores = {}, 0
    for exp in pedidos:
        tareas = armar_tareas(exp, modo, semillas, cfg_base, salida, simulador, ruta_config)
        if verbose:
            print(f"\n== {exp}: {len(tareas)} corridas en {min(nucleos, len(tareas))} procesos ==", flush=True)
        resultados = ejecutar(tareas, nucleos, exp, ruta_errores, verbose)
        buenos = [r for r in resultados if r and r["ok"]]
        n_errores += len(resultados) - len(buenos)
        df = pd.DataFrame([r["fila"] for r in buenos])
        if exp == "barrido":
            _escribir(df, salida / "barrido.csv", verbose)
            salidas["barrido"] = df
        elif exp == "escenarios":
            _escribir(df, salida / "escenarios.csv", verbose)
            curvas = [r["curva"] for r in buenos if r.get("curva") is not None]
            curvas = pd.concat(curvas, ignore_index=True) if curvas else pd.DataFrame(columns=list(COLUMNAS_CURVAS))
            _escribir(curvas, salida / "curvas.csv", verbose)
            salidas["escenarios"], salidas["curvas"] = df, curvas
        elif exp == "sens":
            _escribir(df, salida / "sens_arquitectura.csv", verbose)
            salidas["sens_arq"] = df
        elif exp == "detalladas":
            if verbose:
                for t, r in zip(tareas, resultados):
                    print(f"  -> {t.carpeta} {'ok' if r and r['ok'] else 'ERROR'}", flush=True)
            salidas["detalladas"] = df
    if n_errores and verbose:
        print(f"\n{n_errores} corridas fallaron; detalles en {ruta_errores}", flush=True)
    salidas["n_errores"] = n_errores
    return salidas


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _argumentos(argv=None):
    p = argparse.ArgumentParser(
        prog="python -m siembra.experimentos",
        description="Corre los experimentos de la propuesta y escribe los CSV en resultados/.")
    p.add_argument("--modo", choices=tuple(MODOS), default="rapido",
                   help="rapido: 10-80 ha y 5 semillas; completo: 10-160 ha y 20 semillas (por defecto rapido)")
    p.add_argument("--solo", nargs="+", choices=EXPERIMENTOS, default=list(EXPERIMENTOS),
                   metavar="EXP", help=f"experimentos a correr: {' '.join(EXPERIMENTOS)} (por defecto todos)")
    p.add_argument("--semillas", type=int, default=None, help="número de semillas (sobrescribe el del modo)")
    p.add_argument("--nucleos", type=int, default=None, help="procesos en paralelo (por defecto núcleos - 1)")
    p.add_argument("--salida", default=None, help=f"carpeta de salida (por defecto {SALIDA_POR_DEFECTO})")
    p.add_argument("--config", default=None, help="archivo de parámetros base (por defecto config/parametros.json)")
    p.add_argument("--simulador", default=SIMULADOR,
                   help="función a usar como simulador, 'modulo:funcion' (para pruebas; por defecto %(default)s)")
    args = p.parse_args(argv)
    if args.semillas is not None and args.semillas < 1:
        p.error("--semillas debe ser >= 1")
    if args.nucleos is not None and args.nucleos < 1:
        p.error("--nucleos debe ser >= 1")
    return args


def main(argv=None):
    """Punto de entrada de la línea de comandos. Devuelve 0 si todo salió bien, 1 si alguna
    corrida falló y 2 si no se pudo importar el simulador."""
    args = _argumentos(argv)
    try:
        resolver_simulador(args.simulador)
    except Exception as e:  # noqa: BLE001 - se informa cualquier problema al importar
        print(f"No se pudo importar el simulador {args.simulador!r}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    inicio = time.perf_counter()
    salidas = correr(args.solo, args.modo, args.semillas, args.nucleos, args.salida,
                     args.simulador, args.config)
    print(f"\nListo en {_formato_tiempo(time.perf_counter() - inicio)}.", flush=True)
    return 1 if salidas["n_errores"] else 0


if __name__ == "__main__":
    # Se importa el módulo por su nombre para que los procesos trabajadores (spawn en Windows)
    # encuentren correr_tarea y Tarea como siembra.experimentos.* y no como __main__.*.
    from siembra.experimentos import main as _main
    sys.exit(_main())
