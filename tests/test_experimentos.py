"""Pruebas del armado y la ejecución de experimentos con un simulador falso (sin el modelo)."""

import sys
import types
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from siembra import experimentos, metricas, telemetria  # noqa: E402
from siembra.config import cargar_config  # noqa: E402

SINTETICO = "siembra.telemetria:corrida_sintetica"


@pytest.fixture
def stub_modelo(monkeypatch):
    """Reemplaza siembra.modelo por un módulo falso cuyo simular devuelve la corrida sintética.

    Las corridas con semilla 1 de 10 ha fallan a propósito para probar errores.log.
    """
    llamadas = []

    def simular(cfg, detalle=False):
        llamadas.append((cfg["mecanismo"], cfg["campo"]["hectareas"], cfg["flota"]["n_tractores"],
                         cfg["semilla"], detalle))
        if cfg["campo"]["hectareas"] == 10 and cfg["semilla"] == 1:
            raise RuntimeError("falla de prueba")
        return telemetria.corrida_sintetica(cfg, detalle=detalle)

    modulo = types.ModuleType("siembra.modelo")
    modulo.simular = simular
    monkeypatch.setitem(sys.modules, "siembra.modelo", modulo)
    return llamadas


def test_numero_de_tareas_modo_rapido():
    cfg = cargar_config()
    n = {e: len(experimentos.armar_tareas(e, "rapido", cfg_base=cfg)) for e in experimentos.EXPERIMENTOS}
    assert n["barrido"] == 4 * 4 * 3 * 5          # hectáreas × N × mecanismo × semillas
    assert n["escenarios"] == 8 * 3 * 5 + 1 * 3 * 2  # el de 160 ha con lluvia usa 2 semillas
    assert n["sens"] == (4 * 2 + 5 * 3 + 3 + 3) * 5
    assert n["detalladas"] == 3 + 3 + 1 + 1


def test_numero_de_tareas_modo_completo_y_semillas():
    cfg = cargar_config()
    assert len(experimentos.armar_tareas("barrido", "completo", cfg_base=cfg)) == 1200
    assert len(experimentos.armar_tareas("escenarios", "completo", cfg_base=cfg)) == 9 * 3 * 20
    assert len(experimentos.armar_tareas("sens", "completo", cfg_base=cfg)) == 29 * 10
    assert len(experimentos.armar_tareas("escenarios", "rapido", semillas=3, cfg_base=cfg)) == 9 * 3 * 3


def test_tareas_bien_formadas(tmp_path):
    cfg = cargar_config()
    barrido = experimentos.armar_tareas("barrido", "rapido", cfg_base=cfg)
    assert len({t.id for t in barrido}) == len(barrido)
    # Mismas semillas 0..S-1 para los tres mecanismos en cada combinación
    semillas = {}
    for t in barrido:
        clave = (t.cambios["campo.hectareas"], t.cambios["flota.n_tractores"])
        semillas.setdefault(clave, {}).setdefault(t.cambios["mecanismo"], set()).add(t.semilla)
    for por_mec in semillas.values():
        assert set(por_mec) == {"M0", "M1", "M2"}
        assert all(s == set(range(5)) for s in por_mec.values())

    esc = {t.etiquetas["escenario"]: t for t in experimentos.armar_tareas("escenarios", "rapido", cfg_base=cfg)}
    assert esc["tolva_mitad_20ha_4t"].cambios["agente.tolva_ha"] == cfg["agente"]["tolva_ha"] / 2
    assert esc["limite_1t_160ha_lluvia"].cambios["escala_tiempo.dias_laborables"] == 0.6
    assert esc["falla_20ha_4t"].cambios["falla.activa"] is True
    assert esc["normal_40ha_3t_obst"].cambios["campo.n_obstaculos"] == 2
    assert all(t.etiquetas["escenario_nombre"] for t in esc.values())

    sens = experimentos.armar_tareas("sens", "rapido", cfg_base=cfg)
    por_param = Counter((t.etiquetas["parametro"], t.cambios["mecanismo"]) for t in sens)
    assert por_param[("comunicacion.timeout_ofertas", "M0")] == 0
    assert por_param[("comunicacion.timeout_ofertas", "M1")] == 4 * 5
    assert por_param[("comunicacion.perdida_mensajes", "M0")] == 5 * 5
    assert por_param[("comunicacion.ventana_reservas", "M2")] == 3 * 5
    assert all(t.cambios["campo.hectareas"] == 20 and t.cambios["flota.n_tractores"] == 4 for t in sens)

    det = experimentos.armar_tareas("detalladas", "rapido", cfg_base=cfg, salida=tmp_path)
    ids = {t.id for t in det}
    assert "normal_20ha_2t_M1_s0" in ids and "perdida30_20ha_4t_M1_s0" in ids and "normal_40ha_3t_obst_M2_s0" in ids
    assert all(t.detalle and t.semilla == 0 and Path(t.carpeta).parent == tmp_path / "corridas" for t in det)


