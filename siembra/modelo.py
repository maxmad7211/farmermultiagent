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
from .campo import LIBRE, SEMBRADA, Campo, manhattan
from .comunicacion import Bus
from .config import derivados, derivados_m3, parametros_m3, validar
from .coordinador import EMERGENCIA, Coordinador, _bola
from .eventos import Eventos
from .planificador import TablaReservas

COLUMNAS_PASOS = ["t", "agente", "x", "y", "theta", "estado", "implemento", "intencion",
                  "objetivo_x", "objetivo_y", "tarea_x", "carga", "diesel_frac"]
COLUMNAS_SERIE = ["t", "surcado_frac", "sembrado_frac", "fila_estacion", "en_servicio",
                  "reservas_activas", "mensajes_acum", "perdidos_acum"]
COLUMNAS_MENSAJES = ["t_envio", "t_entrega", "performativa", "emisor", "receptor", "evento",
                     "tipo_tarea", "x", "ronda", "u", "perdido"]
COLUMNAS_REGISTRO = ["t", "fuente", "tipo", "evento", "tractor", "texto", "motivo"]
# Momentos de M3 que se miden (paso; -1 si no ocurrió)
MARCAS = ("t_deteccion_incendio", "t_respuesta_incendio", "t_deteccion_obstaculo", "t_respuesta_obstaculo",
          "t_deteccion_falla", "t_respuesta_falla", "t_remolque_entregado", "t_reparado")


def _bloques(valores, k):
    return [list(b) for b in np.array_split(np.array(valores), k)] if k > 0 else []


