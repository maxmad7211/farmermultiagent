"""Función de costo J, costo por hectárea, estadística entre semillas y sensibilidad económica.

Todo se calcula con el resumen de cada corrida y los parámetros, sin volver a simular,
para poder repetir el análisis con otros precios, otra jornada u otros días laborables.
Las fórmulas son las de la sección "Función de costo" de `docs/contrato_datos.md`.
"""

import math
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from .config import aplicar, derivados

# Cuantiles del paso de siembra que trae el resumen: q00, q05, ..., q100.
CUANTILES = tuple(f"q{p:02d}" for p in range(0, 101, 5))
PROB_CUANTILES = np.linspace(0.0, 1.0, len(CUANTILES))

# Llaves que agrega `costos` al resumen (en este orden).
LLAVES_COSTO = (
    "R_ha_dia", "costo_R", "costo_H", "costo_colisiones", "costo_diesel", "costo_no_sembrada",
    "J", "costo_propiedad", "costo_ha", "pct_en_ventana", "T_dias_calendario",
)

# Todas las llaves del resumen según el contrato (sección "resumen").
LLAVES_RESUMEN = (
    # Identificación
    "mecanismo", "hectareas", "ha_sembrables", "ancho", "n_tractores", "n_surcadores", "semilla",
    "n_obstaculos", "perdida_mensajes", "timeout_ofertas", "ventana_reservas",
    "margen_recarga_hileras", "tolva_ha", "falla_activa", "jornada_h", "dias_laborables", "celda_m",
    # Escala
    "paso_s", "pasos_dia",
    # Tiempo
    "T_pasos", "T_h", "T_dias", "pasos_simulados", "estancado",
    # Distancia y seguridad
    "D_celdas", "D_por_agente", "colisiones", "intercambios", "vetos",
    # Tiempos por estado (horas-tractor)
    "trabajo_h", "traslado_h", "W_ocio_h", "W_negociacion_h", "W_espera_h", "W_servicio_h",
    "W_conflicto_h", "W_precedencia_h", "fuera_servicio_h",
    # Motor
    "H_motor_h", "diesel_l", "recargas",
    # Cobertura
    "n_celdas_trabajo", "n_surcadas", "n_sembradas", "n_no_sembradas", "cobertura",
    "suma_t_siembra_pasos", "t_primera_siembra", "t_ultima_siembra", "dispersion_dias",
    *CUANTILES,
    # Comunicación
    "mensajes_total", "mensajes_perdidos", "msg_cfp", "msg_propose", "msg_accept", "msg_reject",
    "msg_inform", "subastas", "reanuncios", "ofertas_tardias",
    # Carga y eficiencia
    "hileras_max", "hileras_min", "balance_carga", "eficiencia_campo", "tiempo_computo_s",
    # Falla de un tractor
    "celdas_inaccesibles", "t_falla", "tractor_fallado",
    # Costos
    *LLAVES_COSTO,
)

# Rangos de la sensibilidad económica (propuesta, p. 18-19): ruta en notación de puntos -> (bajo, alto).
# La capacidad de tolva no está aquí: cambia la simulación y se cubre con el escenario tolva_mitad_20ha_4t.
RANGOS_SENSIBILIDAD = {
    "economia.precio_tractor": (750_000, 840_000),
    "escala_tiempo.dias_laborables": (0.6, 1.0),
    "escala_tiempo.jornada_h": (8, 14),
    "economia.precio_maiz": (5_200, 7_200),
    "agronomia.perdida_dia": (0.002, 0.006),
    "agronomia.ventana_dias": (20, 40),  # solo cambia pct_en_ventana, no costo_ha
    "economia.temporadas_vida": (15, 25),
}

NIVEL_CONFIANZA = 0.95


# ---------------------------------------------------------------------------
# Función de costo
# ---------------------------------------------------------------------------

