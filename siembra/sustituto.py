"""Modelo sustituto (machine learning) de la simulación y aprendizaje activo.

Responde la pregunta central (¿cuántos tractores por hectárea minimizan el costo por hectárea?)
en cualquier tamaño de campo, no solo en los 5 del barrido, con su incertidumbre.

Idea
----
Un modelo por mecanismo aprende dos salidas físicas de la simulación, no el costo. El modelo por
defecto es un Random Forest (uno de los métodos del documento del curso), con la incertidumbre
tomada de la dispersión entre sus árboles; `--modelo gp` usa en su lugar un proceso gaussiano.

- ``y_retraso = log(t_medio · N / ha)``: paso medio de siembra de las celdas, normalizado por la
  regla física «el retraso crece con hectáreas por tractor». Con esa normalización la variable
  casi no cambia (≈ 5.0 a 6.0), y un modelo que extrapola a una constante (como los árboles)
  extrapola en realidad esa regla física.
- ``H_ha``: horas de motor por hectárea sembrable (el diésel es proporcional a ellas).

Entradas: ``log(ha)``, ``log(N)`` y ``1 / hileras por tolva``. La tercera es geométrica: cuántas
hileras completas alcanza a sembrar una tolva llena; M2 recarga antes de empezar una hilera que
no puede terminar, así que su número de viajes al depósito salta cuando cambia ese entero.

El costo por hectárea se calcula después con la función de costo de `metricas` (que es lineal
en el retraso y en las horas de motor), así que la sensibilidad a precios, jornada o días
laborables sigue sin necesitar simular ni reentrenar.

Aprendizaje activo: en cada ronda se buscan los tamaños de campo donde el modelo más duda cuál N
es el óptimo (entropía de la probabilidad de cada N), se simulan ahí los N que compiten y se
reentrena. Antes de simular se guarda la predicción, así cada ronda es también una validación
prospectiva. Un conjunto de prueba al azar, que el modelo nunca usa para entrenar, mide el
error final contra el modelo que solo conoce el barrido.

Uso (desde la raíz del proyecto, con el entorno virtual y `resultados/barrido.csv` ya generado):

    python -m siembra.sustituto                      # modo completo, Random Forest
    python -m siembra.sustituto --modelo gp          # con proceso gaussiano
    python -m siembra.sustituto --modo rapido --nucleos 6
    python -m siembra.sustituto --iteraciones 0      # sin aprendizaje activo

Escribe en `resultados/sustituto/` (ver docs/sustituto.md).
"""

import argparse
import json
import math
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import experimentos, metricas
from .config import aplicar, cargar_config, derivados, lado_campo

OBJETIVOS = ("y_retraso", "H_ha")
N_EXTRA = 2              # el modelo considera hasta (N máximo del barrido + N_EXTRA) tractores
MUESTRAS = 300           # muestras conjuntas de la posterior para probabilidades e intervalos
NIVEL = 0.95
UMBRAL_ENTROPIA = 0.05   # nats: por debajo, el modelo ya está seguro de qué N gana
SEPARACION_LOG_HA = 0.08 # dos tamaños propuestos en la misma ronda difieren al menos ~8 %
SEMILLA_PRUEBA = 12345   # semilla del sorteo de tamaños del conjunto de prueba

MODOS = {
    "rapido": {"iteraciones": 2, "ha_por_iteracion": 2, "semillas": 3,
               "prueba_ha": 6, "prueba_semillas": 2},
    "completo": {"iteraciones": 4, "ha_por_iteracion": 3, "semillas": 5,
                 "prueba_ha": 10, "prueba_semillas": 3},
}

CARPETA = "sustituto"
ARCHIVOS = {
    "prueba": "prueba.csv",
    "activo": "activo.csv",
    "verificacion": "verificacion.csv",
    "evaluacion": "evaluacion.csv",
    "evaluacion_detalle": "evaluacion_detalle.csv",
    "curva": "curva.csv",
    "optimo": "optimo.csv",
    "cruces": "cruces.csv",
    "mapa": "mapa.csv",
    "atorados": "atorados.csv",
    "meta": "sustituto.json",
    "modelo": "modelo.joblib",
}


# ---------------------------------------------------------------------------
# Datos y características
# ---------------------------------------------------------------------------

def _bool(serie):
    return serie.astype(str).str.lower().isin(("true", "1", "1.0"))


def validas(df):
    """Corridas que terminaron bien: sin estancarse y con todo el campo sembrado.

    Las demás son corridas en las que la simulación se atoró; no describen el desempeño de la
    flota, así que no entran al entrenamiento (se reportan en `atorados`).
    """
    if df is None or len(df) == 0:
        return df
    ok = ~_bool(df["estancado"]) if "estancado" in df.columns else pd.Series(True, index=df.index)
    if "n_no_sembradas" in df.columns:
        ok &= pd.to_numeric(df["n_no_sembradas"], errors="coerce").fillna(1) == 0
    return df[ok]


def geometria(hectareas, cfg):
    """Por tamaño de campo: lado del grid, celdas de trabajo, ha sembrables e hileras por tolva
    (campo sin obstáculos, como el barrido)."""
    ha = np.atleast_1d(np.asarray(hectareas, dtype=float))
    celda_m = cfg["campo"]["celda_m"]
    lado = np.array([lado_campo({"campo": {"hectareas": h, "celda_m": celda_m}}) for h in ha], dtype=float)
    celdas = lado ** 2
    tolva = derivados(cfg)["tolva_celdas"]
    filas = np.floor(tolva / lado)
    return {"lado": lado, "n_celdas": celdas, "ha_sembrables": celdas * celda_m ** 2 / 10_000,
            "filas_tolva": filas}


def caracteristicas(hectareas, n_tractores, cfg, n_categorias=0):
    """Matriz de entradas del modelo: log(ha), log(N), 1 / hileras por tolva y, si
    `n_categorias` > 0, N en codificación one-hot (N = 1 .. n_categorias)."""
    ha = np.atleast_1d(np.asarray(hectareas, dtype=float))
    n = np.broadcast_to(np.asarray(n_tractores, dtype=float), ha.shape)
    g = geometria(ha, cfg)
    filas = g["filas_tolva"]
    # Si una tolva no alcanza ni para una hilera, la variable sigue creciendo (lado / tolva > 1)
    inv = np.where(filas >= 1, 1.0 / np.maximum(filas, 1), g["lado"] / derivados(cfg)["tolva_celdas"])
    columnas = [np.log(ha), np.log(n), inv]
    columnas += [(n == j).astype(float) for j in range(1, n_categorias + 1)]
    return np.column_stack(columnas)


def objetivos_por_corrida(df):
    """Agrega a cada corrida las salidas que aprende el modelo (`y_retraso`, `H_ha`)."""
    d = df.copy()
    ha = pd.to_numeric(d["hectareas"], errors="coerce")
    n = pd.to_numeric(d["n_tractores"], errors="coerce")
    t_medio = pd.to_numeric(d["suma_t_siembra_pasos"], errors="coerce") / pd.to_numeric(d["n_sembradas"], errors="coerce")
    d["t_medio_pasos"] = t_medio
    d["y_retraso"] = np.log(t_medio * n / ha)
    d["H_ha"] = pd.to_numeric(d["H_motor_h"], errors="coerce") / pd.to_numeric(d["ha_sembrables"], errors="coerce")
    d["diesel_por_H"] = pd.to_numeric(d["diesel_l"], errors="coerce") / pd.to_numeric(d["H_motor_h"], errors="coerce")
    return d