class ModeloSiembra(ap.Model):

    def setup(self):
        self.cfg = self.p["cfg"]
        self.detalle = bool(self.p["detalle"])
        self.d = derivados(self.cfg)
        self.mec = self.cfg["mecanismo"]
        self.cooperativo = self.mec in ("M2", "M3")   # Cooperative A*, fila en blackboard, broadcast
        m3 = parametros_m3(self.cfg)
        self.p3 = m3["coordinador"]
        self.d3 = derivados_m3(self.cfg)
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
        self.fallado_activo = False    # entre la falla y la reparación (M3)
        # M3 — estado del mundo y métricas (sin efecto mientras no haya eventos ni coordinador)
        self.remolques = {}            # tractor que remolca -> tractor remolcado
        self.marcas = {}
        self.registro_mundo = []
        self.verdad_reportes = {}
        self.n_reportes = 0
        self.reasig_celdas = 0
        self.reasig_hechas = 0
        self.entradas_fuego = 0
        self.entradas_peligro = 0
        self.entradas_prohibidas = 0
        self.entradas_sin_aviso = 0
        self.toques_obstaculo = 0
        self.frenadas_fuego = 0
        self._cache_zona = (None, frozenset())
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
        self.gestor = Gestor(self) if self.mec in ("M1", "M2", "M3") else None
        self.eventos = Eventos(self, m3["eventos"], reportes_falsos=self.p3["tasa_reporte_falso"] > 0)
        self.coordinador = Coordinador(self, self.p3) if self.mec == "M3" else None
        self.m3_activo = self.eventos.activo or self.coordinador is not None
        self.filas_pasos = []
        self.filas_serie = []
        self.prev_pos = [tr.pos for tr in self.orden]
        self._registrar(0)

    def tractor(self, nombre):
        for tr in self.orden:
            if tr.nombre == nombre:
                return tr
        return None

    def marcar(self, clave, t):
        """Anota la primera vez que ocurre un momento medible de M3 (ver MARCAS)."""
        self.marcas.setdefault(clave, int(t))

    def anotar_verdad(self, t, evento, texto):
        self.registro_mundo.append({"t": int(t), "fuente": "mundo", "tipo": "evento", "evento": evento,
                                    "tractor": "", "texto": texto, "motivo": ""})

    def contar_reasignacion(self, clave, inicio, d):
        """Métrica — celdas que se vuelven a repartir tras la falla y cuántas ya estaban hechas."""
        tipo, x = clave
        col = self.campo.columnas[x]
        if inicio is not None:
            inicio = tuple(inicio)
            d = d or 1
            col = [c for c in col if (c[1] >= inicio[1] if d == 1 else c[1] <= inicio[1])]
        hechas = 0
        for c in col:
            e = self.campo.estado(c)
            if (e != LIBRE and e != SEMBRADA and tipo == "surcar") or e == SEMBRADA:
                hechas += 1
        self.reasig_celdas += len(col)
        self.reasig_hechas += hechas

    def lugar_taller(self, quien):
        """Celda libre del patio, lejos de la entrada de la estación, donde se deja a un tractor remolcado."""
        dx = self.campo.deposito[0]
        ocupadas = {tr.pos for tr in self.orden}
        # Cerca de la estación y lejos de los estacionamientos (que están en las orillas del patio),
        # para no encerrar a nadie en una esquina mientras dura la reparación
        estacionamientos = {tr.estacionamiento for tr in self.orden}
        libres = [(x, 0) for x in range(self.campo.ancho)
                  if abs(x - dx) >= 3 and (x, 0) not in ocupadas and (x, 0) not in self.bloqueadas
                  and (x, 0) not in estacionamientos and 0 < x < self.campo.ancho - 1]
        if not libres:
            libres = [(x, 0) for x in range(self.campo.ancho) if abs(x - dx) >= 2] or [quien.pos]
        return min(libres, key=lambda c: (abs(c[0] - dx), manhattan(quien.pos, c), c))

    def ocupante(self, c):
        for tr in self.orden:
            if tr.pos == c:
                return tr
        return None

    # ------------------------------------------------------------------ paso
    def step(self):
        t = self.t
        if self.cooperativo:
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
        self.eventos.paso(t)
        if self.coordinador is not None:
            self.coordinador.paso(t)
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
        antes = {tr.nombre: tr.pos for tr in self.orden}
        obst = self.eventos.celdas_obstaculo
        fuego = self.eventos.fuego
        reclamadas = set()
        for tr in self.orden:  # orden de prioridad fijo: surcadores primero
            c = tr.deseo
            if c is None or c == tr.pos:
                continue
            if (c in ocupadas or c in reclamadas or c in self.bloqueadas
                    or c not in self.campo.vecinos[tr.pos] or tr.diesel <= 0 or c in obst or c in fuego):
                tr.vetado = True
                self.vetos += 1
                if c in obst:
                    # Topó con un obstáculo que no conocía — ahora sí lo sabe
                    self.toques_obstaculo += 1
                    tr.obst_visto.add(c)
                elif c in fuego:
                    # Capa reactiva — frena antes de entrar a una celda que arde (la tiene enfrente)
                    self.frenadas_fuego += 1
                    tr.ver_fuego(c, self.t)
                continue
            reclamadas.add(c)
            tr.mover(c)
        # M3 — el tractor remolcado ocupa la celda que deja quien lo remolca
        for n_grua, n_rem in self.remolques.items():
            grua, rem = self.tractor(n_grua), self.tractor(n_rem)
            if grua.movio:
                self.bloqueadas.discard(rem.pos)
                if self.campo.es_trabajo(rem.pos) and self.campo.estado(rem.pos) != SEMBRADA:
                    self.gestor.reabrir_celda(rem.pos)
                delta = (antes[n_grua][0] - rem.pos[0], antes[n_grua][1] - rem.pos[1])
                rem.theta = {(1, 0): 0, (0, 1): 90, (-1, 0): 180, (0, -1): 270}.get(delta, rem.theta)
                rem.pos = antes[n_grua]
                self.bloqueadas.add(rem.pos)

    def _verificar_seguridad(self):
        pos = [tr.pos for tr in self.orden]
        if self.m3_activo:
            self._medir_entradas(pos)
        self.colisiones += len(pos) - len(set(pos))
        for i in range(len(pos)):
            for j in range(i + 1, len(pos)):
                if pos[i] == self.prev_pos[j] and pos[j] == self.prev_pos[i] and pos[i] != pos[j]:
                    self.intercambios += 1
        self.prev_pos = pos

    def _zona_vigente(self):
        """Celdas que ya rigen como zona prohibida — las que llevan prohibidas sin interrupción al menos
        retraso_max + 1 pasos (el tiempo para que el aviso llegue). Si el aviso se pierde, sí cuentan
        (el coordinador lo reenvía con los latidos)."""
        if self.coordinador is None:
            return frozenset()
        co = self.coordinador
        if self._cache_zona[0] != self.t:
            limite = self.t - self.c["retraso_max"] - 1
            self._cache_zona = (self.t, frozenset(c for c, t0 in co.zona_desde.items() if t0 <= limite))
        return self._cache_zona[1]

    def _medir_entradas(self, pos):
        """M3 — entradas al fuego, junto al fuego (verdad) y a la zona que declaró el coordinador."""
        fuego = self.eventos.fuego
        peligro = _bola(fuego, 1, self.campo) if fuego else set()
        zona = self._zona_vigente()
        actual = self.coordinador.zona if self.coordinador is not None else frozenset()
        for tr, c, prev in zip(self.orden, pos, self.prev_pos):
            if c == prev or tr.remolcado_por:
                continue
            if c in fuego:
                self.entradas_fuego += 1
            if c in peligro and prev not in peligro:
                self.entradas_peligro += 1
            if c in zona and prev not in actual and prev not in tr.zona:   # salir de la zona no es entrar
                if c in tr.zona:
                    self.entradas_prohibidas += 1    # la conocía y aun así entró (no debe pasar)
                else:
                    self.entradas_sin_aviso += 1     # el aviso de la zona no le llegó (mensajes perdidos)

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
        self.fallado_activo = True
        self.anotar_verdad(t, "falla", f"{tr.nombre} se descompone en {list(tr.pos)}")
        self.bloqueadas_nombres.add(tr.nombre)
        self.falla_hecha = True
        self.t_falla = t
        self.tractor_fallado = tr.nombre

    def inaccesibles(self):
        """Celdas de trabajo sin sembrar que ya no se pueden trabajar (bajo un tractor descompuesto,
        quemadas o bajo un obstáculo nuevo)."""
        campo = self.campo
        perdidas = self.eventos.perdidas()
        n = sum(1 for c in self.bloqueadas
                if campo.es_trabajo(c) and campo.estado(c) != SEMBRADA and c not in perdidas)
        return n + len(perdidas)

    def _coordinador_pendiente(self):
        """M3: el coordinador todavía tiene a quién remolcar y con quién hacerlo (no se termina aún)."""
        co = self.coordinador
        if co is None or not (co.fallados or co.misiones or co.pendientes or self.fallado_activo):
            return False
        return any(tr.modo != M_FUERA for tr in self.orden)

    def _terminar(self, t):
        campo = self.campo
        inaccesibles = self.inaccesibles()
        if campo.n_sembradas + inaccesibles >= campo.n_trabajo:
            return True
        if all(tr.modo in (M_FUERA, M_TERMINADO) for tr in self.orden) and \
                not any(tr.reparando for tr in self.orden) and not self._coordinador_pendiente():
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
                    t, tr.nombre, tr.pos[0], tr.pos[1], tr.theta, tr.estado, tr.herramienta or tr.implemento,
                tr.intencion,
                    obj[0], obj[1], tr.tarea[1] if tr.tarea else -1,
                    tr.tolva / tolva if tr.implemento == SEMBRADORA else float("nan"),
                    max(0.0, tr.diesel) / tanque,
                ))
        if self.detalle or t % 10 == 0:
            self.filas_serie.append((
                t, campo.n_surcadas / campo.n_trabajo, campo.n_sembradas / campo.n_trabajo,
                sum(1 for tr in self.orden if tr.estado == EN_FILA),
                1 if self.en_servicio else 0,
                len(self.reservas.celdas) if self.cooperativo else 0,
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
    vigentes = campo.t_sembrado >= 0
    if m.eventos.activo:   # lo quemado o tapado por el obstáculo nuevo ya no cuenta como sembrado
        vigentes &= np.array([[e == SEMBRADA for e in fila] for fila in campo.est])
    sembradas = campo.t_sembrado[vigentes]
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
    inaccesibles = m.inaccesibles()

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
    if m.m3_activo or cfg["falla"]["activa"]:
        r.update(resumir_m3(m, g(EMERGENCIA)))
    try:
        from .metricas import costos
    except ImportError:  # el módulo de métricas se integra aparte
        costos = None
    if costos is not None:
        r.update(costos(r, cfg))
    return r


def resumir_m3(m, emergencia_h):
    """Métricas de la comparación M2 contra M3 (docs/m3.md). Solo con eventos activos o en M3."""
    ev, celda_ha = m.eventos, m.d["celda_ha"]
    marcas = {k: m.marcas.get(k, -1) for k in MARCAS}

    def dt(t_fin, t_ini):
        return t_fin - t_ini if t_fin >= 0 and t_ini >= 0 else -1

    r = {
        "t_incendio": ev.t_incendio,
        "t_obstaculo_nuevo": ev.t_obstaculo,
        "t_fuego_extinto": ev.t_fuego_extinto,
        **marcas,
        "dt_deteccion_incendio": dt(marcas["t_deteccion_incendio"], ev.t_incendio),
        "dt_respuesta_incendio": dt(marcas["t_respuesta_incendio"], ev.t_incendio),
        "dt_deteccion_obstaculo": dt(marcas["t_deteccion_obstaculo"], ev.t_obstaculo),
        "dt_deteccion_falla": dt(marcas["t_deteccion_falla"], m.t_falla),
        "dt_respuesta_falla": dt(marcas["t_respuesta_falla"], m.t_falla),
        "celdas_quemadas": len(ev.quemadas),
        "area_quemada_ha": len(ev.quemadas) * celda_ha,
        "celdas_apagadas": len(ev.apagadas),
        "area_perdida_ha": len(ev.perdidas()) * celda_ha,
        "celdas_reasignadas": m.reasig_celdas,
        "reasignadas_ya_hechas": m.reasig_hechas,
        "area_doble_ha": m.reasig_hechas * celda_ha,
        "entradas_fuego": m.entradas_fuego,
        "entradas_peligro": m.entradas_peligro,
        "entradas_prohibidas": m.entradas_prohibidas,
        "entradas_sin_aviso": m.entradas_sin_aviso,
        "toques_obstaculo": m.toques_obstaculo,
        "frenadas_fuego": m.frenadas_fuego,
        "emergencia_h": emergencia_h,
    }
    vacio = {"reportes_total": 0, "reportes_reales": 0, "reportes_falsos": 0, "falsos_descartados": 0,
             "falsos_confirmados": 0, "reales_descartados": 0, "reportes_verificados": 0,
             "reportes_sin_decidir": 0, "subastas_urgentes": 0, "replanes": 0, "decisiones_coordinador": 0}
    r.update(m.coordinador.resumen() if m.coordinador is not None else vacio)
    return r


def _df_registro(m):
    filas = list(m.registro_mundo)
    if m.coordinador is not None:
        filas += m.coordinador.registro
    filas.sort(key=lambda f: (f["t"], 0 if f["fuente"] == "mundo" else 1))
    return pd.DataFrame(filas, columns=COLUMNAS_REGISTRO)


def _df_mensajes(log):
    filas = []
    for msg in log:
        c = msg.contenido
        x, u = c.get("x", -1), float("nan")
        if msg.performativa == "accept-proposal":
            x = c["tarea"]["x"] if "tarea" in c else -1   # M3 — la adjudicación urgente no lleva hilera
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
    if modelo.m3_activo:
        # M3 / eventos — datos extra para la vista 2D (no cambian las llaves del contrato)
        eventos = modelo.eventos.exportar()
        eventos["zonas"] = modelo.coordinador.historia_zona if modelo.coordinador is not None else []
        res["eventos"] = eventos
        res["registro"] = _df_registro(modelo)
    return res