def _valor(fuente, clave, defecto=np.nan):
    """Lee `clave` como número de un dict, una Series (fila de CSV) o un DataFrame (columna)."""
    if isinstance(fuente, pd.DataFrame):
        if clave in fuente.columns:
            return pd.to_numeric(fuente[clave], errors="coerce").to_numpy(dtype=float)
        return np.full(len(fuente), defecto, dtype=float)
    try:
        v = fuente[clave]
    except (KeyError, IndexError, TypeError):
        return defecto
    if v is None:
        return defecto
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def _cdf_cuantiles(q, t):
    """Fracción de las celdas sembradas con paso de siembra <= t, interpolando los 21 cuantiles."""
    q = np.asarray(q, dtype=float)
    if not np.isfinite(t) or np.isnan(q).any():
        return np.nan
    # Si varios cuantiles empatan (muchas celdas sembradas en el mismo paso), la CDF en ese
    # valor es la probabilidad más alta del empate.
    valores, inverso = np.unique(q, return_inverse=True)
    prob = np.zeros(len(valores))
    np.maximum.at(prob, inverso, PROB_CUANTILES)
    return float(np.interp(t, valores, prob, left=0.0, right=1.0))


def _pct_en_ventana(fuente, t_ventana, frac_sembrada):
    if isinstance(fuente, pd.DataFrame):
        q = np.column_stack([_valor(fuente, c) for c in CUANTILES]) if len(fuente) else np.empty((0, 21))
        t_v = np.broadcast_to(np.asarray(t_ventana, dtype=float), (len(fuente),))
        cdf = np.array([_cdf_cuantiles(q[i], t_v[i]) for i in range(len(fuente))], dtype=float)
    else:
        cdf = _cdf_cuantiles([_valor(fuente, c) for c in CUANTILES], float(t_ventana))
    pct = frac_sembrada * cdf
    # Si no se sembró nada, el porcentaje es 0 aunque los cuantiles vengan vacíos (NaN).
    return np.where(frac_sembrada == 0, 0.0, pct)


def _calcular(fuente, cfg):
    """Núcleo de la función de costo. Acepta un resumen (dict o Series) o un DataFrame de resúmenes.

    Con un DataFrame cada llave devuelve un arreglo (una entrada por fila); con un dict, escalares.
    """
    eco, agr, esc = cfg["economia"], cfg["agronomia"], cfg["escala_tiempo"]

    def v(clave, defecto=np.nan):
        return _valor(fuente, clave, defecto)

    celda_m = v("celda_m", cfg["campo"]["celda_m"])
    celda_ha = celda_m ** 2 / 10_000
    # pasos_dia se recalcula con la jornada del cfg y el paso_s del resumen: así la sensibilidad
    # a la jornada y a los días laborables no necesita volver a simular.
    paso_s = v("paso_s", derivados(cfg)["paso_s"])
    pasos_dia = esc["jornada_h"] * 3600 / paso_s
    pasos_por_dia_calendario = pasos_dia * esc["dias_laborables"]  # dias(t) = t / esto

    rendimiento, precio_maiz = eco["rendimiento_t_ha"], eco["precio_maiz"]

    R_ha_dia = celda_ha * v("suma_t_siembra_pasos") / pasos_por_dia_calendario
    costo_R = rendimiento * agr["perdida_dia"] * precio_maiz * R_ha_dia
    costo_H = eco["precio_tractor"] * eco["reparacion_frac"] / eco["vida_h"] * v("H_motor_h")
    costo_colisiones = eco["penaliza_colision"] * v("colisiones")
    costo_diesel = eco["precio_diesel"] * v("diesel_l")
    costo_no_sembrada = (v("n_no_sembradas") * celda_ha * rendimiento * precio_maiz
                         * eco["perdida_no_sembrada_frac"])
    # El término 0·W_ocio se omite a propósito: su peso es 0 (se reporta, no se cobra) y así un
    # W_ocio_h faltante no vuelve NaN a J.
    J = costo_R + costo_H + costo_colisiones + costo_diesel + costo_no_sembrada

    costo_propiedad = v("n_tractores") * eco["precio_tractor"] / eco["temporadas_vida"]
    ha_sembrables = v("ha_sembrables")
    ha_sembrables = np.where(np.isnan(ha_sembrables), v("n_celdas_trabajo") * celda_ha, ha_sembrables)
    with np.errstate(divide="ignore", invalid="ignore"):
        costo_ha = (costo_propiedad + J) / ha_sembrables
        frac_sembrada = v("n_sembradas") / v("n_celdas_trabajo")

    t_ventana = agr["ventana_dias"] * pasos_por_dia_calendario
    pct_en_ventana = _pct_en_ventana(fuente, t_ventana, frac_sembrada)
    T_dias_calendario = v("T_pasos") / pasos_por_dia_calendario

    return {
        "R_ha_dia": R_ha_dia, "costo_R": costo_R, "costo_H": costo_H,
        "costo_colisiones": costo_colisiones, "costo_diesel": costo_diesel,
        "costo_no_sembrada": costo_no_sembrada, "J": J, "costo_propiedad": costo_propiedad,
        "costo_ha": costo_ha, "pct_en_ventana": pct_en_ventana, "T_dias_calendario": T_dias_calendario,
    }