def preparar(df):
    """Tabla de entrenamiento: una fila por (mecanismo, hectáreas, N) con la media y la varianza
    de la media de cada objetivo entre semillas, y el costo observado (media e IC 95 %).

    Solo usa corridas válidas (`validas`).
    """
    columnas = ["mecanismo", "hectareas", "n_tractores", "n", *[f"{o}{s}" for o in OBJETIVOS for s in ("", "_var")],
                "costo_obs", "costo_obs_ic", "diesel_por_H"]
    d = validas(df)
    if d is None or len(d) == 0:
        return pd.DataFrame(columns=columnas)
    d = objetivos_por_corrida(d)
    d = d.replace([np.inf, -np.inf], np.nan).dropna(subset=list(OBJETIVOS))
    filas = []
    for (mec, ha, n), g in d.groupby(["mecanismo", "hectareas", "n_tractores"], sort=True):
        fila = {"mecanismo": str(mec), "hectareas": float(ha), "n_tractores": int(n), "n": len(g)}
        for o in OBJETIVOS:
            v = g[o].to_numpy(dtype=float)
            fila[o] = float(v.mean())
            fila[f"{o}_var"] = float(v.var(ddof=1)) / len(v) if len(v) > 1 else np.nan
        c = pd.to_numeric(g["costo_ha"], errors="coerce").dropna().to_numpy()
        e = metricas._estadisticos(c)
        fila["costo_obs"], fila["costo_obs_ic"] = e["media"], e["ic95"]
        fila["diesel_por_H"] = float(g["diesel_por_H"].mean())
        filas.append(fila)
    t = pd.DataFrame(filas, columns=columnas)
    # Con una sola semilla no hay varianza: se usa la mediana de las demás
    for o in OBJETIVOS:
        col = f"{o}_var"
        mediana = t[col].median()
        t[col] = t[col].fillna(mediana if np.isfinite(mediana) else 1e-4)
    return t


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

_ESCALA = (0.05, 100.0)
_IGNORAR = (1e5, 1e6)  # una escala de longitud enorme y fija hace que el kernel no vea esa entrada


def _kernel(n_categorias):
    """f(ha, N) = tendencia común + desviación propia de cada N + ruido.

    - Tendencia: RBF en (log ha, log N, 1/hileras por tolva). Comparte información entre N y
      permite estimar N que no se han simulado.
    - Desviación por N: RBF en (log ha, 1/hileras por tolva, N one-hot). Dos N distintos quedan a
      distancia fija en la parte one-hot, así que cada N puede apartarse de la tendencia (por
      ejemplo, 3 tractores con roles fijos = 1 surcador y 2 sembradoras).
    - Ruido blanco pequeño para lo que no explican las dos partes.

    scikit-learn no tiene kernels que elijan columnas; se logra con escalas de longitud por
    dimensión, fijando en un valor enorme las de las columnas que cada parte no debe ver.
    Se trabaja con la variable normalizada.
    """
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

    k = n_categorias
    tendencia = RBF([1.0, 1.0, 1.0] + [2e5] * k, [_ESCALA] * 3 + [_IGNORAR] * k)
    por_n = RBF([1.0, 2e5, 1.0] + [1.0] * k, [_ESCALA, _IGNORAR, _ESCALA] + [(0.3, 100.0)] * k)
    return (ConstantKernel(1.0, (1e-3, 1e2)) * tendencia
            + ConstantKernel(0.1, (1e-4, 1e2)) * por_n
            + WhiteKernel(1e-3, (1e-6, 5e-2)))


class _Base:
    """Lo común a los modelos sustitutos: datos de entrenamiento, rango y entradas.

    Cada modelo concreto implementa `_ajustar_uno`, `predecir`, `muestras` y `describir`. El resto
    del módulo (análisis, aprendizaje activo, evaluación) solo usa esa interfaz.
    """

    clave = ""
    nombre = ""

    def __init__(self, cfg=None, semilla=0, n_max=None):
        """`n_max`: N más grande que considera el modelo. Por defecto, el mayor N de los datos más
        `N_EXTRA`; el flujo completo lo fija con el del barrido para que no crezca en cada ronda."""
        self.cfg = cfg if cfg is not None else cargar_config()
        self.n_max_fijo = n_max
        self.semilla = semilla
        self.datos = None
        self.modelos = {}

    def ajustar(self, df_corridas):
        self.datos = preparar(df_corridas)
        if len(self.datos) == 0:
            raise ValueError("no hay corridas válidas para entrenar el modelo sustituto")
        self.mecanismos = sorted(self.datos["mecanismo"].unique())
        self.ha_min = float(self.datos["hectareas"].min())
        self.ha_max = float(self.datos["hectareas"].max())
        self.n_max_obs = {m: int(g["n_tractores"].max()) for m, g in self.datos.groupby("mecanismo")}
        self.n_max = self.n_max_fijo or max(self.n_max_obs.values()) + N_EXTRA
        self.n_categorias = self.n_max
        r = self.datos["diesel_por_H"].dropna()
        self.diesel_por_H = float(r.mean()) if len(r) else float(self.cfg["agente"]["consumo_lh"])
        self.modelos = {}
        for mec in self.mecanismos:
            d = self.datos[self.datos["mecanismo"] == mec]
            X = self._X(d["hectareas"], d["n_tractores"])
            for o in OBJETIVOS:
                self._ajustar_uno(mec, o, X, d[o].to_numpy(dtype=float), d[f"{o}_var"].to_numpy(dtype=float))
        return self

    def _X(self, hectareas, n_tractores):
        return caracteristicas(hectareas, n_tractores, self.cfg, self.n_categorias)


class SustitutoRF(_Base):
    """Random Forest (uno por mecanismo y objetivo), el modelo por defecto.

    Es uno de los métodos del documento del curso. La incertidumbre sale de la dispersión entre sus
    árboles: cada árbol es una predicción posible, y el árbol i de cada objetivo se toma junto
    como una muestra conjunta.
    """

    clave = "rf"
    nombre = "Random Forest"
    ARBOLES = 300

    def _ajustar_uno(self, mec, o, X, y, var):
        from sklearn.ensemble import RandomForestRegressor

        rf = RandomForestRegressor(n_estimators=self.ARBOLES, random_state=self.semilla, n_jobs=1)
        rf.fit(X, y)
        self.modelos[(mec, o)] = rf

    def _por_arbol(self, mecanismo, o, X):
        return np.stack([arbol.predict(X) for arbol in self.modelos[(mecanismo, o)].estimators_])

    def predecir(self, mecanismo, hectareas, n_tractores):
        """Media y desviación estándar entre árboles de cada objetivo: {objetivo: (media, de)}."""
        X = self._X(hectareas, n_tractores)
        out = {}
        for o in OBJETIVOS:
            p = self._por_arbol(mecanismo, o, X)
            out[o] = (p.mean(axis=0), p.std(axis=0))
        return out

    def muestras(self, mecanismo, hectareas, n_tractores, k=MUESTRAS, semilla=None):
        """Predicción de cada árbol como muestra: {objetivo: arreglo (k, puntos)}.

        Con k igual al número de árboles se usan todos, en orden; si no, se eligen k árboles con
        una semilla fija (los mismos índices para los dos objetivos)."""
        X = self._X(hectareas, n_tractores)
        semilla = self.semilla if semilla is None else semilla
        if k == self.ARBOLES:
            idx = np.arange(self.ARBOLES)
        else:
            rng = np.random.default_rng([semilla, int.from_bytes(mecanismo.encode(), "little") % 2 ** 31])
            idx = rng.choice(self.ARBOLES, size=k, replace=k > self.ARBOLES)
        return {o: self._por_arbol(mecanismo, o, X)[idx] for o in OBJETIVOS}

    def describir(self):
        return {f"{m}/{o}": f"RandomForestRegressor(n_estimators={rf.n_estimators}, random_state={self.semilla})"
                for (m, o), rf in self.modelos.items()}


