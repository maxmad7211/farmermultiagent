"""M3 — coordinador supervisor y la parte del tractor que habla con él (docs/m3.md).

El coordinador es un agente con su propio ciclo en cada paso
1. Percibe — lee los mensajes de los tractores (latidos, reportes, ofertas, avisos de misión) y,
   cada `periodo_revision` pasos, revisa desde arriba una franja del campo (en rotación).
2. Actualiza lo que cree — fuego, obstáculos nuevos, posición y estado de cada tractor.
3. Decide — confirma o descarta reportes, declara fallas, abre subastas urgentes.
4. Actúa — avisa la zona prohibida, adjudica misiones, le pide al gestor que reparta lo pendiente.
5. Revisa su plan — si el tractor que mandó no avanza o el fuego crece de más, cambia de plan.

Toda decisión queda en `registro` con su motivo.

Los tractores siguen siendo autónomos — perciben, reportan, ofertan y se protegen solos
(`TractorM3`). Solo saben lo que ven en su radio y lo que el coordinador les avisa.
"""

import numpy as np

from .campo import OBSTACULO, QUEMADA, SEMBRADA, SURCADA, manhattan

COORD = "SUP"
INF = 10 ** 9

# Modo lógico del tractor durante una misión del coordinador (los demás están en agentes.py)
M_MISION = 7
EMERGENCIA = "emergencia"
HERRAMIENTA = {"apagar": "pipa", "remolcar": "grua"}


def _celda(c):
    return (int(c[0]), int(c[1]))


def _bola(celdas, r, campo, excluir=()):
    """Celdas a distancia Manhattan <= r de alguna de `celdas`, dentro del campo y sin obstáculos fijos."""
    out = set()
    for (x, y) in celdas:
        for dx in range(-r, r + 1):
            k = r - abs(dx)
            for dy in range(-k, k + 1):
                v = (x + dx, y + dy)
                if v in campo.vecinos and v not in excluir:
                    out.add(v)
    return out


