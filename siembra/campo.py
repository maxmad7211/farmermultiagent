"""Ambiente: grid del campo con patio, cabeceras, área de trabajo y obstáculos.

Geometría (ver docs/contrato_datos.md): x de 0 a ancho-1, y de 0 a alto-1 con alto = ancho + 3.
Fila 0 = patio del depósito, fila 1 = cabecera sur, filas 2..ancho+1 = trabajo, última fila = cabecera norte.
"""

import numpy as np

from .config import lado_campo

# Estados dinámicos de cada celda (lista de listas para acceso rápido en Python)
PATIO, CABECERA, LIBRE, SURCADA, SEMBRADA, OBSTACULO = 0, 1, 2, 3, 4, 5
# M3 — celda alcanzada por el fuego (se pierde lo que tenía). Solo aparece con eventos activos.
QUEMADA = 6
# Código del tipo base que se exporta en celdas["tipo_base"]
TIPO_TRABAJO = 2

# Costo de transitar por cada tipo de celda en A* (prefiere cabeceras y evita compactar lo sembrado)
PESO = {PATIO: 1.0, CABECERA: 1.0, LIBRE: 1.3, SURCADA: 1.6, SEMBRADA: 2.0}
# Cruzar hileras en lateral dentro del área de trabajo: se permite (para rodear a otro tractor),
# pero cuesta más que dar la vuelta por la cabecera (salir 1 + lateral 1 + entrar >= 1.3)
PESO_CRUCE = 4.0