def costos(resumen, cfg):
    """Costos de una corrida a partir de su resumen y de los parámetros.

    `resumen` puede ser el dict de `simular` o una fila de CSV (Series con valores numpy).
    Los parámetros económicos, `jornada_h` y `dias_laborables` salen de `cfg`; `paso_s`,
    `celda_m` y los conteos salen del resumen. Devuelve un dict con las llaves de
    `LLAVES_COSTO` (todas float).
    """
    if isinstance(resumen, pd.DataFrame):
        raise TypeError("costos recibe un solo resumen; para un DataFrame usa agregar_costos")
    r = _calcular(resumen, cfg)
    return {k: float(r[k]) for k in LLAVES_COSTO}


def agregar_costos(df, cfg, escala_de_fila=False):
    """Recalcula las columnas de costo de cada fila de un DataFrame de resúmenes.

    Devuelve una copia de `df` con las columnas de `LLAVES_COSTO` reemplazadas (o agregadas).
    Por defecto todas las filas usan los parámetros de `cfg`, igual que `costos`.
    Con `escala_de_fila=True`, cada fila usa su propia `jornada_h` y sus `dias_laborables`
    (las columnas del resumen) y solo los precios salen de `cfg`; úsalo con tablas que mezclan
    escenarios con distinta escala de tiempo, como `escenarios.csv` (escenario de lluvia).
    """
    salida = df.copy()
    if len(df) == 0:
        for k in LLAVES_COSTO:
            salida[k] = pd.Series(dtype=float)
        return salida
    columnas_escala = ["jornada_h", "dias_laborables"]
    if escala_de_fila and set(columnas_escala) <= set(df.columns):
        resultado = {k: np.full(len(df), np.nan) for k in LLAVES_COSTO}
        for (jornada, dias), idx in df.groupby(columnas_escala, dropna=False).indices.items():
            cambios = {}
            if pd.notna(jornada):
                cambios["escala_tiempo.jornada_h"] = float(jornada)
            if pd.notna(dias):
                cambios["escala_tiempo.dias_laborables"] = float(dias)
            r = _calcular(df.iloc[idx], aplicar(cfg, cambios))
            for k in LLAVES_COSTO:
                resultado[k][idx] = r[k]
    else:
        resultado = _calcular(df, cfg)
    for k in LLAVES_COSTO:
        salida[k] = np.asarray(resultado[k], dtype=float)
    return salida


# ---------------------------------------------------------------------------
# Estadística entre semillas
# ---------------------------------------------------------------------------

def _como_lista(x):
    if x is None:
        return []
    if isinstance(x, str):
        return [x]
    return list(x)


