"""Compara los modelos de regresión del documento del curso como modelo sustituto.

Todos usan los mismos datos de entrenamiento (barrido + corridas del aprendizaje activo), las
mismas entradas y salidas físicas (`siembra.sustituto.caracteristicas` y `OBJETIVOS`), la misma
función de costo y el mismo conjunto de prueba (`resultados/sustituto/prueba.csv`), que ninguno
usa para entrenar. Ningún modelo se ajusta mirando la prueba: todos con sus valores por defecto
(o los del documento del curso).

Uso (desde la raíz del proyecto, después de `python -m siembra.sustituto`):

    python herramientas/comparar_modelos.py
    python herramientas/comparar_modelos.py --salida otra/carpeta

Escribe `<salida>/sustituto/comparacion_modelos.csv`.
"""

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from siembra import sustituto as su  # noqa: E402
from siembra.config import cargar_config  # noqa: E402


def _modelos_puntuales():
    """Modelos del documento del curso sin incertidumbre propia: (número, nombre, fábrica)."""
    from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor
    from sklearn.linear_model import Lasso, LinearRegression, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeRegressor

    return [
        ("1", "Regresión lineal", lambda: make_pipeline(StandardScaler(), LinearRegression())),
        ("3", "Ridge (L2)", lambda: make_pipeline(StandardScaler(), Ridge(alpha=1.0))),
        ("4", "Lasso (L1)", lambda: make_pipeline(StandardScaler(), Lasso(alpha=0.001, max_iter=100000))),
        ("5", "Árbol de decisión", lambda: DecisionTreeRegressor(max_depth=6, random_state=0)),
        ("7", "Gradient Boosting", lambda: GradientBoostingRegressor(random_state=0)),
        ("9", "LightGBM (versión por histogramas de scikit-learn)",
         lambda: HistGradientBoostingRegressor(min_samples_leaf=3, random_state=0)),
    ]


def _metricas(nombre, numero, test, pred_fn, cfg):
    filas = []
    for mec, g in test.groupby("mecanismo"):
        ha, n = g["hectareas"].to_numpy(), g["n_tractores"].to_numpy()
        t, H = pred_fn(mec, ha, n)
        a, b, c = su.coeficientes_costo(cfg, ha, n, 10.5)
        filas.append(g.assign(pred=a + b * t + c * H))
    d = pd.concat(filas)
    err = 100 * (d["pred"] / d["costo_obs"] - 1)
    aciertos, sobre = [], []
    for _clave, h in d.groupby(["mecanismo", "hectareas"]):
        if len(h) < 2:
            continue
        real, elegido = h.loc[h["costo_obs"].idxmin()], h.loc[h["pred"].idxmin()]
        aciertos.append(int(elegido["n_tractores"] == real["n_tractores"]))
        sobre.append(elegido["costo_obs"] - real["costo_obs"])
    return {"numero_curso": numero, "modelo": nombre, "error_medio_pct": float(err.abs().mean()),
            "error_max_pct": float(err.abs().max()), "aciertos": int(sum(aciertos)), "decisiones": len(aciertos),
            "sobrecosto_medio_ha": float(np.mean(sobre))}


def comparar(salida=None):
    salida = Path(salida) if salida is not None else RAIZ / "resultados"
    carpeta = salida / su.CARPETA
    cfg = cargar_config()
    entrenamiento = pd.concat([pd.read_csv(salida / "barrido.csv"),
                               pd.read_csv(carpeta / su.ARCHIVOS["activo"])], ignore_index=True)
    prueba_corridas = pd.read_csv(carpeta / su.ARCHIVOS["prueba"])
    train, test = su.preparar(entrenamiento), su.preparar(prueba_corridas)
    filas = []
    for numero, nombre, fabrica in _modelos_puntuales():
        modelos = {}
        for mec, g in train.groupby("mecanismo"):
            X = su.caracteristicas(g["hectareas"], g["n_tractores"], cfg, 6)
            for o in su.OBJETIVOS:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    modelos[(mec, o)] = fabrica().fit(X, g[o].to_numpy())

        def pred(mec, ha, n, modelos=modelos):
            X = su.caracteristicas(ha, n, cfg, 6)
            return su._t_medio(modelos[(mec, "y_retraso")].predict(X), ha, n), modelos[(mec, "H_ha")].predict(X)

        fila = _metricas(nombre, numero, test, pred, cfg)
        fila.update(incertidumbre="ninguna", cobertura_ic95=np.nan, semiancho_pct=np.nan)
        filas.append(fila)
    # Los dos modelos con incertidumbre, tal como los usa siembra.sustituto
    for clave, numero in (("rf", "6"), ("gp", "no está en el documento")):
        modelo = su.crear(clave, cfg, n_max=6).ajustar(entrenamiento)

        def pred(mec, ha, n, modelo=modelo):
            p = modelo.predecir(mec, ha, n)
            return su._t_medio(p["y_retraso"][0], ha, n), p["H_ha"][0]

        fila = _metricas(modelo.nombre, numero, test, pred, cfg)
        det, _res = su.evaluar(modelo, prueba_corridas, cfg)
        fila.update(incertidumbre="dispersión entre árboles" if clave == "rf" else "posterior del proceso gaussiano",
                    cobertura_ic95=float(det["dentro_ic"].mean()),
                    semiancho_pct=float((100 * (det["ic_alto"] - det["ic_bajo"]) / 2 / det["costo_pred"]).mean()))
        filas.append(fila)
    tabla = pd.DataFrame(filas).sort_values("error_medio_pct").reset_index(drop=True)
    ruta = carpeta / "comparacion_modelos.csv"
    tabla.to_csv(ruta, index=False, encoding="utf-8")
    return tabla, ruta


def main(argv=None):
    p = argparse.ArgumentParser(description="Compara los modelos de regresión del curso como modelo sustituto.")
    p.add_argument("--salida", default=None, help="carpeta de resultados (por defecto resultados/)")
    a = p.parse_args(argv)
    tabla, ruta = comparar(a.salida)
    pd.set_option("display.width", 200)
    print(tabla.round(3).to_string(index=False))
    print(f"\n-> {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
