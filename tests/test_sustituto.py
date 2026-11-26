"""Pruebas del modelo sustituto (`siembra.sustituto`) y de sus gráficas.

Usan un simulador analítico (`simulador_analitico`) cuyo costo verdadero se conoce, así que se
puede comprobar que el modelo recupera el N óptimo y el tamaño donde cambia. Corre en segundos:
no usa la simulación de AgentPy.
"""

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from siembra import metricas, sustituto as su, viz  # noqa: E402
from siembra.config import aplicar, cargar_config, derivados, lado_campo  # noqa: E402

# El simulador falso se pasa a `experimentos` como 'modulo:funcion'. Algunas dependencias instalan
# un paquete llamado `tests` que tapa esta carpeta, así que el módulo se registra con nombre propio
# (las pruebas corren con nucleos=1, en este mismo proceso).
sys.modules.setdefault("sustituto_simulador_prueba", sys.modules[__name__])
SIMULADOR = "sustituto_simulador_prueba:simulador_analitico"
ATORADA = (37, 3)  # (ha, N) donde el simulador falso se "atora"


# --------------------------------------------------------------------------- simulador falso

def _t_verdadero(ha, n, mec):
    """Paso medio de siembra verdadero: proporcional a ha/N con un leve efecto de escala."""
    return 200.0 * ha / n * (1 + 0.05 * math.log(ha)) * (1 + 0.03 * ("M0", "M1", "M2").index(mec))


def _H_verdadero(ha):
    return 0.9 + 0.002 * ha


def simulador_analitico(cfg, detalle=False):
    """Misma firma que `siembra.modelo.simular`; devuelve solo el resumen que usa el sustituto."""
    ha, n, mec = cfg["campo"]["hectareas"], cfg["flota"]["n_tractores"], cfg["mecanismo"]
    rng = np.random.default_rng(cfg["semilla"] * 1000 + int(ha) * 10 + n)
    lado = lado_campo(cfg)
    celdas = lado ** 2
    ha_s = celdas * cfg["campo"]["celda_m"] ** 2 / 10_000
    t = _t_verdadero(ha, n, mec) * (1 + 0.005 * rng.standard_normal())
    H = _H_verdadero(ha) * ha_s
    atorada = (int(ha), int(n)) == ATORADA
    sembradas = celdas // 2 if atorada else celdas
    d = derivados(cfg)
    r = {
        "mecanismo": mec, "hectareas": ha, "n_tractores": n, "semilla": cfg["semilla"],
        "ha_sembrables": ha_s, "n_celdas_trabajo": celdas, "n_sembradas": sembradas,
        "n_no_sembradas": celdas - sembradas, "cobertura": sembradas / celdas, "estancado": atorada,
        "suma_t_siembra_pasos": t * sembradas, "H_motor_h": H, "diesel_l": 10.5 * H, "colisiones": 0,
        "paso_s": d["paso_s"], "pasos_dia": d["pasos_dia"], "celda_m": cfg["campo"]["celda_m"],
        "T_pasos": 2 * t, "jornada_h": cfg["escala_tiempo"]["jornada_h"],
        "dias_laborables": cfg["escala_tiempo"]["dias_laborables"],
    }
    return {"resumen": r}


def costo_verdadero(cfg, ha, n, mec):
    a, b, c = su.coeficientes_costo(cfg, [ha], [n], 10.5)
    return float(a[0] + b[0] * _t_verdadero(ha, n, mec) + c[0] * _H_verdadero(ha))


def barrido_falso(cfg, hectareas=(10, 20, 40, 80, 160), ns=(1, 2, 3, 4), mecs=("M0", "M2"), semillas=3):
    filas = []
    for ha in hectareas:
        for n in ns:
            for mec in mecs:
                for s in range(semillas):
                    c = aplicar(cfg, {"campo.hectareas": ha, "flota.n_tractores": n, "mecanismo": mec, "semilla": s})
                    r = simulador_analitico(c)["resumen"]
                    r.update(metricas.costos(r, c))
                    filas.append({"grupo": "barrido", **r})
    return pd.DataFrame(filas)


