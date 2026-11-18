"""Pruebas de guardar/cargar corridas y del JSON para Unity."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from siembra import VERSION_ESQUEMA, metricas, telemetria  # noqa: E402
from siembra.config import aplicar, cargar_config  # noqa: E402


@pytest.fixture(scope="module")
def res():
    cfg = aplicar(cargar_config(), {"campo.hectareas": 2, "flota.n_tractores": 2, "mecanismo": "M1",
                                    "semilla": 3, "comunicacion.perdida_mensajes": 0.2})
    r = telemetria.corrida_sintetica(cfg, detalle=True)
    # Tipos de numpy en el resumen y una tupla en el campo, como podría devolverlos simular
    r["resumen"]["colisiones"] = np.int64(0)
    r["resumen"]["cobertura"] = np.float64(r["resumen"]["cobertura"])
    r["resumen"]["estancado"] = np.bool_(False)
    r["resumen"]["W_conflicto_h"] = np.nan  # un NaN debe volver como NaN
    r["campo"]["deposito"] = tuple(r["campo"]["deposito"])
    return r


def test_corrida_sintetica_tiene_forma_del_contrato(res):
    assert set(metricas.LLAVES_RESUMEN) == set(res["resumen"])
    assert list(res["pasos"].columns) == list(telemetria.COLUMNAS_PASOS)
    assert list(res["mensajes"].columns) == list(telemetria.COLUMNAS_MENSAJES)
    assert list(res["serie"].columns) == list(telemetria.COLUMNAS_SERIE)
    ancho, alto = res["campo"]["ancho"], res["campo"]["alto"]
    assert alto == ancho + 3
    for nombre, dtype in (("tipo_base", np.int8), ("t_surcado", np.int32), ("t_sembrado", np.int32),
                          ("pasadas", np.int32)):
        assert res["celdas"][nombre].shape == (ancho, alto) and res["celdas"][nombre].dtype == dtype
    # Precedencia: ninguna celda se siembra antes de surcarse
    s, m = res["celdas"]["t_surcado"], res["celdas"]["t_sembrado"]
    assert np.all(m[m >= 0] > s[m >= 0])


def test_ida_y_vuelta(res, tmp_path):
    carpeta = telemetria.guardar_corrida(res, tmp_path / "normal_20ha_2t_M1_s0")
    assert {p.name for p in carpeta.iterdir()} == set(telemetria.ARCHIVOS)
    meta = json.loads((carpeta / "meta.json").read_text(encoding="utf-8"))
    assert meta["version_esquema"] == VERSION_ESQUEMA
    assert set(meta) == {"version_esquema", "parametros", "resumen", "campo", "derivados"}

    vuelta = telemetria.cargar_corrida(carpeta)
    assert set(vuelta) == set(res)
    assert vuelta["parametros"] == res["parametros"]
    assert vuelta["derivados"] == pytest.approx(res["derivados"])
    assert vuelta["campo"] == {**res["campo"], "deposito": list(res["campo"]["deposito"])}
    assert set(vuelta["resumen"]) == set(res["resumen"])
    for k, v in res["resumen"].items():
        w = vuelta["resumen"][k]
        if isinstance(v, str):
            assert w == v
        elif isinstance(v, (float, np.floating)) and np.isnan(v):
            assert np.isnan(w)
        else:
            assert w == pytest.approx(v), k
    for nombre, arreglo in res["celdas"].items():
        assert vuelta["celdas"][nombre].dtype == arreglo.dtype
        np.testing.assert_array_equal(vuelta["celdas"][nombre], arreglo)
    for tabla in ("serie", "pasos", "mensajes"):
        pd.testing.assert_frame_equal(vuelta[tabla].reset_index(drop=True),
                                      res[tabla].reset_index(drop=True), check_dtype=False)
    # Los textos vacíos de mensajes vuelven como "" y no como NaN
    assert (vuelta["mensajes"]["evento"] == "").any() and vuelta["mensajes"]["evento"].notna().all()
    assert vuelta["mensajes"]["perdido"].dtype == bool


def test_guardar_sin_detalle_no_deja_archivos_viejos(res, tmp_path):
    carpeta = telemetria.guardar_corrida(res, tmp_path / "c")
    sin_detalle = {k: v for k, v in res.items() if k not in ("pasos", "mensajes")}
    telemetria.guardar_corrida(sin_detalle, carpeta)
    assert {p.name for p in carpeta.iterdir()} == {"meta.json", "serie.csv", "celdas.npz"}
    assert "pasos" not in telemetria.cargar_corrida(carpeta)


def test_unity_esquema_y_checksums(res, tmp_path):
    ruta = telemetria.exportar_unity(res, tmp_path / "unity.json")
    ok, errores = telemetria.validar_unity(ruta)
    assert ok, errores
    doc = json.loads(ruta.read_text(encoding="utf-8"))
    for k in ("version_esquema", "semilla", "version_parametros", "mecanismo", "checksum_archivo", "frames"):
        assert k in doc
    assert doc["semilla"] == 3 and doc["mecanismo"] == "M1"
    assert len(doc["frames"]) == res["pasos"]["t"].nunique()
    m = doc["frames"][5]["mensajes"][0]
    assert list(m) == list(telemetria.CAMPOS_MENSAJE_UNITY)
    assert set(m["pose"]) == {"x", "y", "theta"} and set(m["objetivo"]) == {"x", "y"}
    assert m["confianza"] == 1.0 and m["implemento"] in ("surcador", "sembradora")
    assert len(m["checksum"]) == 16
    sin = {k: v for k, v in m.items() if k != "checksum"}
    esperado = __import__("hashlib").sha256(
        json.dumps(sin, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    assert m["checksum"] == esperado
    # Escena: arreglos aplanados con índice y*ancho+x
    esc = doc["escena"]
    ancho = esc["ancho"]
    x, y = 3, 4
    assert esc["t_sembrado"][y * ancho + x] == res["celdas"]["t_sembrado"][x, y]
    # Submuestreo: uno de cada 10 pasos y siempre el último
    ruta10 = telemetria.exportar_unity(res, tmp_path / "unity10.json", cada=10)
    doc10 = json.loads(ruta10.read_text(encoding="utf-8"))
    assert doc10["frames"][-1]["t"] == doc["frames"][-1]["t"]
    assert len(doc10["frames"]) <= len(doc["frames"]) // 10 + 2
    assert telemetria.validar_unity(ruta10)[0]


def _alterar(ruta, funcion):
    doc = json.loads(ruta.read_text(encoding="utf-8"))
    funcion(doc)
    ruta.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_validar_unity_detecta_alteraciones(res, tmp_path):
    ruta = telemetria.exportar_unity(res, tmp_path / "u.json")

    # Checksum de un mensaje cambiado
    _alterar(ruta, lambda d: d["frames"][2]["mensajes"][0].update(checksum="0" * 16))
    ok, errores = telemetria.validar_unity(ruta)
    assert not ok
    assert any("checksum no coincide" in e for e in errores)
    assert any("checksum_archivo" in e for e in errores)

    # Contenido cambiado sin actualizar el checksum del mensaje
    ruta = telemetria.exportar_unity(res, tmp_path / "u.json")
    _alterar(ruta, lambda d: d["frames"][3]["mensajes"][1]["pose"].update(x=999))
    ok, errores = telemetria.validar_unity(ruta)
    assert not ok and any("frame t=" in e and "checksum no coincide" in e for e in errores)

    # Versión de esquema distinta
    ruta = telemetria.exportar_unity(res, tmp_path / "u.json")
    _alterar(ruta, lambda d: d.update(version_esquema="0.9"))
    ok, errores = telemetria.validar_unity(ruta)
    assert not ok and any("version_esquema" in e for e in errores)

    # Escena alterada
    ruta = telemetria.exportar_unity(res, tmp_path / "u.json")
    _alterar(ruta, lambda d: d["escena"].update(ancho=1))
    assert not telemetria.validar_unity(ruta)[0]

    # Archivo que no es JSON
    (tmp_path / "roto.json").write_text("{no es json", encoding="utf-8")
    ok, errores = telemetria.validar_unity(tmp_path / "roto.json")
    assert not ok and errores


def test_exportar_unity_sin_detalle_falla(res, tmp_path):
    with pytest.raises(ValueError):
        telemetria.exportar_unity({k: v for k, v in res.items() if k != "pasos"}, tmp_path / "x.json")


def test_a_json_convierte_numpy():
    convertido = telemetria.a_json({"a": np.int32(3), "b": np.float32(0.5), "c": np.array([1, 2]),
                                    "d": np.bool_(True), "e": float("nan"), "f": (1, np.int64(2))})
    assert convertido == {"a": 3, "b": 0.5, "c": [1, 2], "d": True, "e": None, "f": [1, 2]}
    json.dumps(convertido, allow_nan=False)
