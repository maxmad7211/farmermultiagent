"""Pruebas de `siembra.viz` y del dashboard con datos sintéticos.

Los datos se generan en una carpeta temporal con el mismo pipeline que produce `resultados/`
(`siembra.experimentos.correr`) pero con `siembra.telemetria.corrida_sintetica` como simulador,
así que tienen exactamente el formato del contrato (`docs/contrato_datos.md`). Una copia de una
corrida se «enriquece» con un obstáculo, un tractor fuera de servicio y fila en la estación para
cubrir esas partes de los mapas.

Uso extra (revisión visual):

    python tests/test_viz.py --muestras CARPETA   # genera datos sintéticos y todas las figuras en PNG

La ejecución completa del notebook tarda alrededor de un minuto; para saltarla:
`SIEMBRA_SALTAR_NOTEBOOK=1 python -m pytest tests/test_viz.py`.
"""

import copy
import importlib.util
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from siembra import viz  # noqa: E402

SIMULADOR_SINTETICO = "siembra.telemetria:corrida_sintetica"


# --------------------------------------------------------------------------------- datos

def generar_resultados(carpeta, semillas=2):
    """Escribe en `carpeta` los CSV y las corridas detalladas con el formato del contrato."""
    from siembra import experimentos

    from siembra import sustituto

    experimentos.correr(modo="rapido", semillas=semillas, nucleos=1, salida=carpeta,
                        simulador=SIMULADOR_SINTETICO, verbose=False)
    # Modelo sustituto con el mismo simulador falso y lo mínimo para llenar la sección 5
    sustituto.correr(carpeta, modo="rapido", iteraciones=1, ha_por_iteracion=1, semillas=2, prueba_ha=2,
                     prueba_semillas=1, nucleos=1, simulador=SIMULADOR_SINTETICO, verbose=False)
    spec = importlib.util.spec_from_file_location("comparar_modelos", RAIZ / "herramientas" / "comparar_modelos.py")
    comparar_modelos = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(comparar_modelos)
    comparar_modelos.comparar(carpeta)
    return Path(carpeta)


def enriquecer(c):
    """Copia de la corrida con un obstáculo 2×2, el último tractor fuera de servicio desde el 70 %
    del tiempo y un tractor en la fila de la estación durante un tramo."""
    c = {k: (v.copy() if isinstance(v, pd.DataFrame) else copy.deepcopy(v)) for k, v in c.items()}
    campo, cel = c["campo"], c["celdas"]
    x0, y0 = 3, int(campo["y0"]) + 5
    for k in ("tipo_base", "t_surcado", "t_sembrado", "pasadas"):
        cel[k] = np.array(cel[k], copy=True)
    cel["tipo_base"][x0:x0 + 2, y0:y0 + 2] = viz.TIPO_OBSTACULO
    cel["t_surcado"][x0:x0 + 2, y0:y0 + 2] = -1
    cel["t_sembrado"][x0:x0 + 2, y0:y0 + 2] = -1
    cel["pasadas"][x0:x0 + 2, y0:y0 + 2] = 0
    campo["obstaculos"] = [[x0, y0, 2, 2, "arbol"]]
    pasos = c["pasos"]
    T = int(pasos["t"].max())
    ultimo = sorted(pasos["agente"].unique(), key=viz._orden_agente)[-1]
    falla = (pasos["agente"] == ultimo) & (pasos["t"] > 0.7 * T)
    t_falla = int(pasos.loc[falla, "t"].min())
    x_f, y_f = pasos.loc[(pasos["agente"] == ultimo) & (pasos["t"] == t_falla), ["x", "y"]].iloc[0]
    pasos.loc[falla, ["estado", "intencion", "x", "y"]] = ["fuera_servicio", "ninguna", x_f, y_f]
    serie = c["serie"]
    tramo = (serie["t"] > 0.2 * T) & (serie["t"] < 0.3 * T)
    serie.loc[tramo, "fila_estacion"] = 1
    c["resumen"].update({"falla_activa": True, "n_obstaculos": 1})
    c["id"] = c.get("id", "sintetica") + "_enriquecida"
    return c


@pytest.fixture(scope="session")
def resultados(tmp_path_factory):
    return generar_resultados(tmp_path_factory.mktemp("resultados_sinteticos"))