def _estadisticos(x, nivel=NIVEL_CONFIANZA):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    media = float(x.mean()) if n else np.nan
    if n >= 2:
        de = float(x.std(ddof=1))
        ee = de / math.sqrt(n)
        semiancho = float(stats.t.ppf(0.5 + nivel / 2, n - 1)) * ee
    else:
        de = ee = semiancho = np.nan
    return {"n": n, "media": media, "de": de, "ee": ee, "ic95": semiancho,
            "ic_bajo": media - semiancho, "ic_alto": media + semiancho}


ESTADISTICOS = ("n", "media", "de", "ee", "ic95", "ic_bajo", "ic_alto")


def resumen_ic(df, metricas, por=None, formato="largo", nivel=NIVEL_CONFIANZA):
    """Media, desviación estándar, n e intervalo de confianza (t de Student) por grupo.

    - `metricas`: una columna o una lista de columnas.
    - `por`: columna o lista de columnas para agrupar (None = todo el DataFrame).
    - `formato="largo"` (por defecto): una fila por grupo y métrica, con columnas
      `[*por, metrica, n, media, de, ee, ic95, ic_bajo, ic_alto]`. `ic95` es el semiancho
      del intervalo (media ± ic95), `ee` el error estándar.
    - `formato="ancho"`: una fila por grupo y columnas `<metrica>_<estadístico>`, por ejemplo
      `costo_ha_media`, `costo_ha_ic_bajo`.
    Los NaN se ignoran (n cuenta solo valores válidos). Con n < 2, de e IC son NaN.
    """
    if formato not in ("largo", "ancho"):
        raise ValueError("formato debe ser 'largo' o 'ancho'")
    metricas = _como_lista(metricas)
    por = _como_lista(por)
    grupos = df.groupby(por, dropna=False, sort=True) if por else [((), df)]
    largo, ancho = [], []
    for clave, g in grupos:
        clave = clave if isinstance(clave, tuple) else (clave,)
        ident = dict(zip(por, clave))
        fila_ancha = dict(ident)
        for m in metricas:
            valores = pd.to_numeric(g[m], errors="coerce").astype(float).to_numpy()
            est = _estadisticos(valores, nivel)
            largo.append({**ident, "metrica": m, **est})
            fila_ancha.update({f"{m}_{k}": v for k, v in est.items()})
        ancho.append(fila_ancha)
    if formato == "largo":
        return pd.DataFrame(largo, columns=[*por, "metrica", *ESTADISTICOS])
    columnas = [*por, *[f"{m}_{k}" for m in metricas for k in ESTADISTICOS]]
    return pd.DataFrame(ancho, columns=columnas)


def _probar_diferencias(d, nivel=NIVEL_CONFIANZA):
    """Pruebas sobre las diferencias pareadas d = b − a."""
    n = len(d)
    out = {"n": n, "diferencia_media": float(d.mean()) if n else np.nan, "ic_bajo": np.nan,
           "ic_alto": np.nan, "p_t": np.nan, "p_wilcoxon": np.nan, "p_normalidad": np.nan,
           "prueba_sugerida": "", "nota": ""}
    if n < 2:
        out["nota"] = f"n = {n} pares: se necesitan al menos 2 para probar"
        return out
    de = float(d.std(ddof=1))
    semiancho = float(stats.t.ppf(0.5 + nivel / 2, n - 1)) * de / math.sqrt(n)
    out["ic_bajo"] = out["diferencia_media"] - semiancho
    out["ic_alto"] = out["diferencia_media"] + semiancho
    if np.all(d == 0):
        out["nota"] = "todas las diferencias son 0: los dos mecanismos dan el mismo valor en cada semilla"
        return out
    notas = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if de == 0:
            notas.append("diferencias constantes (de = 0): la t pareada no está definida")
        else:
            out["p_t"] = float(stats.ttest_rel(d, np.zeros(n)).pvalue)
        try:
            out["p_wilcoxon"] = float(stats.wilcoxon(d).pvalue)
        except ValueError as e:
            notas.append(f"Wilcoxon no aplica: {e}")
        if n >= 3 and de > 0:
            try:
                out["p_normalidad"] = float(stats.shapiro(d).pvalue)
            except ValueError:
                pass
    if not np.isnan(out["p_normalidad"]):
        out["prueba_sugerida"] = "t pareada" if out["p_normalidad"] >= 0.05 else "Wilcoxon"
    if n < 6:
        notas.append(f"solo {n} pares: Wilcoxon tiene poca potencia")
    out["nota"] = "; ".join(notas)
    return out