# ============================================================================ coordinador
class Coordinador:

    def __init__(self, modelo, p):
        self.m = modelo
        self.p = p
        campo = modelo.campo
        self.t_vista = np.full((campo.ancho, campo.alto), -INF, dtype=np.int64)
        self.vista_estado = np.full((campo.ancho, campo.alto), -1, dtype=np.int8)  # estado visto de cada celda
        self.vista_fuego = set()      # lo que vio arder en la última revisión de cada franja
        self.vista_quemada = set()    # lo que vio ya quemado (sin fuego)
        self.vista_obst = set()
        self.fuego = {}               # creencia — celda -> paso en que lo supo
        self.obst = set()
        self.margen = p["margen_zona"]
        self.zona = frozenset()
        self.zona_fuego = frozenset()
        self.zona_desde = {}          # celda -> paso desde el que está prohibida sin interrupción
        self.version_zona = 0
        self.repetir_zona = -1
        lim = p["periodo_latido"] * p["latidos_perdidos"] + modelo.c["retraso_max"] + 1
        self.limite_latido = lim
        self.tractores = {tr.nombre: {"t": 0, "pos": tr.pos, "info": {}} for tr in modelo.orden}
        self.sospechosos = {}
        self.fallados = set()
        self.reparto_pendiente = {}   # tractor -> (datos, paso del último dato), espera su vista desde arriba
        self.remolcados = set()       # tractores a los que se les mandó la grúa
        self.entregados = set()       # tractores que la grúa ya dejó en la estación
        self.vista_pos = {}           # tractor -> (paso, posición) la última vez que lo vio desde arriba
        self.reportes = []
        self.n_reporte = 0
        self.misiones = {}
        self.subastas = {}
        self.n_id = 0
        self.stock = {"pipa": p["n_pipas"], "grua": p["n_gruas"]}
        self.pendientes = []          # subastas por abrir — (tipo, objetivo, datos)
        self.sector = 0
        self.vistazos = set()
        self.registro = []
        self.historia_zona = []       # [{"t", "celdas", "fuego"}] cada vez que cambia la zona
        self.incendio_activo = False
        self.ref_fuego = 0            # tamaño del fuego cuando se mandó la pipa (para revisar el plan)
        # métricas
        self.n_subastas = 0
        self.n_replanes = 0
        self.n_decisiones = 0

    # ------------------------------------------------------------------ registro
    def anotar(self, t, tipo, evento, texto, motivo="", tractor=""):
        if tipo == "decision":
            self.n_decisiones += 1
        self.registro.append({"t": int(t), "fuente": "coordinador", "tipo": tipo, "evento": evento,
                              "tractor": tractor, "texto": texto, "motivo": motivo})

    def _enviar(self, t, perf, receptor, contenido):
        self.m.bus.enviar(t, perf, COORD, receptor, contenido)

    def _difundir(self, t, perf, contenido, excluir=()):
        vivos = [tr.nombre for tr in self.m.orden if tr.nombre not in self.fallados and tr.nombre not in excluir]
        self.m.bus.difundir(t, perf, COORD, vivos, contenido)

    # ------------------------------------------------------------------ ciclo
    def paso(self, t):
        for msg in self.m.bus.recibir(COORD, t):       # 1. percibir (mensajes)
            self._procesar(t, msg)
        if t % self.p["periodo_revision"] == 0:          # 1. percibir (vista desde arriba)
            self._revisar_desde_arriba(t)
        self._decidir_reportes(t)                        # 2-3. creencias y decisiones
        self._vigilar_tractores(t)
        self._cerrar_subastas(t)
        self._abrir_pendientes(t)
        self._revisar_planes(t)                          # 5. revisar el plan
        self._actualizar_zona(t)                         # 4. actuar (avisar a todos)
        if self.repetir_zona == t:
            self._difundir(t, "inform", self._contenido_zona())   # el aviso de zona se manda dos veces

    # ------------------------------------------------------------------ percepción desde arriba
    def _franja(self, k):
        ancho = self.m.campo.ancho
        n = self.p["sectores_revision"]
        return range(k * ancho // n, (k + 1) * ancho // n)

    def _sector_de(self, c):
        return min(self.p["sectores_revision"] - 1, c[0] * self.p["sectores_revision"] // self.m.campo.ancho)

    def _revisar_desde_arriba(self, t):
        m, campo, ev = self.m, self.m.campo, self.m.eventos
        sectores = {self.sector} | self.vistazos
        self.sector = (self.sector + 1) % self.p["sectores_revision"]
        self.vistazos = set()
        nuevos_fuego, nuevos_obst, apagados = [], [], []
        for k in sorted(sectores):
            xs = self._franja(k)
            if not len(xs):
                continue
            self.t_vista[xs.start:xs.stop, :] = t
            self.vista_estado[xs.start:xs.stop, :] = np.array(campo.est[xs.start:xs.stop], dtype=np.int8)
            for x in xs:
                for y in range(campo.alto):
                    c = (x, y)
                    arde = ev.activo and ev.ardiendo(c)
                    obst = ev.activo and c in ev.celdas_obstaculo
                    if arde:
                        self.vista_fuego.add(c)
                        if c not in self.fuego:
                            nuevos_fuego.append(c)
                    else:
                        self.vista_fuego.discard(c)
                        if c in self.fuego:
                            apagados.append(c)
                    if not arde and campo.estado(c) == QUEMADA:
                        self.vista_quemada.add(c)
                    if obst:
                        self.vista_obst.add(c)
                        if c not in self.obst:
                            nuevos_obst.append(c)
            # También ve dónde están los tractores de esa franja
            for tr in m.orden:
                if tr.pos[0] in xs:
                    self.vista_pos[tr.nombre] = (t, tr.pos)
        for c in apagados:
            self.fuego.pop(c, None)
        if apagados and self.fuego:
            self._mandar_objetivo(t)
        if nuevos_fuego:
            self._confirmar(t, "incendio", nuevos_fuego, "lo vio desde arriba en su revisión")
        if nuevos_obst:
            self._confirmar(t, "obstaculo", nuevos_obst, "lo vio desde arriba en su revisión")
        for k in sorted(sectores):
            self._revisar_hileras(t, self._franja(k))
        for n in list(self.reparto_pendiente):
            datos, t_dato = self.reparto_pendiente.pop(n)
            self._repartir(t, n, self._refinar(datos), "con lo que sabía del tractor y lo que vio desde arriba")

    # ------------------------------------------------------------------ mensajes
    def _procesar(self, t, msg):
        c, p, e = msg.contenido, msg.performativa, msg.emisor
        if p == "propose" and c.get("urgente"):
            s = self.subastas.get(c.get("id"))
            if s is not None:
                s["ofertas"].append((e, c))
            return
        if p != "inform":
            return
        ev = c.get("evento")
        if ev == "latido":
            self._latido(t, e, msg.t_envio, c)
        elif ev == "falla":
            self.tractores[e]["info"].update({k: c.get(k) for k in ("tipo", "x", "siguiente", "restantes", "dir")})
            if c.get("pos"):
                self.tractores[e]["pos"] = _celda(c["pos"])
            if e not in self.fallados:
                self._declarar_falla(t, e, "el tractor avisó que se descompuso", exacta=True)
        elif ev == "reporte":
            self._nuevo_reporte(t, e, c)
        elif ev == "mision_inicio":
            mi = self.misiones.get(c.get("mision"))
            if mi is not None and mi["tractor"] == e:
                mi["iniciada"] = True
                mi["t_avance"] = t
        elif ev == "rechazo":
            mi = self.misiones.pop(c.get("mision"), None)
            if mi is not None and mi["tipo"] == "revisar":
                self.anotar(t, "aviso", "revisar", f"{e} no puede ir a revisar; lo revisará desde arriba", tractor=e)
            elif mi is not None:
                self._devolver_stock(mi)
                self.anotar(t, "plan", "rechazo", f"{e} no puede tomar la misión de {mi['tipo']}; se repite la subasta",
                            "el tractor ya no estaba disponible", e)
                self.pendientes.append((mi["tipo"], mi["objetivo"], mi.get("datos", {})))
        elif ev == "apague":
            for celda in c.get("celdas", []):
                celda = _celda(celda)
                self.fuego.pop(celda, None)
                self.vista_fuego.discard(celda)
                self.vista_quemada.add(celda)   # sabe que ardió (y que ya se apagó)
            self._avance(t, e)
        elif ev == "sin_fuego":
            for celda in c.get("celdas", []):
                self.fuego.pop(_celda(celda), None)
            self._avance(t, e)
            if not self.fuego:
                self._terminar_misiones(t, "apagar", "ya no ve fuego en el campo")
            else:
                self._mandar_objetivo(t)
        elif ev == "verificacion":
            self._resultado_verificacion(t, e, c)
        elif ev == "entregado":
            mi = self._mision_de(e)
            nombre = c.get("remolcado")
            self.anotar(t, "aviso", "remolque", f"{e} dejó a {nombre} en la estación; empieza su reparación",
                        tractor=e)
            self.m.marcar("t_remolque_entregado", t)
            self.entregados.add(nombre)
            if mi is not None:
                mi["fase"] = "devolver"
        elif ev == "mision_fin":
            mi = self.misiones.pop(c.get("mision"), None)
            if mi is not None:
                self._devolver_stock(mi)
                self.anotar(t, "aviso", "mision_fin", f"{e} terminó la misión de {mi['tipo']} y quedó libre",
                            tractor=e)
        elif ev == "no_descompuesto":
            nombre = c.get("remolcado")
            if nombre in self.fallados:
                self._falsa_falla(t, nombre, f"{e} llegó con la grúa y lo vio trabajando")
        elif ev == "reparado":
            self.entregados.discard(e)
            self.remolcados.discard(e)
            self.m.gestor.reincorporar(e)
            self.fallados.discard(e)
            self.sospechosos.pop(e, None)
            self.tractores[e].update(t=t, pos=_celda(c.get("pos", self.tractores[e]["pos"])))
            self.anotar(t, "aviso", "reparado", f"{e} quedó reparado y vuelve a trabajar", tractor=e)
            self.m.marcar("t_reparado", t)

    def _latido(self, t, e, t_envio, c):
        tr = self.tractores[e]
        if t_envio >= tr["t"]:
            tr.update(t=t_envio, pos=_celda(c["pos"]), info=dict(c))
        if e in self.sospechosos:
            del self.sospechosos[e]
            self.anotar(t, "aviso", "latido", f"{e} respondió; sigue trabajando", tractor=e)
        if e in self.fallados and c.get("modo") != "fuera":
            self.fallados.discard(e)
            self.m.gestor.reincorporar(e)
            if e in self.entregados:
                # Se perdió su aviso de "reparado" — el latido dice que ya trabaja
                self.entregados.discard(e)
                self.remolcados.discard(e)
                self.anotar(t, "aviso", "reparado", f"{e} quedó reparado y vuelve a trabajar", tractor=e)
                self.m.marcar("t_reparado", t)
            else:
                # Un tractor declarado descompuesto sí estaba bien (se perdieron sus mensajes)
                self._falsa_falla(t, e, "llegó un latido suyo después de declararla")
        labor = {"surcador": "surcar", "sembradora": "sembrar"}.get(c.get("implemento"))
        g = self.m.gestor
        if labor and e not in self.fallados and c.get("modo") == "libre" and g.impl.get(e) != labor:
            # Se perdió su aviso de cambio de implemento — el gestor lo seguía tratando con el anterior
            g.reincorporar(e)
            self.anotar(t, "aviso", "implemento", f"{e} ya trabaja con {c['implemento']}; se lo avisa al gestor",
                        tractor=e)
        clave = g.ocupados.get(e)
        if clave is not None and c.get("modo") == "libre" and e not in self.fallados:
            tiene = {(c.get("tarea_tipo"), c.get("hilera")), tuple(c.get("siguiente_tarea") or ())}
            if clave not in tiene:
                # Su latido dice que está libre: el gestor lo tenía ocupado por un aviso que se perdió
                del g.ocupados[e]
                g.evento[g.impl.get(e, clave[0])] = True
        if c.get("zona_v", 0) < self.version_zona:
            self._enviar(t, "inform", e, self._contenido_zona())
        mid = c.get("mision")
        for otra in [mi for mi in self.misiones.values() if mi["tractor"] == e and mi["id"] != mid]:
            if otra["iniciada"] and t_envio > otra["t_asignada"] and c.get("modo") != "servicio":
                # Su latido ya no trae esa misión: terminó y se perdió su aviso
                self.misiones.pop(otra["id"], None)
                self._devolver_stock(otra)
                self.anotar(t, "aviso", "mision_fin", f"{e} ya no tiene la misión de {otra['tipo']} (se perdió su "
                            "aviso de fin); queda libre", tractor=e)
        if mid is not None and mid not in self.misiones:
            self._enviar(t, "request", e, {"evento": "cancelar", "mision": mid})
        if mid is not None and mid in self.misiones:
            mi = self.misiones[mid]
            if mi["tractor"] == e:
                mi["iniciada"] = True   # el latido confirma que la tomó
                if mi.get("fase") == "devolver" and c.get("modo") == "mision" and t - mi.get("t_fin_pedido", -INF) >= 10:
                    # Le pidió regresar la herramienta y sigue en la misión: el pedido se perdió
                    mi["t_fin_pedido"] = t
                    self._enviar(t, "request", e, {"evento": "fin_mision", "mision": mid})
            self._avance(t, e, c)

    # ------------------------------------------------------------------ reportes
    def _nuevo_reporte(self, t, e, c):
        celdas = [_celda(x) for x in c.get("celdas", [])]
        if not celdas:
            return
        self.n_reporte += 1
        r = {"id": c.get("id"), "emisor": e, "clase": c.get("clase"), "celdas": celdas,
             "t_obs": int(c.get("t_obs", t)), "t_rec": t, "estado": "pendiente", "verificador": None,
             "pedido": False}
        self.reportes.append(r)
        self.anotar(t, "aviso", "reporte", f"{e} reporta {r['clase']} en {[list(x) for x in celdas[:3]]}"
                    + (" ..." if len(celdas) > 3 else ""), tractor=e)

    def _reciente(self, r, t):
        return all(self.t_vista[c] >= r["t_obs"] and t - self.t_vista[c] <= self.p["vigencia_vista"]
                   for c in r["celdas"])

    def _decidir_reportes(self, t):
        for r in self.reportes:
            if r["estado"] not in ("pendiente", "verificando"):
                continue
            conocidas = self.fuego if r["clase"] == "incendio" else self.obst
            if self._reciente(r, t):
                vistas = self.vista_fuego if r["clase"] == "incendio" else self.vista_obst
                if any(c in vistas for c in r["celdas"]):
                    self._cerrar_reporte(t, r, "confirmado", "lo vio hace poco y sí hay algo")
                    self._confirmar(t, r["clase"], [c for c in r["celdas"] if c in vistas],
                                    f"reporte de {r['emisor']} confirmado con su vista reciente")
                elif r["clase"] == "incendio" and any(c in self.vista_quemada for c in r["celdas"]):
                    self._cerrar_reporte(t, r, "ya_no_arde", "lo vio hace poco — ya se quemó y no arde")
                else:
                    self._cerrar_reporte(t, r, "descartado", "vio esa zona hace poco y no hay nada")
                    self._enviar(t, "inform", r["emisor"], {"evento": "descartado", "reporte": r["id"],
                                                            "celdas": [list(c) for c in r["celdas"]]})
                continue
            if any(c in conocidas for c in r["celdas"]):
                self._cerrar_reporte(t, r, "ya_conocido", "ya lo tenía confirmado")
                continue
            if not r["pedido"]:
                self._pedir_verificacion(t, r)

    def _cerrar_reporte(self, t, r, estado, motivo):
        r["estado"] = estado
        r["t_decision"] = t
        ev = self.m.eventos   # solo para las métricas; no entra en la decisión
        r["hay_al_decidir"] = any(ev.ardiendo(c) or c in ev.celdas_obstaculo for c in r["celdas"])
        verbo = {"confirmado": "Confirma", "descartado": "Descarta", "ya_no_arde": "Registra",
                 "ya_conocido": "Ya conocía"}[estado]
        texto = f"{verbo} el reporte de {r['emisor']} ({r['clase']} en {list(r['celdas'][0])})"
        if estado == "descartado":
            texto += f"; le avisa — ahí no pasa nada, sigue trabajando"
        self.anotar(t, "decision" if estado in ("confirmado", "descartado") else "aviso", "reporte",
                    texto, motivo, r["emisor"])

    def _pedir_verificacion(self, t, r):
        r["pedido"] = True
        r["estado"] = "verificando"
        self.vistazos.add(self._sector_de(r["celdas"][0]))   # respaldo — la mira en la próxima revisión
        radio = self.p["radio_percepcion"]
        cerca = []
        libres = []
        for n, tr in self.tractores.items():
            if n == r["emisor"] or n in self.fallados or n in self._ocupados_en_mision():
                continue
            d = min(manhattan(tr["pos"], c) for c in r["celdas"])
            if d <= radio:
                cerca.append((d, n))
            elif tr["info"].get("libre"):
                libres.append((d, n))
        if cerca:
            _d, n = min(cerca)
            r["verificador"] = n
            self._enviar(t, "query-if", n, {"evento": "verificar", "reporte": r["id"],
                                            "clase": r["clase"], "celdas": [list(c) for c in r["celdas"]]})
            self.anotar(t, "decision", "verificar", f"No ha visto esa zona hace poco — le pide a {n} que confirme",
                        f"{n} está a {_d} celdas del reporte de {r['emisor']}", n)
        elif libres:
            _d, n = min(libres)
            r["verificador"] = n
            self.n_id += 1
            mid = self.n_id
            self.misiones[mid] = {"id": mid, "tipo": "revisar", "tractor": n, "objetivo": r["celdas"][0],
                                  "t_asignada": t, "iniciada": False, "t_avance": t, "mejor": INF,
                                  "datos": {"reporte": r["id"]}}
            self._enviar(t, "request", n, {"evento": "revisar", "mision": mid, "reporte": r["id"],
                                           "clase": r["clase"], "celdas": [list(c) for c in r["celdas"]]})
            self.anotar(t, "decision", "verificar", f"No ha visto esa zona hace poco — manda a {n} a revisar",
                        f"{n} está libre y a {_d} celdas; además la revisará desde arriba", n)
        else:
            self.anotar(t, "decision", "verificar", f"No ha visto esa zona hace poco — la revisará desde arriba",
                        "no hay un tractor cerca ni libre para ir a ver")

    def _resultado_verificacion(self, t, e, c):
        r = next((x for x in self.reportes if x["id"] == c.get("reporte")), None)
        mi = self._mision_de(e)
        if mi is not None and mi["tipo"] == "revisar":
            self.misiones.pop(mi["id"], None)
        if r is None or r["estado"] != "verificando":
            return
        if c.get("visto"):
            self._cerrar_reporte(t, r, "confirmado", f"{e} lo confirmó")
            self._confirmar(t, r["clase"], [_celda(x) for x in c.get("celdas", r["celdas"])],
                            f"{e} confirmó el reporte de {r['emisor']}")
        else:
            # Nunca descarta por lo que dice otro tractor — solo por lo que él mismo vio
            self.anotar(t, "aviso", "verificar", f"{e} no lo ve; espera su propia revisión desde arriba",
                        "solo descarta si él mismo vio la zona", e)

    # ------------------------------------------------------------------ confirmar eventos
    def _confirmar(self, t, clase, celdas, motivo):
        nuevas = [c for c in celdas if (c not in self.fuego if clase == "incendio" else c not in self.obst)]
        if not nuevas:
            return
        if clase == "incendio":
            primero = not self.incendio_activo
            self.incendio_activo = True
            for c in nuevas:
                self.fuego[c] = t
            self.m.marcar("t_deteccion_incendio", t)
            if primero:
                self.anotar(t, "decision", "incendio",
                            f"Confirma un incendio ({len(nuevas)} celda(s)); marca zona prohibida y avisa a todos",
                            motivo)
            else:
                self.anotar(t, "aviso", "incendio", f"Suma {len(nuevas)} celda(s) al incendio "
                            f"({len(self.fuego)} en total) y actualiza la zona", motivo)
            hay_mision = any(mi["tipo"] == "apagar" and mi.get("fase") != "devolver" for mi in self.misiones.values()) or \
                any(p[0] == "apagar" for p in self.pendientes) or \
                any(s["tipo"] == "apagar" for s in self.subastas.values())
            if not hay_mision:
                self.ref_fuego = len(self.fuego)
                self.pendientes.append(("apagar", min(nuevas), {}))
            else:
                self._mandar_objetivo(t)
        else:
            self.obst |= set(nuevas)
            self.m.marcar("t_deteccion_obstaculo", t)
            self.m.marcar("t_respuesta_obstaculo", t)
            self.anotar(t, "decision", "obstaculo",
                        f"Confirma un obstáculo nuevo ({len(nuevas)} celdas); marca zona prohibida y avisa para que rodeen",
                        motivo)

    # ------------------------------------------------------------------ fallas
    def _vigilar_tractores(self, t):
        espera_ping = 2 * self.m.c["retraso_max"] + 3
        for n, tr in self.tractores.items():
            if n in self.fallados:
                continue
            s = self.sospechosos.get(n)
            if s is None:
                if t - tr["t"] > self.limite_latido:
                    self.sospechosos[n] = {"t_ping": t, "pings": 1, "t0": t}
                    self.vistazos.add(self._sector_de(tr["pos"]))   # también lo buscará desde arriba
                    self._enviar(t, "query-if", n, {"evento": "estado"})
                    self.anotar(t, "aviso", "latido", f"{n} dejó de reportarse; le pregunta si sigue bien",
                                f"{t - tr['t']} pasos sin latido", n)
            elif t - s["t_ping"] > espera_ping:
                if s["pings"] < 2:
                    s["pings"] += 1
                    s["t_ping"] = t
                    self._enviar(t, "query-if", n, {"evento": "estado"})
                else:
                    visto = self.vista_pos.get(n)
                    if visto is None or visto[0] < s["t0"]:
                        continue   # espera a verlo desde arriba antes de declarar la falla
                    del self.sospechosos[n]
                    if visto[1] != tr["pos"]:
                        # No contesta, pero se movió desde su último latido: sigue trabajando
                        tr.update(t=visto[0], pos=visto[1])
                        self.anotar(t, "decision", "latido", f"{n} no contesta, pero lo vio moverse desde arriba; "
                                    "no lo da por descompuesto", "sus mensajes se están perdiendo", n)
                        continue
                    self._declarar_falla(t, n, "no se reporta, no contestó dos preguntas y desde arriba lo vio "
                                         "detenido donde estaba", exacta=False)

    def _declarar_falla(self, t, n, motivo, exacta):
        self.fallados.add(n)
        self.sospechosos.pop(n, None)
        info = self.tractores[n]["info"]
        datos = {"tipo": info.get("tipo", info.get("tarea_tipo")), "x": info.get("x", info.get("hilera")),
                 "siguiente": info.get("siguiente"), "restantes": info.get("restantes"),
                 "dir": info.get("dir")}
        self.m.marcar("t_deteccion_falla", t)
        self.m.gestor.fallados.add(n)   # no se le ofrecen más hileras
        # Antes de repartir mira desde arriba la franja de su hilera (en la próxima revisión, a más
        # tardar periodo_revision pasos) — así no vuelve a anunciar celdas que ya están hechas, ni las
        # que el tractor alcanzó a trabajar después de su último latido
        self.vistazos.add(self._sector_de(self.tractores[n]["pos"]))
        if datos.get("x") is not None and datos["x"] >= 0:
            self.vistazos.add(self._sector_de((datos["x"], 0)))
        self.reparto_pendiente[n] = (datos, self.tractores[n]["t"])
        fuente = "avisó dónde se quedó" if exacta else "con su último latido"
        self.anotar(t, "decision", "falla", f"{n} se descompuso; manda a un tractor por la grúa y revisará "
                    "desde arriba lo que quedó pendiente antes de repartirlo", f"{motivo} ({fuente})", n)
        self.pendientes.append(("remolcar", self.tractores[n]["pos"], {"remolcado": n}))

    def _falsa_falla(self, t, n, motivo):
        """Se declaró la falla de un tractor que en realidad sigue bien: se retira y se cancela la grúa."""
        self.fallados.discard(n)
        self.remolcados.discard(n)
        self.reparto_pendiente.pop(n, None)
        self.m.gestor.reincorporar(n)
        self.pendientes = [p for p in self.pendientes if not (p[0] == "remolcar" and p[2].get("remolcado") == n)]
        for mi in self.misiones.values():
            if mi["tipo"] == "remolcar" and mi.get("datos", {}).get("remolcado") == n and mi.get("fase") != "devolver":
                mi["fase"] = "devolver"
                self._enviar(t, "request", mi["tractor"], {"evento": "fin_mision", "mision": mi["id"]})
        self.anotar(t, "decision", "falla", f"{n} sí estaba bien — retira la falla y cancela la grúa", motivo, n)

    def _refinar(self, datos):
        """Recorre la hilera desde `siguiente` y salta lo que ya vio hecho desde arriba. Lo que vio hecho
        sigue hecho (surcar y sembrar no se deshacen), así que sirve cualquier vista, aunque sea vieja."""
        tipo, x, sig = datos.get("tipo"), datos.get("x"), datos.get("siguiente")
        if tipo is None or x is None or x < 0:
            return datos
        if not sig:
            # No le quedaba nada en la hilera (iba a avisar que terminó) — se cierra, no se reabre
            return {**datos, "completa": True} if not datos.get("restantes") else datos
        d = datos.get("dir") or 1
        col = self.m.campo.columnas[x]
        seq = [c for c in (col if d == 1 else col[::-1]) if (c[1] >= sig[1] if d == 1 else c[1] <= sig[1])]
        hechos = (SURCADA, SEMBRADA, QUEMADA, OBSTACULO) if tipo == "surcar" else (SEMBRADA, QUEMADA, OBSTACULO)
        k = 0
        while k < len(seq) and self.vista_estado[seq[k]] in hechos:
            k += 1
        if k == len(seq):
            return {**datos, "siguiente": None, "restantes": 0, "completa": True}
        return {**datos, "siguiente": list(seq[k]), "restantes": len(seq) - k}

    def _refinar_tarea(self, clave):
        """Para una hilera adjudicada que el tractor descompuesto todavía no empezaba: desde dónde
        anunciarla según lo que vio desde arriba (None si no sabe nada)."""
        tarea = self.m.gestor.tareas[clave]
        tipo, x = clave
        col = self.m.campo.columnas[x]
        d = tarea["dir"] or 0
        if tarea["inicio"]:
            inicio = tarea["inicio"]
        elif d:
            inicio = list(col[0] if d == 1 else col[-1])
        else:
            hechos = (SURCADA, SEMBRADA, QUEMADA, OBSTACULO) if tipo == "surcar" else (SEMBRADA, QUEMADA, OBSTACULO)
            if all(self.vista_estado[c] in hechos for c in col):
                return {"completa": True}
            return None
        return self._refinar({"tipo": tipo, "x": x, "siguiente": inicio, "dir": d or 1,
                              "restantes": tarea["restantes"]})

    def _repartir(self, t, n, datos, fuente):
        if datos.get("completa"):
            self.m.gestor.cerrar_por_falla(n, datos["tipo"], datos["x"], datos.get("dir"), t, self._refinar_tarea)
            texto = f"La hilera que tenía {n} ya quedó terminada — no hay nada que repartir"
        else:
            reparto = self.m.gestor.reasignar_por_falla(n, datos, self._refinar_tarea)
            if reparto:
                tipo, x, restantes = reparto
                texto = f"Reparte solo lo que {n} no alcanzó a hacer ({tipo}, hilera {x}, {restantes} celdas)"
            else:
                texto = f"{n} no tenía trabajo pendiente que repartir"
        self.m.marcar("t_respuesta_falla", t)
        self.anotar(t, "decision", "reparto", texto, fuente, n)

    def _revisar_hileras(self, t, xs):
        """Desde arriba también ve si una hilera que el gestor da por terminada quedó con celdas sin
        trabajar (por ejemplo, las que tapaba un tractor descompuesto). Si es así, la vuelve a anunciar."""
        m, g = self.m, self.m.gestor
        for x in xs:
            for tipo in ("surcar", "sembrar"):
                tarea = g.tareas.get((tipo, x))
                if tarea is None or tarea["estado"] != "completa" or tarea.get("t_fin", -1) >= t:
                    continue
                col = m.campo.columnas[x]
                d = tarea["dir"] or 1
                for c in (col if d == 1 else col[::-1]):
                    e = int(self.vista_estado[c])
                    falta = e == 2 or (tipo == "sembrar" and e == SURCADA)   # 2 = LIBRE
                    if falta and c not in m.bloqueadas:
                        if g.reabrir_celda(c, libre=(e == 2)):
                            self.anotar(t, "decision", "hilera",
                                        f"Ve desde arriba que la hilera {x} quedó sin terminar en {list(c)}; "
                                        f"la vuelve a anunciar", "el gestor la daba por terminada")
                        break

    def sigue_con(self, nombre, clave, t):
        """Para el gestor (M3) — True si el último latido dice que el tractor trabaja esa hilera (o la
        tiene como siguiente), None si el tractor falló o está en duda (el coordinador se encarga),
        False si no la tiene (el gestor la puede reabrir)."""
        if nombre in self.fallados or nombre in self.sospechosos or nombre in self.reparto_pendiente:
            return None
        info = self.tractores[nombre]["info"]
        if t - self.tractores[nombre]["t"] > self.limite_latido:
            return None
        if (info.get("tarea_tipo"), info.get("hilera")) == clave or tuple(info.get("siguiente_tarea") or ()) == clave:
            return True
        return False

    # ------------------------------------------------------------------ subastas urgentes
    def _ocupados_en_mision(self):
        return {mi["tractor"] for mi in self.misiones.values()}

    def _mision_de(self, n):
        return next((mi for mi in self.misiones.values() if mi["tractor"] == n), None)

    def _abrir_pendientes(self, t):
        quedan = []
        for tipo, objetivo, datos in self.pendientes:
            herr = HERRAMIENTA.get(tipo)
            if herr and self.stock[herr] <= 0:
                quedan.append((tipo, objetivo, datos))
                continue
            if tipo == "remolcar" and datos.get("remolcado") not in self.fallados:
                continue   # ya no hace falta (resultó estar bien)
            if not self._subastar(t, tipo, objetivo, datos):
                if not datos.get("_avisado"):
                    datos["_avisado"] = True
                    self.anotar(t, "plan", tipo, f"No hay ningún tractor disponible para {tipo}; la misión espera",
                                "todos los demás están descompuestos, en duda o sin reportarse")
                quedan.append((tipo, objetivo, datos))
        self.pendientes = quedan

    def _subastar(self, t, tipo, objetivo, datos):
        ocupados = self._ocupados_en_mision()
        cand = [n for n, tr in self.tractores.items()
                if n not in self.fallados and n not in ocupados and n not in self.sospechosos
                and t - tr["t"] <= self.limite_latido and n != datos.get("remolcado")]
        if not cand:
            return False
        self.n_id += 1
        sid = self.n_id
        self.n_subastas += 1
        contenido = {"urgente": True, "id": sid, "mision": tipo, "objetivo": list(objetivo)}
        for n in cand:
            self._enviar(t, "cfp", n, contenido)
        self.subastas[sid] = {"id": sid, "tipo": tipo, "objetivo": tuple(objetivo), "datos": datos,
                              "ofertas": [], "candidatos": cand,
                              "t_limite": t + self.m.c["timeout_ofertas"] + self.m.c["retraso_max"] + 1}
        self.anotar(t, "subasta", tipo, f"Subasta urgente para {tipo} en {list(objetivo)}, invita a {', '.join(cand)}")
        return True

    def _costo(self, o):
        p = self.p
        return (p["peso_tiempo"] * o["eta"] + p["peso_trabajo"] * o["trabajo"]
                + p["peso_energia"] * (1 - o["energia"]) + p["peso_riesgo"] * o["riesgo"])

    def _cerrar_subastas(self, t):
        for sid in [s for s, v in self.subastas.items() if t >= v["t_limite"]]:
            s = self.subastas.pop(sid)
            ocupados = self._ocupados_en_mision()
            ofertas = sorted(((self._costo(o), e, o) for e, o in s["ofertas"]
                              if e not in self.fallados and e not in ocupados), key=lambda z: (z[0], z[1]))
            if not ofertas:
                self.anotar(t, "subasta", s["tipo"], "Nadie ofertó a tiempo; se repite la subasta",
                            "ofertas perdidas o tractores ocupados")
                self.pendientes.append((s["tipo"], s["objetivo"], s["datos"]))
                continue
            costo, ganador, o = ofertas[0]
            herr = HERRAMIENTA.get(s["tipo"])
            if herr:
                if self.stock[herr] <= 0:
                    self.pendientes.append((s["tipo"], s["objetivo"], s["datos"]))
                    continue
                self.stock[herr] -= 1
            self.n_id += 1
            mid = self.n_id
            objetivo = s["objetivo"]
            if s["tipo"] == "remolcar":
                objetivo = self.tractores[s["datos"]["remolcado"]]["pos"]
                self.remolcados.add(s["datos"]["remolcado"])
            self.misiones[mid] = {"id": mid, "tipo": s["tipo"], "tractor": ganador, "objetivo": objetivo,
                                  "t_asignada": t, "iniciada": False, "t_avance": t, "mejor": INF,
                                  "datos": s["datos"], "fase": "estacion"}
            acepta = {"urgente": True, "id": sid, "mision": mid, "tipo_mision": s["tipo"],
                      "objetivo": list(objetivo), **{k: v for k, v in s["datos"].items() if not k.startswith("_")}}
            if s["tipo"] == "apagar":
                acepta["fuego"] = [list(c) for c in sorted(self.fuego)]
                self.ref_fuego = max(1, len(self.fuego))
            self.misiones[mid]["acepta"] = acepta
            self._enviar(t, "accept-proposal", ganador, acepta)
            for _c, e, _o in ofertas[1:]:
                self._enviar(t, "reject-proposal", e, {"urgente": True, "id": sid})
            self.anotar(t, "decision", "subasta", self._texto_adjudicacion(s["tipo"], ofertas),
                        self._motivo_adjudicacion(ofertas), ganador)

    @staticmethod
    def _desc(e, costo, o):
        return (f"{e} con costo {costo:.1f} (llega en {o['eta']} pasos, deja {o['trabajo']} celdas a medias, "
                f"diésel {o['energia'] * 100:.0f} %, riesgo {o['riesgo']:.2f})")

    def _texto_adjudicacion(self, tipo, ofertas):
        costo, e, o = ofertas[0]
        texto = f"Subasta de {tipo}, gana " + self._desc(e, costo, o)
        if len(ofertas) > 1:
            texto += ". Otras ofertas, " + "; ".join(self._desc(e2, c2, o2) for c2, e2, o2 in ofertas[1:])
        return texto

    def _motivo_adjudicacion(self, ofertas):
        costo, e, o = ofertas[0]
        if len(ofertas) == 1:
            return f"{e} fue el único que ofertó"
        _c2, e2, o2 = ofertas[1]
        p = self.p
        ventajas = []
        if o["eta"] < o2["eta"]:
            ventajas.append(f"llega {o2['eta'] - o['eta']} pasos antes que {e2}")
        if o["trabajo"] < o2["trabajo"]:
            ventajas.append(f"deja menos trabajo a medias ({o['trabajo']} contra {o2['trabajo']})")
        if o["energia"] > o2["energia"] + 0.05:
            ventajas.append("tiene más diésel")
        if o["riesgo"] + 1e-9 < o2["riesgo"]:
            ventajas.append("su camino es menos riesgoso")
        if not ventajas:
            ventajas.append(f"tiene el menor costo total ({costo:.1f} contra {_c2:.1f})")
        return f"{e} " + ", ".join(ventajas)

    def _devolver_stock(self, mi):
        herr = HERRAMIENTA.get(mi["tipo"])
        if herr:
            self.stock[herr] = min(self.stock[herr] + 1, self.p["n_pipas" if herr == "pipa" else "n_gruas"])

    # ------------------------------------------------------------------ revisar el plan
    def _avance(self, t, e, info=None):
        mi = self._mision_de(e)
        if mi is None:
            return
        if info is not None:
            if info.get("modo") in ("deposito", "servicio"):
                mi["t_avance"] = t   # va a la estación o está enganchando — eso también es avanzar
                return
            d = info.get("dist_meta")
            if d is not None and d < mi["mejor"]:
                mi["mejor"] = d
                mi["t_avance"] = t
            if info.get("fase") and info["fase"] != mi.get("fase") and mi.get("fase") != "devolver":
                mi["fase"] = info["fase"]
                mi["t_avance"] = t
                mi["mejor"] = INF
        else:
            mi["t_avance"] = t

    def _revisar_planes(self, t):
        espera = self.m.c["timeout_ofertas"] + 2 * self.m.c["retraso_max"] + 6
        for mid, mi in list(self.misiones.items()):
            if not mi["iniciada"] and t - mi["t_asignada"] > espera:
                if self.tractores[mi["tractor"]]["info"].get("mision") == mid:
                    mi["iniciada"] = True
                    continue
                if mi.get("reenvios", 0) < 2 and "acepta" in mi:
                    # Puede que solo se haya perdido el mensaje — se le vuelve a mandar la adjudicación
                    mi["reenvios"] = mi.get("reenvios", 0) + 1
                    mi["t_asignada"] = t
                    self._enviar(t, "accept-proposal", mi["tractor"], mi["acepta"])
                    continue
                del self.misiones[mid]
                self._enviar(t, "request", mi["tractor"], {"evento": "cancelar", "mision": mid})
                self._devolver_stock(mi)
                self.n_replanes += 1
                if mi["tipo"] == "revisar":
                    self.anotar(t, "plan", "revisar", f"{mi['tractor']} no confirmó que iba a revisar; "
                                "espera su revisión desde arriba", "no llegó su aviso de inicio", mi["tractor"])
                    continue
                self.anotar(t, "plan", mi["tipo"], f"{mi['tractor']} no confirmó la misión; se repite la subasta",
                            "no llegó su aviso de inicio (mensaje perdido)", mi["tractor"])
                self.pendientes.append((mi["tipo"], mi["objetivo"], mi.get("datos", {})))
                continue
            if mi["iniciada"] and t - mi["t_avance"] > self.p["paciencia_plan"] and mi.get("fase") != "devolver":
                self.n_replanes += 1
                mi["t_avance"] = t
                mi["mejor"] = INF
                herr = HERRAMIENTA.get(mi["tipo"])
                if mi["tipo"] == "revisar":
                    del self.misiones[mid]
                    self._enviar(t, "request", mi["tractor"], {"evento": "cancelar", "mision": mid})
                    self.anotar(t, "plan", "revisar", f"{mi['tractor']} no llega a revisar; se cancela y "
                                "lo revisa desde arriba", "sin avance", mi["tractor"])
                elif herr and self.stock[herr] > 0:
                    self.pendientes.append((mi["tipo"], mi["objetivo"], mi.get("datos", {})))
                    self.anotar(t, "plan", mi["tipo"], f"{mi['tractor']} no avanza — manda a otro tractor a ayudar",
                                f"{self.p['paciencia_plan']} pasos sin avance", mi["tractor"])
                else:
                    self._enviar(t, "request", mi["tractor"], {"evento": "replanear", "mision": mid})
                    texto = f"{mi['tractor']} no avanza — le pide que busque otro camino"
                    if mi["tipo"] == "apagar" and self.margen < self.p["margen_zona_max"]:
                        self.margen += 1
                        texto += f" y agranda la zona prohibida (margen {self.margen})"
                    self.anotar(t, "plan", mi["tipo"], texto, f"{self.p['paciencia_plan']} pasos sin avance",
                                mi["tractor"])
        if not self.fuego and any(mi["tipo"] == "apagar" and mi["iniciada"] and mi.get("fase") != "devolver"
                                  for mi in self.misiones.values()):
            self._terminar_misiones(t, "apagar", "ya no cree que quede fuego (vista desde arriba y reportes)")
        # El fuego crece más rápido de lo esperado
        if self.fuego and any(mi["tipo"] == "apagar" for mi in self.misiones.values()):
            if len(self.fuego) > self.p["crecimiento_fuego"] * self.ref_fuego + 2:
                self.n_replanes += 1
                texto = f"El fuego crece más rápido de lo esperado ({self.ref_fuego} -> {len(self.fuego)} celdas)"
                if self.margen < self.p["margen_zona_max"]:
                    self.margen += 1
                    texto += f", agranda la zona prohibida (margen {self.margen})"
                if self.stock["pipa"] > 0:
                    self.pendientes.append(("apagar", min(self.fuego), {}))
                    texto += " y manda a otro tractor a ayudar"
                self.ref_fuego = len(self.fuego)
                self.anotar(t, "plan", "apagar", texto, "el fuego creció más que el factor de crecimiento_fuego")

    def _terminar_misiones(self, t, tipo, motivo):
        for mi in self.misiones.values():
            if mi["tipo"] == tipo and mi.get("fase") != "devolver":
                mi["fase"] = "devolver"
                self._enviar(t, "request", mi["tractor"], {"evento": "fin_mision", "mision": mi["id"]})
                self.anotar(t, "decision", tipo, f"El fuego quedó apagado, {mi['tractor']} regresa la pipa a la estación",
                            motivo, mi["tractor"])
        if tipo == "apagar":
            self.margen = self.p["margen_zona"]
            self.incendio_activo = False

    def _mandar_objetivo(self, t):
        celdas = [list(c) for c in sorted(self.fuego)]
        for mi in self.misiones.values():
            if mi["tipo"] == "apagar" and mi.get("fase") != "devolver":
                self._enviar(t, "inform", mi["tractor"], {"evento": "objetivo", "mision": mi["id"], "fuego": celdas})

    # ------------------------------------------------------------------ zona prohibida
    def _contenido_zona(self):
        return {"evento": "zona", "version": self.version_zona,
                "celdas": [list(c) for c in sorted(self.zona)],
                "fuego": [list(c) for c in sorted(self.zona_fuego)]}

    def _actualizar_zona(self, t):
        campo = self.m.campo
        excluir = {(x, 0) for x in range(campo.ancho)}   # el patio de la estación nunca se cierra
        fuego = frozenset(self.fuego)
        zona = _bola(fuego, self.margen, campo, excluir) | set(self.obst)
        zona = frozenset(zona)
        if zona == self.zona and fuego == self.zona_fuego:
            return
        antes = len(self.zona)
        self.zona_desde = {c: self.zona_desde.get(c, t) for c in zona}
        self.zona, self.zona_fuego = zona, fuego
        self.version_zona += 1
        self.historia_zona.append({"t": int(t), "celdas": [list(c) for c in sorted(zona)],
                                   "fuego": [list(c) for c in sorted(fuego)]})
        self._difundir(t, "inform", self._contenido_zona())
        self.repetir_zona = t + 1
        if zona and not antes:
            self.anotar(t, "aviso", "zona", f"Avisa a todos la zona prohibida ({len(zona)} celdas)")
        elif not zona and antes:
            self.anotar(t, "decision", "zona", "Vuelve a habilitar las celdas de la zona prohibida",
                        "ya no hay fuego ni obstáculos confirmados en ella")

    # ------------------------------------------------------------------ salida
    def resumen(self):
        rep = self.reportes
        verdad = self.m.verdad_reportes
        real = lambda r: bool(verdad.get(r["id"], False))
        return {
            "reportes_total": len(rep),
            "reportes_reales": sum(1 for r in rep if real(r)),
            "reportes_falsos": sum(1 for r in rep if not real(r)),
            "falsos_descartados": sum(1 for r in rep if not real(r) and r["estado"] == "descartado"),
            # Un reporte falso cuenta como confirmado por error solo si al confirmarlo de verdad no había
            # nada (si el fuego ya había llegado a esa celda, confirmarlo fue correcto)
            "falsos_confirmados": sum(1 for r in rep if not real(r) and r["estado"] == "confirmado"
                                      and not r.get("hay_al_decidir")),
            "reales_descartados": sum(1 for r in rep if real(r) and r["estado"] == "descartado"),
            "reportes_verificados": sum(1 for r in rep if r["pedido"]),
            "reportes_sin_decidir": sum(1 for r in rep if r["estado"] in ("pendiente", "verificando")),
            "subastas_urgentes": self.n_subastas,
            "replanes": self.n_replanes,
            "decisiones_coordinador": self.n_decisiones,
        }


# ============================================================================ tractor (parte M3)
class TractorM3:
    """Percepción local, reportes, latidos, autoprotección y misiones del coordinador.

    Todo esto solo corre si el modelo tiene eventos activos o es M3 (`model.m3_activo`).
    """

    def _setup_m3(self):
        self.herramienta = None
        self.mision = None
        self.agua = 0
        self.fuego_visto = set()
        self.t_fuego_visto = {}       # celda -> último paso en que la vio arder
        self.obst_visto = set()
        self.zona = frozenset()
        self.zona_fuego = frozenset()
        self.zona_v = 0
        self._vedadas = frozenset()
        self._perdidas_conocidas = frozenset()
        self.reportados = set()
        self.reparando = 0
        self.espera_zona = 0
        self.modo_previo = None
        self.remolcado_por = None
        self._fin_pendiente = False
        self.volver_terminado = False

    # ------------------------------------------------------------------ percepción
    def _percibir(self, t):
        m = self.model
        ev = m.eventos
        r = m.p3["radio_percepcion"]
        pfn = m.p3["prob_no_detectar"]
        x0, y0 = self.pos
        nuevos_f, nuevos_o = [], []
        for dx in range(-r, r + 1):
            k = r - abs(dx)
            for dy in range(-k, k + 1):
                c = (x0 + dx, y0 + dy)
                if c not in m.campo.vecinos:
                    continue
                if ev.ardiendo(c):
                    if pfn > 0 and ev.rng_percepcion.random() < pfn:
                        continue
                    if c not in self.fuego_visto:
                        nuevos_f.append(c)
                    self.ver_fuego(c, t)
                else:
                    self.fuego_visto.discard(c)
                if c in ev.celdas_obstaculo and c not in self.obst_visto:
                    if pfn > 0 and ev.rng_percepcion.random() < pfn:
                        continue
                    self.obst_visto.add(c)
                    nuevos_o.append(c)
        if m.coordinador is None:
            # Sin coordinador, el evento se "detecta" cuando el primer tractor lo ve (y él mismo lo esquiva)
            if nuevos_f:
                m.marcar("t_deteccion_incendio", t)
            if nuevos_o:
                m.marcar("t_deteccion_obstaculo", t)
                m.marcar("t_respuesta_obstaculo", t)
        return nuevos_f, nuevos_o

    def ver_fuego(self, c, t):
        self.fuego_visto.add(c)
        self.t_fuego_visto[c] = t

    def _olvidar_fuego_viejo(self, t):
        """Lo que vio arder hace más de lo que arde una celda ya se apagó o se consumió."""
        dur = self.model.eventos.inc["duracion_pasos"]
        viejas = [c for c in self.fuego_visto if t - self.t_fuego_visto.get(c, t) > dur]
        for c in viejas:
            self.fuego_visto.discard(c)

    def _ve(self, c):
        """¿Ve algo real en la celda c? (si está en su radio; con error de no detectar)."""
        m = self.model
        ev = m.eventos
        if manhattan(self.pos, c) > m.p3["radio_percepcion"]:
            return False
        hay = ev.activo and (ev.ardiendo(c) or c in ev.celdas_obstaculo)
        return hay and not (m.p3["prob_no_detectar"] > 0 and ev.rng_percepcion.random() < m.p3["prob_no_detectar"])

    def _reportar(self, t, nuevos_f, nuevos_o):
        m = self.model
        for clase, nuevos in (("incendio", nuevos_f), ("obstaculo", nuevos_o)):
            celdas = [c for c in nuevos if (clase, c) not in self.reportados]
            if not celdas:
                continue
            for c in celdas:
                self.reportados.add((clase, c))
            self._enviar_reporte(t, clase, celdas, real=True)
        ev = m.eventos
        p = m.p3["tasa_reporte_falso"]
        if p > 0 and ev.rng_falsos.random() < p:
            r = m.p3["radio_percepcion"]
            dx = ev.rng_falsos.randint(-r, r)
            dy = ev.rng_falsos.randint(-(r - abs(dx)), r - abs(dx))
            clase = "incendio" if ev.rng_falsos.random() < 0.5 else "obstaculo"
            c = (self.pos[0] + dx, self.pos[1] + dy)
            if (c in m.campo.vecinos and m.campo.es_trabajo(c) and not ev.ardiendo(c) and c not in ev.celdas_obstaculo
                    and m.campo.estado(c) != QUEMADA):
                self._enviar_reporte(t, clase, [c], real=False)

    def _enviar_reporte(self, t, clase, celdas, real):
        m = self.model
        m.n_reportes += 1
        rid = f"{self.nombre}-{m.n_reportes}"
        m.verdad_reportes[rid] = real   # solo para las métricas; el coordinador no lo ve
        m.bus.enviar(t, "inform", self.nombre, COORD, {"evento": "reporte", "id": rid, "clase": clase,
                                                       "celdas": [list(c) for c in celdas], "t_obs": t})

    def _latido(self, t, forzado=False):
        m = self.model
        indice = int(self.nombre[1:])
        if not forzado and (t + indice) % m.p3["periodo_latido"] != 0:
            return
        mi = self.mision
        info = {"evento": "latido", "pos": list(self.pos), "modo": self._nombre_modo(),
                "diesel": round(self.diesel / m.cfg["agente"]["tanque_l"], 3), "zona_v": self.zona_v,
                "implemento": self.implemento,
                "libre": self.mision is None and self._nombre_modo() in ("libre", "terminado"),
                "mision": mi["id"] if mi else None, "fase": mi.get("fase") if mi else None,
                "dist_meta": mi.get("dist_meta") if mi else None}
        if self.tarea:
            info.update(tarea_tipo=self.tarea[0], hilera=self.tarea[1], dir=self.dir,
                        siguiente=list(self.cola[0]) if self.cola else None, restantes=len(self.cola))
        if self.siguiente:
            info["siguiente_tarea"] = [self.siguiente["tipo"], self.siguiente["x"]]
        m.bus.enviar(t, "inform", self.nombre, COORD, info)

    def _nombre_modo(self):
        from .agentes import M_DEPOSITO, M_FUERA, M_LIBRE, M_NEGOCIA, M_SERVICIO, M_TAREA, M_TERMINADO
        return {M_LIBRE: "libre", M_NEGOCIA: "libre", M_TAREA: "tarea", M_DEPOSITO: "deposito",
                M_SERVICIO: "servicio", M_TERMINADO: "terminado", M_FUERA: "fuera",
                M_MISION: "mision"}.get(self.modo, "otro")

    def _actualizar_vedadas(self):
        campo = self.model.campo
        propia = _bola(self.fuego_visto, 1, campo) if self.fuego_visto else set()
        self._vedadas = frozenset(self.zona | propia | self.obst_visto)
        self._perdidas_conocidas = frozenset(self.fuego_visto | self.zona_fuego | self.obst_visto)

    def _bloq(self):
        m = self.model
        return m.bloqueadas | self._vedadas if self._vedadas else m.bloqueadas

    # ------------------------------------------------------------------ ciclo por paso (M3 / eventos)
    def _paso_m3(self, t):
        """Se llama en decidir después de leer el buzón. True si ya decidió este paso."""
        from .agentes import M_SERVICIO
        m = self.model
        if m.eventos.activo:
            nf, no = self._percibir(t)
            if m.coordinador is not None:
                self._reportar(t, nf, no)
        if m.coordinador is not None:
            self._latido(t)
        if self.fuego_visto:
            self._olvidar_fuego_viejo(t)
        self._actualizar_vedadas()
        if self.modo == M_SERVICIO:
            return False
        if self._en_peligro():
            self._huir(t)
            return True
        if self.modo == M_MISION:
            self._paso_mision(t)
            return True
        return False

    def _en_peligro(self):
        if self.pos in self.zona:
            return True
        return any(manhattan(self.pos, f) <= 1 for f in self.fuego_visto)

    def _huir(self, t):
        """Regla de seguridad — se aleja del fuego o sale de la zona prohibida sin esperar a nadie."""
        from .agentes import EN_RUTA
        m = self.model
        ocupadas = {tr.pos for tr in m.orden if tr is not self}
        fuego = self.fuego_visto | self.zona_fuego
        opciones = []
        dentro = self.pos in self.zona
        aqui = min((manhattan(self.pos, f) for f in fuego), default=99)
        for v in m.campo.vecinos[self.pos]:
            if v in ocupadas or v in m.bloqueadas or v == m.campo.deposito or v in m.eventos.celdas_obstaculo:
                continue
            if v in fuego or (v in self.zona and not dentro):
                continue   # nunca huye hacia el fuego ni se mete a la zona prohibida
            dist = min((manhattan(v, f) for f in fuego), default=99)
            if dist < aqui and not dentro:
                continue   # no se acerca más
            opciones.append((v in self._vedadas, -dist, v))
        self.estado, self.intencion = EN_RUTA, "alejarse"
        self.objetivo = None
        self.deseo = min(opciones)[2] if opciones else None
        if m.cooperativo and self.deseo is not None:
            m.reservas.liberar_futuro(self.nombre, t)
            m.reservas.reservar(self.nombre, self.deseo, t + 1)

    # ------------------------------------------------------------------ mensajes del coordinador
    def _mensaje_coord(self, t, msg):
        from .agentes import M_FUERA
        p, c = msg.performativa, msg.contenido
        ev = c.get("evento")
        if p == "cfp" and c.get("urgente"):
            self._ofertar_urgente(t, c)
        elif p == "accept-proposal" and c.get("urgente"):
            self._aceptar_mision(t, c)
        elif p == "inform" and ev == "zona":
            if c["version"] > self.zona_v:
                self.zona_v = c["version"]
                self.zona = frozenset(_celda(x) for x in c["celdas"])
                self.zona_fuego = frozenset(_celda(x) for x in c["fuego"])
                # Lo que el coordinador ya no cree que arda se olvida (salvo lo que acaba de ver arder)
                self.fuego_visto = {x for x in self.fuego_visto
                                    if x in self.zona_fuego or self.t_fuego_visto.get(x, -INF) >= t - 1}
                self.ruta = []
        elif p == "inform" and ev == "descartado":
            for x in c.get("celdas", []):
                self.fuego_visto.discard(_celda(x))
        elif p == "inform" and ev == "objetivo":
            if self.mision and self.mision["tipo"] == "apagar":
                self.mision["fuego"] = {_celda(x) for x in c.get("fuego", [])}
        elif p == "request" and ev in ("fin_mision", "cancelar"):
            if self.mision and self.mision["id"] == c.get("mision"):
                self._pedir_fin_mision(t)
        elif p == "request" and ev == "replanear":
            if self.mision and self.mision["id"] == c.get("mision"):
                self.mision.setdefault("evitar", set()).add(self.mision.get("meta"))
                self.ruta = []
        elif p == "request" and ev == "revisar":
            if self.mision is None and self.modo != M_FUERA and self._nombre_modo() in ("libre", "terminado"):
                self._empezar_mision(t, {"mision": c["mision"], "tipo_mision": "revisar",
                                         "objetivo": c["celdas"][0], "celdas": c["celdas"],
                                         "reporte": c["reporte"], "clase": c["clase"]})
            else:
                self.model.bus.enviar(t, "inform", self.nombre, COORD, {"evento": "rechazo", "mision": c["mision"]})
        elif p == "query-if" and ev == "estado":
            self._latido(t, forzado=True)
        elif p == "query-if" and ev == "verificar":
            celdas = [_celda(x) for x in c["celdas"]]
            if any(manhattan(self.pos, x) <= self.model.p3["radio_percepcion"] for x in celdas):
                visto = [x for x in celdas if self._ve(x)]
                self.model.bus.enviar(t, "inform", self.nombre, COORD,
                                      {"evento": "verificacion", "reporte": c["reporte"], "visto": bool(visto),
                                       "celdas": [list(x) for x in (visto or celdas)]})
            else:
                self.model.bus.enviar(t, "inform", self.nombre, COORD,
                                      {"evento": "verificacion", "reporte": c["reporte"], "visto": False,
                                       "celdas": c["celdas"]})

    def _ofertar_urgente(self, t, c):
        from .agentes import M_FUERA, M_SERVICIO, M_TAREA
        m = self.model
        if self.modo == M_FUERA or self.mision is not None or self.reparando:
            return
        dep = m.campo.deposito
        objetivo = _celda(c["objetivo"])
        eta = manhattan(self.pos, dep) + manhattan(dep, objetivo) + m.d3["pasos_enganche"]
        if self.modo == M_SERVICIO:
            eta += max(0, self.servicio)
        trabajo = len(self.cola) if self.modo == M_TAREA else 0
        oferta = {"urgente": True, "id": c["id"], "eta": int(eta), "trabajo": int(trabajo),
                  "energia": round(max(0.0, self.diesel) / m.cfg["agente"]["tanque_l"], 3),
                  "riesgo": round(self._riesgo_camino(self.pos, dep, objetivo), 3)}
        m.bus.enviar(t, "propose", self.nombre, COORD, oferta)

    def _riesgo_camino(self, a, dep, b):
        """Fracción del camino (a -> estación -> b, en L) que pasa junto a una zona peligrosa."""
        if not self._vedadas:
            return 0.0
        celdas = []
        for (p, q) in ((a, dep), (dep, b)):
            x, y = p
            paso = 1 if q[0] >= x else -1
            for xx in range(x, q[0] + paso, paso):
                celdas.append((xx, y))
            paso = 1 if q[1] >= y else -1
            for yy in range(y, q[1] + paso, paso):
                celdas.append((q[0], yy))
        cerca = _bola(self._vedadas, 1, self.model.campo)
        return sum(1 for c in celdas if c in cerca) / max(1, len(celdas))

    def _aceptar_mision(self, t, c):
        from .agentes import M_FUERA
        if self.mision is not None and self.mision["id"] == c["mision"]:
            # Adjudicación repetida (se perdió su aviso de inicio) — solo lo vuelve a confirmar
            self.model.bus.enviar(t, "inform", self.nombre, COORD, {"evento": "mision_inicio", "mision": c["mision"]})
            return
        if self.modo == M_FUERA or self.mision is not None or self.reparando:
            self.model.bus.enviar(t, "inform", self.nombre, COORD, {"evento": "rechazo", "mision": c["mision"]})
            return
        self._empezar_mision(t, c)

    def _empezar_mision(self, t, c):
        from .agentes import M_DEPOSITO, M_NEGOCIA, M_SERVICIO, M_TAREA, M_TERMINADO
        m = self.model
        tipo = c["tipo_mision"]
        if tipo == "revisar" and self._nombre_modo() not in ("libre", "terminado"):
            m.bus.enviar(t, "inform", self.nombre, COORD, {"evento": "rechazo", "mision": c["mision"]})
            return
        self.modo_previo = "terminado" if self.modo == M_TERMINADO else "libre"
        # Suelta su trabajo — el gestor reparte solo lo que le faltaba
        if self.modo == M_TAREA and self.tarea is not None:
            if self.cola and m.gestor is not None:
                self._informar(t, "liberada", self.tarea[0], self.tarea[1], siguiente=list(self.cola[0]),
                               restantes=len(self.cola), dir=self.dir)
            self.tarea, self.cola = None, []
        self._soltar_siguiente(t)
        self.ronda_neg = None
        self._fin_pendiente = False
        self.mision = {"id": c["mision"], "tipo": tipo, "objetivo": _celda(c["objetivo"]), "fase": "estacion",
                       "fuego": {_celda(x) for x in c.get("fuego", [])}, "remolcado": c.get("remolcado"),
                       "celdas": [_celda(x) for x in c.get("celdas", [])], "reporte": c.get("reporte"),
                       "clase": c.get("clase")}
        m.bus.enviar(t, "inform", self.nombre, COORD, {"evento": "mision_inicio", "mision": c["mision"]})
        if tipo == "revisar":
            self.mision["fase"] = "ir"
            self.modo = M_MISION
            return
        motivo = HERRAMIENTA[tipo]
        if self.modo == M_SERVICIO:
            return   # al terminar su servicio en la estación engancha la herramienta (_fin_servicio_m3)
        if self.modo == M_DEPOSITO:
            self.motivo = motivo
            return
        if self.modo == M_NEGOCIA:
            self.modo = M_DEPOSITO
        self._ir_deposito(t, motivo)

    def _pedir_fin_mision(self, t):
        mi = self.mision
        if mi is None:
            return
        if self.modo == M_MISION:
            self._fin_mision(t)
        else:
            self._fin_pendiente = True

    def _fin_mision(self, t):
        """Regresa la herramienta a la estación (o termina en el lugar si no llevaba)."""
        self._fin_pendiente = False
        if self.herramienta is not None or (self.mision and self.mision["fase"] == "estacion"):
            self.mision["fase"] = "devolver"
            self._ir_deposito(t, "devolver")
        else:
            self._cerrar_mision(t)

    def _cerrar_mision(self, t):
        from .agentes import M_LIBRE, M_TERMINADO, TIPO
        m = self.model
        mid = self.mision["id"] if self.mision else None
        self.mision = None
        self.herramienta = None
        self._fin_pendiente = False
        m.bus.enviar(t, "inform", self.nombre, COORD, {"evento": "mision_fin", "mision": mid})
        if self.modo_previo == "terminado":
            self.modo = M_TERMINADO
        else:
            self.modo = M_LIBRE
            if m.gestor is not None:
                self._informar(t, "disponible", TIPO[self.implemento], -1)

    # ------------------------------------------------------------------ servicio en la estación
    def _servicio_m3(self, motivo):
        """Pasos de servicio para enganchar/desenganchar herramientas o llenar la pipa (None si no aplica)."""
        if motivo in ("pipa", "grua", "devolver", "agua"):
            return self.model.d3["pasos_enganche"]
        return None

    def _fin_servicio_m3(self, t, motivo):
        """Hook de _fin_servicio. True si ya dejó el modo del tractor listo."""
        if self.mision is None:
            if self.volver_terminado:
                from .agentes import M_TERMINADO
                self.volver_terminado = False
                self.modo = M_TERMINADO   # solo fue a cargar diésel; ya había terminado su labor
                return True
            return False
        m = self.model
        if motivo == "devolver":
            self.herramienta = None
            self._cerrar_mision(t)
            return True
        if motivo in ("pipa", "grua"):
            self.herramienta = motivo
            self.agua = m.p3["agua_celdas"] if motivo == "pipa" else 0
        elif motivo == "agua":
            self.agua = m.p3["agua_celdas"]
        elif self.mision["fase"] == "estacion" and self.herramienta is None:
            # Aceptó la misión mientras cargaba — engancha la herramienta sin salir de la estación
            self.motivo = HERRAMIENTA[self.mision["tipo"]]
            self._iniciar_servicio(t)
            return True
        self.mision["fase"] = "ir" if self.mision["fase"] in ("estacion",) else self.mision["fase"]
        self.modo = M_MISION
        if self._fin_pendiente:
            self._fin_mision(t)
        return True

    # ------------------------------------------------------------------ misiones
    def _paso_mision(self, t):
        m = self.model
        necesario = (manhattan(self.pos, m.campo.deposito) + 2) * m.d["diesel_paso_l"] * 1.5 + m.reserva_l
        if self.diesel < necesario and self.mision["fase"] != "enganchar" and not m.remolques.get(self.nombre):
            self._ir_deposito(t, "diesel")
            return
        tipo = self.mision["tipo"]
        if tipo == "apagar":
            self._paso_apagar(t)
        elif tipo == "remolcar":
            self._paso_remolcar(t)
        else:
            self._paso_revisar(t)

    def _ir_a(self, t, meta, intencion):
        from .agentes import ESPERANDO_CELDA, EN_RUTA
        self.objetivo = meta
        self.intencion = intencion
        self.mision["meta"] = meta
        self.mision["dist_meta"] = manhattan(self.pos, meta)
        paso = self._paso_hacia(t, meta)
        self.deseo = paso
        self.estado = EN_RUTA if paso not in (None, self.pos) else ESPERANDO_CELDA

    def _emergencia_quieto(self, t, intencion, objetivo=None):
        self.estado, self.intencion = EMERGENCIA, intencion
        self.objetivo = objetivo
        self._quieto(t)

    def _transitable(self, v, ocupadas):
        m = self.model
        return (v in m.campo.vecinos and v not in self._vedadas and v not in m.bloqueadas
                and v not in ocupadas and v != m.campo.deposito and v not in m.eventos.celdas_obstaculo)

    def _paso_apagar(self, t):
        m = self.model
        ev = m.eventos
        mi = self.mision
        mi["fase"] = mi["fase"] if mi["fase"] != "estacion" else "ir"
        alcance = m.p3["alcance_pipa"]
        # Con la manguera ve si hay fuego hasta su alcance (o su radio, si es mayor)
        r = max(m.p3["radio_percepcion"], alcance)
        objetivos = {c for c in (mi["fuego"] | self.fuego_visto)
                     if not (manhattan(c, self.pos) <= r and not ev.ardiendo(c))}
        mi["fuego"] = objetivos
        if self.agua > 0:
            al_alcance = sorted((manhattan(c, self.pos), c) for c in objetivos
                                if manhattan(c, self.pos) <= alcance and ev.ardiendo(c))
            if al_alcance:
                apagadas = []
                for _d, c in al_alcance[:min(m.p3["apagado_por_paso"], self.agua)]:
                    ev.apagar(c, t)
                    self.agua -= 1
                    objetivos.discard(c)
                    self.fuego_visto.discard(c)
                    apagadas.append(c)
                m.marcar("t_respuesta_incendio", t)
                mi["fase"] = "apagando"
                mi["dist_meta"] = 0
                m.bus.enviar(t, "inform", self.nombre, COORD,
                             {"evento": "apague", "celdas": [list(c) for c in apagadas]})
                self._emergencia_quieto(t, "apagar", apagadas[0])
                return
        else:
            self._ir_deposito(t, "agua")
            return
        if not objetivos:
            if t - mi.get("t_aviso", -INF) >= 10:
                mi["t_aviso"] = t
                m.bus.enviar(t, "inform", self.nombre, COORD, {"evento": "sin_fuego", "celdas": []})
            self._emergencia_quieto(t, "esperar")
            return
        meta = self._celda_ataque(objetivos)
        if meta is None:
            self._emergencia_quieto(t, "esperar")
            return
        self._ir_a(t, meta, "apagar")

    def _celda_ataque(self, objetivos):
        m = self.model
        alcance = m.p3["alcance_pipa"]
        ocupadas = {tr.pos for tr in m.orden if tr is not self}
        evitar = self.mision.get("evitar", set())
        cercanos = sorted(objetivos, key=lambda c: (manhattan(c, self.pos), c))[:30]
        mejor = None
        for c in _bola(cercanos, alcance, m.campo):
            if c in evitar or not (c == self.pos or self._transitable(c, ocupadas)):
                continue
            if not any(manhattan(c, f) <= alcance for f in cercanos):
                continue
            clave = (manhattan(self.pos, c), c)
            if mejor is None or clave < mejor:
                mejor = clave
        return mejor[1] if mejor else None

    def _paso_remolcar(self, t):
        m = self.model
        mi = self.mision
        br = m.tractor(mi["remolcado"])
        from .agentes import M_FUERA
        r = m.p3["radio_percepcion"]
        if br.modo != M_FUERA and mi["fase"] in ("estacion", "ir", "enganchar") and manhattan(self.pos, br.pos) <= r:
            # Lo ve trabajando: no estaba descompuesto (se perdieron sus mensajes). Regresa la grúa.
            m.bus.enviar(t, "inform", self.nombre, COORD, {"evento": "no_descompuesto", "remolcado": br.nombre})
            self._fin_mision(t)
            return
        if mi["fase"] in ("estacion", "ir"):
            mi["fase"] = "ir"
            destino = br.pos if manhattan(self.pos, br.pos) <= r else mi["objetivo"]
            if manhattan(self.pos, br.pos) == 1:
                mi["fase"] = "enganchar"
                mi["k"] = m.d3["pasos_enganche"]
                mi["dist_meta"] = 0
                self._emergencia_quieto(t, "enganchar", br.pos)
                return
            ocupadas = {tr.pos for tr in m.orden if tr is not self}
            junto = [v for v in m.campo.vecinos.get(destino, []) if self._transitable(v, ocupadas) or v == self.pos]
            if not junto:
                self._emergencia_quieto(t, "esperar", destino)
                return
            meta = min(junto, key=lambda v: (manhattan(self.pos, v), v))
            self._ir_a(t, meta, "remolcar")
            return
        if mi["fase"] == "enganchar":
            mi["k"] -= 1
            if mi["k"] <= 0:
                mi["fase"] = "remolcar"
                m.remolques[self.nombre] = br.nombre
                br.remolcado_por = self.nombre
                mi["destino"] = m.lugar_taller(self)
            self._emergencia_quieto(t, "enganchar", br.pos)
            return
        if mi["fase"] == "remolcar":
            destino = mi["destino"]
            if self.pos == destino:
                if br.pos[1] != 0:
                    # Avanza una celda más por el patio para que el remolcado también quede ahí
                    ocupadas = {tr.pos for tr in m.orden if tr is not self}
                    dx = m.campo.deposito[0]
                    sig = [v for v in m.campo.vecinos[self.pos] if v[1] == 0 and abs(v[0] - dx) >= 2
                           and self._transitable(v, ocupadas)]
                    if sig and not mi.get("extra"):
                        mi["extra"] = True
                        mi["destino"] = min(sig, key=lambda v: (-abs(v[0] - dx), v))
                        self._ir_a(t, mi["destino"], "remolcar")
                        self.estado = EMERGENCIA
                        return
                del m.remolques[self.nombre]
                br.remolcado_por = None
                br.iniciar_reparacion(t)
                mi["fase"] = "devolver"
                m.bus.enviar(t, "inform", self.nombre, COORD, {"evento": "entregado", "remolcado": br.nombre})
                self._ir_deposito(t, "devolver")
                return
            self._ir_a(t, destino, "remolcar")
            self.estado = EMERGENCIA if self.deseo not in (None, self.pos) else self.estado
            return

    def _paso_revisar(self, t):
        m = self.model
        mi = self.mision
        celdas = mi["celdas"] or [mi["objetivo"]]
        r = m.p3["radio_percepcion"]
        if any(manhattan(self.pos, c) <= r for c in celdas):
            visto = [c for c in celdas if self._ve(c)]
            m.bus.enviar(t, "inform", self.nombre, COORD,
                         {"evento": "verificacion", "reporte": mi["reporte"], "visto": bool(visto),
                          "celdas": [list(c) for c in (visto or celdas)]})
            self._cerrar_mision(t)
            self._emergencia_quieto(t, "revisar")
            return
        ocupadas = {tr.pos for tr in m.orden if tr is not self}
        candidatos = [v for v in _bola(celdas[:1], r, m.campo) if self._transitable(v, ocupadas)]
        if not candidatos:
            self._cerrar_mision(t)
            self._emergencia_quieto(t, "revisar")
            return
        meta = min(candidatos, key=lambda v: (manhattan(self.pos, v), v))
        self._ir_a(t, meta, "revisar")

    # ------------------------------------------------------------------ falla y reparación
    def iniciar_reparacion(self, t):
        from .agentes import M_FUERA
        if self.modo == M_FUERA:
            self.reparando = self.model.d3["pasos_reparacion"]

    def _paso_reparacion(self, t):
        from .agentes import M_LIBRE, SEMBRADORA, TIPO
        m = self.model
        self.reparando -= 1
        if self.reparando > 0:
            return
        self.modo = M_LIBRE
        self.diesel = float(m.cfg["agente"]["tanque_l"])
        if self.implemento == SEMBRADORA:
            self.tolva = m.d["tolva_celdas"]
        m.bloqueadas.discard(self.pos)
        m.bloqueadas_nombres.discard(self.nombre)
        m.fallado_activo = False
        if m.gestor is not None:
            self._informar(t, "reparado", TIPO[self.implemento], -1)
        m.bus.enviar(t, "inform", self.nombre, COORD, {"evento": "reparado", "pos": list(self.pos)})