class SustitutoGP(_Base):
    """Procesos gaussianos (uno por mecanismo y objetivo): la alternativa con `--modelo gp`."""

    clave = "gp"
    nombre = "Proceso gaussiano"

    def __init__(self, cfg=None, semilla=0, n_max=None, reinicios=3):
        super().__init__(cfg, semilla, n_max)
        self.reinicios = reinicios
        self.escala = {}

    def _ajustar_uno(self, mec, o, X, y, var):
        from sklearn.gaussian_process import GaussianProcessRegressor

        media, de = float(y.mean()), float(y.std()) or 1.0
        # Ruido conocido de cada punto: varianza de la media entre semillas
        alpha = var / de ** 2 + 1e-8
        gp = GaussianProcessRegressor(_kernel(self.n_categorias), alpha=alpha, normalize_y=False,
                                      n_restarts_optimizer=self.reinicios, random_state=self.semilla)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # avisos de convergencia en los límites del kernel
            gp.fit(X, (y - media) / de)
        self.modelos[(mec, o)] = gp
        self.escala[(mec, o)] = (media, de)

    def predecir(self, mecanismo, hectareas, n_tractores):
        """Media y desviación estándar de cada objetivo: {objetivo: (media, de)}."""
        X = self._X(hectareas, n_tractores)
        out = {}
        for o in OBJETIVOS:
            m, s = self.modelos[(mecanismo, o)].predict(X, return_std=True)
            media, de = self.escala[(mecanismo, o)]
            out[o] = (m * de + media, s * de)
        return out

    def muestras(self, mecanismo, hectareas, n_tractores, k=MUESTRAS, semilla=None):
        """Muestras conjuntas de la posterior: {objetivo: arreglo (k, puntos)}."""
        X = self._X(hectareas, n_tractores)
        semilla = self.semilla if semilla is None else semilla
        out = {}
        for i, o in enumerate(OBJETIVOS):
            m, cov = self.modelos[(mecanismo, o)].predict(X, return_cov=True)
            cov = (cov + cov.T) / 2 + 1e-9 * np.eye(len(m))
            # Semilla estable entre procesos (hash() de un texto cambia en cada proceso de Python)
            rng = np.random.default_rng([semilla, i, int.from_bytes(mecanismo.encode(), "little") % 2 ** 31])
            try:
                z = rng.multivariate_normal(m, cov, size=k, method="cholesky")
            except np.linalg.LinAlgError:
                z = rng.multivariate_normal(m, cov, size=k, method="eigh")
            media, de = self.escala[(mecanismo, o)]
            out[o] = z * de + media
        return out

    def describir(self):
        """Hiperparámetros aprendidos (para documentar el modelo)."""
        return {f"{m}/{o}": str(gp.kernel_) for (m, o), gp in self.modelos.items()}


MODELOS = {SustitutoRF.clave: SustitutoRF, SustitutoGP.clave: SustitutoGP}
MODELO_POR_DEFECTO = SustitutoRF.clave
Sustituto = SustitutoRF  # nombre corto del modelo por defecto


def crear(modelo=MODELO_POR_DEFECTO, cfg=None, n_max=None):
    """Instancia el modelo sustituto `modelo` ("rf" o "gp")."""
    if modelo not in MODELOS:
        raise ValueError(f"modelo debe ser uno de {tuple(MODELOS)}, no {modelo!r}")
    return MODELOS[modelo](cfg, n_max=n_max)


# ---------------------------------------------------------------------------
# Costo a partir de las salidas físicas
# ---------------------------------------------------------------------------

def coeficientes_costo(cfg, hectareas, n_tractores, diesel_por_H):
    """Coeficientes (a, b, c) con costo_ha = a + b · t_medio_pasos + c · H_ha.

    Se obtienen evaluando `metricas.agregar_costos` (la función de costo del proyecto) en tres
    puntos, así que cualquier cambio a esa función se refleja aquí. Suponen cobertura completa,
    sin colisiones.
    """
    ha = np.atleast_1d(np.asarray(hectareas, dtype=float))
    n = np.broadcast_to(np.asarray(n_tractores, dtype=float), ha.shape)
    g = geometria(ha, cfg)
    paso_s = derivados(cfg)["paso_s"]

    def costo(t_medio, H_ha):
        H = H_ha * g["ha_sembrables"]
        df = pd.DataFrame({
            "celda_m": cfg["campo"]["celda_m"], "paso_s": paso_s, "n_tractores": n,
            "ha_sembrables": g["ha_sembrables"], "n_celdas_trabajo": g["n_celdas"],
            "n_sembradas": g["n_celdas"], "n_no_sembradas": 0.0, "colisiones": 0.0,
            "suma_t_siembra_pasos": t_medio * g["n_celdas"], "H_motor_h": H,
            "diesel_l": H * diesel_por_H, "T_pasos": np.nan,
        })
        return metricas.agregar_costos(df, cfg)["costo_ha"].to_numpy(dtype=float)

    a = costo(0.0, 0.0)
    return a, costo(1.0, 0.0) - a, costo(0.0, 1.0) - a


def _t_medio(y_retraso, hectareas, n_tractores):
    return np.exp(y_retraso) * np.asarray(hectareas, dtype=float) / np.asarray(n_tractores, dtype=float)


# ---------------------------------------------------------------------------
# Análisis: curva de costo, N óptimo, cruces
# ---------------------------------------------------------------------------

def _rejilla(sust, hectareas=None, n_max=None):
    if hectareas is None:
        hectareas = np.arange(math.ceil(sust.ha_min), math.floor(sust.ha_max) + 1, dtype=float)
    hectareas = np.asarray(sorted(set(float(h) for h in hectareas)))
    ns = np.arange(1, (n_max or sust.n_max) + 1)
    return hectareas, ns


