"""Planeación de rutas: A* con costos por tipo de celda y Cooperative A* con ventana (WHCA*).

WHCA* (Silver, 2005): cada tractor busca en el espacio (x, y, t) hasta `ventana` pasos adelante,
respetando una tabla de reservas compartida (blackboard). Más allá de la ventana usa la distancia
Manhattan como estimación. Esperar en el lugar es una acción con costo (COSTO_ESPERA).
"""

import heapq

from .campo import PESO, PESO_CRUCE, manhattan

# Costo de esperar un paso. Con la distancia Manhattan como estimación, avanzar sobre la celda más
# cara sube f en (2.0 - 1) = 1.0 y retroceder por la cabecera la sube en (1.0 + 1) = 2.0. La espera
# debe quedar entre ambos: con 1.0 el tractor podía quedarse quieto para siempre frente a celdas
# sembradas, y con más de 2.0 prefería retroceder y avanzar (bloqueo vivo) en vez de esperar.
COSTO_ESPERA = 1.5
assert max(PESO.values()) - 1 < COSTO_ESPERA < min(PESO.values()) + 1


def astar(campo, inicio, meta, bloqueadas=frozenset()):
    """Ruta de menor costo de inicio a meta (sin incluir inicio). None si no hay ruta."""
    if inicio == meta:
        return []
    if (meta in campo.vecinos.get(inicio, ()) and meta not in bloqueadas
            and campo.costo(inicio, meta) < PESO_CRUCE):
        return [meta]  # paso directo, salvo que sea cruzar hileras (por la cabecera puede salir más barato)
    g = {inicio: 0.0}
    padre = {}
    abiertos = [(manhattan(inicio, meta), 0.0, inicio)]
    while abiertos:
        _f, gc, c = heapq.heappop(abiertos)
        if c == meta:
            ruta = [c]
            while ruta[-1] in padre and padre[ruta[-1]] != inicio:
                ruta.append(padre[ruta[-1]])
            ruta.reverse()
            return ruta
        if gc > g.get(c, float("inf")):
            continue
        for v in campo.vecinos[c]:
            if v in bloqueadas and v != meta:
                continue
            ng = gc + campo.costo(c, v)
            if ng < g.get(v, float("inf")):
                g[v] = ng
                padre[v] = c
                heapq.heappush(abiertos, (ng + manhattan(v, meta), ng, v))
    return None


class TablaReservas:
    """Blackboard de reservas espacio-tiempo: (x, y, t) -> nombre del tractor."""

    def __init__(self):
        self.celdas = {}
        self.por_agente = {}

    def reiniciar(self, t, posiciones):
        """Borra todo y deja solo las posiciones actuales: cada paso se replanea en orden de prioridad."""
        self.celdas = {(p[0], p[1], t): n for n, p in posiciones.items()}
        self.por_agente = {n: {(p[0], p[1], t)} for n, p in posiciones.items()}

    def libre(self, c, t, yo):
        dueno = self.celdas.get((c[0], c[1], t))
        return dueno is None or dueno == yo

    def reservar(self, yo, c, t, forzar=False):
        clave = (c[0], c[1], t)
        dueno = self.celdas.get(clave)
        if dueno is not None and dueno != yo and not forzar:
            return False
        if dueno is not None and dueno != yo:
            self.por_agente.get(dueno, set()).discard(clave)
        self.celdas[clave] = yo
        self.por_agente.setdefault(yo, set()).add(clave)
        return True

    def liberar_futuro(self, yo, t):
        claves = self.por_agente.get(yo)
        if not claves:
            return
        quitar = [k for k in claves if k[2] > t]
        for k in quitar:
            claves.discard(k)
            if self.celdas.get(k) == yo:
                del self.celdas[k]

    def liberar_todo(self, yo):
        for k in self.por_agente.pop(yo, set()):
            if self.celdas.get(k) == yo:
                del self.celdas[k]

    def podar(self, t):
        for yo, claves in self.por_agente.items():
            viejas = [k for k in claves if k[2] < t]
            for k in viejas:
                claves.discard(k)
                if self.celdas.get(k) == yo:
                    del self.celdas[k]

    def activas(self, t):
        return sum(1 for k in self.celdas if k[2] > t)