@pytest.fixture(scope="module")
def cfg():
    return cargar_config()


@pytest.fixture(scope="module")
def barrido(cfg):
    return barrido_falso(cfg)


# Las pruebas del modelo corren con los dos modelos sustitutos: Random Forest (por defecto) y
# proceso gaussiano. Las tolerancias son por modelo: los árboles no interpolan entre puntos.
TOLERANCIA = {"rf": {"entrenamiento": 0.03, "interpolacion": 0.03, "cruce_ha": 6},
              "gp": {"entrenamiento": 0.01, "interpolacion": 0.02, "cruce_ha": 1}}


@pytest.fixture(scope="module", params=["rf", "gp"])
def modelo(request, cfg, barrido):
    return su.crear(request.param, cfg).ajustar(barrido)


@pytest.fixture(scope="module")
def analisis(cfg, modelo):
    return su.analizar(modelo, cfg, rangos={"agronomia.perdida_dia": (0.002, 0.006)}, n_valores=3)


# --------------------------------------------------------------------------- datos

def test_validas_descarta_corridas_atoradas(cfg):
    df = barrido_falso(cfg, hectareas=(20, 37), ns=(2, 3), mecs=("M0",), semillas=2)
    v = su.validas(df)
    assert len(v) == len(df) - 2
    assert not ((v["hectareas"] == 37) & (v["n_tractores"] == 3)).any()


def test_preparar_agrega_por_configuracion(barrido):
    t = su.preparar(barrido)
    assert len(t) == 5 * 4 * 2
    assert (t["n"] == 3).all()
    assert (t["y_retraso_var"] > 0).all()
    # costo observado = media del costo por hectárea de las semillas
    g = barrido.groupby(["mecanismo", "hectareas", "n_tractores"])["costo_ha"].mean()
    fila = t.iloc[0]
    assert fila["costo_obs"] == pytest.approx(g[(fila["mecanismo"], fila["hectareas"], fila["n_tractores"])])