def _muestras_costo(sust, mec, hectareas, ns, cfgs, k, semilla):
    """Muestras del costo por hectárea: {nombre_cfg: arreglo (k, len(ha), len(ns))}."""
    HA, NN = np.meshgrid(hectareas, ns, indexing="ij")
    ha_p, n_p = HA.ravel(), NN.ravel()
    m = sust.muestras(mec, ha_p, n_p, k, semilla)
    t = _t_medio(m["y_retraso"], ha_p, n_p)
    H = m["H_ha"]
    out = {}
    for nombre, cfg in cfgs.items():
        a, b, c = coeficientes_costo(cfg, ha_p, n_p, sust.diesel_por_H)
        out[nombre] = (a + b * t + c * H).reshape(k, len(hectareas), len(ns))
    return out


def _probabilidades(costos):
    """P(N es el óptimo) por tamaño de campo, a partir de las muestras (k, ha, N)."""
    k, _nh, nn = costos.shape
    gana = costos.argmin(axis=2)
    return np.stack([(gana == j).mean(axis=0) for j in range(nn)], axis=1)


def _entropia(p):
    with np.errstate(divide="ignore", invalid="ignore"):
        return -np.nansum(np.where(p > 0, p * np.log(p), 0.0), axis=1)


def _cruces(hectareas, ns, costos):
    """Tamaños de campo donde cambia el N óptimo (por costo esperado) con su intervalo."""
    media = costos.mean(axis=0)
    n_opt = ns[media.argmin(axis=1)]
    cambios = [i for i in range(len(hectareas) - 1) if n_opt[i] != n_opt[i + 1]]
    filas = []
    for j, i in enumerate(cambios):
        n_de, n_a = int(n_opt[i]), int(n_opt[i + 1])
        ja, jb = int(np.where(ns == n_de)[0][0]), int(np.where(ns == n_a)[0][0])
        dif = media[:, jb] - media[:, ja]  # < 0 donde conviene n_a
        d0, d1 = dif[i], dif[i + 1]
        frac = d0 / (d0 - d1) if d0 != d1 else 0.5
        ha_cruce = float(hectareas[i] + frac * (hectareas[i + 1] - hectareas[i]))
        # Ventana: entre el cambio anterior y el siguiente
        lo = cambios[j - 1] + 1 if j > 0 else 0
        hi = cambios[j + 1] if j + 1 < len(cambios) else len(hectareas) - 1
        hv = hectareas[lo:hi + 1]
        ds = costos[:, lo:hi + 1, jb] - costos[:, lo:hi + 1, ja]
        valores = []
        for s in range(ds.shape[0]):
            signo = np.sign(ds[s])
            idx = np.where(np.diff(signo) != 0)[0]
            if len(idx) == 0:
                # Sin cruce en la ventana: queda más allá de un borde
                valores.append(hv[-1] if ds[s].mean() > 0 else hv[0])
                continue
            mejor = idx[np.argmin(np.abs(hv[idx] - ha_cruce))]
            a0, a1 = ds[s, mejor], ds[s, mejor + 1]
            f = a0 / (a0 - a1) if a0 != a1 else 0.5
            valores.append(hv[mejor] + f * (hv[mejor + 1] - hv[mejor]))
        q = (1 - NIVEL) / 2
        bajo, alto = np.quantile(valores, [q, 1 - q])
        filas.append({"n_de": n_de, "n_a": n_a, "hectareas": ha_cruce,
                      "ic_bajo": float(bajo), "ic_alto": float(alto),
                      "ic_abierto_bajo": bool(np.isclose(bajo, hv[0]) and lo == 0),
                      "ic_abierto_alto": bool(np.isclose(alto, hv[-1]) and hi == len(hectareas) - 1)})
    return filas


def analizar(sust, cfg=None, hectareas=None, n_max=None, k=MUESTRAS, semilla=0, rangos=None, n_valores=9):
    """Curva de costo, N óptimo, cruces y (opcional) mapa de sensibilidad económica.

    Devuelve un dict de DataFrames: `curva` (mecanismo, hectareas, n_tractores, costo_ha, ic_bajo,
    ic_alto, extrapolado), `optimo` (mecanismo, hectareas, n_optimo, costo_ha, p_optimo,
    p_N1..p_Nk, entropia), `cruces` y, si se pasan `rangos` ({ruta: (bajo, alto)}), `mapa`
    (mecanismo, parametro, valor, hectareas, n_optimo, costo_ha).
    """
    cfg = cfg if cfg is not None else sust.cfg
    hectareas, ns = _rejilla(sust, hectareas, n_max)
    cfgs = {"base": cfg}
    variantes = []
    for ruta, (bajo, alto) in (rangos or {}).items():
        for v in np.linspace(bajo, alto, n_valores):
            nombre = f"{ruta}={v:.6g}"
            cfgs[nombre] = aplicar(cfg, {ruta: float(v)})
            variantes.append((nombre, ruta, float(v)))
    curva, optimo, cruces, mapa = [], [], [], []
    q = (1 - NIVEL) / 2
    for mec in sust.mecanismos:
        todos = _muestras_costo(sust, mec, hectareas, ns, cfgs, k, semilla)
        c = todos["base"]
        media = c.mean(axis=0)
        bajo, alto = np.quantile(c, [q, 1 - q], axis=0)
        for i, ha in enumerate(hectareas):
            for j, n in enumerate(ns):
                curva.append({"mecanismo": mec, "hectareas": ha, "n_tractores": int(n),
                              "costo_ha": media[i, j], "ic_bajo": bajo[i, j], "ic_alto": alto[i, j],
                              "extrapolado": bool(n > sust.n_max_obs[mec])})
        p = _probabilidades(c)
        ent = _entropia(p)
        for i, ha in enumerate(hectareas):
            j = int(media[i].argmin())
            fila = {"mecanismo": mec, "hectareas": ha, "n_optimo": int(ns[j]), "costo_ha": media[i, j],
                    "p_optimo": p[i, j], "entropia": ent[i]}
            fila.update({f"p_N{int(n)}": p[i, jj] for jj, n in enumerate(ns)})
            optimo.append(fila)
        for f in _cruces(hectareas, ns, c):
            cruces.append({"mecanismo": mec, **f})
        for nombre, ruta, v in variantes:
            mv = todos[nombre].mean(axis=0)
            jj = mv.argmin(axis=1)
            for i, ha in enumerate(hectareas):
                mapa.append({"mecanismo": mec, "parametro": ruta, "valor": v, "hectareas": ha,
                             "n_optimo": int(ns[jj[i]]), "costo_ha": mv[i, jj[i]]})
    res = {
        "curva": pd.DataFrame(curva),
        "optimo": pd.DataFrame(optimo),
        "cruces": pd.DataFrame(cruces, columns=["mecanismo", "n_de", "n_a", "hectareas", "ic_bajo",
                                                "ic_alto", "ic_abierto_bajo", "ic_abierto_alto"]),
    }
    if rangos:
        res["mapa"] = pd.DataFrame(mapa)
    return res


# ---------------------------------------------------------------------------
# Evaluación contra corridas que el modelo no vio
# ---------------------------------------------------------------------------

def _dentro(obs, obs_ic, bajo, alto):
    """¿El costo observado cae en el intervalo predicho? El observado es una media de pocas
    semillas con su propio error, así que el intervalo se amplía con su semiancho (IC 95 %)."""
    ic = np.nan_to_num(np.asarray(obs_ic, dtype=float))
    obs = np.asarray(obs, dtype=float)
    return (obs >= np.asarray(bajo, dtype=float) - ic) & (obs <= np.asarray(alto, dtype=float) + ic)