class DistanciaReal:
    """Reverse Resumable A* (Silver, 2005): distancia real de cualquier celda a la meta en el mapa
    estático (sin otros tractores). Busca hacia atrás desde la meta y se reanuda solo cuando se le
    pregunta por una celda que todavía no ha cerrado. Es la estimación que usa WHCA* más allá de su
    ventana; con la distancia Manhattan, un tractor que debe rodear un tramo prohibido oscila."""

    def __init__(self, campo, meta, origen, bloqueadas=frozenset()):
        self.campo, self.meta, self.origen, self.bloqueadas = campo, meta, origen, bloqueadas
        self.g = {meta: 0.0}
        self.cerrado = {}
        self.abiertos = [(manhattan(meta, origen), 0.0, meta)]

    def __call__(self, c):
        if c in self.cerrado:
            return self.cerrado[c]
        campo = self.campo
        while self.abiertos:
            _f, gc, v = heapq.heappop(self.abiertos)
            if v in self.cerrado:
                continue
            self.cerrado[v] = gc
            for u in campo.vecinos[v]:
                if u in self.bloqueadas and u != self.origen:
                    continue
                ng = gc + campo.costo(u, v)
                if ng < self.g.get(u, float("inf")):
                    self.g[u] = ng
                    heapq.heappush(self.abiertos, (ng + manhattan(u, self.origen), ng, u))
            if v == c:
                return gc
        self.cerrado[c] = manhattan(c, self.meta) + 1000.0  # inalcanzable en el mapa estático
        return self.cerrado[c]


def whca(campo, inicio, meta, t0, ventana, reservas, yo, bloqueadas=frozenset(), h=None):
    """Plan de `ventana` celdas para los pasos t0+1 .. t0+ventana (puede repetir celdas = esperar).

    Regla de seguridad igual a la capa reactiva: no se entra a una celda que otro ocupa en el paso
    anterior, lo que impide choques, intercambios y seguimiento pegado. `h` estima el costo
    restante a la meta (por defecto Manhattan; ver DistanciaReal).
    """
    if h is None:
        h = lambda c: manhattan(c, meta)
    inicio_nodo = (inicio, 0)
    g = {inicio_nodo: 0.0}
    padre = {}
    # (f, h, g, k, celda): en empate gana el nodo más cercano a la meta
    abiertos = [(h(inicio), h(inicio), 0.0, 0, inicio)]
    fin = None
    while abiertos:
        _f, _h, gc, k, c = heapq.heappop(abiertos)
        if gc > g.get((c, k), float("inf")):
            continue
        if c == meta or k == ventana:
            fin = (c, k)
            break
        t = t0 + k + 1
        for v in [c] + campo.vecinos[c]:
            if v != c and v in bloqueadas:
                continue
            if not reservas.libre(v, t, yo):
                continue
            if v != c and not reservas.libre(v, t - 1, yo):
                continue
            costo = COSTO_ESPERA if v == c else campo.costo(c, v)
            nodo = (v, k + 1)
            ng = gc + costo
            if ng < g.get(nodo, float("inf")):
                g[nodo] = ng
                padre[nodo] = (c, k)
                hv = h(v)
                heapq.heappush(abiertos, (ng + hv, hv, ng, k + 1, v))
    if fin is None:
        return []
    camino = []
    nodo = fin
    while nodo != inicio_nodo:
        camino.append(nodo[0])
        nodo = padre[nodo]
    camino.reverse()
    # Si llegó antes de la ventana, se queda en la meta mientras pueda
    k = fin[1]
    while k < ventana and reservas.libre(meta, t0 + k + 1, yo):
        camino.append(meta)
        k += 1
    return camino