def test_caracteristicas_y_geometria(cfg):
    g = su.geometria([10, 20, 160], cfg)
    assert list(g["lado"]) == [32, 45, 126]
    tolva = derivados(cfg)["tolva_celdas"]
    assert list(g["filas_tolva"]) == [tolva // 32, tolva // 45, tolva // 126]
    X = su.caracteristicas([20, 20], [1, 3], cfg, n_categorias=4)
    assert X.shape == (2, 3 + 4)
    assert X[0, 3:].tolist() == [1, 0, 0, 0] and X[1, 3:].tolist() == [0, 0, 1, 0]
    assert X[0, 0] == pytest.approx(math.log(20))


def test_costo_se_reconstruye_con_la_funcion_del_proyecto(cfg, barrido):
    """costo_ha = a + b·t_medio + c·H_ha reproduce exactamente metricas.costos."""
    r = barrido.iloc[7]
    a, b, c = su.coeficientes_costo(cfg, [r["hectareas"]], [r["n_tractores"]], r["diesel_l"] / r["H_motor_h"])
    t = r["suma_t_siembra_pasos"] / r["n_sembradas"]
    H = r["H_motor_h"] / r["ha_sembrables"]
    assert a[0] + b[0] * t + c[0] * H == pytest.approx(r["costo_ha"], rel=1e-9)


# --------------------------------------------------------------------------- modelo

def test_modelo_predice_puntos_de_entrenamiento(cfg, modelo):
    d = modelo.datos
    for mec in modelo.mecanismos:
        g = d[d["mecanismo"] == mec]
        media, _bajo, _alto = su.predecir_costo(modelo, mec, g["hectareas"], g["n_tractores"], cfg)
        assert np.max(np.abs(media / g["costo_obs"].to_numpy() - 1)) < TOLERANCIA[modelo.clave]["entrenamiento"]


def test_modelo_interpola_tamanos_no_vistos(cfg, modelo):
    for ha in (15, 30, 60, 120):
        for n in (1, 2, 4):
            media, bajo, alto = su.predecir_costo(modelo, "M0", [ha], [n], cfg)
            real = costo_verdadero(cfg, ha, n, "M0")
            assert abs(media[0] / real - 1) < TOLERANCIA[modelo.clave]["interpolacion"], (ha, n)


def test_n_maximo_fijo_no_crece(cfg, barrido):
    extra = barrido_falso(cfg, hectareas=(160,), ns=(5,), mecs=("M0",), semillas=2)
    libre = su.Sustituto(cfg).ajustar(pd.concat([barrido, extra]))
    fijo = su.Sustituto(cfg, n_max=6).ajustar(pd.concat([barrido, extra]))
    assert libre.n_max == 7 and fijo.n_max == 6


def test_muestras_reproducibles(cfg, modelo):
    a = modelo.muestras("M0", [25, 50], [1, 2], k=20, semilla=3)
    b = modelo.muestras("M0", [25, 50], [1, 2], k=20, semilla=3)
    np.testing.assert_array_equal(a["y_retraso"], b["y_retraso"])


def test_crear_y_modelo_por_defecto(cfg, barrido):
    assert su.MODELO_POR_DEFECTO == "rf" and su.Sustituto is su.SustitutoRF
    assert isinstance(su.crear("gp", cfg), su.SustitutoGP)
    with pytest.raises(ValueError, match="modelo debe ser"):
        su.crear("svm", cfg)


def test_random_forest_muestras_son_sus_arboles(cfg, barrido):
    rf = su.crear("rf", cfg).ajustar(barrido)
    m = rf.muestras("M0", [25, 50], [1, 2], k=su.SustitutoRF.ARBOLES)
    assert m["y_retraso"].shape == (su.SustitutoRF.ARBOLES, 2)
    media, de = rf.predecir("M0", [25, 50], [1, 2])["y_retraso"]
    np.testing.assert_allclose(m["y_retraso"].mean(axis=0), media)
    assert (de > 0).all()
    pocas = rf.muestras("M0", [25], [1], k=20, semilla=4)
    np.testing.assert_array_equal(pocas["H_ha"], rf.muestras("M0", [25], [1], k=20, semilla=4)["H_ha"])


def test_sin_corridas_validas_falla_con_mensaje(cfg, barrido):
    malo = barrido.assign(estancado=True)
    with pytest.raises(ValueError, match="no hay corridas válidas"):
        su.Sustituto(cfg).ajustar(malo)


# --------------------------------------------------------------------------- análisis

def test_analizar_columnas_y_probabilidades(analisis, modelo):
    o = analisis["optimo"]
    pcols = [f"p_N{n}" for n in range(1, modelo.n_max + 1)]
    np.testing.assert_allclose(o[pcols].sum(axis=1), 1.0)
    assert set(analisis["curva"].columns) >= {"mecanismo", "hectareas", "n_tractores", "costo_ha", "ic_bajo",
                                               "ic_alto", "extrapolado"}
    assert analisis["curva"].query("n_tractores > 4")["extrapolado"].all()
    assert set(analisis["mapa"]["parametro"]) == {"agronomia.perdida_dia"}


def test_n_optimo_coincide_con_el_verdadero(cfg, analisis):
    o = analisis["optimo"]
    for ha in (12, 25, 50, 100, 150):
        fila = o[(o["mecanismo"] == "M0") & (o["hectareas"] == ha)].iloc[0]
        real = min(range(1, 5), key=lambda n: costo_verdadero(cfg, ha, n, "M0"))
        assert fila["n_optimo"] == real, ha


def test_cruces_contienen_el_verdadero(cfg, analisis, modelo):
    hs = np.arange(10, 161)
    n_real = np.array([min(range(1, 5), key=lambda n: costo_verdadero(cfg, h, n, "M0")) for h in hs])
    cambios = hs[1:][np.diff(n_real) != 0]
    c = analisis["cruces"]
    c = c[c["mecanismo"] == "M0"]
    assert len(c) == len(cambios)
    for (_, fila), h in zip(c.iterrows(), cambios):
        holgura = TOLERANCIA[modelo.clave]["cruce_ha"]
        assert fila["ic_bajo"] - holgura <= h <= fila["ic_alto"] + holgura
        assert fila["ic_bajo"] <= fila["hectareas"] <= fila["ic_alto"]


def test_mapa_mas_perdida_mas_tractores(analisis):
    m = analisis["mapa"]
    m = m[(m["mecanismo"] == "M0") & (m["hectareas"] == 120)].sort_values("valor")
    assert m["n_optimo"].is_monotonic_increasing


# --------------------------------------------------------------------------- evaluación y activo

def test_evaluar_contra_prueba(cfg, modelo):
    prueba = barrido_falso(cfg, hectareas=(15, 30, 37, 60), ns=(1, 2, 3, 4), mecs=("M0",), semillas=2)
    det, res = su.evaluar(modelo, prueba, cfg, etiqueta="x")
    assert len(det) == 4 * 4 - 1  # la configuración atorada no tiene corridas válidas
    fila = res.iloc[0]
    assert fila["error_abs_medio_pct"] < 2
    assert fila["acierto_n_optimo"] == 1.0
    assert fila["sobrecosto_medio_ha"] == pytest.approx(0.0)


def test_atorados(cfg):
    df = barrido_falso(cfg, hectareas=(20, 37), ns=(2, 3), mecs=("M0",), semillas=2)
    a = su.atorados(df)
    assert len(a) == 1
    assert a.iloc[0][["hectareas", "n_tractores", "corridas", "atoradas"]].tolist() == [37, 3, 2, 2]


def test_proponer_elige_tamanos_cerca_de_un_cruce(cfg, modelo, analisis):
    c = analisis["cruces"]
    cruces = c[c["mecanismo"] == "M0"]["hectareas"].to_numpy(dtype=float)
    puntos = su.proponer(modelo, "M0", range(10, 161), set(), ha_por_iteracion=1, cfg=cfg, umbral=0.0)
    assert puntos
    # el tamaño con más duda queda junto a alguno de los cambios de N óptimo
    assert min(abs(math.log(puntos[0]["hectareas"] / x)) for x in cruces) < 0.15
    assert len({p["n_tractores"] for p in puntos}) >= 2
    # no vuelve a proponer lo ya simulado
    ya = {("M0", p["hectareas"], p["n_tractores"]) for p in puntos}
    otra = su.proponer(modelo, "M0", [puntos[0]["hectareas"]], ya, ha_por_iteracion=1, cfg=cfg, umbral=0.0)
    assert not {(p["hectareas"], p["n_tractores"]) for p in otra} & {(h, n) for _m, h, n in ya}


def test_tamanos_prueba_excluye_y_es_reproducible():
    a = su.tamanos_prueba(10, 160, 6, excluir=[10, 20, 40, 80, 160])
    assert a == su.tamanos_prueba(10, 160, 6, excluir=[10, 20, 40, 80, 160])
    assert len(a) == 6 and not set(a) & {10, 20, 40, 80, 160}
    assert all(10 <= h <= 160 for h in a)


def test_flujo_completo_escribe_archivos(tmp_path, cfg, barrido):
    barrido.to_csv(tmp_path / "barrido.csv", index=False)
    s = su.correr(tmp_path, modo="rapido", iteraciones=1, ha_por_iteracion=1, semillas=2, prueba_ha=3,
                  prueba_semillas=1, nucleos=1, simulador=SIMULADOR, verbose=False)
    assert s["meta"]["modelo"] == "rf" and s["meta"]["modelo_nombre"] == "Random Forest"
    carpeta = tmp_path / su.CARPETA
    for nombre, archivo in su.ARCHIVOS.items():
        assert (carpeta / archivo).exists(), nombre
    assert s["n_errores"] == 0
    assert set(s["evaluacion"]["modelo"]) == {"solo barrido", "barrido + activo"}
    v = pd.read_csv(carpeta / "verificacion.csv")
    assert {"iteracion", "costo_pred", "costo_obs", "error_pct", "dentro_ic"} <= set(v.columns)
    assert (pd.read_csv(carpeta / "activo.csv")["grupo"] == "activo").all()
    # El modelo guardado es el que generó la curva, y reentrenarlo con los CSV da el mismo modelo
    guardado = su.cargar_modelo(carpeta / su.ARCHIVOS["modelo"])
    curva = pd.read_csv(carpeta / "curva.csv")
    fila = curva[curva["mecanismo"] == "M0"].iloc[len(curva) // 6]
    r = su.consultar(guardado, "M0", fila["hectareas"])
    assert r["flotas"][int(fila["n_tractores"]) - 1]["costo_ha"] == pytest.approx(fila["costo_ha"], rel=1e-12)
    rehecho = su.reconstruir_modelo(tmp_path)
    assert su.consultar(rehecho, "M0", fila["hectareas"]) == r


def test_cli_guardar_modelo(tmp_path, barrido, capsys):
    assert su.main(["--guardar-modelo", "--salida", str(tmp_path)]) == 2
    barrido.to_csv(tmp_path / "barrido.csv", index=False)
    assert su.main(["--guardar-modelo", "--salida", str(tmp_path)]) == 0
    assert (tmp_path / su.CARPETA / su.ARCHIVOS["modelo"]).exists()
    assert "Modelo guardado" in capsys.readouterr().out


def test_cli_sin_barrido_devuelve_2(tmp_path, capsys):
    assert su.main(["--salida", str(tmp_path)]) == 2
    assert "barrido.csv" in capsys.readouterr().err


# --------------------------------------------------------------------------- guardar y consultar

def test_guardar_y_cargar_predice_igual(tmp_path, modelo):
    ruta = su.guardar_modelo(modelo, tmp_path / "modelo.joblib")
    cargado = su.cargar_modelo(ruta)
    assert cargado.clave == modelo.clave
    for mec in modelo.mecanismos:
        assert su.consultar(cargado, mec, 57) == su.consultar(modelo, mec, 57)


def test_consultar_coincide_con_analizar(modelo, analisis):
    # Random Forest es determinista: da exactamente lo de curva.csv y optimo.csv. Las muestras del
    # proceso gaussiano son conjuntas para los puntos que se piden, así que solo coinciden de cerca.
    exacto = modelo.clave == "rf"
    curva, optimo = analisis["curva"], analisis["optimo"]
    for mec in modelo.mecanismos:
        r = su.consultar(modelo, mec, 57)
        assert sum(f["p_optimo"] for f in r["flotas"]) == pytest.approx(1)
        costos = [f["costo_ha"] for f in r["flotas"]]
        assert r["n_recomendado"] == int(np.argmin(costos)) + 1
        assert all(f["ic_bajo"] <= f["ic_alto"] for f in r["flotas"])
        c = curva[(curva["mecanismo"] == mec) & (curva["hectareas"] == 57)].sort_values("n_tractores")
        np.testing.assert_allclose(costos, c["costo_ha"], rtol=1e-12 if exacto else 1e-3)
        o = optimo[(optimo["mecanismo"] == mec) & (optimo["hectareas"] == 57)].iloc[0]
        assert r["n_recomendado"] == o["n_optimo"]
        assert r["p_recomendado"] == pytest.approx(o["p_optimo"], abs=0 if exacto else 0.15)
        d = su.n_optimo_por_tamano(modelo, mec)
        o_mec = optimo[optimo["mecanismo"] == mec].sort_values("hectareas")
        iguales = (d["n_optimo"].to_numpy() == o_mec["n_optimo"].to_numpy()).mean()
        assert iguales == 1 if exacto else iguales >= 0.95
        if exacto:
            np.testing.assert_allclose(d["p_optimo"], o_mec["p_optimo"])


def test_consultar_valida_rango_y_precios(modelo):
    assert not su.consultar(modelo, "M0", 57)["fuera_de_rango"]
    assert su.consultar(modelo, "M0", 300)["fuera_de_rango"]
    base = su.consultar(modelo, "M0", 57)["flotas"][0]["costo_ha"]
    caro = su.consultar(modelo, "M0", 57, {"economia.precio_maiz": 9000})["flotas"][0]["costo_ha"]
    assert caro > base   # más caro el maíz, más cuesta el retraso
    for mec, ha in (("M9", 57), ("M0", 0), ("M0", float("nan"))):
        with pytest.raises(ValueError):
            su.consultar(modelo, mec, ha)
    with pytest.raises(ValueError):
        su.consultar(modelo, "M0", [20, 40])


def test_cambios_de_parametros_llegan_al_costo(cfg, modelo):
    # Cada parámetro de la interfaz debe dar lo mismo que el mapa de sensibilidad de `analizar`
    rangos = {"escala_tiempo.jornada_h": (8, 14), "escala_tiempo.dias_laborables": (0.6, 1.0),
              "economia.precio_diesel": (15, 40), "economia.precio_tractor": (600_000, 900_000),
              "economia.temporadas_vida": (10, 30), "economia.rendimiento_t_ha": (6, 10)}
    mapa = su.analizar(modelo, cfg, rangos=rangos, n_valores=2)["mapa"]
    mec = modelo.mecanismos[0]
    for ruta, (bajo, _alto) in rangos.items():
        esperado = mapa[(mapa["mecanismo"] == mec) & (mapa["parametro"] == ruta) & (mapa["valor"] == bajo)]
        d = su.n_optimo_por_tamano(modelo, mec, cambios={ruta: bajo})
        assert (d["n_optimo"].to_numpy() == esperado.sort_values("hectareas")["n_optimo"].to_numpy()).all(), ruta
        fila = esperado.iloc[len(esperado) // 2]
        r = su.consultar(modelo, mec, fila["hectareas"], {ruta: bajo})
        # consultar pide un solo tamaño: con el proceso gaussiano sus muestras no son las de la rejilla
        tolerancia = 1e-9 if modelo.clave == "rf" else 1e-3
        assert min(f["costo_ha"] for f in r["flotas"]) == pytest.approx(fila["costo_ha"], rel=tolerancia), ruta
    # Una jornada más corta alarga el retraso en días y lo encarece
    corta = su.consultar(modelo, mec, 80, {"escala_tiempo.jornada_h": 8})["flotas"][0]["costo_ha"]
    larga = su.consultar(modelo, mec, 80, {"escala_tiempo.jornada_h": 14})["flotas"][0]["costo_ha"]
    assert corta > larga


def test_reconstruir_usa_el_modelo_de_la_ultima_corrida(tmp_path, barrido):
    barrido.to_csv(tmp_path / "barrido.csv", index=False)
    (tmp_path / su.CARPETA).mkdir()
    (tmp_path / su.CARPETA / su.ARCHIVOS["meta"]).write_text('{"modelo": "gp"}', encoding="utf-8")
    assert su.reconstruir_modelo(tmp_path).clave == "gp"
    assert su.reconstruir_modelo(tmp_path, modelo="rf").clave == "rf"


# --------------------------------------------------------------------------- interfaz

def _peticion(url, datos=None, encabezados=None):
    import json
    import urllib.request

    cuerpo = None if datos is None else (datos if isinstance(datos, bytes) else json.dumps(datos).encode())
    req = urllib.request.Request(url, data=cuerpo, method="POST" if cuerpo is not None else "GET",
                                 headers={"Content-Type": "application/json", **(encabezados or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_interfaz_servidor(cfg, barrido):
    import json
    import threading

    from siembra import interfaz

    sust = su.crear("rf", cfg).ajustar(barrido)
    srv = interfaz.crear_servidor(sust, puerto=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        codigo, html = _peticion(base + "/")
        assert codigo == 200 and b"<title>" in html
        codigo, info = _peticion(base + "/api/info")
        info = json.loads(info)
        assert codigo == 200 and [m["clave"] for m in info["mecanismos"]] == sust.mecanismos
        assert info["n_max"] == sust.n_max and info["corridas"] == int(sust.datos["n"].sum())
        cambios = {"economia.precio_maiz": 7000}
        codigo, r = _peticion(base + "/api/predecir", {"mecanismo": "M0", "hectareas": 57, "parametros": cambios})
        r = json.loads(r)
        assert codigo == 200
        directo = su.consultar(sust, "M0", 57, cambios)
        assert r["flotas"] == directo["flotas"] and r["n_recomendado"] == directo["n_recomendado"]
        assert len(r["por_tamano"]) == int(sust.ha_max - sust.ha_min) + 1
        malas = [{"mecanismo": "M9", "hectareas": 57}, {"mecanismo": "M0", "hectareas": 0},
                 {"mecanismo": "M0", "hectareas": True}, {"mecanismo": "M0", "hectareas": 57, "parametros": {"x.y": 1}},
                 {"mecanismo": "M0", "hectareas": 57, "parametros": {"economia.precio_maiz": -1}}, [1, 2], b"no es json",
                 b'{"mecanismo": "M0", "hectareas": ' + b"9" * 400 + b"}",
                 b'{"mecanismo": "M0", "hectareas": ' + b"9" * 5000 + b"}",
                 b'{"mecanismo": "M0", "hectareas": NaN}']
        for mala in malas:
            codigo, cuerpo = _peticion(base + "/api/predecir", mala)
            assert codigo == 400 and "error" in json.loads(cuerpo), mala
        assert _peticion(base + "/otra")[0] == 404
        ok = {"mecanismo": "M0", "hectareas": 57}
        assert _peticion(base + "/api/predecir", ok, {"Content-Type": "text/plain"})[0] == 415
        assert _peticion(base + "/api/predecir", ok, {"Host": "sitio-ajeno.com"})[0] == 403
        assert _peticion(base + "/api/info", None, {"Host": "sitio-ajeno.com"})[0] == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_interfaz_reentrena_si_no_hay_modelo(tmp_path, barrido):
    from siembra import interfaz

    barrido.to_csv(tmp_path / "barrido.csv", index=False)
    sust, ruta = interfaz.preparar_modelo(tmp_path, verbose=False)
    assert ruta.exists() and sust.clave == "rf"
    cargado, _ = interfaz.preparar_modelo(tmp_path, verbose=False)
    assert su.consultar(cargado, "M0", 30) == su.consultar(sust, "M0", 30)


# --------------------------------------------------------------------------- gráficas

def test_graficas(cfg, barrido, modelo, analisis):
    prueba = barrido_falso(cfg, hectareas=(15, 30, 60), ns=(1, 2, 3, 4), mecs=("M0", "M2"), semillas=2)
    det, _res = su.evaluar(modelo, prueba, cfg, etiqueta="solo barrido")
    verif = det.assign(iteracion=1).head(5)
    figuras = [
        viz.sustituto_optimo(analisis["optimo"], analisis["cruces"], metricas.optimo_por_campo(barrido)),
        viz.sustituto_costos(analisis["curva"], su.preparar(barrido)),
        viz.sustituto_evaluacion(det, verif),
        viz.sustituto_mapa(analisis["mapa"], "agronomia.perdida_dia", base=0.004),
    ]
    for f in figuras:
        assert isinstance(f, plt.Figure)
        plt.close(f)
    assert viz.color_n(1) != viz.color_n(4)