def predecir_costo(sust, mecanismo, hectareas, n_tractores, cfg=None, k=MUESTRAS, semilla=0):
    """Costo por hectárea predicho en puntos sueltos: (media, ic_bajo, ic_alto)."""
    cfg = cfg if cfg is not None else sust.cfg
    ha = np.atleast_1d(np.asarray(hectareas, dtype=float))
    n = np.broadcast_to(np.asarray(n_tractores, dtype=float), ha.shape)
    m = sust.muestras(mecanismo, ha, n, k, semilla)
    a, b, c = coeficientes_costo(cfg, ha, n, sust.diesel_por_H)
    costo = a + b * _t_medio(m["y_retraso"], ha, n) + c * m["H_ha"]
    q = (1 - NIVEL) / 2
    return costo.mean(axis=0), np.quantile(costo, q, axis=0), np.quantile(costo, 1 - q, axis=0)


# ---------------------------------------------------------------------------
# Guardar, cargar y consultar el modelo entrenado
# ---------------------------------------------------------------------------

def guardar_modelo(sust, ruta):
    """Guarda el modelo entrenado con joblib (comprimido). Se carga con `cargar_modelo` y la misma
    versión de scikit-learn."""
    import joblib
    import sklearn

    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"modelo": sust, "scikit_learn": sklearn.__version__,
                 "fecha": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}, ruta, compress=3)
    return ruta


def cargar_modelo(ruta):
    """Carga un modelo guardado con `guardar_modelo`. Avisa si cambió la versión de scikit-learn,
    porque un modelo guardado con otra versión puede no cargar o predecir distinto."""
    import joblib
    import sklearn

    paquete = joblib.load(ruta)
    if paquete.get("scikit_learn") != sklearn.__version__:
        warnings.warn(f"el modelo se guardó con scikit-learn {paquete.get('scikit_learn')} y está instalada "
                      f"la {sklearn.__version__}; regenéralo con: python -m siembra.sustituto --guardar-modelo")
    return paquete["modelo"]


def _leer_csv(ruta):
    try:
        return pd.read_csv(ruta)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def reconstruir_modelo(salida=None, modelo=None, ruta_config=None):
    """Reentrena el modelo final con los CSV que ya existen, igual que `correr` (barrido + activo +
    prueba, con el n_max del barrido), sin simular nada.

    Por defecto usa la clase de modelo y el archivo de parámetros de la última corrida (los guarda
    `sustituto.json`); `modelo` y `ruta_config` los cambian."""
    salida = Path(salida) if salida is not None else experimentos.SALIDA_POR_DEFECTO
    ruta_barrido = salida / "barrido.csv"
    if not ruta_barrido.exists():
        raise FileNotFoundError(f"No existe {ruta_barrido}. Corre primero: python -m siembra.experimentos --solo barrido")
    ruta_meta = salida / CARPETA / ARCHIVOS["meta"]
    meta = json.loads(ruta_meta.read_text(encoding="utf-8")) if ruta_meta.exists() else {}
    modelo = modelo or (meta.get("modelo") if meta.get("modelo") in MODELOS else MODELO_POR_DEFECTO)
    ruta_config = ruta_config or meta.get("config")
    cfg = cargar_config(ruta_config)
    barrido = pd.read_csv(ruta_barrido)
    base = crear(modelo, cfg).ajustar(barrido)
    extra = [_leer_csv(salida / CARPETA / ARCHIVOS[n]) for n in ("activo", "prueba")]
    datos = pd.concat([barrido] + [d for d in extra if len(d)], ignore_index=True)
    return crear(modelo, cfg, n_max=base.n_max).ajustar(datos)


def _costos_consulta(sust, mecanismo, hectareas, cambios, cfg):
    if mecanismo not in sust.mecanismos:
        raise ValueError(f"mecanismo desconocido: {mecanismo!r}; el modelo tiene {', '.join(sust.mecanismos)}")
    ha = np.atleast_1d(np.asarray(hectareas, dtype=float))
    if not np.all(np.isfinite(ha)) or np.any(ha <= 0):
        raise ValueError("las hectáreas deben ser un número positivo")
    cfg = aplicar(cfg if cfg is not None else sust.cfg, cambios)
    ns = np.arange(1, sust.n_max + 1)
    # Las mismas muestras que `analizar` (todas las del modelo, semilla 0): da las mismas respuestas
    return ha, ns, _muestras_costo(sust, mecanismo, ha, ns, {"c": cfg}, MUESTRAS, 0)["c"]


def consultar(sust, mecanismo, hectareas, cambios=None, cfg=None):
    """Lo que dice el modelo para un campo: costo por hectárea con 1 a n_max tractores (media e
    IC 95 %), probabilidad de que cada N sea el más barato y el N recomendado (el de menor costo
    esperado, como en `optimo.csv`).

    `cambios`: parámetros del costo en notación de puntos, por ejemplo
    {"economia.precio_maiz": 7000}. Solo entran en la fórmula de costo, no hace falta simular.
    Fuera del rango de hectáreas del entrenamiento el modelo no extrapola (`fuera_de_rango`).
    Con Random Forest la respuesta es exactamente la de `curva.csv` y `optimo.csv`; con el proceso
    gaussiano las muestras son aleatorias y puede variar un poco.
    """
    ha, ns, costos = _costos_consulta(sust, mecanismo, hectareas, cambios, cfg)
    if len(ha) != 1:
        raise ValueError("consultar recibe un solo tamaño de campo; usa n_optimo_por_tamano para varios")
    q = (1 - NIVEL) / 2
    media = costos.mean(axis=0)[0]
    bajo, alto = np.quantile(costos, q, axis=0)[0], np.quantile(costos, 1 - q, axis=0)[0]
    p = _probabilidades(costos)[0]
    i = int(media.argmin())
    return {
        "modelo": sust.nombre, "mecanismo": mecanismo, "hectareas": float(ha[0]),
        "n_recomendado": int(ns[i]), "p_recomendado": float(p[i]),
        "rango_hectareas": [sust.ha_min, sust.ha_max],
        "fuera_de_rango": bool(not sust.ha_min <= ha[0] <= sust.ha_max),
        "flotas": [{"n_tractores": int(n), "costo_ha": float(media[j]), "ic_bajo": float(bajo[j]),
                    "ic_alto": float(alto[j]), "p_optimo": float(p[j]),
                    "extrapolado": bool(n > sust.n_max_obs[mecanismo])} for j, n in enumerate(ns)],
    }


def n_optimo_por_tamano(sust, mecanismo, hectareas=None, cambios=None, cfg=None):
    """N recomendado y su probabilidad en varios tamaños (por defecto cada hectárea del rango)."""
    if hectareas is None:
        hectareas = np.arange(math.ceil(sust.ha_min), math.floor(sust.ha_max) + 1, dtype=float)
    ha, ns, costos = _costos_consulta(sust, mecanismo, hectareas, cambios, cfg)
    media = costos.mean(axis=0)
    p = _probabilidades(costos)
    i = media.argmin(axis=1)
    return pd.DataFrame({"hectareas": ha, "n_optimo": ns[i], "p_optimo": p[np.arange(len(ha)), i]})


