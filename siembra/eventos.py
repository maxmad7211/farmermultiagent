"""Eventos del mundo que usa M3 (docs/m3.md) — incendio que se propaga y obstáculo nuevo.

Esta clase es la "verdad" del ambiente. Los agentes no la consultan directo — los tractores la
perciben en su radio (con errores) y el coordinador la ve desde arriba por sectores.

Mientras los eventos estén apagados no se crea ningún generador aleatorio ni se toca el campo,
así que M0, M1 y M2 dan exactamente lo mismo que antes.

Las semillas de los eventos son propias (no usan `model.random`) — el incendio arranca en la
misma celda y se propaga con los mismos números aleatorios en M2 y en M3, y solo cambia si
alguien lo apaga.
"""

import random

import numpy as np

from .campo import OBSTACULO, QUEMADA

VECINOS4 = ((0, 1), (0, -1), (1, 0), (-1, 0))


class Eventos:
    def __init__(self, modelo, parametros, reportes_falsos=False):
        self.m = modelo
        campo = modelo.campo
        self.inc = parametros["incendio"]
        self.obs = parametros["obstaculo_nuevo"]
        # Con reportes falsos también se encienden la percepción y sus generadores, aunque no haya eventos
        self.activo = bool(self.inc["activo"] or self.obs["activo"] or reportes_falsos)
        semilla = int(modelo.cfg["semilla"])
        # Fuego — celda -> paso en que se apaga sola. Historia para la vista 2D — t_fin_fuego.
        self.fuego = {}
        self.t_fin_fuego = np.full((campo.ancho, campo.alto), -1, dtype=np.int32)
        self.apagadas = set()          # celdas que apagó la pipa (no se consumieron solas)
        self.quemadas = set()          # todas las celdas que alguna vez ardieron
        self.celdas_obstaculo = set()  # celdas del obstáculo nuevo (perdidas para el trabajo)
        self.t_incendio = -1
        self.t_obstaculo = -1
        self.t_fuego_extinto = -1
        self.origen = None
        self.rect_obstaculo = None
        if not self.activo:
            return
        elegir = random.Random(semilla * 7919 + 101)
        self.rng_fuego = np.random.default_rng(semilla * 7919 + 211)
        self.rng_percepcion = random.Random(semilla * 7919 + 307)
        self.rng_falsos = random.Random(semilla * 7919 + 401)
        if self.inc["activo"]:
            self.origen = self._elegir_origen(elegir)
        if self.obs["activo"]:
            self.rect_obstaculo = self._elegir_rectangulo(elegir)

    # ------------------------------------------------------------------ lugar de cada evento
    def _libre_de_obstaculos(self, celdas):
        campo = self.m.campo
        return all(campo.estado(c) != OBSTACULO for c in celdas)

    def _elegir_origen(self, rng):
        campo = self.m.campo
        for _ in range(500):
            x = rng.randint(1, max(1, campo.ancho - 2))
            y = rng.randint(campo.y0 + 2, max(campo.y0 + 2, campo.y1 - 2))
            if self._libre_de_obstaculos([(x, y)]):
                return (x, y)
        return None

    def _elegir_rectangulo(self, rng):
        campo = self.m.campo
        w, h = int(self.obs["ancho"]), int(self.obs["alto"])
        if campo.ancho - w - 1 < 1 or campo.y1 - h - 1 < campo.y0 + 2:
            return None
        for _ in range(500):
            x = rng.randint(1, campo.ancho - w - 1)
            y = rng.randint(campo.y0 + 2, campo.y1 - h - 1)
            anillo = [(i, j) for i in range(x - 1, x + w + 1) for j in range(y - 1, y + h + 1)
                      if 0 <= i < campo.ancho and 0 <= j < campo.alto]
            if self._libre_de_obstaculos(anillo):
                return (x, y, w, h)
        return None

    # ------------------------------------------------------------------ dinámica
    def paso(self, t):
        if not self.activo:
            return
        m = self.m
        frac = m.campo.n_sembradas / m.campo.n_trabajo
        ocupadas = {tr.pos for tr in m.orden}
        if self.origen is not None and self.t_incendio < 0 and frac >= self.inc["cobertura_disparo"]:
            if self.origen not in ocupadas and self._encender(self.origen, t):
                self.t_incendio = t
                m.anotar_verdad(t, "incendio", f"Empieza un incendio en {list(self.origen)}")
        if self.rect_obstaculo is not None and self.t_obstaculo < 0 and frac >= self.obs["cobertura_disparo"]:
            x, y, w, h = self.rect_obstaculo
            celdas = {(i, j) for i in range(x, x + w) for j in range(y, y + h)}
            if not (celdas & ocupadas) and not (celdas & m.bloqueadas):
                self.celdas_obstaculo |= set(m.campo.poner_obstaculo(x, y, w, h, t))
                for c in celdas:
                    self.fuego.pop(c, None)
                self.t_obstaculo = t
                m.anotar_verdad(t, "obstaculo", f"Aparece un obstáculo de {w}x{h} en {[x, y]}")
        if self.fuego:
            self._propagar(t, ocupadas)

    def _encender(self, c, t):
        if self.m.campo.quemar(c, t):
            self.fuego[c] = t + int(self.inc["duracion_pasos"])
            self.quemadas.add(c)
            return True
        return False

    def _propagar(self, t, ocupadas):
        campo = self.m.campo
        # Siempre se sacan los mismos números por paso — la propagación no depende del mecanismo
        u = self.rng_fuego.random((campo.ancho, campo.alto, 4))
        p = self.inc["prob_propagacion"]
        nuevas = []
        for (x, y) in sorted(self.fuego):
            for k, (dx, dy) in enumerate(VECINOS4):
                v = (x + dx, y + dy)
                if not (0 <= v[0] < campo.ancho and campo.y0 <= v[1] <= campo.y1):
                    continue
                if u[x, y, k] < p and v not in ocupadas and campo.estado(v) not in (QUEMADA, OBSTACULO):
                    nuevas.append(v)
        for v in nuevas:
            self._encender(v, t)
        for c in [c for c, t_fin in self.fuego.items() if t_fin <= t]:
            del self.fuego[c]
            self.t_fin_fuego[c] = t
        self._revisar_extinto(t)

    def apagar(self, c, t):
        """La pipa apaga una celda que arde. True si estaba ardiendo."""
        if c not in self.fuego:
            return False
        del self.fuego[c]
        self.t_fin_fuego[c] = t
        self.apagadas.add(c)
        self._revisar_extinto(t)
        return True

    def _revisar_extinto(self, t):
        if not self.fuego and self.t_incendio >= 0 and self.t_fuego_extinto < 0:
            self.t_fuego_extinto = t
            self.m.anotar_verdad(t, "incendio", "Ya no queda fuego en el campo")

    # ------------------------------------------------------------------ consultas
    def ardiendo(self, c):
        return c in self.fuego

    def perdidas(self):
        """Celdas de trabajo que ya no se pueden sembrar (quemadas u ocupadas por el obstáculo nuevo)."""
        return (self.quemadas | self.celdas_obstaculo) if self.activo else set()

    def exportar(self):
        """Datos para la vista 2D — `t_quemado`, `t_fin_fuego`, origen y obstáculos nuevos."""
        campo = self.m.campo
        return {
            "t_quemado": campo.t_quemado.copy(),
            "t_fin_fuego": self.t_fin_fuego.copy(),
            "apagadas": sorted([list(c) for c in self.apagadas]),
            "origen_incendio": list(self.origen) if self.origen and self.t_incendio >= 0 else None,
            "t_incendio": self.t_incendio,
            "t_fuego_extinto": self.t_fuego_extinto,
            "obstaculos_nuevos": [list(o) for o in campo.obstaculos_nuevos],
        }