@pytest.fixture(scope="session")
def tablas(resultados):
    return {n: pd.read_csv(resultados / f) for n, f in (
        ("barrido", "barrido.csv"), ("esc", "escenarios.csv"), ("sens", "sens_arquitectura.csv"),
        ("curvas", "curvas.csv"))}


@pytest.fixture(scope="session")
def corridas(resultados):
    from siembra.telemetria import cargar_corrida

    out = {}
    for d in sorted((resultados / "corridas").iterdir()):
        out[d.name] = cargar_corrida(d)
        out[d.name]["id"] = d.name
    out["enriquecida"] = enriquecer(out["falla_20ha_4t_M1_s0"])
    return out


@pytest.fixture(autouse=True)
def _estilo():
    viz.estilo()
    yield
    plt.close("all")


def _es_figura(fig):
    assert isinstance(fig, Figure)
    fig.canvas.draw()  # dibuja de verdad: detecta errores que solo salen al renderizar
    plt.close(fig)


# ---------------------------------------------------------------------- panel del entorno

@pytest.mark.parametrize("cid", ["normal_20ha_2t_M1_s0", "normal_40ha_3t_obst_M2_s0", "enriquecida"])
def test_mapa_campo(corridas, cid):
    c = corridas[cid]
    T = int(c["resumen"]["T_pasos"])
    _es_figura(viz.mapa_campo(None, c, T // 2))
    _es_figura(viz.mapa_campo(None, c, 0, etiquetas="nombre"))
    _es_figura(viz.mapa_campo(None, c, T, etiquetas=None, leyenda=False))


def test_mapa_campo_en_ax_existente(corridas):
    fig, ax = plt.subplots()
    assert viz.mapa_campo(ax, corridas["normal_20ha_2t_M0_s0"], 10) is fig
    _es_figura(fig)


def test_estado_celdas_reconstruye_y_no_retrocede(corridas):
    c = corridas["enriquecida"]
    cel = c["celdas"]
    T = int(c["resumen"]["T_pasos"])
    anterior = viz.estado_celdas(cel, 0)
    base = np.asarray(cel["tipo_base"])
    assert set(np.unique(anterior)) <= {0, 1, 2, 3, 4, 5}
    assert (anterior[base == viz.TIPO_OBSTACULO] == 5).all()
    for t in np.linspace(0, T, 6).astype(int):
        actual = viz.estado_celdas(cel, t)
        trabajo = base == viz.TIPO_TRABAJO
        assert (actual[trabajo] >= anterior[trabajo]).all()  # libre -> surcada -> sembrada
        assert (actual[~trabajo] == base[~trabajo]).all()
        anterior = actual
    tm = np.asarray(cel["t_sembrado"])
    assert viz.fraccion_sembrada(cel, T) == pytest.approx(((tm >= 0) & (base == 2)).sum() / (base == 2).sum())


def test_secuencia_y_trayectorias(corridas):
    _es_figura(viz.secuencia_estados(corridas["normal_20ha_2t_M1_s0"]))
    _es_figura(viz.secuencia_estados(corridas["enriquecida"], fracciones=(0.5, 1.0)))
    _es_figura(viz.mapa_trayectorias(None, corridas["enriquecida"]))
    fig, ax = plt.subplots()
    _es_figura(viz.mapa_trayectorias(ax, corridas["normal_20ha_2t_M0_s0"]))


def test_mapas_de_calor(corridas):
    for c in (corridas["normal_20ha_2t_M1_s0"], corridas["enriquecida"]):
        _es_figura(viz.mapa_pasadas(None, c))
        _es_figura(viz.mapa_edad(None, c))
    trio = [corridas[f"falla_20ha_4t_{m}_s0"] for m in ("M0", "M1", "M2")]
    _es_figura(viz.mapas_comparados(trio, "pasadas"))
    _es_figura(viz.mapas_comparados(trio + [corridas["enriquecida"]], "edad"))
    with pytest.raises(ValueError):
        viz.mapas_comparados(trio, "otro")


def test_animacion_jshtml_y_gif(corridas, tmp_path):
    anim = viz.animacion(corridas["enriquecida"], n_cuadros=5, dpi=40)
    html = viz.animacion_html(anim, dpi=30)
    assert "data:image" in html or "<img" in html
    assert len(html) < len(viz.animacion_html(anim, dpi=60))  # el dpi sí controla el tamaño
    ruta = viz.guardar_gif(anim, tmp_path / "anim.gif", fps=5)
    plt.close(anim._fig)
    from PIL import Image

    with Image.open(ruta) as im:
        assert im.n_frames == 5


# ------------------------------------------------------------------- panel de indicadores

def test_tarjetas_y_actividad(corridas):
    c = corridas["enriquecida"]
    _es_figura(viz.tarjetas_kpi(c["resumen"], "falla_20ha_4t"))
    _es_figura(viz.tarjetas_kpi({}))  # sin datos: tarjetas con «—», sin errores
    _es_figura(viz.barras_actividad(None, c["pasos"], c["resumen"]))
    _es_figura(viz.actividad_comparada([corridas["normal_20ha_2t_M0_s0"], c]))


def test_horas_por_actividad_suma_los_pasos(corridas):
    c = corridas["normal_20ha_2t_M1_s0"]
    tabla = viz.horas_por_actividad(c["pasos"], c["resumen"])
    assert list(tabla.columns) == list(viz.GRUPOS_ACTIVIDAD)
    T = c["resumen"]["T_pasos"]
    p = c["pasos"][c["pasos"]["t"] <= T]
    esperados = p["estado"].map(viz.GRUPO_DE_ESTADO).notna().sum()
    paso_h = c["resumen"]["paso_s"] / 3600
    assert tabla.to_numpy().sum() == pytest.approx(esperados * paso_h)


def test_tabla_comparativa_e_ic(tablas):
    esc = tablas["esc"]
    t = viz.tabla_comparativa(esc, ["costo_ha", "T_h", "cobertura"], por=["escenario", "mecanismo"])
    assert t.index.names == ["escenario", "mecanismo"]
    assert "Costo por hectárea ($/ha)" in t.columns and "±" in t.iloc[0]["Tiempo total T (h)"]
    # El IC coincide con la t de Student
    from scipy import stats

    x = np.array([1.0, 2.0, 4.0, 7.0])
    media, lo, hi = viz.ic95(x)
    h = stats.t.ppf(0.975, 3) * x.std(ddof=1) / 2
    assert (media, lo, hi) == pytest.approx((3.5, 3.5 - h, 3.5 + h))
    assert viz.ic95([5.0])[1] == 5.0
    assert np.isnan(viz.ic95([])[0])


def test_tablas_de_condiciones_y_parametros(tablas, corridas):
    cond = viz.tabla_condiciones(tablas["esc"], "escenario")
    assert "normal_20ha_2t" in cond.index and "mecanismos" in cond.columns
    params = viz.tabla_parametros(corridas["normal_20ha_2t_M1_s0"]["parametros"])
    assert {"parámetro", "valor", "fuente"} <= set(params.columns)
    assert (params["parámetro"] == "economia.precio_tractor").any()
    kpi = viz.tabla_kpi(list(corridas.values()))
    assert len(kpi) == len(corridas) and "Costo ($/ha)" in kpi.columns
    malo = tablas["esc"].copy()
    malo.loc[malo.index[0], "cobertura"] = 0.5
    cc = viz.control_calidad(malo, "escenario")
    assert len(cc) == 1 and cc["incompletas"].iloc[0] == 1


def test_texto_parametros(corridas):
    c = corridas["enriquecida"]
    txt = viz.texto_parametros(c["resumen"], viz.escenario_de(c))
    for parte in ("M1", "20 ha", "N = 4", "semilla 0", "escenario falla_20ha_4t", "falla de un tractor",
                  "1 obstáculo"):
        assert parte in txt
    assert viz.escenario_de({"id": "normal_40ha_3t_obst_M2_s0"}) == "normal_40ha_3t_obst"


# ------------------------------------------------------------------- panel de comunicación

def test_comunicacion(corridas, tablas):
    m1, m2, m0 = (corridas[f"falla_20ha_4t_{m}_s0"] for m in ("M1", "M2", "M0"))
    _es_figura(viz.serie_performativas([m0, m1, m2]))
    _es_figura(viz.serie_performativas(m1))
    _es_figura(viz.perdidos_y_reanuncios(tablas["sens"]))
    _es_figura(viz.hileras_por_tractor(None, m1))
    _es_figura(viz.hileras_comparadas([m0, m1, corridas["enriquecida"]]))
    _es_figura(viz.serie_estacion([m0, m1, corridas["enriquecida"]]))
    _es_figura(viz.serie_reservas([m2, corridas["normal_40ha_3t_obst_M2_s0"]]))
    p = corridas["perdida30_20ha_4t_M1_s0"]
    _es_figura(viz.linea_tiempo_subasta(None, p["mensajes"], None, p["resumen"]))
    _es_figura(viz.linea_tiempo_subasta(None, m0["mensajes"], None, m0["resumen"]))  # M0: sin subastas


def _log(filas):
    cols = ["t_envio", "t_entrega", "performativa", "emisor", "receptor", "evento", "tipo_tarea", "x",
            "ronda", "u", "perdido"]
    return pd.DataFrame(filas, columns=cols)


def test_subasta_elige_ronda_y_agrega_reanuncio():
    nan = np.nan
    log = _log([
        # ronda 1: un solo postor, completa
        (0, 0, "cfp", "DEP", "T1", "", "surcar", -1, 1, nan, False),
        (1, 1, "propose", "T1", "DEP", "", "surcar", 3, 1, 990, False),
        (3, 3, "accept-proposal", "DEP", "T1", "", "", 3, 1, nan, False),
        # ronda 2: dos postores, la adjudicación a T2 se pierde
        (10, 10, "cfp", "DEP", "T2", "", "sembrar", -1, 2, nan, False),
        (10, 11, "cfp", "DEP", "T3", "", "sembrar", -1, 2, nan, False),
        (11, 11, "propose", "T2", "DEP", "", "sembrar", 5, 2, 980, False),
        (11, 12, "propose", "T3", "DEP", "", "sembrar", 5, 2, 950, False),
        (13, 13, "accept-proposal", "DEP", "T2", "", "", 5, 2, nan, True),
        (13, 13, "reject-proposal", "DEP", "T3", "", "", -1, 2, nan, False),
        # ronda 3: reanuncio de la hilera 5 a T2
        (20, 20, "cfp", "DEP", "T2", "", "sembrar", -1, 3, nan, False),
        (21, 21, "propose", "T2", "DEP", "", "sembrar", 5, 3, 975, False),
        (23, 23, "accept-proposal", "DEP", "T2", "", "", 5, 3, nan, False),
        (24, 24, "inform", "T2", "DEP", "inicio", "sembrar", 5, -1, nan, False),
        (70, 70, "inform", "T2", "DEP", "fin", "sembrar", 5, -1, nan, False),
        (71, 71, "inform", "T1", "DEP", "fin", "surcar", 3, -1, nan, False),
    ])
    assert viz.elegir_ronda(log) == 2
    sel, rondas = viz.mensajes_subasta(log, 2)
    assert rondas == [2, 3]
    assert set(sel["ronda"]) == {2, 3, -1}
    assert set(sel.loc[sel["ronda"] == -1, "evento"]) == {"inicio", "fin"}  # solo los de T2 y x = 5
    assert (sel["t_envio"].diff().dropna() >= 0).all()
    _es_figura(viz.linea_tiempo_subasta(None, log, None, {"paso_s": 13.2, "mecanismo": "M1"}))
    assert viz.elegir_ronda(log.iloc[0:0]) is None


# --------------------------------------------------------------------- panel experimental

def test_panel_experimental(tablas):
    bar, esc, sens, cur = tablas["barrido"], tablas["esc"], tablas["sens"], tablas["curvas"]
    _es_figura(viz.curvas_costo(bar))
    _es_figura(viz.curvas_costo(bar[bar["hectareas"] == 20]))
    for m in ("costo_ha", "T_h", "W_ocio_h", "cobertura"):
        _es_figura(viz.barras_escenarios(esc, m))
    _es_figura(viz.barras_escenarios(esc, "costo_ha", escenarios=["normal_20ha_2t", "no_existe"]))
    _es_figura(viz.diferencias_pareadas(esc, "costo_ha"))
    _es_figura(viz.curvas_cobertura(cur, "normal_20ha_2t"))
    _es_figura(viz.curvas_cobertura(cur, "no_existe"))
    _es_figura(viz.cobertura_por_escenario(cur, nombres={"normal_20ha_2t": "Normal"}))
    _es_figura(viz.histograma_T(esc, "normal_20ha_2t"))
    _es_figura(viz.histograma_T(bar[bar["hectareas"] == 20], metrica="costo_ha"))
    _es_figura(viz.sens_arquitectura(sens))
    _es_figura(viz.sens_arquitectura(sens, fila_costo=False))


def test_tornado_con_sensibilidad_economica(tablas):
    from siembra import metricas
    from siembra.config import cargar_config

    se = metricas.sensibilidad_economica(tablas["barrido"], cargar_config())
    norm = viz._normalizar_sens_eco(se[(se["mecanismo"] == "M1") & (se["hectareas"] == 20)])
    assert {"costo_bajo", "costo_base", "costo_alto", "n_opt_base"} <= set(norm.columns)
    assert norm["parametro"].is_unique
    _es_figura(viz.tornado(se, "M1", 20))
    _es_figura(viz.tornado(se, "M0", 20, n_tractores=2))


def test_colores_siguen_a_la_entidad():
    assert viz.COLOR_MECANISMO == {"M0": "#2a78d6", "M1": "#eb6834", "M2": "#1baf7a"}
    assert viz.COLOR_CELDA["sembrada"] == "#3f8f3f" and viz.COLOR_CELDA["obstaculo"] == "#383835"
    assert viz.COLOR_ACTIVIDAD["Estación"] == "#eda100"
    # Filtrar mecanismos no cambia el color de los que quedan
    assert viz._color_mecanismo("M2") == "#1baf7a"
    assert viz._mecanismos(pd.DataFrame({"mecanismo": ["M2", "M0"]})) == ["M0", "M2"]


# ------------------------------------------------------------------------------- notebook

def _modulo_dashboard():
    spec = importlib.util.spec_from_file_location("construir_dashboard",
                                                  RAIZ / "herramientas" / "construir_dashboard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_notebook_se_construye(tmp_path):
    import nbformat

    mod = _modulo_dashboard()
    nb = mod.construir(tmp_path / "dashboard.ipynb")
    nbformat.validate(nb)
    texto = "\n".join(c.source for c in nb.cells if c.cell_type == "markdown")
    posiciones = [texto.index(s) for s in ("## 0. Datos", "## 1. Panel del entorno", "## 2. Panel de indicadores",
                                           "## 3. Panel de comunicación", "## 4. Panel experimental")]
    assert posiciones == sorted(posiciones)
    assert "python -m siembra.experimentos --modo rapido" in texto


saltar_notebook = pytest.mark.skipif(os.environ.get("SIEMBRA_SALTAR_NOTEBOOK") == "1",
                                     reason="SIEMBRA_SALTAR_NOTEBOOK=1")


@saltar_notebook
def test_notebook_sin_datos_se_detiene_con_instrucciones(tmp_path, monkeypatch):
    from nbclient.exceptions import CellExecutionError

    mod = _modulo_dashboard()
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    monkeypatch.setenv("SIEMBRA_RESULTADOS", str(vacia))
    nb = mod.construir(tmp_path / "dashboard.ipynb")
    with pytest.raises(CellExecutionError) as e:
        mod.ejecutar(nb, tmp_path / "dashboard.ipynb", vacia, timeout=300)
    assert "python -m siembra.experimentos --modo rapido" in str(e.value)


@saltar_notebook
def test_notebook_con_datos_parciales_avisa_y_termina(tmp_path, resultados, monkeypatch):
    import shutil

    mod = _modulo_dashboard()
    parcial = tmp_path / "parcial"
    (parcial / "corridas").mkdir(parents=True)
    shutil.copy(resultados / "escenarios.csv", parcial)
    shutil.copytree(resultados / "corridas" / "normal_20ha_2t_M0_s0", parcial / "corridas" / "normal_20ha_2t_M0_s0")
    monkeypatch.setenv("SIEMBRA_RESULTADOS", str(parcial))
    nb = mod.ejecutar(mod.construir(tmp_path / "dashboard.ipynb"), tmp_path / "dashboard.ipynb", parcial,
                      timeout=600)
    salidas = "\n".join(str(o) for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", []))
    assert "Falta información" in salidas
    assert "error" not in {o.get("output_type") for c in nb.cells if c.cell_type == "code"
                           for o in c.get("outputs", [])}


@saltar_notebook
def test_notebook_completo_y_html(tmp_path, resultados, monkeypatch):
    mod = _modulo_dashboard()
    monkeypatch.setenv("SIEMBRA_RESULTADOS", str(resultados))
    ruta_nb = tmp_path / "dashboard.ipynb"
    nb = mod.ejecutar(mod.construir(ruta_nb), ruta_nb, resultados, timeout=1200)
    salidas = [o for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", [])]
    assert not [o for o in salidas if o.get("output_type") == "error"]
    avisos = [str(o) for o in salidas if "Falta información" in str(o)]
    assert not avisos, avisos
    figuras = resultados / "figuras"
    for nombre in ("entorno_mapa_campo.png", "animacion_campo.gif", "indicadores_tarjetas.png",
                   "comunicacion_subasta.png", "experimental_curvas_costo.png",
                   "experimental_sens_arquitectura.png", "experimental_tornado_M1_20ha.png",
                   "ml_n_optimo.png", "ml_costos.png", "ml_evaluacion.png", "ml_mapa_perdida_dia.png"):
        assert (figuras / nombre).exists(), nombre
    html = mod.exportar_html(nb, resultados / "dashboard.html")
    assert html.stat().st_size > 100_000


# ------------------------------------------------------------------- muestras para revisar

def generar_muestras(carpeta):
    """Genera datos sintéticos en `carpeta/datos` y todas las figuras en `carpeta/figuras`."""
    from siembra import metricas
    from siembra.config import cargar_config
    from siembra.telemetria import cargar_corrida

    carpeta = Path(carpeta)
    res = generar_resultados(carpeta / "datos")
    figs = carpeta / "figuras"
    viz.estilo()
    C = {}
    for d in sorted((res / "corridas").iterdir()):
        C[d.name] = cargar_corrida(d)
        C[d.name]["id"] = d.name
    e = enriquecer(C["falla_20ha_4t_M1_s0"])
    bar, esc = pd.read_csv(res / "barrido.csv"), pd.read_csv(res / "escenarios.csv")
    sens, cur = pd.read_csv(res / "sens_arquitectura.csv"), pd.read_csv(res / "curvas.csv")
    trio = [C[f"falla_20ha_4t_{m}_s0"] for m in ("M0", "M1", "M2")]
    T = int(e["resumen"]["T_pasos"])
    figuras = {
        "mapa_campo": lambda: viz.mapa_campo(None, e, int(0.75 * T)),
        "secuencia": lambda: viz.secuencia_estados(e),
        "trayectorias": lambda: viz.mapa_trayectorias(None, e),
        "pasadas": lambda: viz.mapa_pasadas(None, e),
        "edad": lambda: viz.mapa_edad(None, e),
        "comparados_edad": lambda: viz.mapas_comparados(trio, "edad"),
        "kpi": lambda: viz.tarjetas_kpi(e["resumen"], "falla_20ha_4t"),
        "actividad": lambda: viz.actividad_comparada(trio + [e]),
        "performativas": lambda: viz.serie_performativas(trio),
        "perdidos": lambda: viz.perdidos_y_reanuncios(sens),
        "hileras": lambda: viz.hileras_comparadas(trio + [e]),
        "estacion": lambda: viz.serie_estacion(trio + [e]),
        "reservas": lambda: viz.serie_reservas([C["normal_20ha_2t_M2_s0"], C["normal_40ha_3t_obst_M2_s0"]]),
        "subasta": lambda: viz.linea_tiempo_subasta(None, C["perdida30_20ha_4t_M1_s0"]["mensajes"], None,
                                                    C["perdida30_20ha_4t_M1_s0"]["resumen"]),
        "curvas_costo": lambda: viz.curvas_costo(bar),
        "barras_costo": lambda: viz.barras_escenarios(esc, "costo_ha"),
        "diferencias": lambda: viz.diferencias_pareadas(esc, "costo_ha"),
        "cobertura": lambda: viz.cobertura_por_escenario(cur),
        "histograma": lambda: viz.histograma_T(esc, "normal_20ha_2t"),
        "tornado": lambda: viz.tornado(metricas.sensibilidad_economica(bar, cargar_config()), "M1", 20),
        "sens_arq": lambda: viz.sens_arquitectura(sens),
    }
    for nombre, f in figuras.items():
        fig = f()
        viz.guardar(fig, nombre, figs)
        plt.close(fig)
    anim = viz.animacion(e, n_cuadros=20)
    viz.guardar_gif(anim, figs / "animacion.gif", fps=5)
    plt.close(anim._fig)
    return figs


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--muestras":
        print(f"Figuras en {generar_muestras(sys.argv[2])}")
    else:
        print(__doc__)
