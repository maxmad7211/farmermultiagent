"""Modelo AgentPy de la flota y función `simular` (API pública, ver docs/contrato_datos.md)."""

import json
import time
from collections import Counter

import agentpy as ap
import numpy as np
import pandas as pd

from .agentes import (CAMBIANDO, EN_FILA, EN_RUTA, ESPERANDO_CELDA, ESPERANDO_SURCO, ESTADOS_ESPERA,
                      FUERA, Gestor, M_FUERA, M_SERVICIO, M_TERMINADO, NEGOCIANDO, RECARGANDO, RUTA_DEPOSITO,
                      SEMBRADORA, SIN_TAREA, SURCADOR, TERMINADO, TRABAJANDO, Tractor)
from .campo import SEMBRADA, Campo
from .comunicacion import Bus
from .config import derivados, validar
from .planificador import TablaReservas

COLUMNAS_PASOS = ["t", "agente", "x", "y", "theta", "estado", "implemento", "intencion",
                  "objetivo_x", "objetivo_y", "tarea_x", "carga", "diesel_frac"]
COLUMNAS_SERIE = ["t", "surcado_frac", "sembrado_frac", "fila_estacion", "en_servicio",
                  "reservas_activas", "mensajes_acum", "perdidos_acum"]
COLUMNAS_MENSAJES = ["t_envio", "t_entrega", "performativa", "emisor", "receptor", "evento",
                     "tipo_tarea", "x", "ronda", "u", "perdido"]


def _bloques(valores, k):
    return [list(b) for b in np.array_split(np.array(valores), k)] if k > 0 else []


