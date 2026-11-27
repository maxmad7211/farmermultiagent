"""Agentes: tractor (arquitectura híbrida) y gestor de subastas del depósito.

Tractor: capa deliberativa (elige hilera, planea ruta con A* o WHCA*, decide recargas) y capa
reactiva (la resuelve el modelo en `_resolver`: nadie entra a una celda ocupada).
Gestor: iniciador de Contract Net para todas las hileras (M1, M2 y M3).
M3 agrega el coordinador supervisor y la parte del tractor que habla con él (coordinador.py).
"""

import agentpy as ap

from .campo import LIBRE, OBSTACULO, QUEMADA, SEMBRADA, manhattan
from .comunicacion import GESTOR
from .coordinador import COORD, EMERGENCIA, TractorM3
from .planificador import DistanciaReal, astar, whca

# Estados por paso (figura 2 de la propuesta + ruta_deposito)
SIN_TAREA = "sin_tarea"
NEGOCIANDO = "negociando"
EN_RUTA = "en_ruta"
TRABAJANDO = "trabajando"
ESPERANDO_CELDA = "esperando_celda"
ESPERANDO_SURCO = "esperando_surco"
RUTA_DEPOSITO = "ruta_deposito"
EN_FILA = "en_fila"
RECARGANDO = "recargando"
CAMBIANDO = "cambiando_implemento"
FUERA = "fuera_servicio"
TERMINADO = "terminado"
ESTADOS = [SIN_TAREA, NEGOCIANDO, EN_RUTA, TRABAJANDO, ESPERANDO_CELDA, ESPERANDO_SURCO,
           RUTA_DEPOSITO, EN_FILA, RECARGANDO, CAMBIANDO, FUERA, TERMINADO, EMERGENCIA]
ESTADOS_ESPERA = {SIN_TAREA, NEGOCIANDO, ESPERANDO_CELDA, ESPERANDO_SURCO, EN_FILA}

SURCADOR, SEMBRADORA = "surcador", "sembradora"
TIPO = {SURCADOR: "surcar", SEMBRADORA: "sembrar"}

# Modos lógicos (qué está haciendo el tractor); el estado por paso se deriva de aquí.
# M_MISION (7, misión del coordinador de M3) está en coordinador.py.
M_LIBRE, M_NEGOCIA, M_TAREA, M_DEPOSITO, M_SERVICIO, M_TERMINADO, M_FUERA = range(7)

THETA = {(1, 0): 0, (0, 1): 90, (-1, 0): 180, (0, -1): 270}


