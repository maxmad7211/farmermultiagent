"""Interfaz web local para probar el modelo sustituto entrenado.

Uso (desde la raíz del proyecto):

    python -m siembra.interfaz                 # abre http://127.0.0.1:8421 en el navegador
    python -m siembra.interfaz --puerto 9000 --no-abrir

Carga `resultados/sustituto/modelo.joblib`. Si no existe, reentrena el modelo final con los CSV
que ya hay (barrido + activo + prueba, unos segundos, sin simular) y lo guarda. La página
(`siembra/interfaz.html`) pide al servidor lo que dice el modelo para el tamaño de campo, el
mecanismo y los precios que se elijan. El servidor solo escucha en la propia computadora.
"""

import argparse
import json
import math
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import experimentos, metricas
from . import sustituto as su

PAGINA = Path(__file__).with_name("interfaz.html")
PUERTO = 8421
HA_MAXIMA = 1000          # tope de la consulta (el modelo solo se entrenó hasta 160 ha)
BYTES_MAXIMOS = 10_000    # tamaño máximo de una petición

# Parámetros del costo que se pueden cambiar en la página: (etiqueta, unidad, mínimo, máximo).
# Solo entran en la fórmula de costo (metricas.agregar_costos), así que no requieren simular.
PARAMETROS = {
    "economia.precio_maiz": ("Precio del maíz", "$/t", 1, 100_000),
    "economia.rendimiento_t_ha": ("Rendimiento", "t/ha", 0.1, 50),
    "agronomia.perdida_dia": ("Pérdida de rendimiento por día de retraso", "fracción por día", 0, 0.1),
    "economia.precio_diesel": ("Precio del diésel", "$/L", 0, 1_000),
    "economia.precio_tractor": ("Precio del tractor", "$", 1, 100_000_000),
    "economia.temporadas_vida": ("Vida del tractor", "temporadas", 1, 100),
    "escala_tiempo.jornada_h": ("Jornada", "h por día", 1, 24),
    "escala_tiempo.dias_laborables": ("Días laborables", "fracción de los días", 0.05, 1),
}

MECANISMOS = {"M0": "Franjas fijas", "M1": "Subasta de hileras", "M2": "Subasta y avisos"}


def _valor(cfg, clave):
    destino = cfg
    for parte in clave.split("."):
        destino = destino[parte]
    return destino


def preparar_modelo(salida=None, ruta=None, verbose=True):
    """Carga el modelo guardado o, si no existe, lo reentrena con los CSV y lo guarda."""
    salida = Path(salida) if salida is not None else experimentos.SALIDA_POR_DEFECTO
    ruta = Path(ruta) if ruta is not None else salida / su.CARPETA / su.ARCHIVOS["modelo"]
    if ruta.exists():
        return su.cargar_modelo(ruta), ruta
    if verbose:
        print(f"No existe {ruta}; se reentrena el modelo final con los CSV de {salida} (no simula)...",
              flush=True)
    sust = su.reconstruir_modelo(salida)   # misma clase de modelo y config que la última corrida
    su.guardar_modelo(sust, ruta)
    return sust, ruta


def info(sust):
    """Datos del modelo y valores base de los parámetros, para armar la página."""
    return {
        "modelo": sust.nombre,
        "configuraciones": int(len(sust.datos)),
        "corridas": int(sust.datos["n"].sum()),
        "rango_hectareas": [sust.ha_min, sust.ha_max],
        "ha_maxima": HA_MAXIMA,
        "n_max": int(sust.n_max),
        "mecanismos": [{"clave": m, "nombre": MECANISMOS.get(m, m)} for m in sust.mecanismos],
        "parametros": [{"clave": k, "etiqueta": e, "unidad": u, "minimo": lo, "maximo": hi,
                        "valor": _valor(sust.cfg, k),
                        "rango_sensibilidad": metricas.RANGOS_SENSIBILIDAD.get(k)}
                       for k, (e, u, lo, hi) in PARAMETROS.items()],
    }


def _numero(x, nombre):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ValueError(f"{nombre} debe ser un número")
    try:
        v = float(x)
    except OverflowError:
        v = math.inf
    if not math.isfinite(v):
        raise ValueError(f"{nombre} debe ser un número finito")
    return v


def _cifra(x):
    """Número legible: separador de miles y sin notación científica."""
    return f"{x:,.10g}"


def validar(datos, sust):
    """Revisa una petición {mecanismo, hectareas, parametros} y devuelve (mecanismo, ha, cambios)."""
    if not isinstance(datos, dict):
        raise ValueError("La petición debe ser un objeto JSON")
    mecanismo = datos.get("mecanismo")
    if mecanismo not in sust.mecanismos:
        raise ValueError(f"El mecanismo debe ser {', '.join(sust.mecanismos)}")
    ha = _numero(datos.get("hectareas"), "El tamaño del campo")
    if not 1 <= ha <= HA_MAXIMA:
        raise ValueError(f"El tamaño del campo debe estar entre 1 y {_cifra(HA_MAXIMA)} ha")
    cambios = {}
    parametros = datos.get("parametros") or {}
    if not isinstance(parametros, dict):
        raise ValueError("Los parámetros deben ser un objeto JSON")
    for clave, valor in parametros.items():
        if clave not in PARAMETROS:
            raise ValueError(f"Parámetro desconocido: {clave}")
        etiqueta, unidad, lo, hi = PARAMETROS[clave]
        v = _numero(valor, etiqueta)
        if not lo <= v <= hi:
            raise ValueError(f"{etiqueta} debe estar entre {_cifra(lo)} y {_cifra(hi)} ({unidad})")
        cambios[clave] = v
    return mecanismo, ha, cambios