class ModeloSiembra(ap.Model):

    def setup(self):
        self.cfg = self.p["cfg"]
        self.detalle = bool(self.p["detalle"])
        self.d = derivados(self.cfg)
        self.mec = self.cfg["mecanismo"]
        self.c = self.cfg["comunicacion"]
        a = self.cfg["agente"]
        self.campo = Campo(self.cfg, self.random)
        self.bus = Bus(self.random, self.c["perdida_mensajes"], self.c["retraso_max"])
        self.reservas = TablaReservas()
        self.fila = {}                 # blackboard de la estación (M2): nombre -> hora estimada de llegada
        self.en_servicio = None
        self.bloqueadas = set()        # celdas ocupadas por tractores descompuestos
        self.bloqueadas_nombres = set()
        self.paciencia = a["paciencia_pasos"]
        self.paciencia_surco = 2 * self.campo.largo_hilera
        self.k_anticipo = self.c["timeout_ofertas"] + 2 * self.c["retraso_max"] + 3
        self.reserva_l = a["reserva_diesel_frac"] * a["tanque_l"]
        self.ultimo_progreso = 0
        self.max_estancado = self.cfg["simulacion"]["max_estancado_pasos"]
        self.estancado = False
        self.falla_hecha = False
        self.t_falla = -1
        self.tractor_fallado = ""
        self.colisiones = 0
        self.intercambios = 0
        self.vetos = 0

        n = self.cfg["flota"]["n_tractores"]
        self.n = n
        if n == 1:
            roles = [SURCADOR]
        else:
            nf = self.cfg["flota"].get("n_surcadores") or max(1, n // 2)
            roles = [SURCADOR] * nf + [SEMBRADORA] * (n - nf)
        self.n_surcadores = roles.count(SURCADOR)

        ancho = self.campo.ancho
        dx = self.campo.deposito[0]
        patio = sorted((abs(x - dx), x) for x in range(ancho) if abs(x - dx) >= 2)
        inicios = [(x, 0) for _d, x in patio[:n]]
        if len(inicios) < n:  # campos muy angostos: usa también la cabecera sur
            inicios += [(x, 1) for x in range(ancho) if (x, 1) not in inicios][: n - len(inicios)]
        lejanos = sorted(((x, 0) for x in range(ancho) if abs(x - dx) >= 2),
                         key=lambda c: (-abs(c[0] - dx), c[0]))
        estacionamientos = [lejanos[i % len(lejanos)] for i in range(n)]

        franjas = [[] for _ in range(n)]
        if self.mec == "M0":
            columnas = list(range(ancho))
            # Surcadores: franjas contiguas, empezando por la orilla más cercana a su posición inicial
            orden_surco = {}
            idx = sorted((i for i in range(n) if roles[i] == SURCADOR), key=lambda i: inicios[i][0])
            for i, bloque in zip(idx, _bloques(columnas, len(idx))):
                bloque = [int(v) for v in bloque]
                if abs(inicios[i][0] - bloque[0]) > abs(inicios[i][0] - bloque[-1]):
                    bloque.reverse()
                franjas[i] = bloque
                orden_surco.update({x: k for k, x in enumerate(bloque)})
            # Sembradoras: su franja en el mismo orden en que se surca, para ir detrás del surcador
            idx = sorted((i for i in range(n) if roles[i] == SEMBRADORA), key=lambda i: inicios[i][0])
            for i, bloque in zip(idx, _bloques(columnas, len(idx))):
                franjas[i] = sorted((int(v) for v in bloque), key=lambda x: orden_surco[x])

        self.orden = ap.AgentList(self, [
            Tractor(self, nombre=f"T{i + 1}", implemento=roles[i], pos=inicios[i],
                    franja=franjas[i], estacionamiento=estacionamientos[i])
            for i in range(n)
        ])
        self.tractores = self.orden
        self.gestor = Gestor(self) if self.mec in ("M1", "M2") else None
        self.filas_pasos = []
        self.filas_serie = []
        self.prev_pos = [tr.pos for tr in self.orden]
        self._registrar(0)

    def ocupante(self, c):
        for tr in self.orden:
            if tr.pos == c:
                return tr
        return None

    # ------------------------------------------------------------------ paso
    def step(self):
        t = self.t
        if self.mec == "M2":
            # Cooperative A*: tabla limpia cada paso; los tractores replanean en orden de prioridad.
            # Los que no se pueden mover (en servicio o estacionados) se reservan primero.
            self.reservas.reiniciar(t, {tr.nombre: tr.pos for tr in self.orden})
            W = self.c["ventana_reservas"]
            for tr in self.orden:
                if tr.modo == M_SERVICIO:
                    horizonte = min(W, tr.servicio)
                elif tr.modo == M_TERMINADO and tr.pos == tr.estacionamiento:
                    horizonte = W
                else:
                    continue
                for k in range(1, horizonte + 1):
                    self.reservas.reservar(tr.nombre, tr.pos, t + k)
        if self.gestor is not None:
            self.gestor.paso(t)
        self._falla(t)
        for tr in self.orden:
            tr.decidir(t)
        self._resolver()
        for tr in self.orden:
            tr.actuar(t)
        self._verificar_seguridad()
        self._registrar(t)
        if self._terminar(t):
            self.stop()

    def _resolver(self):
        """Capa reactiva: nadie entra a una celda ocupada al inicio del paso ni a una ya reclamada."""
        ocupadas = {tr.pos for tr in self.orden}
        reclamadas = set()
        for tr in self.orden:  # orden de prioridad fijo: surcadores primero
            c = tr.deseo
            if c is None or c == tr.pos:
                continue
            if (c in ocupadas or c in reclamadas or c in self.bloqueadas
                    or c not in self.campo.vecinos[tr.pos] or tr.diesel <= 0):
                tr.vetado = True
                self.vetos += 1
                continue
            reclamadas.add(c)
            tr.mover(c)

    def _verificar_seguridad(self):
        pos = [tr.pos for tr in self.orden]
        self.colisiones += len(pos) - len(set(pos))
        for i in range(len(pos)):
            for j in range(i + 1, len(pos)):
                if pos[i] == self.prev_pos[j] and pos[j] == self.prev_pos[i] and pos[i] != pos[j]:
                    self.intercambios += 1
        self.prev_pos = pos

    def _falla(self, t):
        f = self.cfg["falla"]
        if not f["activa"] or self.falla_hecha:
            return
        if self.campo.n_sembradas < f["cobertura_disparo"] * self.campo.n_trabajo:
            return
        candidatos = [tr for tr in self.orden if tr.tarea is not None and tr.pos != self.campo.deposito]
        if not candidatos:
            return
        tr = self.random.choice(candidatos)
        tr.fallar(t)
        self.bloqueadas_nombres.add(tr.nombre)
        self.falla_hecha = True
        self.t_falla = t
        self.tractor_fallado = tr.nombre

    def _terminar(self, t):
        campo = self.campo
        inaccesibles = sum(1 for c in self.bloqueadas if campo.es_trabajo(c) and campo.estado(c) != SEMBRADA)
        if campo.n_sembradas + inaccesibles >= campo.n_trabajo:
            return True
        if all(tr.modo in (M_FUERA, M_TERMINADO) for tr in self.orden):
            return True
        if t - self.ultimo_progreso > self.max_estancado:
            self.estancado = True
            return True
        return False

    def _registrar(self, t):
        campo = self.campo
        if self.detalle:
            tolva = self.d["tolva_celdas"]
            tanque = self.cfg["agente"]["tanque_l"]
            for tr in self.orden:
                obj = tr.objetivo or (-1, -1)
                self.filas_pasos.append((
                    t, tr.nombre, tr.pos[0], tr.pos[1], tr.theta, tr.estado, tr.implemento, tr.intencion,
                    obj[0], obj[1], tr.tarea[1] if tr.tarea else -1,
                    tr.tolva / tolva if tr.implemento == SEMBRADORA else float("nan"),
                    max(0.0, tr.diesel) / tanque,
                ))
        if self.detalle or t % 10 == 0:
            self.filas_serie.append((
                t, campo.n_surcadas / campo.n_trabajo, campo.n_sembradas / campo.n_trabajo,
                sum(1 for tr in self.orden if tr.estado == EN_FILA),
                1 if self.en_servicio else 0,
                len(self.reservas.celdas) if self.mec == "M2" else 0,
                len(self.bus.log), self.bus.n_perdidos,
            ))

    def end(self):
        self.resumen = resumir(self)
        for k in ("costo_ha", "T_h", "cobertura", "colisiones"):
            if k in self.resumen:
                self.report(k, self.resumen[k])


# ---------------------------------------------------------------------- resumen
def resumir(m):
    campo, d, cfg = m.campo, m.d, m.cfg
    sembradas = campo.t_sembrado[campo.t_sembrado >= 0]
    T = int(sembradas.max()) if sembradas.size else int(m.t)
    T = max(T, 1)
    paso_h = d["paso_h"]
    conteo = Counter()
    movs = 0
    activos = 0
    for tr in m.orden:
        estados = tr.hist_estado[:T]
        conteo.update(estados)
        movs += sum(tr.hist_mov[:T])
        activos += sum(1 for e in estados if e not in (TERMINADO, FUERA))
    h = {e: conteo.get(e, 0) * paso_h for e in set(conteo) | {TRABAJANDO}}
    g = lambda e: h.get(e, 0.0)
    espera_pasos = sum(conteo.get(e, 0) for e in ESTADOS_ESPERA)
    diesel = (movs + espera_pasos * cfg["agente"]["consumo_ralenti_frac"]) * d["diesel_paso_l"]

    # Balance de carga: hileras equivalentes trabajadas, dentro de cada rol
    largo = campo.largo_hilera
    por_rol = {}
    for tr in m.orden:
        rol = "mixto" if tr.cambiado else tr.implemento
        por_rol.setdefault(rol, []).append(tr.celdas_trabajadas / largo)
    hileras = [v for vals in por_rol.values() for v in vals]
    balance = max((max(v) - min(v)) for v in por_rol.values()) if por_rol else 0.0

    perf = Counter(msg.performativa for msg in m.bus.log)
    q = np.percentile(sembradas, np.arange(0, 101, 5)) if sembradas.size else np.zeros(21)
    inaccesibles = sum(1 for c in m.bloqueadas if campo.es_trabajo(c) and campo.estado(c) != SEMBRADA)

    r = {
        "mecanismo": m.mec,
        "hectareas": cfg["campo"]["hectareas"],
        "ha_sembrables": campo.ha_sembrables,
        "ancho": campo.ancho,
        "n_tractores": m.n,
        "n_surcadores": m.n_surcadores,
        "semilla": cfg["semilla"],
        "n_obstaculos": len(campo.obstaculos),
        "perdida_mensajes": m.c["perdida_mensajes"],
        "timeout_ofertas": m.c["timeout_ofertas"],
        "ventana_reservas": m.c["ventana_reservas"],
        "margen_recarga_hileras": m.c["margen_recarga_hileras"],
        "tolva_ha": cfg["agente"]["tolva_ha"],
        "falla_activa": bool(cfg["falla"]["activa"]),
        "jornada_h": cfg["escala_tiempo"]["jornada_h"],
        "dias_laborables": cfg["escala_tiempo"]["dias_laborables"],
        "celda_m": cfg["campo"]["celda_m"],
        "paso_s": d["paso_s"],
        "pasos_dia": d["pasos_dia"],
        "T_pasos": T,
        "T_h": T * paso_h,
        "T_dias": T / d["pasos_dia"],
        "pasos_simulados": int(m.t),
        "estancado": bool(m.estancado),
        "D_celdas": movs,
        "D_por_agente": movs / m.n,
        "colisiones": m.colisiones,
        "intercambios": m.intercambios,
        "vetos": m.vetos,
        "trabajo_h": g(TRABAJANDO),
        "traslado_h": g(EN_RUTA) + g(RUTA_DEPOSITO),
        "W_ocio_h": g(SIN_TAREA) + g(NEGOCIANDO),
        "W_negociacion_h": g(NEGOCIANDO),
        "W_espera_h": g(EN_FILA),
        "W_servicio_h": g(RECARGANDO) + g(CAMBIANDO),
        "W_conflicto_h": g(ESPERANDO_CELDA),
        "W_precedencia_h": g(ESPERANDO_SURCO),
        "fuera_servicio_h": g(FUERA),
        "H_motor_h": movs * paso_h,
        "diesel_l": diesel,
        "recargas": sum(tr.recargas for tr in m.orden),
        "n_celdas_trabajo": campo.n_trabajo,
        "n_surcadas": campo.n_surcadas,
        "n_sembradas": campo.n_sembradas,
        "n_no_sembradas": campo.n_trabajo - campo.n_sembradas,
        "celdas_inaccesibles": inaccesibles,
        "cobertura": campo.n_sembradas / campo.n_trabajo,
        "suma_t_siembra_pasos": float(sembradas.sum()),
        "t_primera_siembra": int(sembradas.min()) if sembradas.size else -1,
        "t_ultima_siembra": int(sembradas.max()) if sembradas.size else -1,
        "dispersion_dias": float(sembradas.max() - sembradas.min()) / d["pasos_dia"] if sembradas.size else 0.0,
        "mensajes_total": len(m.bus.log),
        "mensajes_perdidos": m.bus.n_perdidos,
        "msg_cfp": perf.get("cfp", 0),
        "msg_propose": perf.get("propose", 0),
        "msg_accept": perf.get("accept-proposal", 0),
        "msg_reject": perf.get("reject-proposal", 0),
        "msg_inform": perf.get("inform", 0),
        "subastas": m.gestor.subastas if m.gestor else 0,
        "reanuncios": m.gestor.reanuncios if m.gestor else 0,
        "ofertas_tardias": m.gestor.tardias if m.gestor else 0,
        "hileras_max": max(hileras),
        "hileras_min": min(hileras),
        "balance_carga": balance,
        "eficiencia_campo": conteo.get(TRABAJANDO, 0) / activos if activos else 0.0,
        "t_falla": m.t_falla,
        "tractor_fallado": m.tractor_fallado,
    }
    for i, v in zip(range(0, 101, 5), q):
        r[f"q{i:02d}" if i < 100 else "q100"] = float(v)
    try:
        from .metricas import costos
    except ImportError:  # el módulo de métricas se integra aparte
        costos = None
    if costos is not None:
        r.update(costos(r, cfg))
    return r


def _df_mensajes(log):
    filas = []
    for msg in log:
        c = msg.contenido
        x, u = c.get("x", -1), float("nan")
        if msg.performativa == "accept-proposal":
            x = c["tarea"]["x"]
        elif msg.performativa == "propose" and c.get("ofertas"):
            x, u = c["ofertas"][0]["x"], c["ofertas"][0]["u"]
        filas.append((msg.t_envio, msg.t_entrega, msg.performativa, msg.emisor, msg.receptor,
                      c.get("evento", "") if msg.performativa == "inform" else "",
                      c.get("tipo") or "", -1 if x is None else x, c.get("ronda", -1), u, msg.perdido))
    return pd.DataFrame(filas, columns=COLUMNAS_MENSAJES)


def simular(cfg, detalle=False):
    """Corre una simulación completa y devuelve el dict del contrato de datos."""
    validar(cfg)
    inicio = time.perf_counter()
    lado = cfg["campo"]["hectareas"] * 10000 / cfg["campo"]["celda_m"] ** 2
    max_pasos = int(cfg["simulacion"]["max_pasos_factor"] * lado) + 5000
    modelo = ModeloSiembra({"cfg": cfg, "detalle": detalle, "seed": cfg["semilla"]})
    modelo.run(steps=max_pasos, display=False)
    if modelo.t >= max_pasos and not modelo.resumen["estancado"]:
        modelo.resumen["estancado"] = True
    resumen = modelo.resumen
    resumen["tiempo_computo_s"] = time.perf_counter() - inicio
    campo = modelo.campo
    res = {
        "resumen": resumen,
        "parametros": json.loads(json.dumps(cfg)),
        "derivados": modelo.d,
        "campo": campo.descripcion(),
        "serie": pd.DataFrame(modelo.filas_serie, columns=COLUMNAS_SERIE),
        "celdas": {
            "tipo_base": campo.tipo_base(),
            "t_surcado": campo.t_surcado.copy(),
            "t_sembrado": campo.t_sembrado.copy(),
            "pasadas": campo.pasadas.copy(),
        },
    }
    if detalle:
        res["pasos"] = pd.DataFrame(modelo.filas_pasos, columns=COLUMNAS_PASOS)
        res["mensajes"] = _df_mensajes(modelo.bus.log)
    return res