class Tractor(TractorM3, ap.Agent):

    def setup(self, nombre, implemento, pos, franja=(), estacionamiento=None):
        m = self.model
        self.nombre = nombre
        self.implemento = implemento
        self.pos = tuple(pos)
        self.theta = 90
        self.estacionamiento = tuple(estacionamiento) if estacionamiento else self.pos
        self.modo = M_LIBRE
        self.estado = SIN_TAREA
        self.intencion = "ninguna"
        self.objetivo = None
        self.tarea = None          # (tipo, x)
        self.cola = []             # celdas pendientes de la hilera, en orden de trabajo
        self.dir = 0
        self.siguiente = None      # hilera ganada con oferta anticipada
        self.aviso_casi = False
        self.inicio_avisado = False
        self.ronda_neg = None
        self.t_neg = None
        self.franja = list(franja)  # M0: hileras fijas pendientes
        self.suspendida = None     # M0: hilera interrumpida por una recarga
        self.motivo = None
        self.servicio = 0
        self.estado_servicio = None
        self.ruta = []
        self.meta_ruta = None
        self._h_clave = None       # caché de la distancia real a la meta (WHCA*)
        self._h = None
        self.bloqueado = 0
        self.bloqueado_fila = 0
        self.espera_surco = 0
        self.deseo = None
        self.movio = False
        self.vetado = False
        self.tolva = m.d["tolva_celdas"] if implemento == SEMBRADORA else 0
        self.diesel = float(m.cfg["agente"]["tanque_l"])
        self.cambiado = False
        self.fin_tipo = None       # labor que el gestor declaró terminada ("surcar")
        self.fallados_conocidos = set()
        # Antibloqueo escalonado: el de menor prioridad (índice mayor) cede y replanea primero,
        # así dos tractores de frente no replanean en el mismo paso con movimientos simétricos.
        indice = int(nombre[1:]) - 1
        self.paciencia = m.paciencia + 3 * (m.n - 1 - indice)
        # Contabilidad
        self.hist_estado = []
        self.hist_mov = []
        self.celdas_trabajadas = 0
        self.hileras = 0
        self.recargas = 0
        self.cede_hasta = -1
        self._setup_m3()

    # ------------------------------------------------------------------ ciclo por paso
    def decidir(self, t):
        m = self.model
        self.deseo = None
        self.movio = False
        self.vetado = False
        if self.modo == M_FUERA:
            self.estado = FUERA
            self.intencion = "ninguna"
            if self.reparando:
                self._paso_reparacion(t)
            return
        self._leer_buzon(t)
        if m.m3_activo and self._paso_m3(t):
            return

        if self.modo == M_SERVICIO:
            self.servicio -= 1
            self.estado = self.estado_servicio
            if self.servicio <= 0:
                self._fin_servicio(t)
            self._quieto(t)
            return

        if self.modo == M_TAREA:
            motivo = self._necesita_deposito()
            if motivo:
                self._dejar_tarea(t, motivo)
        elif self.modo in (M_LIBRE, M_NEGOCIA):
            motivo = self._necesita_deposito()
            if motivo:
                self.modo = M_LIBRE
                self.ronda_neg = None
                self._ir_deposito(t, motivo)

        for _ in range(4):
            if self.modo == M_LIBRE:
                r = self._paso_libre(t)
                if r == "cambio":
                    continue
                if r == "hecho":
                    return
                self.estado, self.intencion = SIN_TAREA, "esperar"
                self._quieto_fuera_de_hilera(t)
                return
            if self.modo == M_TAREA:
                if self._paso_tarea(t):
                    continue
                return
            if self.modo == M_DEPOSITO:
                self._paso_deposito(t)
                return
            if self.modo == M_NEGOCIA:
                limite = self.model.c["timeout_ofertas"] + self.model.c["retraso_max"] + 2
                if t - self.t_neg > limite:
                    self.modo = M_LIBRE
                    self.ronda_neg = None
                    continue
                self.estado, self.intencion = NEGOCIANDO, "ofertar"
                self._quieto_fuera_de_hilera(t)
                return
            if self.modo == M_TERMINADO:
                self.estado, self.intencion = TERMINADO, "estacionar"
                self.objetivo = self.estacionamiento
                if m.coordinador is not None and self._ceder_estacionado(t):
                    return
                if m.coordinador is not None and t < self.cede_hasta:
                    self._quieto(t)   # acaba de quitarse — espera a que el otro salga antes de volver
                    return
                if self.pos != self.estacionamiento:
                    self.deseo = self._paso_hacia(t, self.estacionamiento)
                else:
                    self._quieto(t)
                return
            if self.modo == M_SERVICIO:
                self.estado = self.estado_servicio
                self._quieto(t)
                return
        self._quieto(t)

    def actuar(self, t):
        m = self.model
        if self.vetado and self.estado not in (EN_FILA, TERMINADO, SIN_TAREA, NEGOCIANDO):
            self.estado = ESPERANDO_CELDA
        if self.movio:
            self.bloqueado = 0
            m.campo.pasadas[self.pos] += 1
            self.diesel -= m.d["diesel_paso_l"]
            if self.ruta and self.ruta[0] == self.pos:
                self.ruta.pop(0)
            if self.modo == M_TAREA and self.cola and self.pos == self.cola[0]:
                self._trabajar_celda(t)
        else:
            if self.estado == ESPERANDO_CELDA or self.vetado:
                self.bloqueado += 1
            if self.estado in ESTADOS_ESPERA:
                self.diesel -= m.d["diesel_paso_l"] * m.cfg["agente"]["consumo_ralenti_frac"]
        self.hist_estado.append(self.estado)
        self.hist_mov.append(1 if self.movio else 0)

    def mover(self, c):
        delta = (c[0] - self.pos[0], c[1] - self.pos[1])
        self.theta = THETA.get(delta, self.theta)
        self.pos = c
        self.movio = True

    def fallar(self, t):
        m = self.model
        info = {"evento": "falla",
                "tipo": self.tarea[0] if self.tarea else None,
                "x": self.tarea[1] if self.tarea else -1,
                "siguiente": list(self.cola[0]) if self.cola else None,
                "restantes": len(self.cola),
                "dir": self.dir}
        self.modo = M_FUERA
        self.estado = FUERA
        m.bloqueadas.add(self.pos)
        m.fila.pop(self.nombre, None)
        if m.cooperativo:
            m.reservas.liberar_todo(self.nombre)
        if m.mec == "M2":
            # Broadcast de falla: el gestor reanuncia la hilera de inmediato
            m.bus.difundir(t, "inform", self.nombre, [GESTOR] + [tr.nombre for tr in m.orden], info)
        elif m.coordinador is not None:
            # M3 — solo le avisa al coordinador (el mensaje se puede perder; si no, lo nota por los latidos)
            m.bus.enviar(t, "inform", self.nombre, COORD, {**info, "pos": list(self.pos)})
        self.tarea, self.cola, self.siguiente = None, [], None

    # ------------------------------------------------------------------ trabajo
    def _hecha(self, c):
        e = self.model.campo.estado(c)
        if e == QUEMADA or e == OBSTACULO:
            return True   # M3 — se perdió (fuego u obstáculo nuevo); ya no hay nada que hacer ahí
        return e == SEMBRADA if self.implemento == SEMBRADORA else e != LIBRE

    def _trabajar_celda(self, t):
        m = self.model
        c = self.cola.pop(0)
        tipo = self.tarea[0]
        if tipo == "surcar":
            hecho = m.campo.surcar(c, t)
        else:
            hecho = self.tolva > 0 and m.campo.sembrar(c, t)
        if not hecho:
            if not self._hecha(c):
                self.cola.insert(0, c)  # no se pudo trabajar (p. ej. aún sin surco): sigue pendiente
            self.estado = EN_RUTA
            return
        self.estado = TRABAJANDO
        self.celdas_trabajadas += 1
        m.ultimo_progreso = t
        if tipo == "sembrar":
            self.tolva -= 1
        elif m.campo.dir_surco[c[0]] == 0:
            m.campo.dir_surco[c[0]] = self.dir  # estigmergia: la sembradora sigue esta dirección
        if m.gestor is not None and not self.inicio_avisado:
            self._informar(t, "inicio", tipo, c[0], dir=self.dir, inicio=list(c),
                           restantes=len(self.cola) + 1)
            self.inicio_avisado = True

    def _paso_tarea(self, t):
        """Avanza en la hilera. Devuelve True si cambió de modo (terminó o soltó la hilera)."""
        m = self.model
        tipo, x = self.tarea
        # Percepción local: descarta las celdas vecinas ya trabajadas o tapadas por un tractor descompuesto
        while self.cola:
            c = self.cola[0]
            if manhattan(self.pos, c) <= 1 and (self._hecha(c) or c in m.bloqueadas):
                self.cola.pop(0)
                continue
            if c in self._perdidas_conocidas:   # M3 — sabe que ahí hay fuego u obstáculo
                self.cola.pop(0)
                continue
            break
        if (m.gestor is not None and m.c["oferta_anticipada"] and not self.aviso_casi
                and len(self.cola) <= m.k_anticipo):
            self._informar(t, "casi_libre", tipo, x)
            self.aviso_casi = True
        if not self.cola:
            self._fin_tarea(t)
            return True
        c = self.cola[0]
        self.objetivo = c
        if c in self._vedadas:
            # M3 — la siguiente celda está en zona prohibida o junto al fuego; espera fuera de ella
            self.espera_zona += 1
            if m.gestor is not None and self.espera_zona > 2 * m.campo.largo_hilera:
                self._informar(t, "liberada", tipo, x, siguiente=list(c), restantes=len(self.cola), dir=self.dir)
                self.tarea, self.cola = None, []
                self.espera_zona = 0
                self._soltar_siguiente(t)
                self.modo = M_LIBRE
                return True
            self.estado, self.intencion = ESPERANDO_CELDA, "esperar"
            self._quieto(t)
            return False
        self.espera_zona = 0
        if c == self.pos:
            # Quedó parado sobre una celda pendiente (llegó sin poder trabajarla): la trabaja aquí si ya se puede
            puede = (m.campo.estado(c) == LIBRE if self.implemento == SURCADOR
                     else m.campo.estado(c) != LIBRE and self.tolva > 0)
            if puede:
                self._trabajar_celda(t)
                self.estado, self.intencion = TRABAJANDO, tipo
                self._quieto(t)
                return False
        if self.implemento == SEMBRADORA and manhattan(self.pos, c) <= 1 and m.campo.estado(c) == LIBRE:
            # Precedencia: la sembradora espera a que el surcador abra el surco
            self.espera_surco += 1
            if m.gestor is not None and self.espera_surco > m.paciencia_surco:
                self._informar(t, "liberada", tipo, x, siguiente=list(c), restantes=len(self.cola), dir=self.dir)
                self.tarea, self.cola = None, []
                self.espera_surco = 0
                if self.siguiente:
                    s, self.siguiente = self.siguiente, None
                    self._asignar(s, t)
                else:
                    self.modo = M_LIBRE
                return True
            self.estado, self.intencion = ESPERANDO_SURCO, "sembrar"
            self._quieto(t)
            return False
        self.espera_surco = 0
        self.intencion = tipo
        # Para llegar al inicio no pisa lo que le falta trabajar de su hilera: entra por detrás,
        # en el sentido del trabajo, y no de frente contra quien viene trabajando la misma hilera.
        evitar = frozenset(self.cola[1:]) if manhattan(self.pos, c) > 1 else frozenset()
        paso = self._paso_hacia(t, c, evitar)
        self.deseo = paso
        if paso == c:
            self.estado = TRABAJANDO
        elif paso is None or paso == self.pos:
            self.estado = ESPERANDO_CELDA
        else:
            self.estado = EN_RUTA
        return False

    def _asignar(self, info, t):
        m = self.model
        x = info["x"]
        col = m.campo.columnas[x]
        inicio = tuple(info["inicio"]) if info.get("inicio") else None
        d = info.get("dir", 0) or 0
        if info.get("completa_surco") and inicio is None:
            d = 0
        if d == 0:
            d = 1 if manhattan(self.pos, col[0]) <= manhattan(self.pos, col[-1]) else -1
        if d == 1:
            cola = [c for c in col if inicio is None or c[1] >= inicio[1]]
        else:
            cola = [c for c in reversed(col) if inicio is None or c[1] <= inicio[1]]
        self.tarea = (info["tipo"], x)
        self.dir = d
        self.cola = cola
        self.modo = M_TAREA
        self.aviso_casi = False
        self.inicio_avisado = False
        self.espera_surco = 0
        self.ruta = []

    def _fin_tarea(self, t):
        m = self.model
        tipo, x = self.tarea
        self.hileras += 1
        if m.gestor is not None:
            self._informar(t, "fin", tipo, x, dir=self.dir)
        self.tarea, self.cola, self.aviso_casi = None, [], False
        if m.cooperativo and self.siguiente:
            motivo = self._anticipar_recarga()
            if motivo:
                self._soltar_siguiente(t)
                self._ir_deposito(t, motivo)
                return
        if self.siguiente:
            s, self.siguiente = self.siguiente, None
            self._asignar(s, t)
            return
        self.modo = M_LIBRE

    def _soltar_siguiente(self, t):
        s, self.siguiente = self.siguiente, None
        if s:
            self._informar(t, "liberada", s["tipo"], s["x"], siguiente=s.get("inicio"),
                           restantes=s.get("restantes"), dir=s.get("dir", 0))

    # ------------------------------------------------------------------ sin tarea
    def _paso_libre(self, t):
        """M0 toma la siguiente hilera de su franja; M2 revisa si debe recargar antes de ofertar."""
        m = self.model
        if m.mec == "M0":
            campo = m.campo
            while self.franja:
                x = self.franja[0]
                if self.implemento == SEMBRADORA:
                    if campo.hilera_completa(x, "sembrar"):
                        self.franja.pop(0)
                        continue
                    surcada = campo.hilera_completa(x, "surcar")
                    if not surcada and campo.dir_surco[x] == 0:
                        # Estigmergia: espera a que su surcador abra la hilera
                        self.estado, self.intencion = ESPERANDO_SURCO, "esperar"
                        self.objetivo = None
                        self._quieto_fuera_de_hilera(t)
                        return "hecho"
                    self.franja.pop(0)
                    self._asignar({"tipo": "sembrar", "x": x, "dir": campo.dir_surco[x],
                                   "completa_surco": surcada}, t)
                    return "cambio"
                if campo.hilera_completa(x, "surcar"):
                    self.franja.pop(0)
                    continue
                self.franja.pop(0)
                self._asignar({"tipo": "surcar", "x": x, "dir": 0}, t)
                return "cambio"
            if m.n == 1 and self.implemento == "surcador" and not self.cambiado:
                self._ir_deposito(t, "cambio")
                return "cambio"
            self.modo = M_TERMINADO
            return "cambio"
        if m.cooperativo:
            motivo = self._anticipar_recarga()
            if motivo:
                self._ir_deposito(t, motivo)
                return "cambio"
        return None

    def _anticipar_recarga(self):
        """M2: recarga antes de empezar una hilera que no podría terminar."""
        m = self.model
        largo = m.campo.largo_hilera
        if self.implemento == SEMBRADORA:
            margen = m.c["margen_recarga_hileras"]
            if self.tolva < (1 + margen) * largo:
                hay_fila = any(n != self.nombre for n in m.fila)
                if self.tolva < largo or not hay_fila:
                    return "semilla"
        necesario = ((largo + manhattan(self.pos, m.campo.deposito) + m.campo.ancho)
                     * m.d["diesel_paso_l"] * 1.3 + m.reserva_l)
        if self.diesel < necesario:
            return "diesel"
        return None

    def _necesita_deposito(self):
        """Regla reactiva de todos los mecanismos: tolva vacía o diésel justo para regresar."""
        m = self.model
        if self.implemento == SEMBRADORA and self.tolva <= 0:
            return "semilla"
        necesario = (manhattan(self.pos, m.campo.deposito) + 2) * m.d["diesel_paso_l"] * 1.5 + m.reserva_l
        if self.diesel < necesario:
            return "diesel"
        return None

    def _dejar_tarea(self, t, motivo):
        m = self.model
        if m.mec == "M0":
            self.suspendida = (self.tarea, list(self.cola), self.dir)
        else:
            if self.cola:
                self._informar(t, "liberada", self.tarea[0], self.tarea[1], siguiente=list(self.cola[0]),
                               restantes=len(self.cola), dir=self.dir)
            self._soltar_siguiente(t)
        self.tarea, self.cola = None, []
        self._ir_deposito(t, motivo)

    # ------------------------------------------------------------------ depósito
    def _ir_deposito(self, t, motivo):
        m = self.model
        self.modo = M_DEPOSITO
        self.motivo = motivo
        self.ruta = []
        self.bloqueado_fila = 0
        if m.cooperativo:
            m.fila[self.nombre] = t + manhattan(self.pos, m.campo.deposito)
            otros = [tr.nombre for tr in m.orden if tr.modo != M_FUERA]
            m.bus.difundir(t, "inform", self.nombre, otros, {"evento": "recarga", "motivo": motivo})

    def _paso_deposito(self, t):
        m = self.model
        dep = m.campo.deposito
        self.intencion = {"cambio": "cambiar", "pipa": "enganchar pipa", "grua": "enganchar grua",
                          "agua": "llenar pipa", "devolver": "regresar herramienta"}.get(self.motivo, "recargar")
        self.objetivo = dep
        if self.pos == dep:
            self._iniciar_servicio(t)
            self._quieto(t)
            return
        d = manhattan(self.pos, dep)
        ocupado = m.en_servicio is not None  # la estación está ocupada si alguien está cargando
        if m.cooperativo:
            # El blackboard ordena la fila por la hora estimada de llegada que cada tractor anotó al
            # formarse (fija: si se actualizara cada paso, cada uno compararía contra datos viejos)
            en_espera = sorted((eta, n) for n, eta in m.fila.items()
                               if n != m.en_servicio and n not in m.bloqueadas_nombres)
            turno = not en_espera or en_espera[0][1] == self.nombre
            esperar = d <= 2 and (ocupado or not turno)
        else:
            esperar = d <= 2 and ocupado
        if esperar:
            self.estado = EN_FILA
            self.bloqueado_fila += 1
            if d == 1 and self.bloqueado_fila > m.paciencia:
                # Se hace a un lado para no tapar la salida del depósito
                for v in m.campo.vecinos[self.pos]:
                    if (manhattan(v, dep) == 2 and m.ocupante(v) is None and v not in m.bloqueadas
                            and v not in self._vedadas):
                        self.deseo = v
                        return
            self._quieto(t)
            return
        self.bloqueado_fila = 0
        paso = self._paso_hacia(t, dep)
        self.deseo = paso
        self.estado = RUTA_DEPOSITO if paso not in (None, self.pos) else ESPERANDO_CELDA

    def _iniciar_servicio(self, t):
        m = self.model
        a = m.cfg["agente"]
        extra = self._servicio_m3(self.motivo) if m.m3_activo else None
        if extra is not None:
            base = extra   # M3 — enganchar o regresar la pipa o la grúa, o llenar la pipa
            self.estado_servicio = CAMBIANDO
        elif self.motivo == "cambio":
            base = m.d["pasos_cambio"]
            self.estado_servicio = CAMBIANDO
        else:
            base = 1
            if self.implemento == SEMBRADORA and self.tolva < m.d["tolva_celdas"]:
                base = max(base, m.d["pasos_recarga_semilla"])
            if self.diesel < a["tanque_l"]:
                base = max(base, m.d["pasos_recarga_diesel"])
            self.estado_servicio = RECARGANDO
        var = a["variacion_servicio"]
        self.servicio = max(1, int(round(base * (1 + m.random.uniform(-var, var)))))
        self.modo = M_SERVICIO
        self.estado = self.estado_servicio
        self.recargas += 1
        m.en_servicio = self.nombre

    def _fin_servicio(self, t):
        m = self.model
        motivo = self.motivo
        self.diesel = float(m.cfg["agente"]["tanque_l"])
        if self.motivo == "cambio":
            self.implemento = SEMBRADORA
            self.cambiado = True
            if m.mec == "M0":
                self.franja = list(range(m.campo.ancho))
            else:
                self._informar(t, "implemento", "sembrar", -1)
        if self.implemento == SEMBRADORA:
            self.tolva = m.d["tolva_celdas"]
        m.fila.pop(self.nombre, None)
        if m.en_servicio == self.nombre:
            m.en_servicio = None
        self.motivo = None
        if m.m3_activo and self._fin_servicio_m3(t, motivo):
            return
        if self.suspendida:
            (self.tarea, self.cola, self.dir), self.suspendida = self.suspendida, None
            self.modo = M_TAREA
        else:
            self.modo = M_LIBRE
            if m.gestor is not None:
                # Avisa que quedó libre para que el gestor abra una subasta sin esperar al reintento
                self._informar(t, "disponible", TIPO[self.implemento], -1)

    # ------------------------------------------------------------------ mensajes
    def _informar(self, t, evento, tipo, x, **extra):
        contenido = {"evento": evento, "tipo": tipo, "x": x}
        contenido.update(extra)
        self.model.bus.enviar(t, "inform", self.nombre, GESTOR, contenido)

    def _leer_buzon(self, t):
        m = self.model
        if m.gestor is None:
            return
        for msg in m.bus.recibir(self.nombre, t):
            p, c = msg.performativa, msg.contenido
            if msg.emisor == COORD:
                self._mensaje_coord(t, msg)
                continue
            if p == "cfp":
                self._responder_cfp(t, c)
            elif p == "accept-proposal":
                if self.ronda_neg is not None and c["ronda"] == self.ronda_neg:
                    self.ronda_neg = None
                    if self.modo == M_NEGOCIA:
                        self._asignar(c["tarea"], t)
                    elif self.modo == M_TAREA and self.siguiente is None:
                        self.siguiente = c["tarea"]
                    else:
                        s = c["tarea"]
                        self._informar(t, "liberada", s["tipo"], s["x"], siguiente=s.get("inicio"),
                                       restantes=s.get("restantes"), dir=s.get("dir", 0))
            elif p == "reject-proposal":
                if self.ronda_neg is not None and c["ronda"] == self.ronda_neg:
                    self.ronda_neg = None
                    if self.modo == M_NEGOCIA:
                        self.modo = M_LIBRE
            elif p == "inform":
                ev = c.get("evento")
                if ev == "fin_tipo":
                    self.fin_tipo = c.get("tipo")  # se atiende en cuanto quede libre, aunque llegue ocupado
                elif ev == "reactivar" and self.modo == M_TERMINADO and c.get("tipo") == TIPO[self.implemento]:
                    # M3: quedaron celdas de su labor sin trabajar; vuelve a ofertar
                    self.modo = M_LIBRE
                    self.fin_tipo = None
                elif ev == "falla":
                    self.fallados_conocidos.add(msg.emisor)
        if self.fin_tipo == TIPO[self.implemento] and self.modo in (M_LIBRE, M_NEGOCIA):
            self.fin_tipo = None
            self.ronda_neg = None
            if m.n == 1 and self.implemento == SURCADOR and not self.cambiado:
                self._ir_deposito(t, "cambio")
            else:
                self.modo = M_TERMINADO

    def _responder_cfp(self, t, c):
        m = self.model
        if c["tipo"] != TIPO[self.implemento]:
            return
        anticipada = (self.modo == M_TAREA and self.aviso_casi and self.siguiente is None
                      and self.ronda_neg is None)
        if not (self.modo == M_LIBRE or anticipada):
            return
        origen = self.cola[-1] if anticipada and self.cola else self.pos
        tolva_disp = self.tolva - (len(self.cola) if anticipada else 0)
        V, costo = m.c["valor_hilera"], m.c["costo_celda"]
        ofertas = []
        for tarea in c["tareas"]:
            inicio = self._inicio_tarea(tarea, origen)
            if inicio in self._perdidas_conocidas:
                inicio = self._saltar_perdidas(tarea, inicio)   # M3 — empieza en un obstáculo o en lo quemado
                if inicio is None:
                    continue
            if inicio in self._vedadas:
                continue   # M3 — no oferta por una hilera que empieza en zona prohibida
            restantes = tarea.get("restantes") or len(m.campo.columnas[tarea["x"]])
            if m.cooperativo and self.implemento == SEMBRADORA and restantes > tolva_disp:
                continue
            dist = manhattan(origen, inicio)
            ofertas.append({"x": tarea["x"], "u": V - costo * dist, "dist": dist})
        if not ofertas:
            return
        ofertas.sort(key=lambda o: (-o["u"], o["x"]))
        m.bus.enviar(t, "propose", self.nombre, GESTOR,
                     {"tipo": c["tipo"], "ronda": c["ronda"], "ofertas": ofertas[:3]})
        self.ronda_neg = c["ronda"]
        self.t_neg = t
        if self.modo == M_LIBRE:
            self.modo = M_NEGOCIA

    def _saltar_perdidas(self, tarea, inicio):
        """M3 — primera celda de la hilera, desde `inicio` en su sentido, que no esté perdida."""
        col = self.model.campo.columnas[tarea["x"]]
        d = tarea.get("dir") or (1 if inicio == col[0] else -1)
        for c in (col if d == 1 else col[::-1]):
            if (c[1] >= inicio[1] if d == 1 else c[1] <= inicio[1]) and c not in self._perdidas_conocidas:
                return c
        return None

    def _inicio_tarea(self, tarea, origen):
        col = self.model.campo.columnas[tarea["x"]]
        if tarea.get("inicio"):
            return tuple(tarea["inicio"])
        d = 0 if tarea.get("completa_surco") else (tarea.get("dir") or 0)
        if d == 1:
            return col[0]
        if d == -1:
            return col[-1]
        return col[0] if manhattan(origen, col[0]) <= manhattan(origen, col[-1]) else col[-1]

    # ------------------------------------------------------------------ movimiento
    def _quieto(self, t):
        self.deseo = None
        m = self.model
        if not m.cooperativo or self.modo == M_SERVICIO:
            return  # en servicio ya quedó reservado al inicio del paso
        res = m.reservas
        res.liberar_futuro(self.nombre, t)
        if self.modo not in (M_SERVICIO, M_FUERA) and not (res.libre(self.pos, t + 1, self.nombre)
                                                           and res.libre(self.pos, t + 2, self.nombre)):
            # Un tractor de mayor prioridad necesita esta celda: se hace a un lado (prefiere no pisar hileras)
            pendientes = set(self.cola)
            vecinos = sorted(m.campo.vecinos[self.pos], key=lambda v: (m.campo.es_trabajo(v), v))
            for v in vecinos:
                if v in pendientes or v == m.campo.deposito or v in self._vedadas:
                    continue  # no pisa lo que le falta trabajar, ni se mete a la estación o a zona prohibida
                if (v not in m.bloqueadas and m.ocupante(v) is None and res.libre(v, t, self.nombre)
                        and res.libre(v, t + 1, self.nombre) and res.libre(v, t + 2, self.nombre)):
                    self.deseo = v
                    for k in range(1, m.c["ventana_reservas"] + 1):
                        res.reservar(self.nombre, v, t + k)
                    return
        for k in range(1, m.c["ventana_reservas"] + 1):
            res.reservar(self.nombre, self.pos, t + k)

    def _quieto_fuera_de_hilera(self, t):
        """Un tractor sin tarea no se queda parado en el área de trabajo ni junto a la estación."""
        m = self.model
        campo = m.campo
        dep = campo.deposito
        if campo.es_trabajo(self.pos):
            x, y = self.pos
            meta = (x, 1) if (y - 1) <= (campo.alto - 1 - y) else (x, campo.alto - 1)
            self.objetivo = meta
            self.deseo = self._paso_hacia(t, meta)
        elif manhattan(self.pos, dep) <= 1:
            ocupadas = {tr.pos for tr in m.orden if tr is not self}
            libres = [(x, 0) for x in range(campo.ancho)
                      if abs(x - dep[0]) >= 2 and (x, 0) not in ocupadas and (x, 0) not in m.bloqueadas]
            if libres:
                meta = min(libres, key=lambda c: (manhattan(self.pos, c), c[0]))
                self.objetivo = meta
                self.deseo = self._paso_hacia(t, meta)
            else:
                self._quieto(t)
        else:
            self._quieto(t)

    def _paso_hacia(self, t, meta, evitar=frozenset()):
        m = self.model
        if self.pos == meta:
            self._quieto(t)
            return None
        if meta != m.campo.deposito:
            evitar = evitar | {m.campo.deposito}  # la estación no es camino de paso
        if m.cooperativo:
            return self._paso_whca(t, meta, evitar)
        base = self._bloq()   # M3 — suma la zona prohibida y lo que vio peligroso
        bloqueadas = base | evitar if evitar else base
        if self.bloqueado >= self.paciencia:
            siguiente = self.ruta[0] if self.ruta else None
            otro = m.ocupante(siguiente) if siguiente else None
            if otro is not None and otro.deseo == self.pos:
                # Bloqueo mutuo (de frente en un carril): cede el de menor prioridad, o cualquiera si dura mucho
                if self.paciencia < otro.paciencia or self.bloqueado >= 3 * self.paciencia:
                    paso = self._ceder(otro)
                    if paso is not None:
                        self.bloqueado = 0
                        return paso
            else:
                # Antibloqueo: replanea tratando a los demás tractores como obstáculos
                ocupadas = {tr.pos for tr in m.orden if tr is not self and tr.pos != meta}
                r = astar(m.campo, self.pos, meta, bloqueadas | ocupadas)
                if r:
                    self.bloqueado = 0
                    self.ruta, self.meta_ruta = r, meta
                    return r[0]
        if not (self.ruta and self.meta_ruta == meta and self.ruta[0] in m.campo.vecinos[self.pos]):
            self.ruta = astar(m.campo, self.pos, meta, bloqueadas) or (
                astar(m.campo, self.pos, meta, base) if evitar else None) or []
            self.meta_ruta = meta
        return self.ruta[0] if self.ruta else None

    def _ceder_estacionado(self, t):
        """M3 — un tractor que ya terminó se quita si tiene al lado a otro que lleva rato atorado (en el
        patio, con la grúa y las reparaciones, un estacionado puede encerrar a otro en una esquina)."""
        m = self.model
        atorados = [tr for tr in m.orden if tr is not self and tr.modo not in (M_FUERA, M_TERMINADO)
                    and manhattan(tr.pos, self.pos) == 1 and tr.bloqueado >= 2 * tr.paciencia]
        if not atorados:
            return False
        ocupadas = {tr.pos for tr in m.orden if tr is not self}
        opciones = [v for v in m.campo.vecinos[self.pos]
                    if v not in ocupadas and v not in m.bloqueadas and v != m.campo.deposito
                    and v not in self._vedadas]
        if not opciones:
            return False
        lejos = max(opciones, key=lambda v: (min(manhattan(v, tr.pos) for tr in atorados), v))
        self.deseo = lejos
        self.cede_hasta = t + 2 * m.paciencia + 2
        if m.cooperativo:
            m.reservas.liberar_futuro(self.nombre, t)
            m.reservas.reservar(self.nombre, lejos, t + 1)
        return True

    def _ceder(self, otro):
        """Retrocede a una celda libre que no sea la del otro tractor (prefiere no pisar hileras)."""
        m = self.model
        pendientes = set(self.cola)
        opciones = [v for v in m.campo.vecinos[self.pos]
                    if v != otro.pos and v not in m.bloqueadas and m.ocupante(v) is None
                    and v not in pendientes and v != m.campo.deposito and v not in self._vedadas]
        if not opciones:
            return None
        opciones.sort(key=lambda v: (m.campo.es_trabajo(v), v))
        self.ruta, self.meta_ruta = [], None
        return opciones[0]

    def _paso_whca(self, t, meta, evitar=frozenset()):
        m = self.model
        res = m.reservas
        res.liberar_futuro(self.nombre, t)
        base = self._bloq()
        bloqueadas = base | evitar if evitar else base
        if self.bloqueado >= 3 * self.paciencia:
            otros = {tr.pos for tr in m.orden if tr is not self and tr.pos != meta}
            bloqueadas = bloqueadas | otros
            if m.coordinador is not None:
                # M3 — si tiene que dejar de evitar su hilera para salir del bloqueo, sigue evitando a los
                # demás tractores (en M2 se conserva el comportamiento original)
                base = base | otros
            self.bloqueado = 0
        W = m.c["ventana_reservas"]
        h = None
        if manhattan(self.pos, meta) > 2:
            clave = (meta, len(evitar), len(base), self.zona_v)
            if self._h_clave != clave:
                self._h_clave = clave
                self._h = DistanciaReal(m.campo, meta, self.pos, bloqueadas)
            h = self._h
        plan = whca(m.campo, self.pos, meta, t, W, res, self.nombre, bloqueadas, h)
        if not plan and evitar:
            plan = whca(m.campo, self.pos, meta, t, W, res, self.nombre, base)
        if not plan:
            res.reservar(self.nombre, self.pos, t + 1)
            return None
        for k, c in enumerate(plan, start=1):
            res.reservar(self.nombre, c, t + k)
        return plan[0] if plan[0] != self.pos else None


