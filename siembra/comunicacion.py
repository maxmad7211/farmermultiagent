"""Mensajes entre agentes (FIPA-ACL) con pérdida y retraso configurables."""

from collections import defaultdict
from dataclasses import dataclass, field

ONTOLOGIA = "siembra-maiz-v1"
GESTOR = "DEP"


@dataclass
class Mensaje:
    t_envio: int
    t_entrega: int
    performativa: str
    emisor: str
    receptor: str
    contenido: dict = field(default_factory=dict)
    perdido: bool = False
    ontologia: str = ONTOLOGIA


class Bus:
    """Canal de mensajes. Un mensaje enviado en t llega entre t y t + retraso_max.

    El gestor actúa antes que los tractores en cada paso, así que un mensaje del gestor con
    retraso 0 se lee en el mismo paso y una respuesta de un tractor se lee a partir del siguiente.
    """

    def __init__(self, rng, p_perdida, retraso_max):
        self.rng = rng
        self.p = p_perdida
        self.retraso_max = retraso_max
        self.pendientes = defaultdict(list)
        self.log = []
        self.n_perdidos = 0

    def enviar(self, t, performativa, emisor, receptor, contenido=None):
        perdido = self.p > 0 and self.rng.random() < self.p
        retraso = self.rng.randint(0, self.retraso_max) if self.retraso_max > 0 else 0
        m = Mensaje(t, t + retraso, performativa, emisor, receptor, dict(contenido or {}), perdido)
        self.log.append(m)
        if perdido:
            self.n_perdidos += 1
        else:
            self.pendientes[receptor].append(m)
        return m

    def difundir(self, t, performativa, emisor, receptores, contenido=None):
        """Broadcast: un mensaje por receptor (cada uno se puede perder por separado)."""
        for r in receptores:
            if r != emisor:
                self.enviar(t, performativa, emisor, r, contenido)

    def recibir(self, nombre, t):
        cola = self.pendientes.get(nombre)
        if not cola:
            return []
        listos = [m for m in cola if m.t_entrega <= t]
        if listos:
            self.pendientes[nombre] = [m for m in cola if m.t_entrega > t]
        return listos
