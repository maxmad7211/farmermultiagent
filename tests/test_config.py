"""Pruebas de siembra.config: carga, notación de puntos, validación de entradas y derivados.

Las pruebas que dependen de un valor fijan ese valor con `aplicar`, para que no se rompan si
cambia el caso base de config/parametros.json.
"""

import copy
import json

import pytest

from siembra.config import (
    RUTA_BASE,
    ErrorConfig,
    aplicar,
    cargar_config,
    derivados,
    lado_campo,
    validar,
)


@pytest.fixture
def base():
    return cargar_config()


def mensaje_error(cfg):
    """Corre validar y devuelve el texto del error (falla la prueba si no hay error)."""
    with pytest.raises(ErrorConfig) as exc:
        validar(cfg)
    return str(exc.value)


# ---------------------------------------------------------------- configuración base


def test_configuracion_base_es_valida(base):
    assert validar(base) is True


def test_base_tiene_version_y_fuentes(base):
    assert isinstance(base["version_parametros"], str) and base["version_parametros"]
    assert isinstance(base["semilla"], int)
    assert base["_fuentes"], "cada parámetro debe documentar su fuente en _fuentes"


def test_cada_fuente_corresponde_a_un_parametro(base):
    for ruta in base["_fuentes"]:
        destino = base
        for parte in ruta.split("."):
            assert parte in destino, f"_fuentes menciona {ruta!r}, que no existe en la configuración"
            destino = destino[parte]


def test_error_config_es_value_error():
    assert issubclass(ErrorConfig, ValueError)


# ---------------------------------------------------------------- aplicar


def test_aplicar_con_notacion_de_puntos(base):
    cfg = aplicar(base, {"campo.hectareas": 40, "flota.n_tractores": 3, "mecanismo": "M2",
                         "comunicacion.perdida_mensajes": 0.1})
    assert cfg["campo"]["hectareas"] == 40
    assert cfg["flota"]["n_tractores"] == 3
    assert cfg["mecanismo"] == "M2"
    assert cfg["comunicacion"]["perdida_mensajes"] == 0.1
    # El resto de la sección queda intacto
    assert cfg["campo"]["celda_m"] == base["campo"]["celda_m"]
    assert validar(cfg) is True


def test_aplicar_no_modifica_el_original(base):
    original = copy.deepcopy(base)
    aplicar(base, {"campo.hectareas": 80, "economia.precio_tractor": 1})
    assert base == original


def test_aplicar_no_comparte_objetos_mutables(base):
    obstaculos = [{"x": 5, "y": 10}]
    cfg = aplicar(base, {"campo.obstaculos": obstaculos})
    obstaculos.append({"x": 6, "y": 11})
    assert len(cfg["campo"]["obstaculos"]) == 1


def test_aplicar_sin_cambios_devuelve_copia(base):
    for cambios in (None, {}):
        cfg = aplicar(base, cambios)
        assert cfg == base and cfg is not base


def test_aplicar_crea_claves_nuevas(base):
    cfg = aplicar(base, {"seccion_nueva.valor": 7})
    assert cfg["seccion_nueva"]["valor"] == 7


def test_cargar_config_aplica_y_valida_cambios():
    cfg = cargar_config(cambios={"campo.hectareas": 10, "flota.n_tractores": 4})
    assert cfg["campo"]["hectareas"] == 10 and cfg["flota"]["n_tractores"] == 4
    with pytest.raises(ErrorConfig):
        cargar_config(cambios={"flota.n_tractores": 0})


def test_cargar_config_no_modifica_el_archivo():
    antes = RUTA_BASE.read_text(encoding="utf-8")
    cargar_config(cambios={"campo.hectareas": 160})
    assert RUTA_BASE.read_text(encoding="utf-8") == antes
    json.loads(antes)  # el archivo sigue siendo JSON válido


# ---------------------------------------------------------------- validar: flota


