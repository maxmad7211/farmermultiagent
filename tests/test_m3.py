"""Pruebas del coordinador supervisor (M3) y de los eventos que maneja (docs/m3.md).

Revisan las reglas de la propuesta M3 — seguridad primero, nunca descartar un reporte real, nadie
entra a la zona prohibida, no se repite trabajo tras una falla y toda decisión lleva su motivo.
También revisan que M0, M1 y M2 no cambien mientras los eventos estén apagados.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa — E402
import pytest  # noqa — E402

from siembra import experimentos, telemetria, viz  # noqa — E402
from siembra.config import ErrorConfig, aplicar, cargar_config, validar  # noqa — E402
from siembra.modelo import simular  # noqa — E402


def correr(mecanismo="M3", n=4, ha=10, semilla=0, detalle=False, **extra):
    cambios = {"campo.hectareas": ha, "flota.n_tractores": n, "mecanismo": mecanismo, "semilla": semilla}
    cambios.update(extra)
    return simular(aplicar(cargar_config(), cambios), detalle=detalle)


def sin_violaciones(r):
    assert r["colisiones"] == 0
    assert r["intercambios"] == 0
    assert r["entradas_prohibidas"] == 0
    assert r["entradas_fuego"] == 0
    assert r["reales_descartados"] == 0


# ------------------------------------------------------------------ M0, M1 y M2 no cambian

@pytest.mark.parametrize("mec", ["M0", "M1", "M2"])
def test_sin_eventos_no_hay_salidas_de_m3(mec):
    res = correr(mec, n=2, ha=3)
    assert "eventos" not in res and "registro" not in res
    assert "area_quemada_ha" not in res["resumen"]


def test_config_sin_secciones_m3_sigue_valida():
    cfg = cargar_config()
    cfg.pop("coordinador")
    cfg.pop("eventos")
    validar(cfg)
    r = simular(aplicar(cfg, {"campo.hectareas": 3, "flota.n_tractores": 2, "mecanismo": "M3"}))["resumen"]
    assert r["cobertura"] == 1.0


def test_validacion_m3():
    base = cargar_config()
    validar(aplicar(base, {"mecanismo": "M3"}))
    with pytest.raises(ErrorConfig, match="alcance_pipa"):
        validar(aplicar(base, {"coordinador.alcance_pipa": 2, "coordinador.margen_zona_max": 2}))
    with pytest.raises(ErrorConfig, match="prob_propagacion"):
        validar(aplicar(base, {"eventos.incendio.prob_propagacion": 1.5}))


# ------------------------------------------------------------------ M3 sin eventos

@pytest.mark.parametrize("n", [1, 2, 4])
def test_m3_sin_eventos_cubre_todo(n):
    res = correr(n=n, ha=3, detalle=True, **{"agente.tolva_ha": 0.6})
    r = res["resumen"]
    assert r["cobertura"] == 1.0 and not r["estancado"]
    sin_violaciones(r)
    p = res["pasos"]
    assert (p.groupby(["t", "x", "y"]).size() <= 1).all()


# ------------------------------------------------------------------ tractor descompuesto

@pytest.fixture(scope="module")
def falla():
    return correr(semilla=1, detalle=True, **{"falla.activa": True})


def test_falla_remolque_y_reparacion(falla):
    r = falla["resumen"]
    assert r["cobertura"] == 1.0 and not r["estancado"]
    assert r["t_falla"] >= 0 and r["t_deteccion_falla"] >= r["t_falla"]
    assert r["t_remolque_entregado"] > r["t_falla"]
    assert r["t_reparado"] > r["t_remolque_entregado"]
    p = falla["pasos"]
    assert (p["implemento"] == "grua").any(), "un tractor debe engancharse la grúa"
    sin_violaciones(r)


def test_falla_solo_reparte_lo_pendiente(falla):
    assert falla["resumen"]["reasignadas_ya_hechas"] == 0


def test_falla_con_mensajes_perdidos():
    r = correr(semilla=2, **{"falla.activa": True, "comunicacion.perdida_mensajes": 0.2})["resumen"]
    assert r["cobertura"] == 1.0 and not r["estancado"]
    assert r["t_deteccion_falla"] >= r["t_falla"] >= 0
    assert r["reasignadas_ya_hechas"] == 0
    sin_violaciones(r)


def test_decisiones_con_motivo(falla):
    reg = falla["registro"]
    decisiones = reg[(reg["fuente"] == "coordinador") & reg["tipo"].isin(["decision", "plan"])]
    assert len(decisiones) > 0
    assert (decisiones["motivo"].str.len() > 0).all()
    subasta = decisiones[decisiones["evento"] == "subasta"]
    assert len(subasta) >= 1 and subasta["texto"].str.contains("llega en").all()


# ------------------------------------------------------------------ incendio

@pytest.fixture(scope="module")
def incendio():
    return {mec: [correr(mec, semilla=s, **{"eventos.incendio.activo": True})["resumen"] for s in range(3)]
            for mec in ("M2", "M3")}


def test_incendio_m3_quema_menos_que_m2(incendio):
    quemado = {mec: sum(r["area_quemada_ha"] for r in rs) for mec, rs in incendio.items()}
    assert quemado["M3"] < quemado["M2"]
    assert all(r["celdas_apagadas"] > 0 for r in incendio["M3"])


def test_incendio_reglas_de_seguridad(incendio):
    for r in incendio["M3"]:
        sin_violaciones(r)
        assert r["t_deteccion_incendio"] >= r["t_incendio"] >= 0
    for r in incendio["M2"]:
        assert r["colisiones"] == 0 and r["entradas_fuego"] == 0


def test_incendio_vista_2d_y_telemetria(tmp_path):
    res = correr(semilla=0, detalle=True, **{"eventos.incendio.activo": True})
    ev = res["eventos"]
    assert ev["zonas"], "el coordinador debe declarar una zona prohibida"
    assert (ev["t_quemado"] >= 0).any()
    assert (res["pasos"]["implemento"] == "pipa").any()
    carpeta = telemetria.guardar_corrida(res, tmp_path / "corrida")
    assert (carpeta / "eventos.json").exists() and (carpeta / "registro.csv").exists()
    assert telemetria.validar_unity(carpeta / "unity.json")[0]
    copia = telemetria.cargar_corrida(carpeta)
    assert len(copia["registro"]) == len(res["registro"])
    t = int(ev["t_incendio"]) + 60
    fig = viz.mapa_campo(None, copia, t=t)
    plt.close(fig)
    anim = viz.animacion(copia, n_cuadros=4, dpi=40)
    anim._func(0)
    anim._func(3)
    anim._draw_was_started = True   # ya se dibujaron cuadros a mano (evita el aviso de matplotlib)
    plt.close("all")
    tabla = viz.registro_coordinador(copia, solo_coordinador=True)
    assert set(tabla.columns) >= {"hora", "texto", "motivo"}


# ------------------------------------------------------------------ reportes falsos y obstáculo

def test_reportes_falsos_se_descartan_y_ningun_real_se_descarta():
    r = correr(semilla=0, **{"coordinador.tasa_reporte_falso": 0.004})["resumen"]
    assert r["reportes_falsos"] > 0
    assert r["falsos_descartados"] > 0
    assert r["falsos_confirmados"] == 0
    assert r["reales_descartados"] == 0
    assert r["cobertura"] == 1.0


def test_obstaculo_nuevo_se_rodea():
    for s in range(2):
        r = correr(semilla=s, **{"eventos.obstaculo_nuevo.activo": True})["resumen"]
        assert r["t_obstaculo_nuevo"] >= 0 and r["t_deteccion_obstaculo"] >= r["t_obstaculo_nuevo"]
        assert r["n_sembradas"] + r["celdas_inaccesibles"] == r["n_celdas_trabajo"]
        assert not r["estancado"]
        sin_violaciones(r)


def test_mismos_eventos_en_m2_y_m3():
    """El incendio arranca en el mismo paso de cobertura y en la misma celda con ambos mecanismos."""
    a = correr("M2", semilla=4, detalle=True, **{"eventos.incendio.activo": True})
    b = correr("M3", semilla=4, detalle=True, **{"eventos.incendio.activo": True})
    assert a["eventos"]["origen_incendio"] == b["eventos"]["origen_incendio"]


# ------------------------------------------------------------------ experimento

def test_tareas_del_experimento_m3():
    tareas = experimentos.armar_tareas("m3", "rapido")
    normales = [t for t in tareas if t.grupo == "m3"]
    assert len(normales) == len(experimentos.escenarios_m3()) * 2 * experimentos.SEMILLAS_M3["rapido"]
    assert {t.cambios["mecanismo"] for t in normales} == {"M2", "M3"}
    assert "m3" not in experimentos.EXPERIMENTOS   # no cambia lo que corre por defecto