FORMAS_OBSTACULO = [("poste", 1, 1), ("arbol", 2, 2)]


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class Campo:
    def __init__(self, cfg, rng):
        c = cfg["campo"]
        n = lado_campo(cfg)
        self.celda_m = c["celda_m"]
        self.ancho = n
        self.alto = n + 3
        self.y0, self.y1 = 2, n + 1
        self.est = [[LIBRE] * self.alto for _ in range(self.ancho)]
        for x in range(self.ancho):
            self.est[x][0] = PATIO
            self.est[x][1] = CABECERA
            self.est[x][self.alto - 1] = CABECERA
        dx = c.get("deposito_x")
        self.deposito = (n // 2 if dx is None else int(dx), 0)

        self.obstaculos = self._colocar_obstaculos(c, rng)
        for (x, y, w, h, _tipo) in self.obstaculos:
            for i in range(x, x + w):
                for j in range(y, y + h):
                    self.est[i][j] = OBSTACULO

        # Celdas donde moverse en lateral cuesta lo normal: patio, cabeceras y el anillo alrededor de
        # obstáculos. En el resto del área de trabajo el movimiento lateral cuesta PESO_CRUCE.
        self.lateral = [[False] * self.alto for _ in range(self.ancho)]
        for x in range(self.ancho):
            for y in (0, 1, self.alto - 1):
                self.lateral[x][y] = True
        for (x, y, w, h, _t) in self.obstaculos:
            for i in range(x - 1, x + w + 1):
                for j in range(y - 1, y + h + 1):
                    if 0 <= i < self.ancho and 0 <= j < self.alto:
                        self.lateral[i][j] = True

        self.vecinos = {}
        for x in range(self.ancho):
            for y in range(self.alto):
                if self.est[x][y] == OBSTACULO:
                    continue
                lista = []
                for ddx, ddy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    nx, ny = x + ddx, y + ddy
                    if not (0 <= nx < self.ancho and 0 <= ny < self.alto):
                        continue
                    if self.est[nx][ny] == OBSTACULO:
                        continue
                    lista.append((nx, ny))
                self.vecinos[(x, y)] = lista

        # Hileras: celdas de trabajo de cada columna, de sur a norte
        self.columnas = [
            [(x, y) for y in range(self.y0, self.y1 + 1) if self.est[x][y] != OBSTACULO]
            for x in range(self.ancho)
        ]
        self.largo_hilera = max(len(col) for col in self.columnas)
        self.n_trabajo = sum(len(col) for col in self.columnas)
        self.ha_sembrables = self.n_trabajo * self.celda_m ** 2 / 10000
        self.dir_surco = [0] * self.ancho  # +1 norte, -1 sur; lo fija el primer surcador (estigmergia)

        forma = (self.ancho, self.alto)
        self.t_surcado = np.full(forma, -1, dtype=np.int32)
        self.t_sembrado = np.full(forma, -1, dtype=np.int32)
        self.pasadas = np.zeros(forma, dtype=np.int32)
        self.t_quemado = np.full(forma, -1, dtype=np.int32)   # M3 — paso en que la alcanzó el fuego
        self.obstaculos_nuevos = []                           # M3 — [x, y, ancho, alto, t] que aparecen después
        self.n_surcadas = 0
        self.n_sembradas = 0

    def _colocar_obstaculos(self, c, rng):
        explicitos = c.get("obstaculos") or []
        if explicitos:
            return [(o["x"], o["y"], o.get("ancho", 1), o.get("alto", 1), o.get("tipo", "obstaculo"))
                    for o in explicitos]
        res, ocupadas = [], set()
        for k in range(int(c.get("n_obstaculos", 0))):
            tipo, w, h = FORMAS_OBSTACULO[k % len(FORMAS_OBSTACULO)]
            if self.ancho - w - 1 < 1 or self.y1 - h - 1 < self.y0 + 2:
                continue  # campo demasiado chico para este obstáculo
            for _ in range(200):
                # Margen de 2 celdas a cabeceras y bordes para no cerrar el paso
                x = rng.randint(1, self.ancho - w - 1)
                y = rng.randint(self.y0 + 2, self.y1 - h - 1)
                celdas = {(i, j) for i in range(x - 1, x + w + 1) for j in range(y - 1, y + h + 1)}
                if not celdas & ocupadas:
                    ocupadas |= celdas
                    res.append((x, y, w, h, tipo))
                    break
        return res

    # ------------------------------------------------------------------ consultas
    def peso(self, c):
        return PESO.get(self.est[c[0]][c[1]], 1.0)

    def costo(self, a, b):
        """Costo de moverse de a a b (vecinas). Lateral fuera de cabeceras = cruzar hileras."""
        if a[1] == b[1] and not (self.lateral[a[0]][a[1]] and self.lateral[b[0]][b[1]]):
            return PESO_CRUCE
        return PESO.get(self.est[b[0]][b[1]], 1.0)

    def estado(self, c):
        return self.est[c[0]][c[1]]

    def es_trabajo(self, c):
        return self.y0 <= c[1] <= self.y1 and self.est[c[0]][c[1]] != OBSTACULO

    def surcar(self, c, t):
        if self.est[c[0]][c[1]] == LIBRE:
            self.est[c[0]][c[1]] = SURCADA
            self.t_surcado[c] = t
            self.n_surcadas += 1
            return True
        return False

    def sembrar(self, c, t):
        if self.est[c[0]][c[1]] == SURCADA:
            self.est[c[0]][c[1]] = SEMBRADA
            self.t_sembrado[c] = t
            self.n_sembradas += 1
            return True
        return False

    def quemar(self, c, t):
        """El fuego alcanza una celda de trabajo — se pierde lo surcado o sembrado. True si ardió."""
        x, y = c
        e = self.est[x][y]
        if e in (OBSTACULO, QUEMADA) or not (self.y0 <= y <= self.y1):
            return False
        if e == SEMBRADA:
            self.n_sembradas -= 1   # la cobertura cuenta solo lo que sigue sembrado
        self.est[x][y] = QUEMADA
        self.t_quemado[c] = t
        return True

    def poner_obstaculo(self, x, y, w, h, t):
        """Aparece un obstáculo que no estaba en el mapa (M3). Devuelve sus celdas."""
        celdas = []
        for i in range(x, x + w):
            for j in range(y, y + h):
                if self.est[i][j] == SEMBRADA:
                    self.n_sembradas -= 1
                if self.est[i][j] != OBSTACULO:
                    self.est[i][j] = OBSTACULO
                    celdas.append((i, j))
        self.obstaculos_nuevos.append([x, y, w, h, t])
        return celdas

    def hilera_completa(self, x, tipo):
        objetivo = SEMBRADA if tipo == "sembrar" else SURCADA
        return all(self.est[c[0]][c[1]] >= objetivo for c in self.columnas[x])

    def tipo_base(self):
        base = np.full((self.ancho, self.alto), TIPO_TRABAJO, dtype=np.int8)
        base[:, 0] = PATIO
        base[:, 1] = CABECERA
        base[:, self.alto - 1] = CABECERA
        for (x, y, w, h, _t) in self.obstaculos:
            base[x:x + w, y:y + h] = OBSTACULO
        return base

    def descripcion(self):
        return {
            "ancho": self.ancho, "alto": self.alto, "y0": self.y0, "y1": self.y1,
            "deposito": list(self.deposito),
            "obstaculos": [list(o) for o in self.obstaculos],
            "celda_m": self.celda_m,
        }