@pytest.mark.parametrize("n", [0, -1, 2.5, None])
def test_rechaza_flota_menor_que_uno_o_no_entera(base, n):
    msg = mensaje_error(aplicar(base, {"flota.n_tractores": n}))
    assert "flota.n_tractores" in msg and ">= 1" in msg


def test_rechaza_surcadores_fuera_de_rango(base):
    msg = mensaje_error(aplicar(base, {"flota.n_tractores": 2, "flota.n_surcadores": 2}))
    assert "flota.n_surcadores" in msg


def test_acepta_surcadores_dentro_de_rango(base):
    assert validar(aplicar(base, {"flota.n_tractores": 3, "flota.n_surcadores": 2})) is True


def test_rechaza_mecanismo_desconocido(base):
    msg = mensaje_error(aplicar(base, {"mecanismo": "M9"}))
    assert "mecanismo" in msg


# ---------------------------------------------------------------- validar: probabilidades


@pytest.mark.parametrize("ruta", [
    "comunicacion.perdida_mensajes",
    "agronomia.perdida_dia",
    "falla.cobertura_disparo",
    "escala_tiempo.dias_laborables",
    "agente.variacion_servicio",
])
@pytest.mark.parametrize("valor", [-0.1, 1.5])
def test_rechaza_probabilidad_fuera_de_0_1(base, ruta, valor):
    msg = mensaje_error(aplicar(base, {ruta: valor}))
    assert ruta in msg and "entre 0 y 1" in msg


@pytest.mark.parametrize("valor", [0.0, 1.0])
def test_acepta_probabilidad_en_los_extremos(base, valor):
    assert validar(aplicar(base, {"comunicacion.perdida_mensajes": valor})) is True


def test_rechaza_cero_dias_laborables(base):
    msg = mensaje_error(aplicar(base, {"escala_tiempo.dias_laborables": 0}))
    assert "dias_laborables" in msg and "mayor que 0" in msg


# ---------------------------------------------------------------- validar: precios y duraciones


@pytest.mark.parametrize("ruta", [
    "economia.precio_diesel",
    "economia.precio_maiz",
    "economia.penaliza_colision",
    "agente.recarga_semilla_min",
    "comunicacion.retraso_max",
])
def test_rechaza_valor_negativo(base, ruta):
    msg = mensaje_error(aplicar(base, {ruta: -1}))
    assert ruta in msg and "negativo" in msg


@pytest.mark.parametrize("ruta", [
    "economia.precio_tractor",
    "economia.vida_h",
    "agente.tolva_ha",
    "escala_tiempo.velocidad_kmh",
    "campo.hectareas",
])
@pytest.mark.parametrize("valor", [0, -1])
def test_rechaza_valor_no_positivo(base, ruta, valor):
    msg = mensaje_error(aplicar(base, {ruta: valor}))
    assert ruta in msg and "positivo" in msg


@pytest.mark.parametrize("ruta", ["comunicacion.timeout_ofertas", "comunicacion.ventana_reservas"])
@pytest.mark.parametrize("valor", [0, 2.5])
def test_rechaza_parametro_de_arquitectura_no_entero(base, ruta, valor):
    msg = mensaje_error(aplicar(base, {ruta: valor}))
    assert ruta in msg


# ---------------------------------------------------------------- validar: geometría


def test_rechaza_deposito_fuera_del_campo(base):
    lado = lado_campo(base)
    for dx in (-1, lado, lado + 10):
        msg = mensaje_error(aplicar(base, {"campo.deposito_x": dx}))
        assert "deposito_x" in msg and "fuera del campo" in msg


def test_acepta_deposito_en_las_orillas(base):
    lado = lado_campo(base)
    for dx in (0, lado - 1, None):
        assert validar(aplicar(base, {"campo.deposito_x": dx})) is True


