"""Pruebas automáticas por regla (propuesta, sección Reproducibilidad).

Cada prueba corre la simulación real en campos chicos con los tres mecanismos y revisa la
telemetría paso a paso.
"""

import numpy as np
import pytest

from siembra.config import aplicar, cargar_config
from siembra.modelo import simular

MECANISMOS = ["M0", "M1", "M2"]
ESTADOS_DEPOSITO = {"recargando", "cambiando_implemento"}


def correr(mecanismo, n, ha=3, semilla=0, **extra):
    cambios = {"campo.hectareas": ha, "flota.n_tractores": n, "mecanismo": mecanismo,
               "semilla": semilla, "agente.tolva_ha": 0.6}
    cambios.update(extra)
    return simular(aplicar(cargar_config(), cambios), detalle=True)


CASOS = [(mec, n) for mec in MECANISMOS for n in (1, 2, 4)]


@pytest.fixture(scope="module", params=CASOS, ids=[f"{m}-{n}t" for m, n in CASOS])
def corrida(request):
    mec, n = request.param
    return correr(mec, n)


def test_cobertura_completa(corrida):
    r = corrida["resumen"]
    assert r["cobertura"] == 1.0
    assert not r["estancado"]


def test_sin_colisiones(corrida):
    p = corrida["pasos"]
    repetidas = p.groupby(["t", "x", "y"]).size()
    assert (repetidas <= 1).all(), repetidas[repetidas > 1].head()
    assert corrida["resumen"]["colisiones"] == 0


def test_sin_intercambios(corrida):
    p = corrida["pasos"].sort_values(["agente", "t"])
    pos = {(a, t): (x, y) for a, t, x, y in zip(p.agente, p.t, p.x, p.y)}
    agentes = sorted(p.agente.unique())
    for t in range(1, int(p.t.max()) + 1):
        for i, a in enumerate(agentes):
            for b in agentes[i + 1:]:
                if pos[(a, t)] == pos[(b, t - 1)] and pos[(b, t)] == pos[(a, t - 1)] and pos[(a, t)] != pos[(b, t)]:
                    pytest.fail(f"{a} y {b} intercambiaron posiciones en t={t}")
    assert corrida["resumen"]["intercambios"] == 0


def test_un_paso_por_celda_y_sin_obstaculos(corrida):
    p = corrida["pasos"].sort_values(["agente", "t"])
    dx = p.groupby("agente").x.diff().abs().fillna(0)
    dy = p.groupby("agente").y.diff().abs().fillna(0)
    assert ((dx + dy) <= 1).all()
    base = corrida["celdas"]["tipo_base"]
    assert (base[p.x.to_numpy(), p.y.to_numpy()] != 5).all()


def test_recargas_solo_en_deposito(corrida):
    p = corrida["pasos"]
    dep = tuple(corrida["campo"]["deposito"])
    en_servicio = p[p.estado.isin(ESTADOS_DEPOSITO)]
    assert ((en_servicio.x == dep[0]) & (en_servicio.y == dep[1])).all()


def test_siembra_solo_sobre_surcos(corrida):
    c = corrida["celdas"]
    sembradas = c["t_sembrado"] >= 0
    assert (c["t_surcado"][sembradas] >= 0).all()
    assert (c["t_surcado"][sembradas] < c["t_sembrado"][sembradas]).all()


def test_estados_de_celda_no_retroceden(corrida):
    """libre -> surcada -> sembrada: se reconstruye en varios momentos y nunca baja."""
    c = corrida["celdas"]
    t_max = int(corrida["resumen"]["pasos_simulados"])
    anterior = None
    for t in np.linspace(0, t_max, 25).astype(int):
        estado = (c["t_surcado"].clip(-1) >= 0) & (c["t_surcado"] <= t)
        estado = estado.astype(int) + ((c["t_sembrado"] >= 0) & (c["t_sembrado"] <= t)).astype(int)
        if anterior is not None:
            assert (estado >= anterior).all()
        anterior = estado
    # Fuera del área de trabajo nunca se surca ni se siembra
    trabajo = c["tipo_base"] == 2
    assert (c["t_surcado"][~trabajo] == -1).all()
    assert (c["t_sembrado"][~trabajo] == -1).all()


def test_reproducible_con_la_misma_semilla():
    a = correr("M2", 3, semilla=7)["resumen"]
    b = correr("M2", 3, semilla=7)["resumen"]
    a.pop("tiempo_computo_s")
    b.pop("tiempo_computo_s")
    assert a == b


@pytest.mark.parametrize("mec", ["M1", "M2"])
def test_contract_net_reasigna_tras_falla(mec):
    r = correr(mec, 4, ha=5, **{"falla.activa": True})["resumen"]
    assert r["tractor_fallado"]
    assert r["n_sembradas"] + r["celdas_inaccesibles"] == r["n_celdas_trabajo"]


def test_franjas_fijas_no_reaccionan_a_falla():
    r = correr("M0", 4, ha=5, **{"falla.activa": True})["resumen"]
    assert r["tractor_fallado"]
    assert r["cobertura"] < 1.0


@pytest.mark.parametrize("mec", ["M1", "M2"])
def test_completa_con_perdida_de_mensajes(mec):
    r = correr(mec, 3, ha=3, **{"comunicacion.perdida_mensajes": 0.2})["resumen"]
    assert r["mensajes_perdidos"] > 0
    assert r["cobertura"] == 1.0


def test_obstaculos_se_rodean():
    r = correr("M2", 3, ha=10, **{"campo.n_obstaculos": 2})
    assert r["resumen"]["n_obstaculos"] == 2
    assert r["resumen"]["cobertura"] == 1.0