def prueba_pareada(df, metrica, a, b, por=None, clave="semilla", col="mecanismo", nivel=NIVEL_CONFIANZA):
    """Compara el valor `b` contra el valor `a` de la columna `col` (por defecto mecanismos),
    emparejando corridas por `clave` (por defecto la semilla) dentro de cada grupo de `por`.

    Devuelve un DataFrame con una fila por grupo y columnas:
    `[*por, metrica, a, b, n, media_a, media_b, diferencia_media (b − a), ic_bajo, ic_alto,
    p_t (t pareada), p_wilcoxon, p_normalidad (Shapiro–Wilk de las diferencias),
    prueba_sugerida, nota]`.
    Si n < 2 o todas las diferencias son 0, los p son NaN y `nota` explica por qué.
    Si una semilla falta en alguno de los dos lados, se descarta y se anota.
    """
    por = _como_lista(por)
    sub = df[df[col].isin([a, b])]
    grupos = sub.groupby(por, dropna=False, sort=True) if por else [((), sub)]
    filas = []
    for llave, g in grupos:
        llave = llave if isinstance(llave, tuple) else (llave,)
        valores = g[[clave, col]].copy()
        valores["_v"] = pd.to_numeric(g[metrica], errors="coerce").astype(float)
        notas = []
        if valores.duplicated([clave, col]).any():
            notas.append(f"{clave} repetida en un mismo {col}: se promediaron")
        tabla = valores.pivot_table(index=clave, columns=col, values="_v", aggfunc="mean")
        for lado in (a, b):
            if lado not in tabla.columns:
                tabla[lado] = np.nan
        completos = tabla[[a, b]].dropna()
        descartados = len(tabla) - len(completos)
        if descartados:
            notas.append(f"{descartados} {clave}(s) sin pareja descartada(s)")
        d = (completos[b] - completos[a]).to_numpy(dtype=float)
        res = _probar_diferencias(d, nivel)
        res["nota"] = "; ".join([x for x in [res["nota"], *notas] if x])
        filas.append({**dict(zip(por, llave)), "metrica": metrica, "a": a, "b": b,
                      "n": res["n"],
                      "media_a": float(completos[a].mean()) if len(completos) else np.nan,
                      "media_b": float(completos[b].mean()) if len(completos) else np.nan,
                      **{k: res[k] for k in ("diferencia_media", "ic_bajo", "ic_alto", "p_t",
                                              "p_wilcoxon", "p_normalidad", "prueba_sugerida", "nota")}})
    columnas = [*por, "metrica", "a", "b", "n", "media_a", "media_b", "diferencia_media", "ic_bajo",
                "ic_alto", "p_t", "p_wilcoxon", "p_normalidad", "prueba_sugerida", "nota"]
    return pd.DataFrame(filas, columns=columnas)


