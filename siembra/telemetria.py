"""Guardar y cargar corridas detalladas, y exportar el JSON precalculado para Unity.

Una corrida detallada vive en `resultados/corridas/<id>/` con estos archivos
- `meta.json`: `version_esquema`, `parametros`, `resumen`, `campo`, `derivados`.
- `pasos.csv`, `mensajes.csv`, `serie.csv`: las tablas del contrato.
- `celdas.npz`: los arreglos de `celdas` (forma `(ancho, alto)`, índice `[x, y]`).
- `unity.json`: telemetría por paso para Unity (ver `exportar_unity`).
- Solo con eventos o en M3 — `eventos.json` (fuego, zonas prohibidas, obstáculos nuevos) y
  `registro.csv` (avisos y decisiones del coordinador). Unity no los usa.

`cargar_corrida(carpeta)` devuelve el mismo dict que `simular(cfg, detalle=True)`.
"""

import hashlib
import json
import math
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from . import VERSION_ESQUEMA

ARCHIVOS = ("meta.json", "pasos.csv", "mensajes.csv", "serie.csv", "celdas.npz", "unity.json")
ARCHIVOS_M3 = ("eventos.json", "registro.csv")   # opcionales (M3 o eventos activos)
COLUMNAS_REGISTRO = ("t", "fuente", "tipo", "evento", "tractor", "texto", "motivo")

COLUMNAS_SERIE = ("t", "surcado_frac", "sembrado_frac", "fila_estacion", "en_servicio",
                  "reservas_activas", "mensajes_acum", "perdidos_acum")
COLUMNAS_PASOS = ("t", "agente", "x", "y", "theta", "estado", "implemento", "intencion",
                  "objetivo_x", "objetivo_y", "tarea_x", "carga", "diesel_frac")
COLUMNAS_MENSAJES = ("t_envio", "t_entrega", "performativa", "emisor", "receptor", "evento",
                     "tipo_tarea", "x", "ronda", "u", "perdido")
_TEXTO_OPCIONAL = {"mensajes.csv": ("evento", "tipo_tarea")}

# Campos de cada mensaje de Unity: el esquema de la propuesta (p. 17) más `implemento`.
CAMPOS_MENSAJE_UNITY = ("version", "t", "agent_id", "pose", "estado", "intencion", "objetivo",
                        "carga", "confianza", "implemento", "checksum")
LLAVES_ARCHIVO_UNITY = ("version_esquema", "semilla", "version_parametros", "mecanismo",
                        "checksum_archivo", "frames")


# ---------------------------------------------------------------------------
# Utilidades de JSON
# ---------------------------------------------------------------------------