def predecir(sust, datos):
    """Respuesta completa para la página: la consulta del campo y el N recomendado por tamaño."""
    mecanismo, ha, cambios = validar(datos, sust)
    r = su.consultar(sust, mecanismo, ha, cambios)
    franja = su.n_optimo_por_tamano(sust, mecanismo, cambios=cambios)
    r["por_tamano"] = [{"hectareas": float(h), "n_optimo": int(n), "p_optimo": float(p)}
                       for h, n, p in franja.itertuples(index=False)]
    return r


class _Servidor(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64   # el valor por defecto (5) rechaza ráfagas de peticiones en macOS


def crear_servidor(sust, host="127.0.0.1", puerto=PUERTO, intentos=10):
    """Servidor HTTP de la interfaz. Si el puerto está ocupado, prueba los siguientes."""

    class Manejador(BaseHTTPRequestHandler):
        timeout = 10   # una conexión que no termina de mandar su petición no retiene el hilo

        def _host_valido(self):
            # Solo peticiones dirigidas a esta computadora (evita que un sitio ajeno use la API
            # cambiando a qué IP apunta su dominio)
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host in ("127.0.0.1", "localhost", "::1"):
                return True
            self._json(403, {"error": "solo se aceptan peticiones a 127.0.0.1 o localhost"})
            return False

        def _enviar(self, codigo, cuerpo, tipo):
            try:
                self.send_response(codigo)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(cuerpo)
            except (BrokenPipeError, ConnectionResetError):
                pass   # el navegador ya cerró la conexión (por ejemplo, al recargar)

        def _json(self, codigo, datos):
            self._enviar(codigo, json.dumps(datos, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8")

        def do_GET(self):
            if not self._host_valido():
                return
            ruta = self.path.split("?", 1)[0]
            if ruta in ("/", "/index.html"):
                self._enviar(200, PAGINA.read_bytes(), "text/html; charset=utf-8")
            elif ruta == "/api/info":
                self._json(200, info(sust))
            else:
                self._json(404, {"error": "no existe"})

        def do_POST(self):
            if not self._host_valido():
                return
            if self.path.split("?", 1)[0] != "/api/predecir":
                self._json(404, {"error": "no existe"})
                return
            if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
                self._json(415, {"error": "la petición debe ser application/json"})
                return
            try:
                largo = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                largo = -1
            if not 0 < largo <= BYTES_MAXIMOS:
                self._json(400, {"error": "petición vacía o demasiado grande"})
                return
            try:
                # parse_int=float: un entero gigante se vuelve inf (y se rechaza) en lugar de fallar
                datos = json.loads(self.rfile.read(largo).decode("utf-8"), parse_int=float)
            except (ValueError, UnicodeDecodeError):   # incluye json.JSONDecodeError
                self._json(400, {"error": "El cuerpo de la petición no es JSON válido"})
                return
            try:
                respuesta = predecir(sust, datos)
            except (ValueError, OverflowError) as e:
                self._json(400, {"error": str(e)})
                return
            self._json(200, respuesta)

        def log_message(self, formato, *args):  # sin una línea en consola por cada petición
            pass

    ultimo = None
    for p in range(puerto, puerto + max(1, intentos)):
        try:
            return _Servidor((host, p), Manejador)
        except OSError as e:
            ultimo = e
            if puerto == 0:
                break
    raise OSError(f"no se pudo abrir un puerto entre {puerto} y {puerto + intentos - 1}: {ultimo}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m siembra.interfaz",
                                description="Página local para probar el modelo sustituto entrenado.")
    p.add_argument("--puerto", type=int, default=PUERTO, help=f"puerto (por defecto {PUERTO})")
    p.add_argument("--salida", default=None, help="carpeta de resultados (por defecto resultados/)")
    p.add_argument("--modelo", default=None, help="ruta del modelo guardado (por defecto <salida>/sustituto/modelo.joblib)")
    p.add_argument("--no-abrir", action="store_true", help="no abrir el navegador")
    a = p.parse_args(argv)
    try:
        sust, ruta = preparar_modelo(a.salida, a.modelo)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2
    servidor = crear_servidor(sust, puerto=a.puerto)
    url = f"http://127.0.0.1:{servidor.server_address[1]}/"
    print(f"Modelo: {sust.nombre} ({ruta})\nInterfaz en {url}  (Ctrl+C para cerrar)", flush=True)
    if not a.no_abrir:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