def optimo_por_campo(df_barrido, metrica="costo_ha"):
    """Por mecanismo y tamaño de campo, el número de tractores con la menor media de `metrica`.

    Columnas: `mecanismo, hectareas, n_optimo, metrica, n, media, de, ic95, ic_bajo, ic_alto,
    ha_por_tractor, n_min_probado, n_max_probado, en_borde`. `media` e IC son los de la
    métrica en el N óptimo. `en_borde` es True si el óptimo es el N más grande probado (el
    verdadero óptimo podría estar más arriba y conviene ampliar el barrido).
    """
    ic = resumen_ic(df_barrido, metrica, ["mecanismo", "hectareas", "n_tractores"])
    filas = []
    for (mecanismo, hectareas), g in ic.groupby(["mecanismo", "hectareas"], sort=True):
        g = g.dropna(subset=["media"])
        if g.empty:
            continue
        mejor = g.loc[g["media"].idxmin()]
        n_opt = int(mejor["n_tractores"])
        n_min, n_max = int(g["n_tractores"].min()), int(g["n_tractores"].max())
        filas.append({
            "mecanismo": mecanismo, "hectareas": hectareas, "n_optimo": n_opt, "metrica": metrica,
            **{k: mejor[k] for k in ("n", "media", "de", "ic95", "ic_bajo", "ic_alto")},
            "ha_por_tractor": float(hectareas) / n_opt,
            "n_min_probado": n_min, "n_max_probado": n_max,
            "en_borde": bool(n_opt == n_max and n_max > n_min),
        })
    columnas = ["mecanismo", "hectareas", "n_optimo", "metrica", "n", "media", "de", "ic95",
                "ic_bajo", "ic_alto", "ha_por_tractor", "n_min_probado", "n_max_probado", "en_borde"]
    return pd.DataFrame(filas, columns=columnas)


# ---------------------------------------------------------------------------
# Sensibilidad económica (sin volver a simular)
# ---------------------------------------------------------------------------

def _leer_ruta(cfg, ruta):
    valor = cfg
    for parte in ruta.split("."):
        valor = valor[parte]
    return valor


def sensibilidad_economica(df_barrido, cfg_base, rangos=None):
    """Recalcula el costo por hectárea de cada corrida del barrido con el valor bajo, base y
    alto de cada parámetro económico, moviendo uno a la vez.

    `rangos`: dict {ruta con puntos: (bajo, alto)}; por defecto `RANGOS_SENSIBILIDAD`. Si se
    pasa, se usan solo esos parámetros. El valor base sale de `cfg_base`.

    Devuelve un DataFrame largo con columnas `parametro, nivel (bajo/base/alto), valor,
    mecanismo, hectareas, n_tractores, costo_ha_media, n_optimo, pct_en_ventana_media`.
    `n_optimo` es el N con menor costo medio para esa combinación de parámetro, nivel,
    mecanismo y hectáreas. `pct_en_ventana_media` se agrega porque la duración de la ventana
    no cambia el costo, solo el porcentaje sembrado dentro de ella.
    La capacidad de tolva no se puede post-procesar (cambia la simulación).
    """
    rangos = RANGOS_SENSIBILIDAD if rangos is None else rangos
    llaves = ["mecanismo", "hectareas", "n_tractores"]
    columnas = ["parametro", "nivel", "valor", *llaves, "costo_ha_media", "n_optimo", "pct_en_ventana_media"]
    partes = []
    for ruta, (bajo, alto) in rangos.items():
        base = _leer_ruta(cfg_base, ruta)
        for nivel, valor in (("bajo", bajo), ("base", base), ("alto", alto)):
            r = _calcular(df_barrido, aplicar(cfg_base, {ruta: valor}))
            tmp = df_barrido[llaves].copy()
            tmp["costo_ha"] = r["costo_ha"]
            tmp["pct_en_ventana"] = r["pct_en_ventana"]
            g = tmp.groupby(llaves, as_index=False, sort=True).agg(
                costo_ha_media=("costo_ha", "mean"), pct_en_ventana_media=("pct_en_ventana", "mean"))
            validos = g.dropna(subset=["costo_ha_media"])
            if len(validos):
                idx = validos.groupby(["mecanismo", "hectareas"])["costo_ha_media"].idxmin()
                opt = validos.loc[idx, ["mecanismo", "hectareas", "n_tractores"]].rename(
                    columns={"n_tractores": "n_optimo"})
                g = g.merge(opt, on=["mecanismo", "hectareas"], how="left")
            else:
                g["n_optimo"] = np.nan
            g["parametro"], g["nivel"], g["valor"] = ruta, nivel, valor
            partes.append(g[columnas])
    if not partes:
        return pd.DataFrame(columns=columnas)
    return pd.concat(partes, ignore_index=True)