def a_json(obj):
    """Convierte tipos de numpy y pandas a tipos nativos de JSON (NaN e infinito pasan a None)."""
    if isinstance(obj, dict):
        return {str(k): a_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [a_json(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [a_json(v) for v in obj.tolist()]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if obj is pd.NA or obj is pd.NaT:
        return None
    return obj


def json_canonico(obj):
    """JSON canónico que se firma: llaves ordenadas, sin espacios, UTF-8 sin escapar."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def checksum_mensaje(mensaje):
    """Primeros 16 hex del sha256 del JSON canónico del mensaje sin el campo `checksum`."""
    sin = {k: v for k, v in mensaje.items() if k != "checksum"}
    return _sha256(json_canonico(sin))[:16]


# ---------------------------------------------------------------------------
# Guardar y cargar
# ---------------------------------------------------------------------------

def guardar_corrida(res, carpeta, unity=True, cada_unity=1):
    """Guarda una corrida (salida de `simular`) en `carpeta` con los archivos del contrato.

    `pasos.csv`, `mensajes.csv` y `unity.json` solo se escriben si la corrida trae `pasos`
    y `mensajes` (es decir, si se simuló con `detalle=True`). Devuelve la ruta de la carpeta.
    """
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    meta = {
        "version_esquema": VERSION_ESQUEMA,
        "parametros": res["parametros"],
        "resumen": res["resumen"],
        "campo": res["campo"],
        "derivados": res["derivados"],
    }
    with open(carpeta / "meta.json", "w", encoding="utf-8") as f:
        json.dump(a_json(meta), f, ensure_ascii=False, indent=2, allow_nan=False)

    escritos = {"meta.json", "serie.csv", "celdas.npz"}
    pd.DataFrame(res["serie"]).to_csv(carpeta / "serie.csv", index=False)
    np.savez_compressed(carpeta / "celdas.npz", **{k: np.asarray(v) for k, v in res["celdas"].items()})
    for llave, archivo in (("pasos", "pasos.csv"), ("mensajes", "mensajes.csv")):
        tabla = res.get(llave)
        if tabla is not None:
            tabla = pd.DataFrame(tabla)
            if tabla.columns.empty:
                columnas = COLUMNAS_PASOS if llave == "pasos" else COLUMNAS_MENSAJES
                tabla = pd.DataFrame(columns=list(columnas))
            tabla.to_csv(carpeta / archivo, index=False)
            escritos.add(archivo)
    if unity and res.get("pasos") is not None:
        exportar_unity(res, carpeta / "unity.json", cada=cada_unity)
        escritos.add("unity.json")
    if res.get("eventos") is not None:
        with open(carpeta / "eventos.json", "w", encoding="utf-8") as f:
            json.dump(a_json(res["eventos"]), f, ensure_ascii=False, allow_nan=False)
        escritos.add("eventos.json")
    if res.get("registro") is not None:
        pd.DataFrame(res["registro"], columns=list(COLUMNAS_REGISTRO)).to_csv(carpeta / "registro.csv", index=False)
        escritos.add("registro.csv")
    # Archivos de una corrida anterior en la misma carpeta que esta corrida no reemplazó.
    for archivo in ARCHIVOS + ARCHIVOS_M3:
        if archivo not in escritos and (carpeta / archivo).exists():
            (carpeta / archivo).unlink()
    return carpeta


def _leer_csv(ruta, columnas):
    try:
        df = pd.read_csv(ruta)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=list(columnas))
    for c in _TEXTO_OPCIONAL.get(ruta.name, ()):
        if c in df.columns:
            # Un texto vacío se escribe como "" y pandas lo lee como NaN; se restaura.
            df[c] = df[c].fillna("").astype(str)
    return df


def cargar_corrida(carpeta):
    """Carga una corrida guardada con `guardar_corrida`.

    Devuelve el mismo dict que `simular(cfg, detalle=True)`: `resumen`, `parametros`,
    `derivados`, `campo`, `serie`, `celdas` y, si existen, `pasos` y `mensajes`. Los valores
    nulos del resumen vuelven como NaN; las tuplas vuelven como listas.
    """
    carpeta = Path(carpeta)
    with open(carpeta / "meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    if meta.get("version_esquema") != VERSION_ESQUEMA:
        warnings.warn(f"{carpeta}: version_esquema {meta.get('version_esquema')!r} distinta de "
                      f"la actual {VERSION_ESQUEMA!r}", stacklevel=2)
    res = {
        "resumen": {k: (np.nan if v is None else v) for k, v in meta["resumen"].items()},
        "parametros": meta["parametros"],
        "derivados": meta["derivados"],
        "campo": meta["campo"],
        "serie": _leer_csv(carpeta / "serie.csv", COLUMNAS_SERIE),
    }
    with np.load(carpeta / "celdas.npz") as z:
        res["celdas"] = {k: z[k] for k in z.files}
    for llave, archivo, columnas in (("pasos", "pasos.csv", COLUMNAS_PASOS),
                                     ("mensajes", "mensajes.csv", COLUMNAS_MENSAJES)):
        if (carpeta / archivo).exists():
            res[llave] = _leer_csv(carpeta / archivo, columnas)
    if (carpeta / "eventos.json").exists():
        with open(carpeta / "eventos.json", encoding="utf-8") as f:
            ev = json.load(f)
        for k in ("t_quemado", "t_fin_fuego"):
            if ev.get(k) is not None:
                ev[k] = np.asarray(ev[k], dtype=np.int32)
        res["eventos"] = ev
    if (carpeta / "registro.csv").exists():
        reg = _leer_csv(carpeta / "registro.csv", COLUMNAS_REGISTRO)
        for c in ("fuente", "tipo", "evento", "tractor", "texto", "motivo"):
            if c in reg.columns:
                reg[c] = reg[c].fillna("").astype(str)
        res["registro"] = reg
    return res


# ---------------------------------------------------------------------------
# Unity
# ---------------------------------------------------------------------------

def _numero(v, decimales=4):
    f = float(v)
    if not math.isfinite(f):
        return -1.0
    return int(f) if f.is_integer() else round(f, decimales)


def _mensaje_unity(t, agente, x, y, theta, estado, intencion, ox, oy, carga, implemento):
    ox, oy = int(ox), int(oy)
    sin_objetivo = ox < 0 or oy < 0
    carga = float(carga)
    mensaje = {
        "version": VERSION_ESQUEMA,
        "t": int(t),
        "agent_id": str(agente),
        "pose": {"x": int(x), "y": int(y), "theta": _numero(theta, 2)},
        "estado": str(estado),
        "intencion": str(intencion),
        # Sin objetivo: (-1, -1), igual que en pasos.csv. No se usa null porque JsonUtility de
        # Unity no lo distingue de (0, 0).
        "objetivo": {"x": -1 if sin_objetivo else ox, "y": -1 if sin_objetivo else oy},
        # Surcador (sin tolva, carga NaN en pasos.csv): -1.
        "carga": round(carga, 4) if math.isfinite(carga) else -1.0,
        "confianza": 1.0,
        "implemento": str(implemento),
    }
    mensaje["checksum"] = checksum_mensaje(mensaje)
    return mensaje


def _plano(arreglo):
    """Arreglo (ancho, alto) con índice [x, y] -> lista plana con índice y * ancho + x."""
    return [int(v) for v in np.asarray(arreglo).T.reshape(-1)]


def _escena(res):
    campo, celdas = res["campo"], res["celdas"]
    deposito = list(campo.get("deposito", [0, 0]))
    obstaculos = []
    for ob in campo.get("obstaculos", []) or []:
        ob = list(ob) + [None] * (5 - len(ob))
        obstaculos.append({"x": int(ob[0]), "y": int(ob[1]), "ancho": int(ob[2] or 1),
                           "alto": int(ob[3] or 1), "tipo": a_json(ob[4]) if ob[4] is not None else ""})
    escena = {
        "ancho": int(campo["ancho"]), "alto": int(campo["alto"]),
        "y0": int(campo["y0"]), "y1": int(campo["y1"]), "celda_m": _numero(campo["celda_m"]),
        "deposito": {"x": int(deposito[0]), "y": int(deposito[1])},
        "obstaculos": obstaculos,
        "orden_celdas": "y*ancho+x",
    }
    for nombre in ("tipo_base", "t_surcado", "t_sembrado"):
        if nombre in celdas:
            escena[nombre] = _plano(celdas[nombre])
    return escena


def exportar_unity(res, ruta, cada=1):
    """Escribe el JSON precalculado que reproduce Unity y devuelve su ruta.

    Estructura del archivo::

        {"version_esquema", "semilla", "version_parametros", "mecanismo",
         "checksum_archivo", "checksum_escena", "escena", "frames": [
            {"t": 0, "mensajes": [ {mensaje de T1}, {mensaje de T2}, ... ]}, ...]}

    Cada mensaje sigue el esquema de la propuesta (p. 17) más `implemento`:
    `version, t, agent_id, pose{x,y,theta}, estado, intencion, objetivo{x,y}, carga,
    confianza (1.0), implemento, checksum`. Sin objetivo: `{"x": -1, "y": -1}`; surcador
    (sin tolva): `carga = -1`.

    - `checksum` de cada mensaje: 16 hex del sha256 del JSON canónico del mensaje sin ese campo.
    - `checksum_archivo`: sha256 completo del JSON canónico de `frames`.
    - `escena` (agregado al esquema; Unity lo necesita para armar el terreno): tamaño del grid,
      depósito, obstáculos y los arreglos `tipo_base`, `t_surcado`, `t_sembrado` aplanados con
      índice `y*ancho+x` (JsonUtility no lee arreglos anidados). `checksum_escena` es el sha256
      de su JSON canónico.
    JSON canónico: `sort_keys=True, separators=(",", ":"), ensure_ascii=False`, en UTF-8.

    `cada`: exporta uno de cada `cada` pasos (siempre incluye el último).
    """
    pasos = res.get("pasos")
    if pasos is None:
        raise ValueError("exportar_unity necesita una corrida simulada con detalle=True (falta 'pasos')")
    cada = max(1, int(cada))
    pasos = pd.DataFrame(pasos).sort_values(["t", "agente"], kind="stable")
    tiempos = np.sort(pasos["t"].unique())
    if cada > 1 and len(tiempos):
        elegidos = set(tiempos[::cada].tolist()) | {tiempos[-1]}
        pasos = pasos[pasos["t"].isin(elegidos)]
    columnas = ("t", "agente", "x", "y", "theta", "estado", "intencion", "objetivo_x", "objetivo_y",
                "carga", "implemento")
    frames = []
    for valores in zip(*(pasos[c].tolist() for c in columnas)):
        mensaje = _mensaje_unity(*valores)
        if not frames or frames[-1]["t"] != mensaje["t"]:
            frames.append({"t": mensaje["t"], "mensajes": []})
        frames[-1]["mensajes"].append(mensaje)

    parametros, resumen = res.get("parametros", {}), res.get("resumen", {})
    escena = _escena(res)
    doc = {
        "version_esquema": VERSION_ESQUEMA,
        "semilla": a_json(parametros.get("semilla", resumen.get("semilla"))),
        "version_parametros": parametros.get("version_parametros", ""),
        "mecanismo": parametros.get("mecanismo", resumen.get("mecanismo", "")),
        "checksum_archivo": _sha256(json_canonico(frames)),
        "checksum_escena": _sha256(json_canonico(escena)),
        "escena": escena,
        "frames": frames,
    }
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return ruta


def validar_unity(ruta, max_errores=50):
    """Hace la misma validación que Unity al cargar el archivo.

    Revisa que estén las llaves del archivo, que `version_esquema` y la `version` de cada
    mensaje coincidan con la versión actual, que cada mensaje tenga todos sus campos y su
    checksum correcto, y que `checksum_archivo` (y `checksum_escena`, si hay escena) coincidan.
    Devuelve `(valido, errores)`; la lista se corta en `max_errores` con una línea de resumen.
    """
    errores = []
    try:
        with open(ruta, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        return False, [f"No se pudo leer {ruta}: {e}"]
    if not isinstance(doc, dict):
        return False, ["El archivo no es un objeto JSON"]
    faltan = [k for k in LLAVES_ARCHIVO_UNITY if k not in doc]
    if faltan:
        return False, [f"Faltan llaves del archivo: {', '.join(faltan)}"]
    if doc["version_esquema"] != VERSION_ESQUEMA:
        errores.append(f"version_esquema {doc['version_esquema']!r} no coincide con {VERSION_ESQUEMA!r}")
    frames = doc["frames"]
    if not isinstance(frames, list):
        return False, errores + ["'frames' no es una lista"]
    if _sha256(json_canonico(frames)) != doc["checksum_archivo"]:
        errores.append("checksum_archivo no coincide con el contenido de 'frames'")
    if "escena" in doc and _sha256(json_canonico(doc["escena"])) != doc.get("checksum_escena"):
        errores.append("checksum_escena no coincide con el contenido de 'escena'")

    def agregar(texto):
        errores.append(texto)

    for i, frame in enumerate(frames):
        if not isinstance(frame, dict) or not isinstance(frame.get("mensajes"), list):
            agregar(f"frame {i}: falta la lista 'mensajes'")
            continue
        for m in frame["mensajes"]:
            donde = f"frame t={frame.get('t')}, agente {m.get('agent_id', '?')}"
            faltan = [c for c in CAMPOS_MENSAJE_UNITY if c not in m]
            if faltan:
                agregar(f"{donde}: faltan campos {', '.join(faltan)}")
            if m.get("version") != VERSION_ESQUEMA:
                agregar(f"{donde}: version {m.get('version')!r} no coincide con {VERSION_ESQUEMA!r}")
            if m.get("t") != frame.get("t"):
                agregar(f"{donde}: t del mensaje ({m.get('t')}) distinto del t del frame")
            if checksum_mensaje(m) != m.get("checksum"):
                agregar(f"{donde}: checksum no coincide")
    if len(errores) > max_errores:
        extra = len(errores) - max_errores
        errores = errores[:max_errores] + [f"... y {extra} errores más"]
    return not errores, errores


# ---------------------------------------------------------------------------
# Corrida sintética (para pruebas)
# ---------------------------------------------------------------------------

def corrida_sintetica(cfg=None, detalle=False):
    """Corrida falsa con la forma exacta del contrato, sin simular nada real.

    Misma firma que `siembra.modelo.simular`. Los surcadores recorren franjas de columnas en
    zigzag a una celda por paso y las sembradoras van detrás respetando la precedencia y
    recargando cada tolva. Sirve para probar telemetría, experimentos y gráficas sin el
    modelo (`--simulador siembra.telemetria:corrida_sintetica`). Sus números no significan nada.
    """
    from . import metricas
    from .config import cargar_config, derivados, lado_campo

    inicio = time.perf_counter()
    cfg = cargar_config() if cfg is None else cfg
    der = derivados(cfg)
    rng = np.random.default_rng(int(cfg.get("semilla", 0) or 0))
    mecanismo = cfg["mecanismo"]
    com = cfg["comunicacion"]

    ancho = lado_campo(cfg)
    alto = ancho + 3
    y0, y1 = 2, ancho + 1
    n = int(cfg["flota"]["n_tractores"])
    n_surc = 1 if n == 1 else int(cfg["flota"].get("n_surcadores") or max(1, n // 2))
    n_siem = 1 if n == 1 else n - n_surc
    dx = cfg["campo"].get("deposito_x")
    deposito = (ancho // 2 if dx is None else int(dx), 0)

    tipo = np.full((ancho, alto), 2, dtype=np.int8)
    tipo[:, 0], tipo[:, 1], tipo[:, alto - 1] = 0, 1, 1
    t_surc = np.full((ancho, alto), -1, dtype=np.int32)
    t_siem = np.full((ancho, alto), -1, dtype=np.int32)
    pasadas = np.zeros((ancho, alto), dtype=np.int32)

    def zigzag(columnas):
        celdas = []
        for k, x in enumerate(columnas):
            ys = range(y0, y1 + 1) if k % 2 == 0 else range(y1, y0 - 1, -1)
            celdas.extend((int(x), y) for y in ys)
        return celdas

    nombres = [f"T{i + 1}" for i in range(n)]
    eventos = {a: [] for a in nombres}  # agente -> [(t, x, y, estado, implemento, intencion, carga, tarea_x)]
    hileras = {a: 0 for a in nombres}
    llegada = max(1, abs(deposito[0] - ancho // 2) + 2)
    viaje = ancho // 2 + 2
    tolva = der["tolva_celdas"]
    recargas = 0
    pasos_recarga = der["pasos_recarga_semilla"]

    # Surcado
    fin_surc = 0
    for i, cols in enumerate(np.array_split(np.arange(ancho), n_surc)):
        agente = nombres[i]
        reloj = llegada + int(rng.integers(0, 3))
        for x, y in zigzag(cols):
            t_surc[x, y] = reloj
            pasadas[x, y] += 1
            eventos[agente].append((reloj, x, y, "trabajando", "surcador", "surcar", np.nan, x))
            reloj += 1
        hileras[agente] += len(cols)
        fin_surc = max(fin_surc, reloj)

    # Siembra
    sembradoras = nombres[n_surc:] if n > 1 else nombres[:1]
    for i, cols in enumerate(np.array_split(np.arange(ancho), n_siem)):
        agente = sembradoras[i]
        if n == 1:
            reloj = fin_surc + der["pasos_cambio"]
        else:
            reloj = llegada + 2 * alto + int(rng.integers(0, alto))
        restante = tolva
        for x, y in zigzag(cols):
            if restante == 0:
                for k in range(pasos_recarga + 2 * viaje):
                    eventos[agente].append((reloj + k, deposito[0], deposito[1], "recargando",
                                            "sembradora", "recargar", 0.0, -1))
                reloj += pasos_recarga + 2 * viaje
                restante, recargas = tolva, recargas + 1
            reloj = max(reloj, int(t_surc[x, y]) + 1)
            t_siem[x, y] = reloj
            pasadas[x, y] += 1
            restante -= 1
            eventos[agente].append((reloj, x, y, "trabajando", "sembradora", "sembrar",
                                    restante / tolva, x))
            reloj += 1
        hileras[agente] += len(cols)

    trabajo_mask = tipo == 2
    n_celdas = int(trabajo_mask.sum())
    sembradas = t_siem[t_siem >= 0].astype(np.int64)
    surcadas = t_surc[t_surc >= 0].astype(np.int64)
    T = int(sembradas.max()) if len(sembradas) else 0
    paso_h = der["paso_h"]

    # Mensajes (Contract Net simplificado): una subasta por hilera y tipo de tarea.
    filas_msg = []
    if mecanismo != "M0":
        ronda = 0
        for tipo_tarea, tiempos, postores in (("surcar", t_surc, nombres[:n_surc]),
                                               ("sembrar", t_siem, sembradoras)):
            for x in range(ancho):
                col = tiempos[x][tiempos[x] >= 0]
                if not len(col):
                    continue
                t0 = max(0, int(col.min()) - 3)
                ganador = postores[x * len(postores) // ancho]

                def msg(perf, emisor, receptor, t_envio, evento="", u=np.nan):
                    perdido = bool(rng.random() < com["perdida_mensajes"])
                    filas_msg.append((t_envio, t_envio + int(rng.integers(0, com["retraso_max"] + 1)),
                                      perf, emisor, receptor, evento, tipo_tarea, x, ronda, u, perdido))

                for p in postores:
                    msg("cfp", "DEP", p, t0)
                    msg("propose", p, "DEP", t0 + 1, u=float(com["valor_hilera"] - rng.integers(0, 200)))
                    msg("accept-proposal" if p == ganador else "reject-proposal", "DEP", p, t0 + 2)
                msg("inform", ganador, "DEP", t0 + 3, evento="inicio")
                msg("inform", ganador, "DEP", int(col.max()), evento="fin")
                ronda += 1
    mensajes = pd.DataFrame(filas_msg, columns=list(COLUMNAS_MENSAJES))
    mensajes = mensajes.sort_values("t_envio", kind="stable").reset_index(drop=True)

    # Serie
    paso_serie = 1 if detalle else 10
    ts = np.arange(0, T + 1, paso_serie)
    if ts[-1] != T:
        ts = np.append(ts, T)
    orden_s, orden_m = np.sort(surcadas), np.sort(sembradas)
    envios = np.sort(mensajes["t_envio"].to_numpy())
    envios_perdidos = np.sort(mensajes.loc[mensajes["perdido"], "t_envio"].to_numpy())
    serie = pd.DataFrame({
        "t": ts,
        "surcado_frac": np.searchsorted(orden_s, ts, side="right") / n_celdas,
        "sembrado_frac": np.searchsorted(orden_m, ts, side="right") / n_celdas,
        "fila_estacion": np.zeros(len(ts), dtype=int),
        "en_servicio": np.zeros(len(ts), dtype=int),
        "reservas_activas": np.full(len(ts), n * com["ventana_reservas"] if mecanismo == "M2" else 0),
        "mensajes_acum": np.searchsorted(envios, ts, side="right"),
        "perdidos_acum": np.searchsorted(envios_perdidos, ts, side="right"),
    })

    # Pasos (solo con detalle): posición de cada tractor en cada paso a partir de sus eventos.
    pasos = None
    if detalle:
        partes = []
        todos_t = np.arange(0, T + 1)
        for agente in nombres:
            ev = sorted(eventos[agente], key=lambda e: e[0])
            t_ev = np.array([e[0] for e in ev])
            idx = np.searchsorted(t_ev, todos_t, side="right") - 1
            filas = []
            for t, j in zip(todos_t, idx):
                if j < 0:
                    e = ev[0]
                    filas.append((t, agente, deposito[0], deposito[1], 90, "en_ruta", e[4], e[5],
                                  e[1], e[2], e[7], e[6], 1.0))
                    continue
                e = ev[j]
                if e[0] == t:
                    estado, intencion = e[3], e[5]
                elif j == len(ev) - 1:
                    estado, intencion = "terminado", "ninguna"
                else:
                    estado, intencion = ("esperando_surco", "esperar") if e[4] == "sembradora" else ("en_ruta", e[5])
                theta = 90 if (e[1] % 2 == 0) else 270
                diesel = max(0.0, 1.0 - t * der["diesel_paso_l"] / cfg["agente"]["tanque_l"] % 1.0)
                filas.append((t, agente, e[1], e[2], theta, estado, e[4], intencion, e[1],
                              min(e[2] + 1, y1), e[7], e[6], diesel))
            partes.append(pd.DataFrame(filas, columns=list(COLUMNAS_PASOS)))
        pasos = pd.concat(partes, ignore_index=True).sort_values(["t", "agente"], kind="stable")
        pasos = pasos.reset_index(drop=True)
        pasos["carga"] = pasos["carga"].astype(float)

    # Resumen
    pasos_dia = der["pasos_dia"]
    pasos_trabajo = len(surcadas) + len(sembradas)
    recarga_pasos = recargas * (pasos_recarga + 2 * viaje)
    traslado_pasos = n * 2 * llegada + recargas * 2 * viaje
    activos = n * (T + 1)
    espera_pasos = max(0, activos - pasos_trabajo - traslado_pasos - recargas * pasos_recarga)
    conteo = mensajes["performativa"].value_counts()
    hs = [hileras[a] for a in nombres]
    roles = [hs[:n_surc], [hileras[a] for a in sembradoras]] if n > 1 else [hs]
    balance = max(max(r) - min(r) for r in roles)
    q = np.percentile(sembradas, np.arange(0, 101, 5)) if len(sembradas) else np.full(21, np.nan)
    D = pasos_trabajo + traslado_pasos
    resumen = {
        "mecanismo": mecanismo, "hectareas": cfg["campo"]["hectareas"],
        "ha_sembrables": n_celdas * der["celda_ha"], "ancho": ancho, "n_tractores": n,
        "n_surcadores": n_surc, "semilla": cfg.get("semilla", 0),
        "n_obstaculos": cfg["campo"].get("n_obstaculos", 0),
        "perdida_mensajes": com["perdida_mensajes"], "timeout_ofertas": com["timeout_ofertas"],
        "ventana_reservas": com["ventana_reservas"], "margen_recarga_hileras": com["margen_recarga_hileras"],
        "tolva_ha": cfg["agente"]["tolva_ha"], "falla_activa": bool(cfg["falla"]["activa"]),
        "jornada_h": cfg["escala_tiempo"]["jornada_h"],
        "dias_laborables": cfg["escala_tiempo"]["dias_laborables"], "celda_m": cfg["campo"]["celda_m"],
        "paso_s": der["paso_s"], "pasos_dia": pasos_dia,
        "T_pasos": T, "T_h": T * paso_h, "T_dias": T / pasos_dia, "pasos_simulados": T + 1,
        "estancado": False,
        "D_celdas": D, "D_por_agente": D / n, "colisiones": 0, "intercambios": 0,
        "vetos": int(rng.integers(0, 5)),
        "trabajo_h": pasos_trabajo * paso_h, "traslado_h": traslado_pasos * paso_h,
        "W_ocio_h": espera_pasos * 0.3 * paso_h, "W_negociacion_h": len(mensajes) * 0.01 * paso_h,
        "W_espera_h": 0.0, "W_servicio_h": recargas * pasos_recarga * paso_h,
        "W_conflicto_h": 0.0, "W_precedencia_h": espera_pasos * 0.7 * paso_h, "fuera_servicio_h": 0.0,
        "H_motor_h": (pasos_trabajo + traslado_pasos) * paso_h,
        "diesel_l": (pasos_trabajo + traslado_pasos) * der["diesel_paso_l"], "recargas": recargas,
        "n_celdas_trabajo": n_celdas, "n_surcadas": len(surcadas), "n_sembradas": len(sembradas),
        "n_no_sembradas": n_celdas - len(sembradas), "cobertura": len(sembradas) / n_celdas,
        "suma_t_siembra_pasos": int(sembradas.sum()),
        "t_primera_siembra": int(sembradas.min()) if len(sembradas) else -1,
        "t_ultima_siembra": T,
        "dispersion_dias": (T - int(sembradas.min())) / pasos_dia if len(sembradas) else 0.0,
        **{c: float(v) for c, v in zip(metricas.CUANTILES, q)},
        "mensajes_total": len(mensajes), "mensajes_perdidos": int(mensajes["perdido"].sum()),
        "msg_cfp": int(conteo.get("cfp", 0)), "msg_propose": int(conteo.get("propose", 0)),
        "msg_accept": int(conteo.get("accept-proposal", 0)),
        "msg_reject": int(conteo.get("reject-proposal", 0)),
        "msg_inform": int(conteo.get("inform", 0)),
        "subastas": int(mensajes["ronda"].nunique()) if len(mensajes) else 0,
        "reanuncios": 0, "ofertas_tardias": 0,
        "hileras_max": max(hs), "hileras_min": min(hs), "balance_carga": balance,
        "eficiencia_campo": pasos_trabajo / max(1, activos - recarga_pasos),
        "celdas_inaccesibles": 0, "t_falla": -1, "tractor_fallado": "",
    }
    resumen["tiempo_computo_s"] = time.perf_counter() - inicio
    resumen.update(metricas.costos(resumen, cfg))

    res = {
        "resumen": resumen,
        "parametros": cfg,
        "derivados": der,
        "campo": {"ancho": ancho, "alto": alto, "y0": y0, "y1": y1, "deposito": list(deposito),
                  "obstaculos": [], "celda_m": cfg["campo"]["celda_m"]},
        "serie": serie,
        "celdas": {"tipo_base": tipo, "t_surcado": t_surc, "t_sembrado": t_siem, "pasadas": pasadas},
    }
    if detalle:
        res["pasos"] = pasos
        res["mensajes"] = mensajes
    return res