def test_rechaza_obstaculo_en_cabeceras_o_patio(base):
    lado = lado_campo(base)
    alto = lado + 3
    # y = 0 patio, y = 1 cabecera sur, y = alto - 1 cabecera norte; un árbol 2x2 que invade la cabecera norte
    for ob in ({"x": 3, "y": 0}, {"x": 3, "y": 1}, {"x": 3, "y": alto - 1},
               {"x": 3, "y": lado + 1, "ancho": 2, "alto": 2}):
        msg = mensaje_error(aplicar(base, {"campo.obstaculos": [ob]}))
        assert "cabecera" in msg, ob


def test_rechaza_obstaculo_fuera_del_campo_en_x(base):
    lado = lado_campo(base)
    for ob in ({"x": -1, "y": 5}, {"x": lado - 1, "y": 5, "ancho": 2, "alto": 2}):
        msg = mensaje_error(aplicar(base, {"campo.obstaculos": [ob]}))
        assert "fuera del campo" in msg, ob


def test_acepta_obstaculos_en_el_area_de_trabajo(base):
    lado = lado_campo(base)
    obstaculos = [{"x": 0, "y": 2, "tipo": "poste"},
                  {"x": lado - 2, "y": lado, "ancho": 2, "alto": 2, "tipo": "arbol"}]
    assert validar(aplicar(base, {"campo.obstaculos": obstaculos})) is True


def test_reporta_todos_los_errores_juntos(base):
    cfg = aplicar(base, {"flota.n_tractores": 0, "comunicacion.perdida_mensajes": 2,
                         "economia.precio_diesel": -5})
    msg = mensaje_error(cfg)
    for ruta in ("flota.n_tractores", "comunicacion.perdida_mensajes", "economia.precio_diesel"):
        assert ruta in msg


# ---------------------------------------------------------------- lado del campo


@pytest.mark.parametrize("ha, lado", [(10, 32), (20, 45), (40, 63), (80, 89), (160, 126)])
def test_lado_del_campo(base, ha, lado):
    assert lado_campo(aplicar(base, {"campo.hectareas": ha, "campo.celda_m": 10})) == lado


# ---------------------------------------------------------------- derivados


@pytest.fixture
def escala_propuesta(base):
    """Valores de la propuesta: 9 km/h, 3.04 m, jornada de 10 h, celda de 10 m, tolva de 2 ha."""
    return aplicar(base, {"escala_tiempo.velocidad_kmh": 9.0, "escala_tiempo.ancho_trabajo_m": 3.04,
                          "escala_tiempo.jornada_h": 10, "campo.celda_m": 10, "agente.tolva_ha": 2.0})


def test_derivados_capacidad_y_paso(escala_propuesta):
    d = derivados(escala_propuesta)
    assert d["celda_ha"] == pytest.approx(0.01)
    assert d["capacidad_teorica_ha_h"] == pytest.approx(2.736)
    assert d["paso_s"] == pytest.approx(13.16, abs=0.01)
    assert d["paso_h"] == pytest.approx(d["paso_s"] / 3600)


def test_derivados_pasos_por_jornada(escala_propuesta):
    assert derivados(escala_propuesta)["pasos_dia"] == pytest.approx(2736, abs=1)


def test_derivados_tolva_en_celdas(escala_propuesta):
    assert derivados(escala_propuesta)["tolva_celdas"] == 200


def test_derivados_servicios_en_pasos(escala_propuesta):
    d = derivados(escala_propuesta)
    cfg = escala_propuesta["agente"]
    assert d["pasos_recarga_semilla"] == round(cfg["recarga_semilla_min"] * 60 / d["paso_s"])
    assert d["pasos_cambio"] == round(cfg["cambio_implemento_min"] * 60 / d["paso_s"])
    assert d["diesel_paso_l"] == pytest.approx(cfg["consumo_lh"] * d["paso_s"] / 3600)


def test_derivados_servicio_minimo_un_paso(escala_propuesta):
    d = derivados(aplicar(escala_propuesta, {"agente.recarga_diesel_min": 0}))
    assert d["pasos_recarga_diesel"] == 1
