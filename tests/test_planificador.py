"""A* con costos variables por tipo de celda, probado sobre mapas con ruta óptima conocida.

Propuesta, "Qué queremos aprender": implementar A* con costos variables por tipo de celda y
demostrarlo con pruebas sobre mapas con ruta óptima conocida. La ruta óptima se conoce de dos
formas: calculada a mano en mapas chicos, y con una búsqueda exhaustiva (Dijkstra) escrita aparte
en esta prueba sobre el mismo grafo.
"""

import heapq
import random

import pytest

from siembra.campo import CABECERA, LIBRE, OBSTACULO, PESO, PESO_CRUCE, SEMBRADA, SURCADA, Campo
from siembra.config import aplicar, cargar_config
from siembra.planificador import COSTO_ESPERA, DistanciaReal, TablaReservas, astar, whca


def campo(ha=1, obstaculos=()):
    cfg = aplicar(cargar_config(), {"campo.hectareas": ha, "campo.obstaculos": list(obstaculos)})
    return Campo(cfg, random.Random(0))


def costo_ruta(c, inicio, ruta):
    total, previa = 0.0, inicio
    for celda in ruta:
        assert celda in c.vecinos[previa], f"{previa} -> {celda} no son vecinas"
        total += c.costo(previa, celda)
        previa = celda
    return total


def dijkstra(c, inicio, meta, bloqueadas=frozenset()):
    """Referencia independiente: búsqueda de costo uniforme sin heurística."""
    dist = {inicio: 0.0}
    abiertos = [(0.0, inicio)]
    while abiertos:
        d, u = heapq.heappop(abiertos)
        if u == meta:
            return d
        if d > dist[u]:
            continue
        for v in c.vecinos[u]:
            if v in bloqueadas and v != meta:
                continue
            nd = d + c.costo(u, v)
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(abiertos, (nd, v))
    return None


# ---------------------------------------------------------------- rutas calculadas a mano

def test_patio_ruta_recta_de_costo_unitario():
    c = campo()
    ruta = astar(c, (1, 0), (7, 0))
    assert ruta == [(x, 0) for x in range(2, 8)]
    assert costo_ruta(c, (1, 0), ruta) == 6.0


def test_vuelta_en_cabecera_mas_barata_que_cruzar_hileras():
    """Del final de la hilera 3 al inicio de la 4: por la cabecera cuesta 1 + 1 + 1.3 = 3.3; cruzar, 4.0."""
    c = campo()
    arriba = c.y1
    ruta = astar(c, (3, arriba), (4, arriba))
    assert ruta == [(3, arriba + 1), (4, arriba + 1), (4, arriba)]
    assert costo_ruta(c, (3, arriba), ruta) == pytest.approx(1.0 + 1.0 + PESO[LIBRE])
    assert costo_ruta(c, (3, arriba), ruta) < PESO_CRUCE


def test_prefiere_cabecera_a_pisar_lo_sembrado():
    """Con toda la hilera 5 sembrada, ir de un extremo a otro de la cabecera no baja al campo."""
    c = campo()
    for celda in c.columnas[5]:
        c.est[celda[0]][celda[1]] = SEMBRADA
    ruta = astar(c, (2, c.alto - 1), (8, c.alto - 1))
    assert all(y == c.alto - 1 for _x, y in ruta)
    assert costo_ruta(c, (2, c.alto - 1), ruta) == 6.0


def test_costos_por_tipo_de_celda():
    """Subir por una hilera cuesta lo que pesa cada celda que se pisa."""
    c = campo()
    x = 2
    estados = [LIBRE, SURCADA, SEMBRADA]
    for i, celda in enumerate(c.columnas[x][:3]):
        c.est[celda[0]][celda[1]] = estados[i]
    inicio = (x, 1)  # cabecera sur
    ruta = astar(c, inicio, c.columnas[x][2])
    assert ruta == c.columnas[x][:3]
    assert costo_ruta(c, inicio, ruta) == pytest.approx(PESO[LIBRE] + PESO[SURCADA] + PESO[SEMBRADA])


