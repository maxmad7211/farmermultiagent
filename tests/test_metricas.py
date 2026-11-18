"""Pruebas de la función de costo, la estadística y la sensibilidad económica."""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from siembra import metricas  # noqa: E402
from siembra.config import aplicar, cargar_config  # noqa: E402

PASO_S = 3600 / 273.6  # celda de 0.01 ha a 2.736 ha/h -> 2736 pasos por jornada de 10 h
PASOS_DIA = 2736


@pytest.fixture
def cfg():
    return cargar_config()


def resumen_a_mano(**cambios):
    """100 celdas de trabajo (1 ha), todas sembradas en el paso 2736 (día 1)."""
    r = {
        "mecanismo": "M1", "n_tractores": 2, "celda_m": 10, "paso_s": PASO_S,
        "ha_sembrables": 1.0, "n_celdas_trabajo": 100, "n_sembradas": 100, "n_no_sembradas": 0,
        "suma_t_siembra_pasos": 100 * PASOS_DIA, "H_motor_h": 2.0, "colisiones": 0,
        "diesel_l": 10.0, "W_ocio_h": 5.0, "T_pasos": PASOS_DIA,
    }
    r.update({c: float(PASOS_DIA) for c in metricas.CUANTILES})
    r.update(cambios)
    return r


def test_pesos_del_caso_base(cfg):
    eco, agr = cfg["economia"], cfg["agronomia"]
    lambda_R = eco["rendimiento_t_ha"] * agr["perdida_dia"] * eco["precio_maiz"]
    assert lambda_R == pytest.approx(195.536)
    lambda_H = eco["precio_tractor"] * eco["reparacion_frac"] / eco["vida_h"]
    assert lambda_H == pytest.approx(66.25)
    assert eco["precio_tractor"] / eco["temporadas_vida"] == pytest.approx(39_750)


def test_costos_resumen_a_mano(cfg):
    c = metricas.costos(resumen_a_mano(), cfg)
    assert set(c) == set(metricas.LLAVES_COSTO)
    assert all(isinstance(v, float) for v in c.values())
    # 1 ha sembrada 1 día después de la fecha óptima -> 1 ha·día
    assert c["R_ha_dia"] == pytest.approx(1.0)
    assert c["costo_R"] == pytest.approx(195.536)
    assert c["costo_H"] == pytest.approx(2 * 66.25)
    assert c["costo_colisiones"] == 0
    assert c["costo_diesel"] == pytest.approx(270.0)
    assert c["costo_no_sembrada"] == 0
    assert c["J"] == pytest.approx(195.536 + 132.5 + 270.0)  # W_ocio pesa 0
    assert c["costo_propiedad"] == pytest.approx(2 * 39_750)
    assert c["costo_ha"] == pytest.approx(79_500 + 195.536 + 132.5 + 270.0)
    assert c["T_dias_calendario"] == pytest.approx(1.0)
    assert c["pct_en_ventana"] == pytest.approx(1.0)


def test_colisiones_y_no_sembradas(cfg):
    c = metricas.costos(resumen_a_mano(colisiones=2, n_no_sembradas=10, n_sembradas=90,
                                       suma_t_siembra_pasos=90 * PASOS_DIA), cfg)
    assert c["costo_colisiones"] == pytest.approx(2 * 39_750)
    # 10 celdas = 0.1 ha × 8.08 t/ha × $6,050/t × 100 %
    assert c["costo_no_sembrada"] == pytest.approx(0.1 * 8.08 * 6050)
    assert c["pct_en_ventana"] == pytest.approx(0.9)


def test_dias_laborables_y_jornada_sin_volver_a_simular(cfg):
    base = metricas.costos(resumen_a_mano(), cfg)
    lluvia = metricas.costos(resumen_a_mano(), aplicar(cfg, {"escala_tiempo.dias_laborables": 0.5}))
    assert lluvia["R_ha_dia"] == pytest.approx(2 * base["R_ha_dia"])
    assert lluvia["T_dias_calendario"] == pytest.approx(2.0)
    # Jornada de 20 h: el mismo paso es medio día
    larga = metricas.costos(resumen_a_mano(), aplicar(cfg, {"escala_tiempo.jornada_h": 20}))
    assert larga["R_ha_dia"] == pytest.approx(0.5)
    assert larga["T_dias_calendario"] == pytest.approx(0.5)