def evaluar(sust, df_prueba, cfg=None, k=MUESTRAS, semilla=0, etiqueta="modelo"):
    """Compara el modelo con corridas de prueba. Devuelve (detalle, resumen).

    `detalle`: una fila por (mecanismo, hectáreas, N) con costo observado y predicho.
    `resumen`: por mecanismo, error absoluto medio (%), cobertura del IC 95 %, acierto del N
    óptimo (entre los N con corridas válidas) y sobrecosto de seguir la recomendación del modelo
    (costo observado del N recomendado menos el del mejor N observado).
    """
    obs = preparar(df_prueba)
    det = []
    for mec, g in obs.groupby("mecanismo"):
        if mec not in sust.mecanismos:
            continue
        media, bajo, alto = predecir_costo(sust, mec, g["hectareas"], g["n_tractores"], cfg, k, semilla)
        det.append(g[["mecanismo", "hectareas", "n_tractores", "n", "costo_obs", "costo_obs_ic"]].assign(
            costo_pred=media, ic_bajo=bajo, ic_alto=alto,
            extrapolado=[bool(n > sust.n_max_obs[mec]) for n in g["n_tractores"]]))
    cols = ["modelo", "mecanismo", "hectareas", "n_tractores", "n", "costo_obs", "costo_obs_ic", "costo_pred",
            "ic_bajo", "ic_alto", "extrapolado", "error_pct", "dentro_ic"]
    if not det:
        return pd.DataFrame(columns=cols), pd.DataFrame()
    det = pd.concat(det, ignore_index=True)
    det["error_pct"] = 100 * (det["costo_pred"] / det["costo_obs"] - 1)
    det["dentro_ic"] = _dentro(det["costo_obs"], det["costo_obs_ic"], det["ic_bajo"], det["ic_alto"])
    det.insert(0, "modelo", etiqueta)
    filas = []
    for mec, g in det.groupby("mecanismo"):
        aciertos, sobre, sobre_pct = [], [], []
        for _ha, h in g.groupby("hectareas"):
            if len(h) < 2:
                continue
            real = h.loc[h["costo_obs"].idxmin()]
            pred = h.loc[h["costo_pred"].idxmin()]
            aciertos.append(int(pred["n_tractores"] == real["n_tractores"]))
            sobre.append(pred["costo_obs"] - real["costo_obs"])
            sobre_pct.append(100 * sobre[-1] / real["costo_obs"])
        filas.append({
            "modelo": etiqueta, "mecanismo": mec, "puntos": len(g), "tamanos": len(aciertos),
            "error_abs_medio_pct": g["error_pct"].abs().mean(),
            "error_abs_max_pct": g["error_pct"].abs().max(),
            "cobertura_ic95": g["dentro_ic"].mean(),
            "acierto_n_optimo": np.mean(aciertos) if aciertos else np.nan,
            "sobrecosto_medio_ha": np.mean(sobre) if sobre else np.nan,
            "sobrecosto_max_pct": np.max(sobre_pct) if sobre_pct else np.nan,
        })
    return det[cols], pd.DataFrame(filas)