class Gestor:
    """Iniciador de Contract Net (vive en el depósito). Solo conoce lo que le informan."""

    def __init__(self, modelo):
        self.m = modelo
        campo = modelo.campo
        self.tareas = {("surcar", x): self._nueva(len(campo.columnas[x])) for x in range(campo.ancho)}
        self.impl = {tr.nombre: TIPO[tr.implemento] for tr in modelo.orden}
        self.ocupados = {}
        self.fallados = set()
        self.terminados = set()
        self.ronda = {"surcar": None, "sembrar": None}
        self.n_ronda = 0
        self.evento = {"surcar": True, "sembrar": False}
        self.ultima = {"surcar": -10 ** 9, "sembrar": -10 ** 9}
        self.avisos_fin = 0
        self.t_aviso_fin = -10 ** 9
        self.reanuncios = 0
        self.tardias = 0
        self.subastas = 0

    @staticmethod
    def _nueva(restantes, inicio=None, d=0):
        return {"estado": "abierta", "ganador": None, "t_lim": None, "inicio": inicio, "dir": d,
                "restantes": restantes, "completa_surco": False}

    def paso(self, t):
        for msg in self.m.bus.recibir(GESTOR, t):
            self._procesar(msg, t)
        self._tiempos_limite(t)
        for tipo in ("surcar", "sembrar"):
            r = self.ronda[tipo]
            if r is not None and t >= r["t_limite"]:
                self._adjudicar(tipo, r, t)
                self.ronda[tipo] = None
            if self.ronda[tipo] is None:
                self._cfp(tipo, t)
        self._avisar_fin_surcado(t)

    def _plazo(self, celdas):
        return int(celdas * self.m.c["holgura_tell"]) + 60

    def _reabrir(self, clave, inicio=None, restantes=None, d=None):
        tarea = self.tareas.get(clave)
        if tarea is None or tarea["estado"] == "completa":
            return
        g = tarea["ganador"]
        if g is not None and g == self.m.tractor_fallado and self.m.fallado_activo:
            self.m.contar_reasignacion(clave, inicio if inicio is not None else tarea["inicio"],
                                       d or tarea["dir"])
        if g is not None and self.ocupados.get(g) == clave:
            del self.ocupados[g]
        tarea.update(estado="abierta", ganador=None, t_lim=None)
        if inicio is not None:
            tarea["inicio"] = inicio
        if restantes:
            tarea["restantes"] = restantes
        if d:
            tarea["dir"] = d
        self.reanuncios += 1
        self.evento[clave[0]] = True

    def _procesar(self, msg, t):
        c, p, e = msg.contenido, msg.performativa, msg.emisor
        if p == "propose":
            r = self.ronda.get(c.get("tipo"))
            if r is not None and c.get("ronda") == r["id"]:
                r["ofertas"].append((e, c["ofertas"]))
            else:
                self.tardias += 1
            return
        if p != "inform":
            return
        ev, tipo, x = c.get("evento"), c.get("tipo"), c.get("x")
        clave = (tipo, x)
        if ev == "inicio":
            tarea = self.tareas.get(clave)
            if tarea and tarea["estado"] != "completa":
                tarea.update(estado="en_curso", ganador=e, dir=c.get("dir", 0),
                             t_lim=t + self._plazo(c.get("restantes") or tarea["restantes"]))
            if tipo == "surcar":
                self._abrir_siembra(x, c.get("inicio"), c.get("dir", 0))
        elif ev == "casi_libre":
            if self.ocupados.get(e) == clave:
                del self.ocupados[e]
                self.evento[tipo] = True
        elif ev == "fin":
            tarea = self.tareas.get(clave)
            if tarea:
                tarea.update(estado="completa", t_lim=None, t_fin=t)
            if self.ocupados.get(e) == clave:
                del self.ocupados[e]
            self.evento[tipo] = True
            if tipo == "surcar":
                self._abrir_siembra(x, None, c.get("dir", 0))
                self.tareas[("sembrar", x)]["completa_surco"] = True
        elif ev == "liberada":
            self._reabrir(clave, inicio=c.get("siguiente"), restantes=c.get("restantes"), d=c.get("dir"))
            if self.ocupados.get(e) == clave:
                del self.ocupados[e]
        elif ev == "falla":
            self.m.marcar("t_deteccion_falla", t)
            self.m.marcar("t_respuesta_falla", t)
            self.fallados.add(e)
            otra = self.ocupados.pop(e, None)
            if tipo is not None:
                self._reabrir(clave, inicio=c.get("siguiente"), restantes=c.get("restantes"), d=c.get("dir"))
            if otra is not None and otra != clave:
                self._reabrir(otra)
        elif ev == "implemento":
            self.impl[e] = tipo
            self.terminados.discard(e)
            self.evento[tipo] = True
        elif ev == "reparado":   # M3 — el tractor remolcado ya se reparó
            self.reincorporar(e)
        elif ev == "disponible":
            if e in self.ocupados and self.tareas.get(self.ocupados[e], {}).get("ganador") != e:
                del self.ocupados[e]
            if tipo in self.evento:
                self.evento[tipo] = True

    def _abrir_siembra(self, x, inicio, d):
        clave = ("sembrar", x)
        if clave not in self.tareas:
            self.tareas[clave] = self._nueva(len(self.m.campo.columnas[x]), inicio=inicio, d=d)
            self.evento["sembrar"] = True

    def _tiempos_limite(self, t):
        co = self.m.coordinador
        for clave, tarea in list(self.tareas.items()):   # M3 puede abrir la siembra de una hilera aquí
            if tarea["estado"] in ("adjudicada", "en_curso") and tarea["t_lim"] is not None and t > tarea["t_lim"]:
                if co is not None and tarea["ganador"] is not None:
                    # M3 — el coordinador sabe mejor si el tractor sigue con esa hilera (latidos) o si falló
                    sigue = co.sigue_con(tarea["ganador"], clave, t)
                    if sigue is None:
                        continue
                    if sigue:
                        tarea["t_lim"] = t + self._plazo(tarea["restantes"])
                        continue
                    if tarea["ganador"] == self.m.tractor_fallado and self.m.fallado_activo:
                        self.m.marcar("t_deteccion_falla", t)
                        self.m.marcar("t_respuesta_falla", t)
                    self._reabrir_con_vista(clave, co._refinar_tarea)
                    continue
                if (tarea["ganador"] is not None and tarea["ganador"] == self.m.tractor_fallado
                        and self.m.fallado_activo):
                    self.m.marcar("t_deteccion_falla", t)
                    self.m.marcar("t_respuesta_falla", t)
                self._reabrir(clave)

    def reabrir_celda(self, c, libre=None):
        """M3 — una celda de una hilera que el gestor da por terminada sigue sin trabajar (la tapaba un
        tractor descompuesto, o el coordinador la vio así desde arriba). Se vuelve a anunciar su hilera
        desde esa celda. Devuelve los tipos reabiertos."""
        campo = self.m.campo
        x = c[0]
        libre = campo.estado(c) == LIBRE if libre is None else libre
        faltan = ["surcar", "sembrar"] if libre else ["sembrar"]
        reabiertas = []
        for tipo in faltan:
            tarea = self.tareas.get((tipo, x))
            if tarea is None or tarea["estado"] != "completa":
                continue   # sigue abierta o en curso — quien la tenga pasará por ahí
            col = campo.columnas[x]
            d = tarea["dir"] or 1
            resto = [v for v in col if (v[1] >= c[1] if d == 1 else v[1] <= c[1])]
            tarea.update(estado="abierta", ganador=None, t_lim=None, inicio=list(c), dir=d,
                         restantes=max(1, len(resto)))
            self.reanuncios += 1
            self.evento[tipo] = True
            reabiertas.append(tipo)
            self._reactivar(tipo)
        return reabiertas

    def _reactivar(self, tipo):
        """Si todos los tractores de esa labor ya se habían dado por terminados, despierta a uno."""
        vivos = [n for n, ti in self.impl.items() if ti == tipo and n not in self.fallados]
        if not vivos or any(n not in self.terminados for n in vivos):
            return
        n = sorted(vivos)[0]
        self.terminados.discard(n)
        self.avisos_fin = 0
        self.m.bus.enviar(self.m.t, "inform", GESTOR, n, {"evento": "reactivar", "tipo": tipo, "x": -1})

    def reincorporar(self, nombre):
        """M3 — el tractor reparado vuelve a recibir anuncios (lo avisa él o el coordinador)."""
        tr = self.m.tractor(nombre)
        tipo = TIPO[tr.implemento]
        self.fallados.discard(nombre)
        self.terminados.discard(nombre)
        self.impl[nombre] = tipo
        self.evento[tipo] = True

    def _reabrir_otra(self, otra, nombre, refinar):
        """La siguiente hilera que ya tenía adjudicada el tractor descompuesto (M3)."""
        if otra is None or self.tareas.get(otra, {}).get("ganador") != nombre:
            return
        self._reabrir_con_vista(otra, refinar)

    def _reabrir_con_vista(self, clave, refinar):
        """M3 — antes de reabrir una hilera, el coordinador dice desde dónde (o que ya está terminada)."""
        datos = refinar(clave) if refinar else None
        if datos is not None and datos.get("completa"):
            tipo, x = clave
            self.tareas[clave].update(estado="completa", t_lim=None, t_fin=self.m.t)
            if tipo == "surcar":
                self._abrir_siembra(x, None, self.tareas[clave]["dir"] or 0)
                self.tareas[("sembrar", x)]["completa_surco"] = True
            self.evento[tipo] = True
        elif datos is not None:
            self._reabrir(clave, inicio=datos.get("siguiente"), restantes=datos.get("restantes"), d=datos.get("dir"))
        else:
            self._reabrir(clave)

    def cerrar_por_falla(self, nombre, tipo, x, d, t=0, refinar=None):
        """M3 — el coordinador vio que la hilera del tractor descompuesto ya quedó terminada."""
        self.fallados.add(nombre)
        otra = self.ocupados.pop(nombre, None)
        clave = (tipo, x)
        tarea = self.tareas.get(clave)
        if tarea is not None and tarea["estado"] != "completa" and tarea["ganador"] in (nombre, None):
            tarea.update(estado="completa", t_lim=None, t_fin=t)
            if tipo == "surcar":
                self._abrir_siembra(x, None, d or 0)
                self.tareas[("sembrar", x)]["completa_surco"] = True
            self.evento[tipo] = True
        if otra != clave:
            self._reabrir_otra(otra, nombre, refinar)

    def reasignar_por_falla(self, nombre, info, refinar=None):
        """M3 — el coordinador confirmó la falla; reabre solo lo que el tractor no alcanzó a hacer.

        Devuelve (tipo, x, restantes) de la hilera reabierta, o None si no tenía trabajo."""
        self.fallados.add(nombre)
        otra = self.ocupados.pop(nombre, None)
        tipo, x = info.get("tipo"), info.get("x")
        clave = (tipo, x) if tipo is not None and x is not None and x >= 0 else None
        out = None
        tarea = self.tareas.get(clave) if clave else None
        if tarea is not None and tarea["estado"] != "completa" and tarea["ganador"] in (nombre, None):
            self._reabrir(clave, inicio=info.get("siguiente"), restantes=info.get("restantes"), d=info.get("dir"))
            out = (tipo, x, info.get("restantes") or tarea["restantes"])
        if otra != clave:
            self._reabrir_otra(otra, nombre, refinar)
        return out

    def _cfp(self, tipo, t):
        abiertas = [(k, v) for k, v in self.tareas.items() if k[0] == tipo and v["estado"] == "abierta"]
        if not abiertas:
            return
        candidatos = [n for n, ti in self.impl.items()
                      if ti == tipo and n not in self.ocupados and n not in self.fallados and n not in self.terminados]
        if not candidatos:
            return
        if not self.evento[tipo] and t - self.ultima[tipo] < self.m.c["reintento_cfp"]:
            return
        self.n_ronda += 1
        self.subastas += 1
        lista = [{"x": k[1], "inicio": v["inicio"], "dir": v["dir"], "restantes": v["restantes"],
                  "completa_surco": v["completa_surco"]} for k, v in abiertas]
        contenido = {"tipo": tipo, "ronda": self.n_ronda, "tareas": lista}
        for n in candidatos:
            self.m.bus.enviar(t, "cfp", GESTOR, n, contenido)
        self.ronda[tipo] = {"id": self.n_ronda, "t_limite": t + self.m.c["timeout_ofertas"], "ofertas": []}
        self.evento[tipo] = False
        self.ultima[tipo] = t

    def _adjudicar(self, tipo, r, t):
        pujas = []
        for e, ofertas in r["ofertas"]:
            if e in self.fallados:
                continue
            for o in ofertas:
                pujas.append((-o["u"], e, o["x"], o["dist"]))
        pujas.sort()
        ganadores, tomadas = set(), set()
        for _negu, e, x, dist in pujas:
            clave = (tipo, x)
            tarea = self.tareas.get(clave)
            if e in ganadores or clave in tomadas or tarea is None or tarea["estado"] != "abierta":
                continue
            ganadores.add(e)
            tomadas.add(clave)
            tarea.update(estado="adjudicada", ganador=e,
                         t_lim=t + int(dist * self.m.c["holgura_tell"]) + 30 + self.m.k_anticipo)
            self.ocupados[e] = clave
            info = {"tipo": tipo, "x": x, "inicio": tarea["inicio"], "dir": tarea["dir"],
                    "restantes": tarea["restantes"], "completa_surco": tarea["completa_surco"]}
            self.m.bus.enviar(t, "accept-proposal", GESTOR, e, {"ronda": r["id"], "tarea": info})
        postores = {e for e, _ in r["ofertas"]}
        for e in sorted(postores - ganadores):
            self.m.bus.enviar(t, "reject-proposal", GESTOR, e, {"ronda": r["id"]})
        if postores - ganadores:
            self.evento[tipo] = True

    def _avisar_fin_surcado(self, t):
        if self.avisos_fin >= 3 or t - self.t_aviso_fin < self.m.c["reintento_cfp"]:
            return
        if any(v["estado"] != "completa" for k, v in self.tareas.items() if k[0] == "surcar"):
            return
        destino = [n for n, ti in self.impl.items() if ti == "surcar" and n not in self.fallados]
        for n in destino:
            self.m.bus.enviar(t, "inform", GESTOR, n, {"evento": "fin_tipo", "tipo": "surcar", "x": -1})
            self.terminados.add(n)
        self.avisos_fin += 1
        self.t_aviso_fin = t