def test_pct_en_ventana_interpola_cuantiles(cfg):
    # Cuantiles lineales de 0 a 2·W (W = paso del día 30): la mitad se siembra dentro de la ventana
    W = 30 * PASOS_DIA
    q = {c: p * 2 * W for c, p in zip(metricas.CUANTILES, metricas.PROB_CUANTILES)}
    c = metricas.costos(resumen_a_mano(**q, n_sembradas=90, n_no_sembradas=10), cfg)
    assert c["pct_en_ventana"] == pytest.approx(0.5 * 0.9)
    # Con ventana de 15 días entra la cuarta parte
    c15 = metricas.costos(resumen_a_mano(**q), aplicar(cfg, {"agronomia.ventana_dias": 15}))
    assert c15["pct_en_ventana"] == pytest.approx(0.25)
    # Todo antes de la ventana y todo después
    assert metricas.costos(resumen_a_mano(**{k: 10.0 for k in metricas.CUANTILES}), cfg)["pct_en_ventana"] == 1.0
    tarde = {k: 2.0 * W for k in metricas.CUANTILES}
    assert metricas.costos(resumen_a_mano(**tarde), cfg)["pct_en_ventana"] == 0.0
    # Nada sembrado: 0 aunque los cuantiles sean NaN
    nada = resumen_a_mano(n_sembradas=0, **{k: np.nan for k in metricas.CUANTILES})
    assert metricas.costos(nada, cfg)["pct_en_ventana"] == 0.0


def test_costos_acepta_fila_de_csv(cfg, tmp_path):
    ruta = tmp_path / "r.csv"
    pd.DataFrame([resumen_a_mano(), resumen_a_mano(n_tractores=3)]).to_csv(ruta, index=False)
    df = pd.read_csv(ruta)
    c = metricas.costos(df.iloc[1], cfg)
    assert c["costo_propiedad"] == pytest.approx(3 * 39_750)
    con = metricas.agregar_costos(df, cfg)
    assert list(con["costo_propiedad"]) == pytest.approx([79_500, 119_250])
    assert con["costo_ha"].iloc[0] == pytest.approx(metricas.costos(resumen_a_mano(), cfg)["costo_ha"])


def test_agregar_costos_escala_de_fila(cfg):
    df = pd.DataFrame([resumen_a_mano(jornada_h=10, dias_laborables=1.0),
                       resumen_a_mano(jornada_h=10, dias_laborables=0.5)])
    fijo = metricas.agregar_costos(df, cfg)
    assert fijo["R_ha_dia"].tolist() == pytest.approx([1.0, 1.0])
    por_fila = metricas.agregar_costos(df, cfg, escala_de_fila=True)
    assert por_fila["R_ha_dia"].tolist() == pytest.approx([1.0, 2.0])


def test_sensibilidad_precio_maiz_proporcional(cfg):
    r = resumen_a_mano(suma_t_siembra_pasos=12_345 * 7, n_no_sembradas=3)
    base = metricas.costos(r, cfg)
    caro = metricas.costos(r, aplicar(cfg, {"economia.precio_maiz": 7200}))
    assert caro["costo_R"] / base["costo_R"] == pytest.approx(7200 / 6050)
    assert caro["costo_no_sembrada"] / base["costo_no_sembrada"] == pytest.approx(7200 / 6050)
    assert caro["costo_H"] == pytest.approx(base["costo_H"])


def barrido_sintetico(cfg):
    """Barrido pequeño: con más tractores se siembra antes pero se paga más propiedad."""
    filas = []
    rng = np.random.default_rng(0)
    for mec in ("M0", "M1"):
        for ha in (10, 80):
            for n in (1, 2, 3):
                for s in range(4):
                    celdas = ha * 100
                    t_fin = celdas * 8 / n * (1.1 if mec == "M0" else 1.0) * rng.uniform(0.95, 1.05)
                    q = {c: p * t_fin for c, p in zip(metricas.CUANTILES, metricas.PROB_CUANTILES)}
                    r = resumen_a_mano(mecanismo=mec, hectareas=ha, n_tractores=n, semilla=s,
                                       ha_sembrables=float(ha), n_celdas_trabajo=celdas, n_sembradas=celdas,
                                       suma_t_siembra_pasos=celdas * t_fin / 2, T_pasos=t_fin,
                                       H_motor_h=ha * 0.73, diesel_l=ha * 7.7, **q)
                    r.update(metricas.costos(r, cfg))
                    filas.append(r)
    return pd.DataFrame(filas)