def test_correr_modo_rapido_con_stub(stub_modelo, tmp_path):
    salidas = experimentos.correr(modo="rapido", semillas=2, nucleos=1, salida=tmp_path, verbose=False)

    # barrido: 4 ha × 4 N × 3 mecanismos × 2 semillas, menos las 12 de 10 ha con semilla 1 que fallan
    barrido = pd.read_csv(tmp_path / "barrido.csv")
    assert len(barrido) == 4 * 4 * 3 * 2 - 4 * 3
    assert set(metricas.LLAVES_RESUMEN) | {"grupo"} <= set(barrido.columns)
    assert (barrido["grupo"] == "barrido").all()
    assert salidas["n_errores"] == 12 + 3  # barrido + limite_4t_10ha (3 mecanismos, semilla 1)
    log = (tmp_path / "errores.log").read_text(encoding="utf-8")
    assert "falla de prueba" in log and "barrido_10ha_1t_M0_s1" in log and "Traceback" in log

    esc = pd.read_csv(tmp_path / "escenarios.csv")
    assert set(metricas.LLAVES_RESUMEN) | {"grupo", "escenario", "escenario_nombre"} <= set(esc.columns)
    assert (esc["grupo"] == "escenario").all()
    assert esc["escenario"].nunique() == 9
    lluvia = esc[esc.escenario == "limite_1t_160ha_lluvia"]
    assert (lluvia["dias_laborables"] == 0.6).all() and (lluvia["hectareas"] == 160).all()

    curvas = pd.read_csv(tmp_path / "curvas.csv")
    assert list(curvas.columns) == list(experimentos.COLUMNAS_CURVAS)
    por_corrida = curvas.groupby(["escenario", "mecanismo", "semilla"]).size()
    assert len(por_corrida) == len(esc) and por_corrida.max() <= 200
    fila = esc.iloc[0]
    c = curvas[(curvas.escenario == fila.escenario) & (curvas.mecanismo == fila.mecanismo)
               & (curvas.semilla == fila.semilla)]
    assert c["t_h"].to_numpy() == pytest.approx(c["t"].to_numpy() * fila.paso_s / 3600)
    assert c["sembrado_frac"].iloc[-1] == pytest.approx(1.0)

    sens = pd.read_csv(tmp_path / "sens_arquitectura.csv")
    assert set(metricas.LLAVES_RESUMEN) | {"grupo", "parametro", "valor"} <= set(sens.columns)
    assert (sens["grupo"] == "sens_arq").all()
    assert len(sens) == 29 * 2
    to = sens[sens.parametro == "comunicacion.timeout_ofertas"]
    assert (to["timeout_ofertas"] == to["valor"]).all()

    for id_ in ("normal_20ha_2t_M0_s0", "normal_20ha_2t_M1_s0", "normal_20ha_2t_M2_s0", "falla_20ha_4t_M2_s0",
                "normal_40ha_3t_obst_M2_s0", "perdida30_20ha_4t_M1_s0"):
        carpeta = tmp_path / "corridas" / id_
        assert {p.name for p in carpeta.iterdir()} == set(telemetria.ARCHIVOS), id_
    assert telemetria.validar_unity(tmp_path / "corridas" / "perdida30_20ha_4t_M1_s0" / "unity.json")[0]
    assert len([d for d in (tmp_path / "corridas").iterdir()]) == 8

    # Las detalladas se piden con detalle=True y semilla 0; las demás sin detalle
    detalladas = [llamada for llamada in stub_modelo if llamada[-1]]
    assert len(detalladas) == 8 and all(s == 0 for _, _, _, s, _ in detalladas)


def test_costos_se_agregan_si_el_resumen_no_los_trae(monkeypatch, tmp_path):
    def simular(cfg, detalle=False):
        res = telemetria.corrida_sintetica(cfg, detalle=detalle)
        for k in metricas.LLAVES_COSTO:
            res["resumen"].pop(k)
        return res

    modulo = types.ModuleType("siembra.modelo")
    modulo.simular = simular
    monkeypatch.setitem(sys.modules, "siembra.modelo", modulo)
    salidas = experimentos.correr(["sens"], semillas=1, nucleos=1, salida=tmp_path, verbose=False)
    assert salidas["n_errores"] == 0
    assert salidas["sens_arq"]["costo_ha"].notna().all()


def test_paralelo_con_spawn(tmp_path):
    """El pool de procesos funciona en Windows (spawn) y da lo mismo que en serie."""
    tareas = experimentos.armar_tareas("barrido", "rapido", semillas=1, simulador=SINTETICO)[:6]
    serie = experimentos.ejecutar(tareas, nucleos=1, verbose=False)
    paralelo = experimentos.ejecutar(tareas, nucleos=2, verbose=False)
    assert all(r["ok"] for r in serie + paralelo), [r.get("error") for r in paralelo if not r["ok"]]
    for a, b in zip(serie, paralelo):
        assert a["fila"]["costo_ha"] == pytest.approx(b["fila"]["costo_ha"])
        assert a["fila"]["n_tractores"] == b["fila"]["n_tractores"]


def test_cli_sin_simulador_devuelve_2(tmp_path, capsys):
    codigo = experimentos.main(["--solo", "barrido", "--salida", str(tmp_path),
                                "--simulador", "siembra.no_existe:simular"])
    assert codigo == 2
    assert "No se pudo importar" in capsys.readouterr().err


def test_cli_con_simulador_sintetico(tmp_path, capsys):
    codigo = experimentos.main(["--solo", "sens", "--semillas", "1", "--nucleos", "1",
                                "--salida", str(tmp_path), "--simulador", SINTETICO])
    assert codigo == 0
    salida = capsys.readouterr().out
    assert "[sens] 29/29" in salida
    assert (tmp_path / "sens_arquitectura.csv").exists()