def atorados(*dfs):
    """Configuraciones con al menos una corrida estancada o incompleta (la simulación se atoró)."""
    d = pd.concat([x for x in dfs if x is not None and len(x)], ignore_index=True) if dfs else pd.DataFrame()
    cols = ["grupo", "mecanismo", "hectareas", "n_tractores", "corridas", "atoradas", "cobertura_min"]
    if len(d) == 0:
        return pd.DataFrame(columns=cols)
    mal = ~d.index.isin(validas(d).index)
    d = pd.DataFrame({"grupo": d["grupo"] if "grupo" in d.columns else "", "mecanismo": d["mecanismo"],
                      "hectareas": d["hectareas"], "n_tractores": d["n_tractores"],
                      "cobertura": d["cobertura"], "_mal": mal})
    g = d.groupby(["grupo", "mecanismo", "hectareas", "n_tractores"]).agg(
        corridas=("_mal", "size"), atoradas=("_mal", "sum"),
        cobertura_min=("cobertura", "min")).reset_index()
    return g[g["atoradas"] > 0][cols].sort_values(["mecanismo", "hectareas", "n_tractores"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Aprendizaje activo
# ---------------------------------------------------------------------------

def proponer(sust, mecanismo, candidatos_ha, simulados, ha_por_iteracion, cfg=None, k=MUESTRAS, semilla=0,
             umbral=UMBRAL_ENTROPIA):
    """Puntos (ha, N) a simular para un mecanismo: los tamaños donde más se duda qué N gana.

    En cada tamaño elegido se simulan los N con probabilidad de ser el óptimo >= 10 % (al menos
    los dos más probables) que todavía no se hayan simulado (`simulados`: set de
    (mecanismo, ha, N)). Devuelve una lista de dicts con la predicción previa de cada punto.
    """
    cfg = cfg if cfg is not None else sust.cfg
    candidatos_ha = np.asarray(sorted(set(float(h) for h in candidatos_ha)))
    if len(candidatos_ha) == 0:
        return []
    _ha, ns = _rejilla(sust, candidatos_ha)
    costos = _muestras_costo(sust, mecanismo, candidatos_ha, ns, {"base": cfg}, k, semilla)["base"]
    p = _probabilidades(costos)
    ent = _entropia(p)
    elegidos, puntos = [], []
    for i in np.argsort(-ent, kind="stable"):
        if len(elegidos) >= ha_por_iteracion or ent[i] < umbral:
            break
        ha = float(candidatos_ha[i])
        if any(abs(math.log(ha) - math.log(e)) < SEPARACION_LOG_HA for e in elegidos):
            continue
        orden = np.argsort(-p[i], kind="stable")
        nuevos = [int(ns[j]) for jj, j in enumerate(orden) if (p[i, j] >= 0.10 or jj < 2)
                  and (mecanismo, ha, int(ns[j])) not in simulados]
        if not nuevos:
            continue
        elegidos.append(ha)
        media, bajo, alto = predecir_costo(sust, mecanismo, [ha] * len(nuevos), nuevos, cfg, k, semilla)
        for n, m_, b_, a_ in zip(nuevos, media, bajo, alto):
            puntos.append({"mecanismo": mecanismo, "hectareas": ha, "n_tractores": n, "entropia": float(ent[i]),
                           "p_optimo_previa": float(p[i, int(np.where(ns == n)[0][0])]),
                           "costo_pred": float(m_), "ic_bajo": float(b_), "ic_alto": float(a_)})
    return puntos


def _tareas(puntos, semillas, grupo, iteracion, simulador, ruta_config):
    tareas = []
    for pt in puntos:
        ha, n, mec = pt["hectareas"], pt["n_tractores"], pt["mecanismo"]
        for s in range(semillas):
            tareas.append(experimentos.Tarea(
                grupo=grupo, id=f"{grupo}_i{iteracion}_{ha:g}ha_{n}t_{mec}_s{s}",
                cambios={"campo.hectareas": int(ha) if float(ha).is_integer() else ha,
                         "flota.n_tractores": int(n), "mecanismo": mec},
                semilla=s, etiquetas={"iteracion": iteracion}, simulador=simulador,
                ruta_config=None if ruta_config is None else str(ruta_config)))
    return tareas


def _correr(tareas, nucleos, etiqueta, ruta_errores, verbose):
    resultados = experimentos.ejecutar(tareas, nucleos, etiqueta, ruta_errores, verbose)
    buenos = [r for r in resultados if r and r["ok"]]
    return pd.DataFrame([r["fila"] for r in buenos]), len(resultados) - len(buenos)


def tamanos_prueba(ha_min, ha_max, n, excluir=(), semilla=SEMILLA_PRUEBA):
    """Tamaños de campo enteros al azar (uniformes en log) para el conjunto de prueba."""
    rng = np.random.default_rng(semilla)
    excluir = {float(e) for e in excluir}
    elegidos = []
    for _ in range(1000):
        if len(elegidos) >= n:
            break
        ha = float(round(math.exp(rng.uniform(math.log(ha_min), math.log(ha_max)))))
        if ha not in excluir and ha not in elegidos and ha_min <= ha <= ha_max:
            elegidos.append(ha)
    return sorted(elegidos)


def aprendizaje_activo(df_base, cfg, iteraciones, ha_por_iteracion, semillas, nucleos=1, excluir_ha=(),
                       simulador=experimentos.SIMULADOR, ruta_config=None, ruta_errores=None, verbose=True,
                       k=MUESTRAS, modelo=MODELO_POR_DEFECTO):
    """Rondas de proponer → simular → reentrenar. Devuelve (corridas nuevas, verificación, errores)."""
    datos = df_base.copy()
    sust = crear(modelo, cfg).ajustar(datos)
    n_max = sust.n_max
    candidatos = [h for h in np.arange(math.ceil(sust.ha_min), math.floor(sust.ha_max) + 1, dtype=float)
                  if h not in {float(e) for e in excluir_ha}]
    simulados = {(str(r.mecanismo), float(r.hectareas), int(r.n_tractores))
                 for r in datos[["mecanismo", "hectareas", "n_tractores"]].itertuples()}
    nuevas, verif, n_err = [], [], 0
    for it in range(1, iteraciones + 1):
        puntos = []
        for mec in sust.mecanismos:
            puntos += proponer(sust, mec, candidatos, simulados, ha_por_iteracion, cfg, k, semilla=it)
        if not puntos:
            if verbose:
                print(f"[activo] ronda {it}: el modelo ya no duda en ningún tamaño; se detiene.", flush=True)
            break
        if verbose:
            resumen = ", ".join(f"{p['mecanismo']} {p['hectareas']:g} ha N={p['n_tractores']}" for p in puntos)
            print(f"[activo] ronda {it}: {len(puntos)} puntos ({resumen})", flush=True)
        df, e = _correr(_tareas(puntos, semillas, "activo", it, simulador, ruta_config), nucleos,
                        f"activo {it}", ruta_errores, verbose)
        n_err += e
        simulados |= {(p["mecanismo"], p["hectareas"], p["n_tractores"]) for p in puntos}
        if len(df):
            obs = preparar(df)
            for p in puntos:
                o = obs[(obs["mecanismo"] == p["mecanismo"]) & (obs["hectareas"] == p["hectareas"])
                        & (obs["n_tractores"] == p["n_tractores"])]
                costo = float(o["costo_obs"].iloc[0]) if len(o) else np.nan
                costo_ic = float(o["costo_obs_ic"].iloc[0]) if len(o) else np.nan
                verif.append({"iteracion": it, **p, "corridas_validas": int(o["n"].iloc[0]) if len(o) else 0,
                              "costo_obs": costo, "costo_obs_ic": costo_ic,
                              "error_pct": 100 * (p["costo_pred"] / costo - 1) if len(o) else np.nan,
                              "dentro_ic": bool(_dentro(costo, costo_ic, p["ic_bajo"], p["ic_alto"])) if len(o) else False})
            nuevas.append(df)
            datos = pd.concat([datos, df], ignore_index=True)
            sust = crear(modelo, cfg, n_max=n_max).ajustar(datos)
    activo = pd.concat(nuevas, ignore_index=True) if nuevas else pd.DataFrame()
    return activo, pd.DataFrame(verif), n_err


# ---------------------------------------------------------------------------
# Flujo completo
# ---------------------------------------------------------------------------

def _escribir(df, ruta, verbose):
    df.to_csv(ruta, index=False, encoding="utf-8")
    if verbose:
        print(f"  -> {ruta} ({len(df)} filas)", flush=True)


def correr(salida=None, modo="completo", iteraciones=None, ha_por_iteracion=None, semillas=None,
           prueba_ha=None, prueba_semillas=None, nucleos=None, simulador=experimentos.SIMULADOR,
           ruta_config=None, verbose=True, modelo=MODELO_POR_DEFECTO):
    """Entrena, evalúa y explora con el modelo sustituto. Lee `<salida>/barrido.csv` y escribe
    `<salida>/sustituto/`. Devuelve un dict con los DataFrames y `n_errores`."""
    salida = Path(salida) if salida is not None else experimentos.SALIDA_POR_DEFECTO
    ruta_barrido = salida / "barrido.csv"
    if not ruta_barrido.exists():
        raise FileNotFoundError(f"No existe {ruta_barrido}. Corre primero: python -m siembra.experimentos --solo barrido")
    m = MODOS[modo]
    iteraciones = m["iteraciones"] if iteraciones is None else iteraciones
    ha_por_iteracion = ha_por_iteracion or m["ha_por_iteracion"]
    semillas = semillas or m["semillas"]
    prueba_ha = m["prueba_ha"] if prueba_ha is None else prueba_ha
    prueba_semillas = prueba_semillas or m["prueba_semillas"]
    nucleos = nucleos or max(1, (os.cpu_count() or 2) - 1)
    carpeta = salida / CARPETA
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_errores = salida / "errores.log"
    cfg = cargar_config(ruta_config)
    inicio = time.perf_counter()

    barrido = pd.read_csv(ruta_barrido)
    base = crear(modelo, cfg).ajustar(barrido)
    n_err = 0

    # 1. Conjunto de prueba (nunca se usa para entrenar)
    ha_prueba = tamanos_prueba(base.ha_min, base.ha_max, prueba_ha, excluir=barrido["hectareas"].unique())
    if verbose:
        print(f"\n== Conjunto de prueba: {len(ha_prueba)} tamaños × N 1-{base.n_max} × "
              f"{len(base.mecanismos)} mecanismos × {prueba_semillas} semillas ==", flush=True)
    puntos = [{"mecanismo": mec, "hectareas": ha, "n_tractores": n}
              for ha in ha_prueba for n in range(1, base.n_max + 1) for mec in base.mecanismos]
    prueba, e = _correr(_tareas(puntos, prueba_semillas, "prueba", 0, simulador, ruta_config),
                        nucleos, "prueba", ruta_errores, verbose) if puntos else (pd.DataFrame(), 0)
    n_err += e

    # 2. Aprendizaje activo
    if verbose:
        print(f"\n== Aprendizaje activo: hasta {iteraciones} rondas, {ha_por_iteracion} tamaños por ronda y "
              f"mecanismo, {semillas} semillas por punto ==", flush=True)
    activo, verif, e = aprendizaje_activo(barrido, cfg, iteraciones, ha_por_iteracion, semillas, nucleos,
                                          ha_prueba, simulador, ruta_config, ruta_errores, verbose,
                                          modelo=modelo)
    n_err += e
    entrenamiento = pd.concat([barrido, activo], ignore_index=True) if len(activo) else barrido
    final = crear(modelo, cfg, n_max=base.n_max).ajustar(entrenamiento)

    # 3. Evaluación en el conjunto de prueba: solo barrido contra barrido + activo
    det_b, res_b = evaluar(base, prueba, cfg, etiqueta="solo barrido") if len(prueba) else (pd.DataFrame(), pd.DataFrame())
    det_f, res_f = evaluar(final, prueba, cfg, etiqueta="barrido + activo") if len(prueba) else (pd.DataFrame(), pd.DataFrame())

    # 4. Análisis. Las métricas de arriba salen de modelos que no vieron la prueba; para la curva
    # final se reentrena con todas las corridas válidas (práctica estándar antes de usar un modelo).
    uso = (crear(modelo, cfg, n_max=base.n_max).ajustar(pd.concat([entrenamiento, prueba], ignore_index=True))
           if len(prueba) else final)
    rangos = {r: v for r, v in metricas.RANGOS_SENSIBILIDAD.items() if r != "agronomia.ventana_dias"}
    an = analizar(uso, cfg, rangos=rangos)

    salidas = {
        "prueba": prueba, "activo": activo, "verificacion": verif,
        "evaluacion": pd.concat([res_b, res_f], ignore_index=True),
        "evaluacion_detalle": pd.concat([det_b, det_f], ignore_index=True),
        "curva": an["curva"], "optimo": an["optimo"], "cruces": an["cruces"], "mapa": an["mapa"],
        "atorados": atorados(barrido.assign(grupo="barrido"), activo, prueba),
    }
    if verbose:
        print("", flush=True)
    for nombre, df in salidas.items():
        _escribir(df, carpeta / ARCHIVOS[nombre], verbose)
    # El modelo final, para consultarlo sin reentrenar (python -m siembra.interfaz)
    ruta_modelo = guardar_modelo(uso, carpeta / ARCHIVOS["modelo"])
    if verbose:
        print(f"  -> {ruta_modelo} (modelo entrenado)", flush=True)
    import sklearn

    meta = {
        "fecha": f"{datetime.now():%Y-%m-%d %H:%M:%S}", "modelo": uso.clave, "modelo_nombre": uso.nombre,
        "modo": modo, "iteraciones": iteraciones,
        "ha_por_iteracion": ha_por_iteracion, "semillas_activo": semillas, "tamanos_prueba": ha_prueba,
        "semillas_prueba": prueba_semillas, "rango_hectareas": [uso.ha_min, uso.ha_max],
        "n_max": uso.n_max, "puntos_barrido": int(len(base.datos)),
        "puntos_barrido_activo": int(len(final.datos)), "puntos_modelo_final": int(len(uso.datos)),
        "muestras": MUESTRAS, "diesel_por_H": uso.diesel_por_H, "hiperparametros": uso.describir(),
        "version_parametros": cfg.get("version_parametros"), "scikit_learn": sklearn.__version__,
        "archivo_modelo": ARCHIVOS["modelo"], "config": str(ruta_config) if ruta_config else None,
        "segundos": round(time.perf_counter() - inicio, 1),
    }
    (carpeta / ARCHIVOS["meta"]).write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    salidas["meta"] = meta
    salidas["n_errores"] = n_err
    return salidas


def _resumen_consola(s):
    pd.set_option("display.width", 160)
    if len(s["evaluacion"]):
        print("\nEvaluación en el conjunto de prueba (corridas que el modelo no vio):")
        print(s["evaluacion"].round(3).to_string(index=False))
    if len(s["cruces"]):
        print("\nCambios del número óptimo de tractores (modelo final):")
        print(s["cruces"].round(1).to_string(index=False))
    if len(s["atorados"]):
        print(f"\nConfiguraciones donde la simulación se atoró: {len(s['atorados'])} "
              f"(ver {CARPETA}/{ARCHIVOS['atorados']})")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m siembra.sustituto",
                                description="Modelo sustituto (Random Forest o proceso gaussiano) y aprendizaje activo.")
    p.add_argument("--modelo", choices=tuple(MODELOS), default=None,
                   help="rf = Random Forest (por defecto), gp = proceso gaussiano; con --guardar-modelo, "
                        "por defecto el de la última corrida")
    p.add_argument("--modo", choices=tuple(MODOS), default="completo",
                   help="valores por defecto de rondas, semillas y conjunto de prueba (por defecto completo)")
    p.add_argument("--iteraciones", type=int, default=None, help="rondas de aprendizaje activo (0 = ninguna)")
    p.add_argument("--ha-por-iteracion", type=int, default=None, help="tamaños de campo por ronda y mecanismo")
    p.add_argument("--semillas", type=int, default=None, help="semillas por punto del aprendizaje activo")
    p.add_argument("--prueba-ha", type=int, default=None, help="tamaños de campo del conjunto de prueba (0 = sin prueba)")
    p.add_argument("--prueba-semillas", type=int, default=None, help="semillas por punto del conjunto de prueba")
    p.add_argument("--nucleos", type=int, default=None, help="procesos en paralelo (por defecto núcleos - 1)")
    p.add_argument("--salida", default=None, help="carpeta de resultados (lee barrido.csv de ahí)")
    p.add_argument("--config", default=None, help="archivo de parámetros base")
    p.add_argument("--simulador", default=experimentos.SIMULADOR, help="'modulo:funcion' (para pruebas)")
    p.add_argument("--guardar-modelo", action="store_true",
                   help="solo reentrena el modelo final con los CSV que ya existen y lo guarda (no simula); "
                        "usa el modelo y los parámetros de la última corrida")
    a = p.parse_args(argv)
    if a.guardar_modelo:
        salida = Path(a.salida) if a.salida is not None else experimentos.SALIDA_POR_DEFECTO
        try:
            sust = reconstruir_modelo(salida, a.modelo, a.config)
        except FileNotFoundError as e:
            print(e, file=sys.stderr)
            return 2
        ruta = guardar_modelo(sust, salida / CARPETA / ARCHIVOS["modelo"])
        print(f"Modelo guardado en {ruta} ({sust.nombre}, {len(sust.datos)} configuraciones, "
              f"{int(sust.datos['n'].sum())} corridas válidas).")
        return 0
    try:
        s = correr(a.salida, a.modo, a.iteraciones, a.ha_por_iteracion, a.semillas, a.prueba_ha,
                   a.prueba_semillas, a.nucleos, a.simulador, a.config, modelo=a.modelo or MODELO_POR_DEFECTO)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2
    _resumen_consola(s)
    print(f"\nListo en {experimentos._formato_tiempo(s['meta']['segundos'])}.", flush=True)
    return 1 if s["n_errores"] else 0


if __name__ == "__main__":
    from siembra.sustituto import main as _main  # para que los procesos trabajadores importen por nombre

    sys.exit(_main())