def test_sensibilidad_economica(cfg):
    df = barrido_sintetico(cfg)
    sens = metricas.sensibilidad_economica(df, cfg)
    assert list(sens.columns[:8]) == ["parametro", "nivel", "valor", "mecanismo", "hectareas",
                                      "n_tractores", "costo_ha_media", "n_optimo"]
    assert set(sens["parametro"]) == set(metricas.RANGOS_SENSIBILIDAD)
    assert len(sens) == len(metricas.RANGOS_SENSIBILIDAD) * 3 * 2 * 2 * 3
    # Nivel base = costo del barrido
    base = sens[(sens.parametro == "economia.precio_maiz") & (sens.nivel == "base")]
    esperado = df.groupby(["mecanismo", "hectareas", "n_tractores"])["costo_ha"].mean().to_numpy()
    assert base["costo_ha_media"].to_numpy() == pytest.approx(esperado)
    # Tractor más caro -> costo más alto; la ventana no cambia el costo pero sí pct_en_ventana
    pt = sens[sens.parametro == "economia.precio_tractor"].pivot_table(
        index=["mecanismo", "hectareas", "n_tractores"], columns="nivel", values="costo_ha_media")
    assert (pt["alto"] > pt["base"]).all() and (pt["bajo"] < pt["base"]).all()
    ven = sens[sens.parametro == "agronomia.ventana_dias"].pivot_table(
        index=["mecanismo", "hectareas", "n_tractores"], columns="nivel", values="costo_ha_media")
    assert np.allclose(ven["alto"], ven["base"]) and np.allclose(ven["bajo"], ven["base"])
    # n_optimo es el N de menor costo medio en cada combinación
    for _, g in sens.groupby(["parametro", "nivel", "mecanismo", "hectareas"]):
        assert g["n_optimo"].nunique() == 1
        assert g["n_optimo"].iloc[0] == g.loc[g["costo_ha_media"].idxmin(), "n_tractores"]


def test_resumen_ic():
    df = pd.DataFrame({"g": ["a"] * 5 + ["b"], "x": [1, 2, 3, 4, 5, 7.0], "y": [1, 1, 1, 1, 1, np.nan]})
    largo = metricas.resumen_ic(df, ["x", "y"], "g")
    fila = largo[(largo.g == "a") & (largo.metrica == "x")].iloc[0]
    assert fila["media"] == 3 and fila["n"] == 5
    assert fila["de"] == pytest.approx(math.sqrt(2.5))
    assert fila["ic95"] == pytest.approx(2.7764451 * math.sqrt(2.5) / math.sqrt(5), rel=1e-6)
    assert fila["ic_bajo"] == pytest.approx(3 - fila["ic95"])
    b = largo[(largo.g == "b") & (largo.metrica == "x")].iloc[0]
    assert b["n"] == 1 and np.isnan(b["ic95"])
    assert largo[(largo.g == "b") & (largo.metrica == "y")].iloc[0]["n"] == 0
    ancho = metricas.resumen_ic(df, ["x", "y"], "g", formato="ancho")
    assert {"x_media", "x_ic_bajo", "x_ic_alto", "y_n"} <= set(ancho.columns)
    assert len(ancho) == 2


def test_prueba_pareada():
    rng = np.random.default_rng(1)
    base = rng.normal(100, 5, 12)
    df = pd.DataFrame({
        "mecanismo": ["M0"] * 12 + ["M1"] * 12, "semilla": list(range(12)) * 2,
        "hectareas": 20, "costo_ha": np.concatenate([base, base - 5 + rng.normal(0, 0.5, 12)]),
    })
    r = metricas.prueba_pareada(df, "costo_ha", "M0", "M1", por="hectareas").iloc[0]
    assert r["n"] == 12
    assert r["diferencia_media"] == pytest.approx(-5, abs=0.5)
    assert r["ic_bajo"] < r["diferencia_media"] < r["ic_alto"] < 0
    assert r["p_t"] < 1e-6 and r["p_wilcoxon"] < 0.001


def test_prueba_pareada_casos_limite():
    iguales = pd.DataFrame({"mecanismo": ["M0", "M0", "M2", "M2"], "semilla": [0, 1, 0, 1],
                            "colisiones": [0, 0, 0, 0]})
    r = metricas.prueba_pareada(iguales, "colisiones", "M0", "M2").iloc[0]
    assert np.isnan(r["p_t"]) and np.isnan(r["p_wilcoxon"])
    assert "0" in r["nota"] and r["diferencia_media"] == 0
    uno = pd.DataFrame({"mecanismo": ["M0", "M1", "M1"], "semilla": [0, 0, 1], "costo_ha": [1.0, 2.0, 3.0]})
    r = metricas.prueba_pareada(uno, "costo_ha", "M0", "M1").iloc[0]
    assert r["n"] == 1 and np.isnan(r["p_t"]) and "sin pareja" in r["nota"]


def test_optimo_por_campo(cfg):
    df = barrido_sintetico(cfg)
    opt = metricas.optimo_por_campo(df)
    assert len(opt) == 4
    medias = df.groupby(["mecanismo", "hectareas", "n_tractores"])["costo_ha"].mean()
    for _, fila in opt.iterrows():
        sub = medias.loc[(fila["mecanismo"], fila["hectareas"])]
        assert fila["n_optimo"] == sub.idxmin()
        assert fila["media"] == pytest.approx(sub.min())
        assert fila["ic_bajo"] <= fila["media"] <= fila["ic_alto"]
    # En 10 ha conviene 1 tractor (la propiedad domina); en 80 ha, más de uno
    assert (opt[opt.hectareas == 10]["n_optimo"] == 1).all()
    assert (opt[opt.hectareas == 80]["n_optimo"] > 1).all()