def test_rodea_obstaculo_con_la_ruta_mas_corta():
    """Un árbol de 2 x 2 en medio de la hilera: la ruta lo rodea por el anillo, sin pisarlo."""
    c = campo(ha=1, obstaculos=[{"x": 4, "y": 5, "ancho": 2, "alto": 2}])
    inicio, meta = (4, 4), (4, 7)
    ruta = astar(c, inicio, meta)
    assert all(c.estado(celda) != OBSTACULO for celda in ruta)
    # Por el anillo: lateral a (3,4), sube (3,5) (3,6) (3,7), lateral a (4,7) = 5 celdas libres
    assert len(ruta) == 5
    assert costo_ruta(c, inicio, ruta) == pytest.approx(5 * PESO[LIBRE])
    assert costo_ruta(c, inicio, ruta) == pytest.approx(dijkstra(c, inicio, meta))


def test_sin_ruta_devuelve_none():
    c = campo()
    inicio = (5, 5)
    encierro = frozenset(c.vecinos[inicio])
    assert astar(c, inicio, (1, 0), encierro) is None


def test_meta_igual_al_inicio():
    c = campo()
    assert astar(c, (3, 3), (3, 3)) == []


# ---------------------------------------------------------------- contra búsqueda exhaustiva

@pytest.mark.parametrize("semilla", range(30))
def test_astar_optimo_contra_dijkstra_en_mapas_aleatorios(semilla):
    """En mapas con estados de celda y obstáculos al azar, A* da el mismo costo que Dijkstra."""
    rng = random.Random(semilla)
    c = campo(ha=2, obstaculos=[{"x": rng.randint(1, 10), "y": rng.randint(4, 9), "ancho": 2, "alto": 2}])
    for col in c.columnas:
        for celda in col:
            c.est[celda[0]][celda[1]] = rng.choice([LIBRE, SURCADA, SEMBRADA])
    libres = [celda for celda in c.vecinos]
    for _ in range(10):
        inicio, meta = rng.sample(libres, 2)
        ruta = astar(c, inicio, meta)
        esperado = dijkstra(c, inicio, meta)
        assert ruta is not None and ruta[-1] == meta
        assert costo_ruta(c, inicio, ruta) == pytest.approx(esperado)


@pytest.mark.parametrize("semilla", range(10))
def test_distancia_real_igual_a_dijkstra(semilla):
    """La heurística de WHCA* (Reverse Resumable A*) es la distancia exacta del mapa estático."""
    rng = random.Random(100 + semilla)
    c = campo(ha=2)
    for col in c.columnas:
        for celda in col:
            c.est[celda[0]][celda[1]] = rng.choice([LIBRE, SURCADA, SEMBRADA])
    celdas = list(c.vecinos)
    meta, origen = rng.sample(celdas, 2)
    h = DistanciaReal(c, meta, origen)
    for celda in rng.sample(celdas, 20):
        assert h(celda) == pytest.approx(dijkstra(c, celda, meta))


# ---------------------------------------------------------------- Cooperative A* (WHCA*)

def test_whca_sin_reservas_sigue_la_ruta_optima():
    c = campo()
    inicio, meta = (1, 0), (6, 0)
    plan = whca(c, inicio, meta, t0=0, ventana=10, reservas=TablaReservas(), yo="T1")
    assert plan[:5] == [(x, 0) for x in range(2, 7)]
    assert all(celda == meta for celda in plan[5:])  # al llegar se queda en la meta


def test_whca_respeta_reservas_y_no_sigue_pegado():
    """Otro tractor reservó la celda siguiente: el plan espera o rodea, nunca la pisa ni entra detrás."""
    c = campo()
    res = TablaReservas()
    res.reiniciar(0, {"T1": (1, 0), "T2": (2, 0)})
    for k in range(1, 11):
        res.reservar("T2", (2, 0), k)  # T2 se queda quieto 10 pasos
    plan = whca(c, (1, 0), (4, 0), t0=0, ventana=10, reservas=res, yo="T1")
    assert len(plan) == 10
    assert (2, 0) not in plan
    # Rodea por la cabecera sur: el costo de esperar (1.5) por paso es mayor que el desvío
    assert plan[0] == (1, 1)
    assert COSTO_ESPERA > 1.0
