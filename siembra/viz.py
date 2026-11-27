"""Visualización 2D y dashboard (Matplotlib).

Cada función recibe datos ya cargados (el ``dict`` de una corrida o un ``DataFrame`` de
``resultados/``) y devuelve la figura; ninguna lee archivos ni inventa valores. Las paletas son las
de ``docs/contrato_datos.md``.

Convenciones
------------
- Funciones de un solo panel: ``f(ax, datos, ...)``; con ``ax=None`` crean su propia figura.
- Funciones de varios paneles: ``f(datos, ..., fig=None)``.
- El tiempo se convierte con ``resumen["paso_s"]`` (horas) y ``resumen["pasos_dia"]`` (jornadas).
- Cada figura lleva título, una línea de parámetros (``texto_parametros``) y ejes con unidades.
"""

from __future__ import annotations

import math
import textwrap
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import animation
from matplotlib import colors as mcolors
from matplotlib import patheffects
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch, Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.transforms import ScaledTranslation
from scipy import stats

# ---------------------------------------------------------------------------------------- paleta

COLOR_MECANISMO = {"M0": "#2a78d6", "M1": "#eb6834", "M2": "#1baf7a"}
NOMBRE_MECANISMO = {
    "M0": "M0 · franjas fijas",
    "M1": "M1 · Contract Net",
    "M2": "M2 · Contract Net + broadcast + blackboard",
    "M3": "M3 · M2 + coordinador supervisor",
}
# M3 queda fuera de COLOR_MECANISMO (el contrato fija los tres colores de la propuesta)
COLOR_M3 = "#c2338a"

# Capa de eventos de M3 en el mapa (fuego, zona prohibida, herramientas)
COLOR_FUEGO = "#f05a28"
COLOR_QUEMADA = "#5b4636"
COLOR_ZONA = "#d03b3b"
COLOR_PIPA = "#2a78d6"
COLOR_GRUA = "#eda100"
ORDEN_MECANISMOS = ("M0", "M1", "M2")
_COLORES_EXTRA = ("#6250d6", "#e87ba4", "#898781")  # solo para variantes fuera del contrato

GRUPOS_ACTIVIDAD = ("Trabajando", "Traslado", "Estación", "Esperas", "Ocio")
COLOR_ACTIVIDAD = {
    "Trabajando": "#008300",
    "Traslado": "#6250d6",
    "Estación": "#eda100",
    "Esperas": "#e87ba4",
    "Ocio": "#c3c2b7",
}
GRUPO_DE_ESTADO = {
    "trabajando": "Trabajando",
    "en_ruta": "Traslado",
    "ruta_deposito": "Traslado",
    "en_fila": "Estación",
    "recargando": "Estación",
    "cambiando_implemento": "Estación",
    "esperando_celda": "Esperas",
    "esperando_surco": "Esperas",
    "sin_tarea": "Ocio",
    "negociando": "Ocio",
    "emergencia": "Traslado",   # M3 — misión del coordinador (apagar, enganchar, remolcar)
    # "terminado" y "fuera_servicio" quedan fuera del análisis
}

ESTADOS_CELDA = ("patio", "cabecera", "libre", "surcada", "sembrada", "obstaculo")
COLOR_CELDA = {
    "patio": "#e1e0d9",
    "cabecera": "#c3c2b7",
    "libre": "#f3ead7",
    "surcada": "#a0784f",
    "sembrada": "#3f8f3f",
    "obstaculo": "#383835",
}
NOMBRE_CELDA = {
    "patio": "Patio del depósito",
    "cabecera": "Cabecera",
    "libre": "Libre",
    "surcada": "Surcada",
    "sembrada": "Sembrada",
    "obstaculo": "Obstáculo",
}
# Códigos de tipo_base del contrato: 0 patio, 1 cabecera, 2 trabajo, 5 obstáculo
TIPO_PATIO, TIPO_CABECERA, TIPO_TRABAJO, TIPO_OBSTACULO = 0, 1, 2, 5

# Tinta y superficie (guía de visualización)
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
TINTA_3 = "#898781"
REJILLA = "#e1e0d9"
EJE = "#c3c2b7"
SUPERFICIE = "#fcfcfb"
FONDO_TARJETA = "#f2f1ed"
ROJO_PERDIDO = "#d03b3b"

# Magnitud: una sola tonalidad de claro a oscuro
AZULES = ["#eef4fc", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
VERDES = ["#eaf5e6", "#c6e6bd", "#93cd86", "#5fb052", "#2f8f2f", "#17721b", "#0b5210"]
# Divergente: azul (baja) / gris (sin cambio) / rojo (sube)
AZUL_DIV, GRIS_DIV, ROJO_DIV = "#1c5cab", "#f0efec", "#e34948"

PERFORMATIVAS = ("cfp", "propose", "accept-proposal", "reject-proposal", "inform")
NOMBRE_PERFORMATIVA = {
    "cfp": "cfp (anuncio)",
    "propose": "propose (oferta)",
    "accept-proposal": "accept-proposal (adjudicación)",
    "reject-proposal": "reject-proposal (rechazo)",
    "inform": "inform (aviso)",
}

ETIQUETA = {
    "costo_ha": "Costo por hectárea ($/ha)",
    "J": "Costo de operación J ($)",
    "T_h": "Tiempo total T (h)",
    "T_dias": "Tiempo total T (jornadas)",
    "T_dias_calendario": "Tiempo total T (días calendario)",
    "cobertura": "Cobertura (%)",
    "colisiones": "Colisiones (conteo)",
    "intercambios": "Intercambios (conteo)",
    "W_ocio_h": "W_ocio (h-tractor)",
    "W_espera_h": "W_espera (h-tractor)",
    "W_conflicto_h": "W_conflicto (h-tractor)",
    "W_precedencia_h": "W_precedencia (h-tractor)",
    "mensajes_total": "Mensajes enviados (conteo)",
    "mensajes_perdidos": "Mensajes perdidos (conteo)",
    "reanuncios": "Reanuncios (conteo)",
    "dispersion_dias": "Dispersión de siembra (jornadas)",
    "diesel_l": "Diésel (L)",
    "eficiencia_campo": "Eficiencia de campo (%)",
    "tiempo_computo_s": "Tiempo de cómputo (s)",
    "balance_carga": "Balance de carga (hileras)",
    "D_celdas": "Distancia D (celdas)",
    "H_motor_h": "Horas de motor (h)",
    "pct_en_ventana": "Sembrado dentro de la ventana (%)",
    "recargas": "Recargas (conteo)",
}
ESCALA = {"cobertura": 100, "eficiencia_campo": 100, "pct_en_ventana": 100, "perdida_mensajes": 100}
DECIMALES = {
    "costo_ha": 0, "J": 0, "T_h": 1, "T_dias": 2, "T_dias_calendario": 2, "cobertura": 1,
    "colisiones": 1, "intercambios": 1, "W_ocio_h": 2, "W_espera_h": 2, "W_conflicto_h": 2,
    "W_precedencia_h": 2, "mensajes_total": 0, "mensajes_perdidos": 0, "reanuncios": 1,
    "dispersion_dias": 2, "diesel_l": 0, "eficiencia_campo": 1, "tiempo_computo_s": 1,
    "balance_carga": 1, "D_celdas": 0, "H_motor_h": 1, "pct_en_ventana": 1, "recargas": 1,
}

NOMBRE_PARAMETRO_ARQ = {
    "timeout_ofertas": "Tiempo límite de ofertas (pasos)",
    "perdida_mensajes": "Pérdida de mensajes (%)",
    "ventana_reservas": "Ventana de reservas de Cooperative A* (pasos)",
    "margen_recarga_hileras": "Margen de recarga anticipada (hileras)",
}
# Métrica que cada parámetro de arquitectura debería mover (propuesta, sección de sensibilidad)
METRICA_ARQ = {
    "timeout_ofertas": "W_ocio_h",
    "perdida_mensajes": "T_h",
    "ventana_reservas": "W_conflicto_h",
    "margen_recarga_hileras": "W_espera_h",
}

_HALO = [patheffects.withStroke(linewidth=2.5, foreground=SUPERFICIE)]


# ---------------------------------------------------------------------------------------- estilo

def estilo():
    """Fija rcParams: fuente sans del sistema, rejilla fina sólida, sin bordes superior/derecho."""
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Helvetica Neue", "Helvetica", "Arial", "Liberation Sans",
                            "DejaVu Sans"],
        "font.size": 9.5,
        "text.color": TINTA,
        "axes.facecolor": SUPERFICIE,
        "figure.facecolor": SUPERFICIE,
        "savefig.facecolor": SUPERFICIE,
        "axes.edgecolor": EJE,
        "axes.linewidth": 0.8,
        "axes.labelcolor": TINTA_2,
        "axes.labelsize": 9.5,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.titlecolor": TINTA,
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "axes.prop_cycle": mpl.cycler(color=list(COLOR_MECANISMO.values())),
        "grid.color": REJILLA,
        "grid.linewidth": 0.6,
        "grid.linestyle": "-",
        "xtick.color": EJE,
        "ytick.color": EJE,
        "xtick.labelcolor": TINTA_2,
        "ytick.labelcolor": TINTA_2,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "lines.linewidth": 1.5,          # ~2 px a 100 dpi
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        "legend.frameon": False,
        "legend.fontsize": 8.5,
        "legend.labelcolor": TINTA_2,
        "legend.title_fontsize": 8.5,
        "image.interpolation": "nearest",
        "figure.dpi": 100,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
        "axes.formatter.use_mathtext": False,
        "text.parse_math": False,        # los montos llevan "$" y no deben leerse como LaTeX
        "animation.embed_limit": 60,
    })


# ---------------------------------------------------------------------------------- utilidades

def _num(v, defecto=np.nan):
    try:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return defecto
        return float(v)
    except (TypeError, ValueError):
        return defecto


def _bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "si", "sí", "yes")
    try:
        return bool(v) and not (isinstance(v, float) and math.isnan(v))
    except (TypeError, ValueError):
        return False


def _fmt(v, dec=1, prefijo="", sufijo=""):
    v = _num(v)
    if np.isnan(v):
        return "—"
    return f"{prefijo}{v:,.{dec}f}{sufijo}"


def _dinero(v, dec=0):
    v = _num(v)
    if np.isnan(v):
        return "—"
    signo = "−" if v < 0 else ""
    return f"{signo}${abs(v):,.{dec}f}"


def _formato_dinero(ax, eje="y"):
    f = FuncFormatter(lambda v, _p: _dinero(v))
    (ax.yaxis if eje == "y" else ax.xaxis).set_major_formatter(f)


def _color_mecanismo(m):
    if m in COLOR_MECANISMO:
        return COLOR_MECANISMO[m]
    if m == "M3":
        return COLOR_M3
    return _COLORES_EXTRA[abs(hash(m)) % len(_COLORES_EXTRA)]


def _mecanismos(df, col="mecanismo"):
    presentes = [m for m in pd.unique(df[col].astype(str))]
    orden = [m for m in ORDEN_MECANISMOS if m in presentes]
    return orden + sorted(m for m in presentes if m not in ORDEN_MECANISMOS)


def _orden_agente(a):
    a = str(a)
    return (0, int(a[1:])) if a[1:].isdigit() else (1, a)


def _base_parametro(p):
    return str(p).split(".")[-1]


def ic95(valores):
    """(media, límite inferior, límite superior) del IC 95 % de la media con t de Student."""
    x = pd.to_numeric(pd.Series(valores), errors="coerce").dropna().to_numpy(dtype=float)
    if x.size == 0:
        return np.nan, np.nan, np.nan
    media = float(x.mean())
    if x.size < 2:
        return media, media, media
    sem = float(x.std(ddof=1)) / math.sqrt(x.size)
    h = float(stats.t.ppf(0.975, x.size - 1)) * sem
    return media, media - h, media + h


def resumen_por_grupo(df, por, metrica, escala=None):
    """Media, IC 95 % y n de ``metrica`` agrupada por ``por`` (columna o lista)."""
    escala = ESCALA.get(metrica, 1) if escala is None else escala
    filas = []
    for clave, g in df.groupby(por, sort=True):
        media, lo, hi = ic95(pd.to_numeric(g[metrica], errors="coerce") * escala)
        fila = dict(zip(por, clave)) if isinstance(por, (list, tuple)) else {por: clave}
        fila.update(media=media, ic_bajo=lo, ic_alto=hi, n=int(g[metrica].notna().sum()))
        filas.append(fila)
    return pd.DataFrame(filas)


def _paso_h(resumen):
    return _num(resumen.get("paso_s"), 13.16) / 3600.0


def _pasos_dia(resumen):
    pd_ = _num(resumen.get("pasos_dia"))
    if np.isnan(pd_):
        pd_ = _num(resumen.get("jornada_h"), 10) / _paso_h(resumen)
    return pd_


def _t_final(corrida):
    r = corrida.get("resumen", {})
    candidatos = []
    pasos = corrida.get("pasos")
    if pasos is not None and len(pasos):
        candidatos.append(int(pasos["t"].max()))
    serie = corrida.get("serie")
    if serie is not None and len(serie):
        candidatos.append(int(serie["t"].max()))
    if candidatos:
        return max(candidatos)
    return max(int(_num(r.get("T_pasos"), 0)), int(_num(r.get("pasos_simulados"), 0)))


def _t_siembra_final(corrida):
    T = int(_num(corrida.get("resumen", {}).get("T_pasos"), -1))
    return T if T > 0 else _t_final(corrida)


def escenario_de(corrida):
    """Id del escenario de una corrida (de ``corrida['id']`` sin el sufijo _M?_s?)."""
    for fuente in (corrida.get("escenario"), corrida.get("resumen", {}).get("escenario"),
                   (corrida.get("parametros") or {}).get("escenario")):
        if fuente:
            return str(fuente)
    cid = corrida.get("id")
    if cid:
        partes = str(cid).split("_")
        if len(partes) >= 3 and partes[-1].startswith("s") and partes[-2].startswith("M"):
            return "_".join(partes[:-2])
        return str(cid)
    return None


def texto_parametros(resumen, escenario=None):
    """Línea corta con mecanismo, hectáreas, N, semilla, escenario y condiciones no base."""
    r = resumen or {}
    partes = []
    mec = r.get("mecanismo")
    if mec is not None:
        partes.append(NOMBRE_MECANISMO.get(str(mec), str(mec)))
    ha = _num(r.get("hectareas"))
    if not np.isnan(ha):
        partes.append(f"{ha:g} ha")
    n = _num(r.get("n_tractores"))
    if not np.isnan(n):
        texto = f"N = {int(n)} tractor{'es' if n != 1 else ''}"
        ns = _num(r.get("n_surcadores"))
        if not np.isnan(ns) and n > 1:
            texto += f" ({int(ns)} surcador{'es' if ns != 1 else ''})"
        partes.append(texto)
    sem = r.get("semilla")
    if sem is not None and not (isinstance(sem, float) and np.isnan(sem)):
        partes.append(f"semilla {int(_num(sem))}")
    esc = escenario or r.get("escenario")
    if esc:
        partes.append(f"escenario {esc}")
    nob = _num(r.get("n_obstaculos"), 0)
    if nob > 0:
        partes.append(f"{int(nob)} obstáculo{'s' if nob != 1 else ''}")
    p = _num(r.get("perdida_mensajes"), 0)
    if p > 0:
        partes.append(f"pérdida de mensajes {p * 100:.0f} %")
    if _bool(r.get("falla_activa")):
        partes.append("falla de un tractor")
    tol = _num(r.get("tolva_ha"))
    if not np.isnan(tol):
        partes.append(f"tolva {tol:g} ha")
    return " · ".join(partes)


def _texto_corrida(corrida):
    return texto_parametros(corrida.get("resumen", {}), escenario_de(corrida))


def _titulo_ax(ax, titulo, sub=None, tam=11, extra=0):
    """Título y subtítulo a la izquierda; ``extra`` (puntos) deja lugar para una leyenda arriba.

    El subtítulo se parte en líneas del ancho del eje: un texto más ancho que la figura hace
    que constrained_layout colapse los ejes."""
    lineas = 0
    if sub:
        ancho_pt = ax.figure.get_figwidth() * max(ax.get_position().width, 0.3) * 72 + 60
        sub = "\n".join(textwrap.wrap(sub, max(40, int(ancho_pt / (8 * 0.5)))))
        lineas = sub.count("\n")
    ax.set_title(titulo, loc="left", pad=(20 + 11 * lineas if sub else 8) + extra, fontsize=tam,
                 fontweight="semibold", color=TINTA)
    if sub:
        ax.annotate(sub, xy=(0, 1), xycoords="axes fraction", xytext=(0, 6 + extra),
                    textcoords="offset points", ha="left", va="bottom", fontsize=8, color=TINTA_2,
                    linespacing=1.25)


def _titulo_fig(fig, titulo, sub=None):
    """Título y subtítulo encima de la figura (se incluyen al guardar con bbox 'tight')."""
    base = fig.transFigure
    if sub:
        fig.text(0.005, 1.0, sub, ha="left", va="bottom", fontsize=8.5, color=TINTA_2,
                 transform=base + ScaledTranslation(0, 6 / 72, fig.dpi_scale_trans))
    fig.text(0.005, 1.0, titulo, ha="left", va="bottom", fontsize=12.5, fontweight="semibold",
             color=TINTA, transform=base + ScaledTranslation(0, (24 if sub else 8) / 72,
                                                              fig.dpi_scale_trans))


def _nueva(ax, figsize):
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize, layout="constrained")
        return fig, ax
    return ax.figure, ax


def _leyenda_mecanismos(mecs, marcador=False, banda=False):
    h = []
    for m in mecs:
        h.append(Line2D([], [], color=_color_mecanismo(m), lw=1.5,
                        marker="o" if marcador else None, ms=4, label=NOMBRE_MECANISMO.get(m, m)))
    return h


def _sin_datos(ax, texto):
    ax.text(0.5, 0.5, texto, ha="center", va="center", transform=ax.transAxes, color=TINTA_2,
            fontsize=9, wrap=True)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)


def guardar(fig, nombre, carpeta, dpi=150):
    """Guarda ``fig`` como ``<carpeta>/<nombre>.png`` y devuelve la ruta."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{nombre}.png"
    fig.savefig(ruta, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    return ruta


# ============================================================================ panel del entorno

_CMAP_CELDAS = mcolors.ListedColormap([COLOR_CELDA[e] for e in ESTADOS_CELDA])
_NORM_CELDAS = mcolors.BoundaryNorm(np.arange(-0.5, 6.5, 1), _CMAP_CELDAS.N)


def estado_celdas(celdas, t):
    """Código de estado por celda en el paso t: 0 patio, 1 cabecera, 2 libre, 3 surcada,
    4 sembrada, 5 obstáculo (mismo orden que ESTADOS_CELDA)."""
    base = np.asarray(celdas["tipo_base"]).astype(np.int8)
    cod = base.copy()
    trabajo = base == TIPO_TRABAJO
    ts = np.asarray(celdas["t_surcado"])
    tm = np.asarray(celdas["t_sembrado"])
    cod[trabajo] = 2
    cod[trabajo & (ts >= 0) & (ts <= t)] = 3
    cod[trabajo & (tm >= 0) & (tm <= t)] = 4
    return cod


def fraccion_sembrada(celdas, t):
    base = np.asarray(celdas["tipo_base"])
    trabajo = base == TIPO_TRABAJO
    tm = np.asarray(celdas["t_sembrado"])
    n = int(trabajo.sum())
    return float(((tm >= 0) & (tm <= t) & trabajo).sum()) / n if n else 0.0


class _Recorridos:
    """Acceso rápido a la telemetría por tractor (arreglos ordenados por t)."""

    def __init__(self, pasos):
        self.agentes = sorted(pd.unique(pasos["agente"].astype(str)), key=_orden_agente)
        self.d = {}
        for a, g in pasos.groupby(pasos["agente"].astype(str), sort=False):
            g = g.sort_values("t")
            self.d[a] = {c: g[c].to_numpy() for c in g.columns}

    def en(self, a, t):
        d = self.d[a]
        i = int(np.searchsorted(d["t"], t, side="right")) - 1
        if i < 0:
            return None
        return {c: v[i] for c, v in d.items()}

    def tramo(self, a, t0, t1):
        d = self.d[a]
        m = (d["t"] > t0) & (d["t"] <= t1)
        return d["x"][m], d["y"][m]


def _marcador_rumbo(theta):
    th = int(round(_num(theta, 90) / 90.0)) % 4
    return {0: ">", 1: "^", 2: "<", 3: "v"}[th]


def _rol(rec, a):
    imps = [str(i) for i in pd.unique(rec.d[a]["implemento"]) if isinstance(i, str) and i]
    return " → ".join(imps) if imps else ""


def _base_mapa(ax, corrida, cod):
    campo = corrida["campo"]
    ancho, alto = int(campo["ancho"]), int(campo["alto"])
    im = ax.imshow(cod.T, origin="lower", cmap=_CMAP_CELDAS, norm=_NORM_CELDAS,
                   interpolation="nearest", extent=(-0.5, ancho - 0.5, -0.5, alto - 0.5))
    _rejilla_celdas(ax, ancho, alto)
    _deposito(ax, campo)
    _ejes_mapa(ax, campo)
    return im


def _rejilla_celdas(ax, ancho, alto):
    if max(ancho, alto) > 90:
        return
    lw = 0.35 if max(ancho, alto) <= 50 else 0.2
    xs = np.arange(-0.5, ancho, 1.0)
    ys = np.arange(-0.5, alto, 1.0)
    ax.vlines(xs, -0.5, alto - 0.5, colors=SUPERFICIE, linewidths=lw, alpha=0.55, zorder=1.5)
    ax.hlines(ys, -0.5, ancho - 0.5, colors=SUPERFICIE, linewidths=lw, alpha=0.55, zorder=1.5)


def _deposito(ax, campo):
    dx, dy = campo.get("deposito", [campo["ancho"] // 2, 0])
    ax.plot([dx], [dy], marker="s", ms=9, mfc="white", mec=TINTA, mew=1.3, ls="", zorder=6)


def _ejes_mapa(ax, campo):
    ancho, alto = int(campo["ancho"]), int(campo["alto"])
    celda = _num(campo.get("celda_m"), 10)
    ax.set_xlim(-0.5, ancho - 0.5)
    ax.set_ylim(-0.5, alto - 0.5)
    ax.set_aspect("equal")
    ax.grid(False)
    paso = 5 if ancho <= 30 else (10 if ancho <= 80 else 20)
    ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(paso))
    ax.yaxis.set_major_locator(mpl.ticker.MultipleLocator(paso))
    ax.set_xlabel(f"x (celdas de {celda:g} m, oeste → este)")
    ax.set_ylabel(f"y (celdas de {celda:g} m, sur → norte)")
    for s in ("left", "bottom"):
        ax.spines[s].set_visible(False)


def _handles_celdas(incluir=ESTADOS_CELDA):
    return [Patch(facecolor=COLOR_CELDA[e], edgecolor="none", label=NOMBRE_CELDA[e]) for e in incluir]


def _hay_falla(corrida):
    pasos = corrida.get("pasos")
    return pasos is not None and len(pasos) and (pasos["estado"].astype(str) == "fuera_servicio").any()


def _handles_tractores(estela=None, intencion=True, falla=False):
    h = [
        Line2D([], [], marker="^", ls="", ms=8, mfc="white", mec=TINTA, mew=1.2,
               label="Tractor con surcador (apunta al rumbo)"),
        Line2D([], [], marker="o", ls="", ms=7, mfc=TINTA, mec="white", mew=1.4,
               label="Tractor con sembradora"),
    ]
    if falla:
        h.append(Line2D([], [], marker="X", ls="", ms=8, mfc=TINTA_3, mec="white", mew=1.0,
                        label="Tractor fuera de servicio"))
    h.append(Line2D([], [], marker="s", ls="", ms=8, mfc="white", mec=TINTA, mew=1.3,
                    label="Depósito (estación de carga)"))
    if estela:
        h.append(Line2D([], [], color=TINTA, alpha=0.55, lw=1.3,
                        label=f"Trayectoria reciente ({estela} pasos)"))
    if intencion:
        h.append(Line2D([], [], color=TINTA, lw=0.9, ls=(0, (1, 2)),
                        label="Intención: celda objetivo"))
    return h


def _dibujar_tractores(ax, rec, t, estela, etiquetas="intencion", tam=1.0):
    artistas = []
    for a in rec.agentes:
        e = rec.en(a, t)
        if e is None:
            continue
        x, y = float(e["x"]), float(e["y"])
        if estela:
            xs, ys = rec.tramo(a, t - estela, t)
            if len(xs) > 1:
                (ln,) = ax.plot(xs, ys, color=TINTA, alpha=0.55, lw=1.3 * tam, zorder=4,
                                solid_capstyle="round")
                artistas.append(ln)
        estado = str(e.get("estado", ""))
        ox, oy = _num(e.get("objetivo_x"), -1), _num(e.get("objetivo_y"), -1)
        if etiquetas == "intencion" and ox >= 0 and oy >= 0 and abs(ox - x) + abs(oy - y) > 1 \
                and estado not in ("terminado", "fuera_servicio"):
            (ln,) = ax.plot([x, ox], [y, oy], color=TINTA, lw=0.9, ls=(0, (1, 2)), zorder=4)
            artistas.append(ln)
            (pt,) = ax.plot([ox], [oy], marker="x", ms=4 * tam, color=TINTA, mew=1.0, zorder=4)
            artistas.append(pt)
        implemento = str(e.get("implemento", ""))
        if estado == "fuera_servicio":
            (m,) = ax.plot([x], [y], marker="X", ms=9 * tam, mfc=TINTA_3, mec="white", mew=1.0,
                           ls="", zorder=7)
        elif implemento == "pipa":
            (m,) = ax.plot([x], [y], marker="D", ms=8 * tam, mfc=COLOR_PIPA, mec="white", mew=1.3,
                           ls="", zorder=7)
        elif implemento == "grua":
            (m,) = ax.plot([x], [y], marker="s", ms=8 * tam, mfc=COLOR_GRUA, mec=TINTA, mew=1.1,
                           ls="", zorder=7)
        elif implemento == "sembradora":
            (m,) = ax.plot([x], [y], marker="o", ms=7.5 * tam, mfc=TINTA, mec="white", mew=1.5,
                           ls="", zorder=7)
        else:
            (m,) = ax.plot([x], [y], marker=_marcador_rumbo(e.get("theta")), ms=8.5 * tam,
                           mfc="white", mec=TINTA, mew=1.2, ls="", zorder=7)
        artistas.append(m)
        if etiquetas:
            texto = a
            intencion = str(e.get("intencion", "") or "")
            if estado == "fuera_servicio":
                texto += " · fuera de servicio"
            elif implemento in ("pipa", "grua") and etiquetas == "intencion":
                texto += f" · {implemento} · {intencion}"
            elif etiquetas == "intencion" and intencion not in ("", "ninguna", "nan"):
                texto += f" · {intencion}"
            tx = ax.annotate(texto, (x, y), xytext=(6, 5), textcoords="offset points",
                             fontsize=7.5 * max(tam, 0.9), color=TINTA, zorder=8,
                             path_effects=_HALO)
            artistas.append(tx)
    artistas += _lineas_remolque(ax, rec, t)
    return artistas


def _lineas_remolque(ax, rec, t):
    """Línea entre un tractor con grúa y el tractor descompuesto que lleva a la estación."""
    actuales = {a: rec.en(a, t) for a in rec.agentes}
    gruas = [(a, e) for a, e in actuales.items()
             if e is not None and str(e.get("implemento", "")) == "grua" and str(e.get("intencion")) == "remolcar"]
    out = []
    for a, e in gruas:
        for b, f in actuales.items():
            if f is None or b == a or str(f.get("estado")) != "fuera_servicio":
                continue
            if abs(float(e["x"]) - float(f["x"])) + abs(float(e["y"]) - float(f["y"])) == 1:
                (ln,) = ax.plot([e["x"], f["x"]], [e["y"], f["y"]], color=COLOR_GRUA, lw=2.4, zorder=6.5)
                out.append(ln)
    return out


# ------------------------------------------------------------------ capa de eventos (M3)
def _hay_eventos(corrida):
    return corrida.get("eventos") is not None


def _zona_en(eventos, t):
    """Celdas de la zona prohibida vigente en el paso t (lista de [x, y])."""
    zona = []
    for z in eventos.get("zonas") or []:
        if z["t"] <= t:
            zona = z["celdas"]
        else:
            break
    return zona


def _mascaras_fuego(eventos, t):
    tq = np.asarray(eventos["t_quemado"])
    tf = np.asarray(eventos["t_fin_fuego"])
    ardiendo = (tq >= 0) & (tq <= t) & ((tf < 0) | (tf > t))
    quemada = (tq >= 0) & (tq <= t) & ~ardiendo
    return ardiendo, quemada


def _capa_eventos(ax, corrida, t):
    """Fuego, celdas quemadas, obstáculos nuevos y zona prohibida en el paso t. Devuelve los artistas."""
    ev = corrida.get("eventos")
    if not ev:
        return []
    campo = corrida["campo"]
    ancho, alto = int(campo["ancho"]), int(campo["alto"])
    arts = []
    ardiendo, quemada = _mascaras_fuego(ev, t)
    if ardiendo.any() or quemada.any():
        rgba = np.zeros((alto, ancho, 4))
        rgba[quemada.T] = mcolors.to_rgba(COLOR_QUEMADA)
        rgba[ardiendo.T] = mcolors.to_rgba(COLOR_FUEGO)
        arts.append(ax.imshow(rgba, origin="lower", interpolation="nearest", zorder=2,
                              extent=(-0.5, ancho - 0.5, -0.5, alto - 0.5)))
    for (x, y, w, h, t0) in ev.get("obstaculos_nuevos") or []:
        if t0 <= t:
            arts.append(ax.add_patch(Rectangle((x - 0.5, y - 0.5), w, h, facecolor=COLOR_CELDA["obstaculo"],
                                               edgecolor=COLOR_ZONA, lw=1.4, zorder=2.5)))
    zona = _zona_en(ev, t)
    if zona:
        pc = PatchCollection([Rectangle((x - 0.5, y - 0.5), 1, 1) for x, y in zona], facecolor="none",
                             edgecolor=COLOR_ZONA, linewidth=0.5, hatch="////", alpha=0.75, zorder=2.6)
        arts.append(ax.add_collection(pc))
    return arts


def _handles_eventos(corrida):
    ev = corrida.get("eventos")
    if not ev:
        return []
    h = []
    tq = np.asarray(ev.get("t_quemado", []))
    if tq.size and (tq >= 0).any():
        h += [Patch(facecolor=COLOR_FUEGO, label="Arde"), Patch(facecolor=COLOR_QUEMADA, label="Quemada")]
    if ev.get("obstaculos_nuevos"):
        h.append(Patch(facecolor=COLOR_CELDA["obstaculo"], edgecolor=COLOR_ZONA, label="Obstáculo nuevo"))
    if ev.get("zonas"):
        h.append(Patch(facecolor="none", edgecolor=COLOR_ZONA, hatch="////", label="Zona prohibida"))
    pasos = corrida.get("pasos")
    imps = set(pasos["implemento"].astype(str)) if pasos is not None and len(pasos) else set()
    if "pipa" in imps:
        h.append(Line2D([], [], marker="D", ls="", ms=7, mfc=COLOR_PIPA, mec="white", label="Tractor con pipa de agua"))
    if "grua" in imps:
        h.append(Line2D([], [], marker="s", ls="", ms=7, mfc=COLOR_GRUA, mec=TINTA, label="Tractor con grúa"))
    return h


def registro_coordinador(corrida, solo_coordinador=False, tipos=None):
    """Tabla del registro de M3 (eventos del mundo, avisos y decisiones del coordinador con su motivo).

    Columnas — ``t``, ``hora`` (h desde el inicio), ``fuente``, ``tipo``, ``tractor``, ``texto``, ``motivo``."""
    reg = corrida.get("registro")
    if reg is None or len(reg) == 0:
        return pd.DataFrame(columns=["t", "hora", "fuente", "tipo", "tractor", "texto", "motivo"])
    reg = pd.DataFrame(reg).copy()
    if solo_coordinador:
        reg = reg[reg["fuente"] == "coordinador"]
    if tipos is not None:
        reg = reg[reg["tipo"].isin(list(tipos))]
    reg.insert(1, "hora", (reg["t"].astype(float) * _paso_h(corrida.get("resumen", {}))).round(2))
    return reg[["t", "hora", "fuente", "tipo", "tractor", "texto", "motivo"]].reset_index(drop=True)


def _lineas_registro(corrida, t, n=9, ancho=78):
    reg = corrida.get("registro")
    if reg is None or len(reg) == 0:
        return ""
    reg = pd.DataFrame(reg)
    ruido = (reg["tipo"] == "subasta") | ((reg["tipo"] == "aviso") & reg["evento"].isin(["reporte", "latido", "incendio"]))
    reg = reg[(reg["t"] <= t) & ~ruido].tail(n)
    paso_h = _paso_h(corrida.get("resumen", {}))
    lineas = []
    for _i, f in reg.iterrows():
        marca = "•" if f["fuente"] == "mundo" else ("»" if f["tipo"] in ("decision", "plan") else "·")
        texto = f"{marca} {float(f['t']) * paso_h:5.1f} h  {f['texto']}"
        lineas.append(textwrap.shorten(texto, ancho, placeholder="…"))
    return "\n".join(lineas)


def mapa_campo(ax, corrida, t=None, estela=None, etiquetas="intencion", leyenda=True, titulo=None):
    """Estado de cada celda en el paso ``t`` con tractores, estela e intención.

    ``etiquetas``: ``"intencion"`` (T1 · sembrar), ``"nombre"`` (T1) o ``None``.
    """
    campo = corrida["campo"]
    prop = campo["alto"] / campo["ancho"]
    fig, ax = _nueva(ax, (9.6, 5.4 * prop + 1.3))
    t = _t_final(corrida) if t is None else int(t)
    alto = int(campo["alto"])
    estela = int(1.5 * alto) if estela is None else int(estela)
    cod = estado_celdas(corrida["celdas"], t)
    _base_mapa(ax, corrida, cod)
    _capa_eventos(ax, corrida, t)
    pasos = corrida.get("pasos")
    if pasos is not None and len(pasos):
        _dibujar_tractores(ax, _Recorridos(pasos), t, estela, etiquetas)
    r = corrida.get("resumen", {})
    h = t * _paso_h(r)
    pct = fraccion_sembrada(corrida["celdas"], t) * 100
    if titulo is None:
        titulo = f"Estado del campo en el paso {t:,} · {h:.1f} h · {pct:.0f} % sembrado"
    _titulo_ax(ax, titulo, _texto_corrida(corrida) if titulo else None)
    if leyenda:
        incluir = [e for e in ESTADOS_CELDA if e != "obstaculo" or (cod == 5).any()]
        ax.legend(handles=_handles_celdas(incluir)
                  + _handles_tractores(estela, etiquetas == "intencion", _hay_falla(corrida))
                  + _handles_eventos(corrida),
                  loc="upper left", bbox_to_anchor=(1.02, 1.0), title="Estado de celda y agentes",
                  alignment="left")
    return fig


def secuencia_estados(corrida, fracciones=(0.25, 0.5, 0.75, 1.0), fig=None):
    """Pequeños múltiplos del mapa del campo en fracciones del tiempo total de siembra."""
    T = _t_siembra_final(corrida)
    n = len(fracciones)
    campo = corrida["campo"]
    proporcion = campo["alto"] / campo["ancho"]
    if fig is None:
        ancho_fig = 3.3 * n
        panel = (ancho_fig - 0.7) / n - 0.1
        fig = plt.figure(figsize=(ancho_fig, panel * proporcion + 1.45), layout="constrained")
    axs = fig.subplots(1, n, sharex=True, sharey=True, squeeze=False)[0]
    r = corrida.get("resumen", {})
    pasos = corrida.get("pasos")
    rec = _Recorridos(pasos) if pasos is not None and len(pasos) else None
    for ax, f in zip(axs, fracciones):
        t = int(round(f * T))
        cod = estado_celdas(corrida["celdas"], t)
        _base_mapa(ax, corrida, cod)
        if rec is not None:
            _dibujar_tractores(ax, rec, t, int(1.5 * campo["alto"]), "nombre", tam=0.85)
        pct = fraccion_sembrada(corrida["celdas"], t) * 100
        ax.set_title(f"{t * _paso_h(r):.1f} h · {pct:.0f} % sembrado", fontsize=10)
        ax.set_xlabel("x (celdas)")
        ax.set_ylabel("y (celdas)" if ax is axs[0] else "")
    hay_obst = (np.asarray(corrida["celdas"]["tipo_base"]) == TIPO_OBSTACULO).any()
    incluir = [e for e in ESTADOS_CELDA if e != "obstaculo" or hay_obst]
    tr = _handles_tractores(None, False, _hay_falla(corrida))
    fig.legend(handles=_handles_celdas(incluir) + tr, loc="outside lower center",
               ncols=math.ceil((len(incluir) + len(tr)) / 2))
    _titulo_fig(fig, "Secuencia de estados del campo (25, 50, 75 y 100 % del tiempo de siembra)",
                _texto_corrida(corrida))
    return fig


def animacion(corrida, n_cuadros=80, dpi=80, intervalo_ms=120, estela=None):
    """``FuncAnimation`` paso a paso de la corrida (para ``to_jshtml()`` o ``guardar_gif``).

    Recorre el tiempo de 0 al último paso en ``n_cuadros`` cuadros equiespaciados."""
    campo = corrida["campo"]
    T = _t_final(corrida)
    ts = np.unique(np.linspace(0, T, int(n_cuadros)).round().astype(int))
    alto = int(campo["alto"])
    estela = int(1.5 * alto) if estela is None else int(estela)
    r = corrida.get("resumen", {})
    proporcion = campo["alto"] / campo["ancho"]
    con_registro = corrida.get("registro") is not None and len(corrida["registro"]) > 0
    if con_registro:
        # M3 — a la derecha va la leyenda y, debajo, los últimos avisos y decisiones del coordinador
        fig = plt.figure(figsize=(13.0, max(6.8, 5.6 * proporcion + 1.2)), dpi=dpi)
        ax = fig.add_axes((0.045, 0.08, 0.44, 0.8))
    else:
        fig = plt.figure(figsize=(8.0, 4.4 * proporcion + 1.2), dpi=dpi)
        ax = fig.add_axes((0.075, 0.1, 0.55, 0.74))
    cod = estado_celdas(corrida["celdas"], ts[0])
    im = _base_mapa(ax, corrida, cod)
    hay_obst = (np.asarray(corrida["celdas"]["tipo_base"]) == TIPO_OBSTACULO).any()
    incluir = [e for e in ESTADOS_CELDA if e != "obstaculo" or hay_obst]
    ax.legend(handles=_handles_celdas(incluir) + _handles_tractores(estela, True, _hay_falla(corrida))
              + _handles_eventos(corrida),
              loc="upper left", bbox_to_anchor=(1.03, 1.0), fontsize=8, ncols=2 if con_registro else 1)
    texto_reg = None
    if con_registro:
        fig.text(0.52, 0.42, "Registro (• mundo · » decisión del coordinador)", fontsize=8.5,
                 fontweight="semibold", color=TINTA, va="bottom")
        texto_reg = fig.text(0.52, 0.405, "", fontsize=7.4, color=TINTA, va="top", family="DejaVu Sans Mono")
    titulo = ax.set_title("", loc="left", pad=20, fontsize=11, fontweight="semibold")
    ax.annotate(_texto_corrida(corrida), xy=(0, 1), xycoords="axes fraction", xytext=(0, 6),
                textcoords="offset points", fontsize=7.5, color=TINTA_2, va="bottom")
    pasos = corrida.get("pasos")
    rec = _Recorridos(pasos) if pasos is not None and len(pasos) else None
    dinamicos = []

    def cuadro(i):
        for a in dinamicos:
            a.remove()
        dinamicos.clear()
        t = int(ts[i])
        im.set_data(estado_celdas(corrida["celdas"], t).T)
        dinamicos.extend(_capa_eventos(ax, corrida, t))
        if rec is not None:
            dinamicos.extend(_dibujar_tractores(ax, rec, t, estela, "intencion"))
        if texto_reg is not None:
            texto_reg.set_text(_lineas_registro(corrida, t))
        pct = fraccion_sembrada(corrida["celdas"], t) * 100
        titulo.set_text(f"Paso {t:,} · {t * _paso_h(r):.1f} h · {pct:.0f} % sembrado")
        return [im, titulo, *dinamicos]

    anim = animation.FuncAnimation(fig, cuadro, frames=len(ts), interval=intervalo_ms, blit=False,
                                   repeat=True)
    return anim


def animacion_html(anim, dpi=60, default_mode="once"):
    """HTML con controles (``to_jshtml``) a resolución baja para no inflar el notebook.

    ``to_jshtml`` usa ``savefig.dpi`` y no el dpi de la figura, así que se fija aquí. Además
    guarda en caché el HTML de la primera llamada; se descarta para que ``dpi`` siempre aplique."""
    anim.__dict__.pop("_html_representation", None)
    with mpl.rc_context({"savefig.dpi": dpi}):
        return anim.to_jshtml(default_mode=default_mode)


def guardar_gif(anim, ruta, fps=10, dpi=None):
    """Guarda la animación como GIF con PillowWriter y devuelve la ruta (``dpi`` por defecto el
    de la figura de la animación)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    anim.save(str(ruta), writer=animation.PillowWriter(fps=fps), dpi=dpi or anim._fig.dpi)
    return ruta


def _fondo_neutro(ax, corrida):
    """Mapa base sin estados (para trayectorias): obstáculos oscuros, cabeceras y patio tenues."""
    campo = corrida["campo"]
    base = np.asarray(corrida["celdas"]["tipo_base"])
    colores = {TIPO_PATIO: "#ebeae4", TIPO_CABECERA: "#e4e3dc", TIPO_TRABAJO: SUPERFICIE,
               TIPO_OBSTACULO: COLOR_CELDA["obstaculo"]}
    rgb = np.zeros(base.shape + (3,))
    for k, c in colores.items():
        rgb[base == k] = mcolors.to_rgb(c)
    ancho, alto = int(campo["ancho"]), int(campo["alto"])
    ax.imshow(np.transpose(rgb, (1, 0, 2)), origin="lower", interpolation="nearest",
              extent=(-0.5, ancho - 0.5, -0.5, alto - 0.5))
    _deposito(ax, campo)
    _ejes_mapa(ax, campo)


def _trayectoria(ax, d, t_fin, lw=1.1):
    m = d["t"] <= t_fin
    x, y = d["x"][m].astype(float), d["y"][m].astype(float)
    grupos = np.array([GRUPO_DE_ESTADO.get(str(e)) for e in d["estado"][m]], dtype=object)
    if len(x) < 2:
        return
    mov = (np.abs(np.diff(x)) + np.abs(np.diff(y))) > 0
    segs = np.stack([np.column_stack([x[:-1], y[:-1]]), np.column_stack([x[1:], y[1:]])], axis=1)
    cols = [COLOR_ACTIVIDAD.get(g, TINTA_3) for g in grupos[1:]]
    segs, cols = segs[mov], [c for c, k in zip(cols, mov) if k]
    ax.add_collection(LineCollection(segs, colors=cols, linewidths=lw, zorder=3,
                                     capstyle="round", joinstyle="round"))
    quieto = ~np.concatenate([[True], mov])
    for g in ("Estación", "Esperas", "Ocio"):
        sel = quieto & (grupos == g)
        if sel.any():
            pts = np.unique(np.column_stack([x[sel], y[sel]]), axis=0)
            ax.scatter(pts[:, 0], pts[:, 1], s=16, color=COLOR_ACTIVIDAD[g], edgecolors=TINTA_2,
                       linewidths=0.4, zorder=5)
    falla = np.array([str(e) == "fuera_servicio" for e in d["estado"][m]])
    if falla.any():
        i = int(np.argmax(falla))
        ax.plot([x[i]], [y[i]], marker="X", ms=9, mfc=TINTA_3, mec="white", mew=1.0, ls="", zorder=6)


def mapa_trayectorias(ax, corrida, t_fin=None):
    """Recorrido completo de cada tractor, coloreado por grupo de actividad.

    Con ``ax=None`` dibuja un panel por tractor (pequeños múltiplos); con un ``ax`` dibuja a
    todos los tractores en el mismo panel.
    """
    pasos = corrida["pasos"]
    rec = _Recorridos(pasos)
    t_fin = _t_final(corrida) if t_fin is None else t_fin
    campo = corrida["campo"]
    proporcion = campo["alto"] / campo["ancho"]
    if ax is None:
        n = len(rec.agentes)
        ncols = min(n, 4)
        nrows = math.ceil(n / ncols)
        ancho_fig = 3.6 * ncols + 0.6
        panel = (ancho_fig - 0.7) / ncols - 0.1
        fig = plt.figure(figsize=(ancho_fig, (panel * proporcion + 0.75) * nrows + 0.7),
                         layout="constrained")
        axs = fig.subplots(nrows, ncols, sharex=True, sharey=True, squeeze=False).ravel()
        for i, a in enumerate(rec.agentes):
            axi = axs[i]
            _fondo_neutro(axi, corrida)
            _trayectoria(axi, rec.d[a], t_fin)
            d = rec.d[a]
            m = d["t"] <= t_fin
            dist = int((np.abs(np.diff(d["x"][m])) + np.abs(np.diff(d["y"][m]))).sum())
            titulo_a = f"{a} · {_rol(rec, a)} · {dist:,} celdas recorridas"
            fs = d["t"][(d["estado"].astype(str) == "fuera_servicio")]
            if len(fs):
                titulo_a += f"\nfuera de servicio desde {fs.min() * _paso_h(corrida.get('resumen', {})):.1f} h"
            axi.set_title(titulo_a, fontsize=9.5)
            if i % ncols:
                axi.set_ylabel("")
            if i < (nrows - 1) * ncols:
                axi.set_xlabel("")
        for axi in axs[len(rec.agentes):]:
            axi.set_visible(False)
        manejar = fig.legend
        kw = {"loc": "outside lower center", "ncols": 6}
    else:
        fig = ax.figure
        _fondo_neutro(ax, corrida)
        for a in rec.agentes:
            _trayectoria(ax, rec.d[a], t_fin)
        manejar = ax.legend
        kw = {"loc": "upper left", "bbox_to_anchor": (1.02, 1.0)}
    handles = [Line2D([], [], color=COLOR_ACTIVIDAD[g], lw=1.5, label=f"{g} (en movimiento)")
               for g in ("Trabajando", "Traslado")]
    handles += [Line2D([], [], marker="o", ls="", ms=5, mfc=COLOR_ACTIVIDAD[g], mec=TINTA_2,
                       mew=0.4, label=f"{g} (detenido)") for g in ("Estación", "Esperas", "Ocio")]
    fuera = set(pasos["estado"].astype(str)) - set(GRUPO_DE_ESTADO)
    if fuera & {"terminado"}:
        handles.append(Line2D([], [], color=TINTA_3, lw=1.5, label="Terminado (va a estacionarse)"))
    if "fuera_servicio" in fuera:
        handles.append(Line2D([], [], marker="X", ls="", ms=8, mfc=TINTA_3, mec="white", mew=1.0,
                              label="Queda fuera de servicio"))
    handles += [Line2D([], [], marker="s", ls="", ms=7, mfc="white", mec=TINTA, mew=1.2,
                       label="Depósito")]
    if ax is None:
        kw["ncols"] = math.ceil(len(handles) / (1 if len(handles) <= 6 else 2))
    manejar(handles=handles, **kw)
    titulo = "Trayectorias completas por tractor, coloreadas por actividad"
    if ax is None:
        _titulo_fig(fig, titulo, _texto_corrida(corrida))
    else:
        _titulo_ax(ax, titulo, _texto_corrida(corrida))
    return fig


def _imagen_magnitud(ax, corrida, valores, mascara_libre, cmap, norm, etiqueta_barra, extend,
                     barra=True):
    campo = corrida["campo"]
    base = np.asarray(corrida["celdas"]["tipo_base"])
    ancho, alto = int(campo["ancho"]), int(campo["alto"])
    ext = (-0.5, ancho - 0.5, -0.5, alto - 0.5)
    # Capa de fondo con los colores base para lo que no tiene valor
    fondo = np.zeros(base.shape + (4,))
    fondo[base == TIPO_PATIO] = mcolors.to_rgba(COLOR_CELDA["patio"])
    fondo[base == TIPO_CABECERA] = mcolors.to_rgba(COLOR_CELDA["cabecera"])
    fondo[base == TIPO_OBSTACULO] = mcolors.to_rgba(COLOR_CELDA["obstaculo"])
    if mascara_libre is not None:
        fondo[mascara_libre] = mcolors.to_rgba(COLOR_CELDA["libre"])
    ax.imshow(np.transpose(fondo, (1, 0, 2)), origin="lower", interpolation="nearest", extent=ext)
    vals = np.ma.masked_invalid(valores.astype(float))
    im = ax.imshow(vals.T, origin="lower", cmap=cmap, norm=norm, interpolation="nearest", extent=ext)
    _rejilla_celdas(ax, ancho, alto)
    _deposito(ax, campo)
    _ejes_mapa(ax, campo)
    if barra:
        _barra_color(im, ax, etiqueta_barra, extend)
    return im


def _barra_color(im, ax, etiqueta, extend="neither"):
    fig = im.axes.figure
    cb = fig.colorbar(im, ax=ax, shrink=0.85, pad=0.02, extend=extend)
    cb.set_label(etiqueta, color=TINTA_2)
    cb.outline.set_visible(False)
    cb.ax.tick_params(color=EJE, labelcolor=TINTA_2)
    return cb


_CMAP_AZULES = mcolors.LinearSegmentedColormap.from_list("azules", AZULES)
_CMAP_VERDES = mcolors.LinearSegmentedColormap.from_list("verdes", VERDES)


def _pasadas(corrida):
    cel = corrida["celdas"]
    p = np.asarray(cel["pasadas"]).astype(float)
    p[np.asarray(cel["tipo_base"]) == TIPO_OBSTACULO] = np.nan
    return p


def _dias_siembra(corrida):
    """(días desde la fecha óptima por celda sembrada, máscara de celdas de trabajo sin sembrar)."""
    cel = corrida["celdas"]
    r = corrida.get("resumen", {})
    base = np.asarray(cel["tipo_base"])
    tm = np.asarray(cel["t_sembrado"]).astype(float)
    trabajo = base == TIPO_TRABAJO
    sembrada = trabajo & (tm >= 0)
    dias_lab = _num(r.get("dias_laborables"), 1.0) or 1.0
    dias = np.where(sembrada, tm / _pasos_dia(r) / dias_lab, np.nan)
    return dias, trabajo & ~sembrada


def _tam_mapa_calor(corrida):
    prop = corrida["campo"]["alto"] / corrida["campo"]["ancho"]
    return (7.0, 5.2 * prop + 1.7)


def mapa_pasadas(ax, corrida, titulo=True):
    """Mapa de calor de pasadas por celda (compactación del suelo), en azules."""
    fig, ax = _nueva(ax, _tam_mapa_calor(corrida))
    base = np.asarray(corrida["celdas"]["tipo_base"])
    p = _pasadas(corrida)
    vmax = max(1.0, float(np.nanpercentile(p, 99)))
    extend = "max" if np.nanmax(p) > vmax else "neither"
    _imagen_magnitud(ax, corrida, p, None, _CMAP_AZULES, mcolors.Normalize(0, vmax),
                     "Pasadas por celda (entradas de tractor)", extend)
    if titulo:
        trabajo = base == TIPO_TRABAJO
        media = float(np.nanmean(p[trabajo])) if trabajo.any() else np.nan
        sub = _texto_corrida(corrida)
        _titulo_ax(ax, f"Compactación: pasadas por celda (media en el área de trabajo {media:.1f})",
                   sub, tam=10.5)
    _leyenda_sin_valor(ax, False, (base == TIPO_OBSTACULO).any())
    return fig


def mapa_edad(ax, corrida, titulo=True):
    """Día de siembra de cada celda en días desde la fecha óptima (verdes)."""
    fig, ax = _nueva(ax, _tam_mapa_calor(corrida))
    r = corrida.get("resumen", {})
    base = np.asarray(corrida["celdas"]["tipo_base"])
    dias, sin_sembrar = _dias_siembra(corrida)
    vmax = float(np.nanmax(dias)) if np.isfinite(dias).any() else 1.0
    _imagen_magnitud(ax, corrida, dias, sin_sembrar, _CMAP_VERDES, mcolors.Normalize(0, max(vmax, 1e-6)),
                     "Día de siembra (días desde la fecha óptima)", "neither")
    if titulo:
        disp = _num(r.get("dispersion_dias"))
        extra = f" (dispersión {disp:.2f} jornadas)" if not np.isnan(disp) else ""
        _titulo_ax(ax, f"Edad del cultivo: día de siembra por celda{extra}", _texto_corrida(corrida),
                   tam=10.5)
    _leyenda_sin_valor(ax, sin_sembrar.any(), (base == TIPO_OBSTACULO).any())
    return fig


def _leyenda_sin_valor(ax, no_sembrada, obstaculo):
    """Leyenda de las celdas sin valor en un mapa de calor. Va como leyenda de la figura cuando
    el mapa es el único panel (una leyenda debajo de un eje con aspecto fijo puede hacer que
    constrained_layout colapse) y debajo del eje si el mapa está dentro de otra figura."""
    handles = []
    if no_sembrada:
        handles.append(Patch(facecolor=COLOR_CELDA["libre"], label="No sembrada"))
    if obstaculo:
        handles += _handles_celdas(["obstaculo"])
    if not handles:
        return
    fig = ax.figure
    if len([a for a in fig.axes if a.get_label() != "<colorbar>"]) == 1:
        fig.legend(handles=handles, loc="outside lower left", ncols=2)
    else:
        ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0, -0.12), ncols=2)


def mapas_comparados(corridas, tipo="pasadas", fig=None):
    """Pequeños múltiplos de pasadas (``tipo="pasadas"``) o de día de siembra (``"edad"``) para
    varias corridas, con una sola escala de color compartida para poder compararlas."""
    corridas = _como_lista(corridas)
    n = len(corridas)
    prop = max(c["campo"]["alto"] / c["campo"]["ancho"] for c in corridas)
    if fig is None:
        ancho_fig = 3.5 * n + 1.3
        panel = (ancho_fig - 1.9) / n - 0.1
        fig = plt.figure(figsize=(ancho_fig, panel * prop + 1.45), layout="constrained")
    axs = fig.subplots(1, n, squeeze=False)[0]
    if tipo == "pasadas":
        valores = [_pasadas(c) for c in corridas]
        libres = [None] * n
        vmax = max(1.0, max(float(np.nanpercentile(v, 99)) for v in valores))
        extend = "max" if max(float(np.nanmax(v)) for v in valores) > vmax else "neither"
        cmap, etiqueta = _CMAP_AZULES, "Pasadas por celda (entradas de tractor)"
        titulo = "¿Dónde se concentra el desgaste? Pasadas por celda (compactación)"
    elif tipo == "edad":
        pares = [_dias_siembra(c) for c in corridas]
        valores, libres = [p[0] for p in pares], [p[1] for p in pares]
        vmax = max([float(np.nanmax(v)) for v in valores if np.isfinite(v).any()] or [1.0])
        extend, cmap = "neither", _CMAP_VERDES
        etiqueta = "Día de siembra (días desde la fecha óptima)"
        titulo = "¿Dónde se concentra la desigualdad? Día de siembra de cada celda (edad del cultivo)"
    else:
        raise ValueError("tipo debe ser 'pasadas' o 'edad'")
    norm = mcolors.Normalize(0, max(vmax, 1e-6))
    im = None
    for ax, c, v, lib in zip(axs, corridas, valores, libres):
        im = _imagen_magnitud(ax, c, v, lib, cmap, norm, etiqueta, extend, barra=False)
        r = c.get("resumen", {})
        if tipo == "pasadas":
            trabajo = np.asarray(c["celdas"]["tipo_base"]) == TIPO_TRABAJO
            dato = f"media en trabajo {np.nanmean(v[trabajo]):.2f}"
        else:
            dato = f"dispersión {_num(r.get('dispersion_dias')):.2f} jornadas"
        ax.set_title(f"{_etiqueta_corrida(c)}\n{dato}", fontsize=9.5)
        if ax is not axs[0]:
            ax.set_ylabel("")
        ax.set_xlabel("x (celdas)")
    _barra_color(im, list(axs), etiqueta, extend)
    obst = any((np.asarray(c["celdas"]["tipo_base"]) == TIPO_OBSTACULO).any() for c in corridas)
    nos = any(l is not None and l.any() for l in libres)
    handles = ([Patch(facecolor=COLOR_CELDA["libre"], label="No sembrada")] if nos else []) + \
              (_handles_celdas(["obstaculo"]) if obst else [])
    if handles:
        fig.legend(handles=handles, loc="outside lower left", ncols=2)
    escs = {escenario_de(c) for c in corridas}
    sub = "Misma escala de color en todos los paneles"
    if len(escs) == 1:
        r0 = {k: v for k, v in corridas[0].get("resumen", {}).items() if k not in ("mecanismo",)}
        sub = texto_parametros(r0, escs.pop()) + " · " + sub.lower()
    _titulo_fig(fig, titulo, sub)
    return fig


# ======================================================================== panel de indicadores

def _tarjeta(ax, etiqueta, valor, sub="", heroe=False):
    ax.set_axis_off()
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.03",
                                transform=ax.transAxes, facecolor=FONDO_TARJETA, edgecolor="none",
                                clip_on=False))
    kw = {"transform": ax.transAxes, "ha": "left", "parse_math": False}
    ax.text(0.07, 0.88 if not heroe else 0.95, etiqueta, va="top", fontsize=9.5 if not heroe else 11,
            color=TINTA_2, **kw)
    ax.text(0.07, 0.5 if not heroe else 0.8, valor, va="center",
            fontsize=21 if not heroe else 32, fontweight="semibold", color=TINTA, **kw)
    if sub:
        ax.text(0.07, 0.1 if not heroe else 0.05, sub, va="bottom", fontsize=8 if not heroe else 8.5,
                color=TINTA_2, linespacing=1.45, **kw)


def tarjetas_kpi(resumen, escenario=None, fig=None):
    """Tarjetas de número grande con los indicadores de una corrida (resumen del contrato)."""
    r = resumen or {}
    g = lambda k: _num(r.get(k))
    ha_s = g("ha_sembrables")
    j_ha = g("J") / ha_s if ha_s and not np.isnan(ha_s) else np.nan
    prop_ha = g("costo_propiedad") / ha_s if ha_s and not np.isnan(ha_s) else np.nan
    jornada = g("jornada_h")
    tarjetas = [
        ("Tiempo total T", _fmt(g("T_h"), 1, sufijo=" h"),
         f"{_fmt(g('T_dias'), 2)} jornadas de {_fmt(jornada, 0)} h"),
        ("Cobertura", _fmt(g("cobertura") * 100, 1, sufijo=" %"),
         f"{_fmt(g('n_sembradas'), 0)} de {_fmt(g('n_celdas_trabajo'), 0)} celdas sembradas"),
        ("Colisiones", _fmt(g("colisiones"), 0),
         f"intercambios {_fmt(g('intercambios'), 0)} · vetos {_fmt(g('vetos'), 0)}"),
        ("Sembrado dentro de la ventana", _fmt(g("pct_en_ventana") * 100, 1, sufijo=" %"),
         "del área de trabajo"),
        ("Tiempo ocioso W_ocio", _fmt(g("W_ocio_h"), 2, sufijo=" h"),
         f"h-tractor sin tarea o negociando\n(negociación {_fmt(g('W_negociacion_h'), 2)} h)"),
        ("Espera en la estación W_espera", _fmt(g("W_espera_h"), 2, sufijo=" h"),
         "h-tractor en la fila del depósito"),
        ("Espera por conflicto W_conflicto", _fmt(g("W_conflicto_h"), 2, sufijo=" h"),
         f"h-tractor esperando celda\n(por surco {_fmt(g('W_precedencia_h'), 2)} h)"),
        ("Mensajes de negociación", _fmt(g("mensajes_total"), 0),
         f"perdidos {_fmt(g('mensajes_perdidos'), 0)} · subastas {_fmt(g('subastas'), 0)}"
         f"\nreanuncios {_fmt(g('reanuncios'), 0)}"),
        ("Dispersión de siembra", _fmt(g("dispersion_dias"), 2, sufijo=" jornadas"),
         "entre la primera y la última celda"),
        ("Diésel", _fmt(g("diesel_l"), 0, sufijo=" L"),
         f"{_dinero(g('costo_diesel'))} · {_fmt(g('H_motor_h'), 1)} h de motor"),
        ("Eficiencia de campo", _fmt(g("eficiencia_campo") * 100, 1, sufijo=" %"),
         "pasos trabajando ÷ pasos activos\n(ASABE: 50 a 75 % en sembradoras)"),
        ("Tiempo de cómputo", _fmt(g("tiempo_computo_s"), 1, sufijo=" s"),
         f"{_fmt(g('pasos_simulados'), 0)} pasos simulados"),
    ]
    if fig is None:
        fig = plt.figure(figsize=(14, 6.2), layout="constrained")
        fig.get_layout_engine().set(w_pad=0.06, h_pad=0.06, wspace=0.02, hspace=0.02)
    gs = fig.add_gridspec(3, 5, width_ratios=[1.35, 1, 1, 1, 1])
    heroe = fig.add_subplot(gs[:, 0])
    _tarjeta(heroe, "Costo por hectárea", _dinero(g("costo_ha")) + "/ha",
             f"propiedad de la flota {_dinero(prop_ha)}/ha"
             f"\n+ operación J {_dinero(j_ha)}/ha"
             f"\nsobre {_fmt(ha_s, 2)} ha sembrables"
             f"\n\nDesglose de J ($ por corrida)"
             f"\nretraso de siembra (R)  {_dinero(g('costo_R'))}"
             f"\nreparación por horas (H)  {_dinero(g('costo_H'))}"
             f"\ndiésel  {_dinero(g('costo_diesel'))}"
             f"\ncolisiones  {_dinero(g('costo_colisiones'))}"
             f"\nsuperficie no sembrada  {_dinero(g('costo_no_sembrada'))}", heroe=True)
    for i, (et, val, sub) in enumerate(tarjetas):
        ax = fig.add_subplot(gs[i // 4, 1 + i % 4])
        _tarjeta(ax, et, val, sub)
    estado = " · terminó por estancamiento o límite de pasos" if _bool(r.get("estancado")) else ""
    _titulo_fig(fig, "Indicadores de la corrida", texto_parametros(r, escenario) + estado)
    return fig


def horas_por_actividad(pasos, resumen):
    """Horas-tractor por (agente, grupo de actividad) hasta T_pasos."""
    T = _num(resumen.get("T_pasos"), np.inf)
    if T < 0:
        T = np.inf
    p = pasos[pasos["t"] <= T]
    grupo = p["estado"].astype(str).map(GRUPO_DE_ESTADO)
    tabla = (p.assign(grupo=grupo).dropna(subset=["grupo"])
             .groupby(["agente", "grupo"]).size().unstack(fill_value=0))
    tabla = tabla.reindex(columns=list(GRUPOS_ACTIVIDAD), fill_value=0) * _paso_h(resumen)
    return tabla.reindex(sorted(tabla.index, key=_orden_agente))


def _barras_apiladas(ax, tabla, columnas, colores, etiquetas_y, unidad=""):
    """Barras horizontales apiladas (una por fila de ``tabla``) con 2 px de separación entre
    segmentos y el total al final de cada barra."""
    n = len(tabla)
    y = np.arange(n)[::-1]
    izq = np.zeros(n)
    for col, color in zip(columnas, colores):
        v = tabla[col].to_numpy(dtype=float)
        ax.barh(y, v, left=izq, height=0.62, color=color, edgecolor=SUPERFICIE, linewidth=1.5,
                label=col)
        izq += v
    for yi, tot in zip(y, izq):
        ax.annotate(f"{tot:,.1f}{unidad}", (tot, yi), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=8.5, color=TINTA_2)
    ax.set_yticks(y, etiquetas_y)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(-0.6, n - 0.4)
    return izq


def barras_actividad(ax, pasos, resumen, titulo=True):
    """Horas por tractor apiladas por grupo de actividad (hasta T)."""
    tabla = horas_por_actividad(pasos, resumen)
    n = len(tabla)
    fig, ax = _nueva(ax, (8.5, 1.2 + 0.55 * n))
    rec = _Recorridos(pasos)
    izq = _barras_apiladas(ax, tabla, list(GRUPOS_ACTIVIDAD),
                           [COLOR_ACTIVIDAD[g] for g in GRUPOS_ACTIVIDAD],
                           [f"{a} · {_rol(rec, a)}" if a in rec.d else a for a in tabla.index], " h")
    ax.set_xlabel("Horas-tractor (h)")
    ax.set_xlim(0, max(izq.max(), 1e-9) * 1.12)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncols=5, handlelength=1.2,
              borderaxespad=0.2)
    if titulo:
        T_h = _num(resumen.get("T_h"))
        sub = texto_parametros(resumen)
        fuera = pasos[pasos["estado"].astype(str) == "fuera_servicio"]
        if len(fuera):
            ini = fuera.groupby("agente")["t"].min()
            sub += " · " + ", ".join(f"{a} fuera de servicio desde {t * _paso_h(resumen):.1f} h"
                                     for a, t in ini.items()) + " (no se grafica)"
        _titulo_ax(ax, f"Horas por tractor según actividad (hasta T = {T_h:,.1f} h)", sub, tam=10.5,
                   extra=22)
    return fig


def _texto_fuera_servicio(corrida):
    pasos = corrida["pasos"]
    fuera = pasos[pasos["estado"].astype(str) == "fuera_servicio"]
    if not len(fuera):
        return ""
    ini = fuera.groupby("agente")["t"].min()
    return " · " + ", ".join(f"{a} fuera de servicio desde {t * _paso_h(corrida['resumen']):.1f} h"
                             for a, t in ini.items())


def actividad_comparada(corridas, fig=None):
    """Horas por tractor y actividad para varias corridas (un panel por corrida, misma escala)."""
    corridas = [c for c in _como_lista(corridas) if c.get("pasos") is not None]
    tablas = [horas_por_actividad(c["pasos"], c["resumen"]) for c in corridas]
    filas = [max(1, len(t)) for t in tablas]
    if fig is None:
        fig = plt.figure(figsize=(9.5, 1.1 + sum(0.36 * k + 0.6 for k in filas)), layout="constrained")
    axs = fig.subplots(len(corridas), 1, sharex=True, squeeze=False,
                       gridspec_kw={"height_ratios": [k + 0.6 for k in filas]})[:, 0]
    xmax = max(float(t.sum(axis=1).max()) for t in tablas) if tablas else 1.0
    for ax, c, t in zip(axs, corridas, tablas):
        rec = _Recorridos(c["pasos"])
        _barras_apiladas(ax, t, list(GRUPOS_ACTIVIDAD), [COLOR_ACTIVIDAD[g] for g in GRUPOS_ACTIVIDAD],
                         [f"{a} · {_rol(rec, a)}" for a in t.index], " h")
        T_h = _num(c["resumen"].get("T_h"))
        ax.set_title(f"{_etiqueta_corrida(c)} · T = {T_h:,.1f} h{_texto_fuera_servicio(c)}",
                     loc="left", fontsize=9.5)
    axs[0].set_xlim(0, xmax * 1.12)
    axs[-1].set_xlabel("Horas-tractor hasta T (h)")
    fig.legend(handles=[Patch(color=COLOR_ACTIVIDAD[g], label=g) for g in GRUPOS_ACTIVIDAD],
               loc="outside lower center", ncols=5)
    escs = {escenario_de(c) for c in corridas}
    sub = "Misma escala horizontal en todos los paneles; las horas fuera de servicio no se grafican"
    if len(escs) == 1 and corridas:
        r0 = {k: v for k, v in corridas[0]["resumen"].items() if k not in ("mecanismo",)}
        sub = texto_parametros(r0, escs.pop()) + " · " + sub[0].lower() + sub[1:]
    _titulo_fig(fig, "Horas por tractor según actividad", sub)
    return fig


FILAS_KPI = [
    ("mecanismo", "Mecanismo", None), ("hectareas", "ha", None), ("n_tractores", "N", None),
    ("semilla", "Semilla", None), ("costo_ha", "Costo ($/ha)", 0), ("T_h", "T (h)", 1),
    ("T_dias", "T (jornadas)", 2), ("cobertura", "Cobertura (%)", 1), ("colisiones", "Colisiones", 0),
    ("W_ocio_h", "W_ocio (h)", 2), ("W_espera_h", "W_espera (h)", 2),
    ("W_conflicto_h", "W_conflicto (h)", 2), ("mensajes_total", "Mensajes", 0),
    ("mensajes_perdidos", "Perdidos", 0), ("dispersion_dias", "Dispersión (jornadas)", 2),
    ("diesel_l", "Diésel (L)", 0), ("eficiencia_campo", "Eficiencia (%)", 1),
    ("tiempo_computo_s", "Cómputo (s)", 1),
]


def tabla_kpi(corridas):
    """Tabla con los indicadores principales de varias corridas detalladas (una fila por id)."""
    filas = []
    for c in _como_lista(corridas):
        r = c.get("resumen", {})
        fila = {"corrida": c.get("id", "")}
        for k, et, dec in FILAS_KPI:
            v = r.get(k)
            if dec is not None:
                v = round(_num(v) * ESCALA.get(k, 1), dec)
            fila[et] = v
        filas.append(fila)
    return pd.DataFrame(filas).set_index("corrida")


def control_calidad(df, por=("escenario",)):
    """Grupos con corridas incompletas (cobertura < 100 %) o estancadas, para revisarlas antes
    de interpretar. Devuelve un DataFrame vacío si todo está completo."""
    por = [p for p in ([por] if isinstance(por, str) else list(por)) if p in df.columns]
    if "mecanismo" in df.columns and "mecanismo" not in por:
        por.append("mecanismo")
    cobertura = pd.to_numeric(df["cobertura"], errors="coerce")
    d = pd.DataFrame({
        **{p: df[p] for p in por},
        "cobertura": cobertura,
        "_incompleta": cobertura < 0.9999,
        "_estancada": df["estancado"].map(_bool) if "estancado" in df.columns else False,
    })
    g = d.groupby(por, sort=False).agg(
        corridas=("_incompleta", "size"), incompletas=("_incompleta", "sum"),
        estancadas=("_estancada", "sum"),
        cobertura_min=("cobertura", lambda s: float(pd.to_numeric(s, errors="coerce").min()) * 100))
    g = g[(g["incompletas"] > 0) | (g["estancadas"] > 0)]
    return g.rename(columns={"cobertura_min": "cobertura mínima (%)"}).round(1)


def tabla_comparativa(df, metricas, por="mecanismo", decimales=None):
    """``DataFrame`` de texto con «media ± semiancho del IC 95 %» por grupo (n semillas)."""
    por = [por] if isinstance(por, str) else list(por)
    decimales = decimales or {}
    filas = []
    for clave, g in df.groupby(por, sort=False):
        clave = clave if isinstance(clave, tuple) else (clave,)
        fila = dict(zip(por, clave))
        fila["n"] = len(g)
        for m in metricas:
            if m not in g.columns:
                continue
            esc = ESCALA.get(m, 1)
            media, lo, hi = ic95(pd.to_numeric(g[m], errors="coerce") * esc)
            d = decimales.get(m, DECIMALES.get(m, 2))
            fila[ETIQUETA.get(m, m)] = "—" if np.isnan(media) else f"{media:,.{d}f} ± {hi - media:,.{d}f}"
        filas.append(fila)
    out = pd.DataFrame(filas)
    if "mecanismo" in por:
        out["_o"] = out["mecanismo"].map({m: i for i, m in enumerate(ORDEN_MECANISMOS)}).fillna(9)
        out = out.sort_values([c for c in por if c != "mecanismo"] + ["_o"], kind="stable").drop(columns="_o")
    return out.set_index(por)


def tabla_parametros(parametros):
    """Parámetros del ``cfg`` aplanados con su fuente (``_fuentes``)."""
    fuentes = (parametros or {}).get("_fuentes", {})
    filas = []

    def recorrer(d, prefijo=""):
        for k, v in d.items():
            if k.startswith("_"):
                continue
            ruta = f"{prefijo}{k}"
            if isinstance(v, dict):
                recorrer(v, ruta + ".")
            else:
                filas.append({"parámetro": ruta, "valor": "null" if v is None else str(v),
                              "fuente": fuentes.get(ruta, "")})

    recorrer(parametros or {})
    return pd.DataFrame(filas)


COLUMNAS_CONDICION = [
    ("hectareas", "ha"), ("ha_sembrables", "ha sembrables"), ("n_tractores", "N"),
    ("n_surcadores", "surcadores"), ("n_obstaculos", "obstáculos"),
    ("perdida_mensajes", "pérdida de mensajes"), ("timeout_ofertas", "timeout (pasos)"),
    ("ventana_reservas", "ventana reservas (pasos)"), ("margen_recarga_hileras", "margen recarga"),
    ("tolva_ha", "tolva (ha)"), ("falla_activa", "falla"), ("jornada_h", "jornada (h)"),
    ("dias_laborables", "días laborables"),
]


def tabla_condiciones(df, por="escenario"):
    """Condiciones de cada experimento: valores únicos de los parámetros de identificación,
    mecanismos y semillas por grupo."""
    por = [por] if isinstance(por, str) else list(por)

    def unicos(s):
        vals = pd.unique(s.dropna())
        try:
            vals = sorted(vals)
        except TypeError:
            pass
        return ", ".join(f"{v:g}" if isinstance(v, (float, np.floating)) else str(v) for v in vals)

    filas = []
    for clave, g in df.groupby(por, sort=False):
        clave = clave if isinstance(clave, tuple) else (clave,)
        fila = dict(zip(por, clave))
        if "escenario_nombre" in g.columns and "escenario_nombre" not in por:
            fila["nombre"] = unicos(g["escenario_nombre"])
        for col, et in COLUMNAS_CONDICION:
            if col in g.columns:
                fila[et] = unicos(g[col])
        if "mecanismo" in g.columns:
            fila["mecanismos"] = ", ".join(_mecanismos(g))
        if "semilla" in g.columns:
            s = pd.to_numeric(g["semilla"], errors="coerce").dropna().astype(int)
            fila["semillas"] = f"{s.nunique()} ({s.min()} a {s.max()})" if len(s) else ""
        fila["corridas"] = len(g)
        filas.append(fila)
    return pd.DataFrame(filas).set_index(por)


# ======================================================================= panel de comunicación

def _como_lista(corridas):
    if isinstance(corridas, dict) and "resumen" in corridas:
        return [corridas]
    if isinstance(corridas, dict):
        return list(corridas.values())
    return list(corridas)


def _etiqueta_corrida(c):
    r = c.get("resumen", {})
    return NOMBRE_MECANISMO.get(str(r.get("mecanismo")), str(r.get("mecanismo", "")))


def serie_performativas(corridas, fig=None):
    """Mensajes acumulados por performativa contra el tiempo (un panel por performativa, una
    línea por corrida en el color de su mecanismo). Incluye los mensajes perdidos (se enviaron)."""
    corridas = [c for c in _como_lista(corridas) if c.get("mensajes") is not None]
    if fig is None:
        fig = plt.figure(figsize=(15, 3.6), layout="constrained")
    axs = fig.subplots(1, len(PERFORMATIVAS), sharex=True, squeeze=False)[0]
    mecs = []
    for ax, perf in zip(axs, PERFORMATIVAS):
        hubo = False
        for c in corridas:
            m = c["mensajes"]
            m = m[m["performativa"].astype(str) == perf]
            mec = str(c["resumen"].get("mecanismo"))
            if len(m) == 0:
                continue
            hubo = True
            t = np.sort(m["t_envio"].to_numpy(dtype=float)) * _paso_h(c["resumen"])
            k = np.arange(1, len(t) + 1)
            t_fin = _t_final(c) * _paso_h(c["resumen"])
            ax.step(np.r_[0, t, t_fin], np.r_[0, k, k[-1]], where="post", color=_color_mecanismo(mec),
                    lw=1.5)
            if mec not in mecs:
                mecs.append(mec)
        ax.set_title(NOMBRE_PERFORMATIVA[perf], fontsize=9.5)
        ax.set_xlabel("Tiempo (h)")
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_ylim(bottom=0)
        if not hubo:
            ax.text(0.5, 0.5, "sin mensajes", transform=ax.transAxes, ha="center", color=TINTA_3)
    axs[0].set_ylabel("Mensajes acumulados (conteo)")
    sin_msg = [str(c["resumen"].get("mecanismo")) for c in corridas if len(c["mensajes"]) == 0]
    if len(mecs) > 1:
        fig.legend(handles=_leyenda_mecanismos(mecs), loc="outside lower center", ncols=len(mecs))
    sub = texto_parametros({k: v for k, v in corridas[0]["resumen"].items() if k not in ("mecanismo", "semilla")},
                           escenario_de(corridas[0])) if corridas else ""
    if len(mecs) == 1:
        sub = _texto_corrida(corridas[0])
    if sin_msg:
        sub += f" · {', '.join(sin_msg)} no envía mensajes"
    _titulo_fig(fig, "Mensajes por performativa acumulados a lo largo de la corrida", sub)
    return fig


def _filtrar_parametro(df, nombre):
    if "parametro" in df.columns:
        return df[df["parametro"].astype(str).map(_base_parametro) == nombre]
    return df


def _linea_ic(ax, df, x, metrica, mec, escala_x=1.0, marcador=True, dx=0.0):
    """Línea de medias con banda IC 95 %; la banda no baja de 0 si la métrica no es negativa.
    ``dx`` desplaza la línea en x (para que mecanismos con valores casi iguales no se tapen)."""
    r = resumen_por_grupo(df, x, metrica).sort_values(x)
    xs = r[x].to_numpy(dtype=float) * escala_x + dx
    c = _color_mecanismo(mec)
    bajo = r["ic_bajo"].to_numpy(dtype=float)
    if (pd.to_numeric(df[metrica], errors="coerce").dropna() >= 0).all():
        bajo = np.maximum(bajo, 0)
    ax.fill_between(xs, bajo, r["ic_alto"], color=c, alpha=0.12, lw=0)
    ax.plot(xs, r["media"], color=c, lw=1.5, marker="o" if marcador else None, ms=4,
            label=NOMBRE_MECANISMO.get(mec, mec))
    return r


def _ordenar_mecs(mecs):
    return [m for m in ORDEN_MECANISMOS if m in mecs] + sorted(m for m in mecs if m not in ORDEN_MECANISMOS)


def perdidos_y_reanuncios(df_sens, fig=None):
    """Mensajes perdidos y reanuncios contra el nivel de pérdida, por mecanismo (dos paneles)."""
    d = _filtrar_parametro(df_sens, "perdida_mensajes")
    x = "valor" if "valor" in d.columns and "parametro" in d.columns else "perdida_mensajes"
    if fig is None:
        fig = plt.figure(figsize=(11, 3.9), layout="constrained")
    axs = fig.subplots(1, 2, sharex=True, squeeze=False)[0]
    mecs = _mecanismos(d) if len(d) else []
    for ax, met, tit in zip(axs, ("mensajes_perdidos", "reanuncios"),
                            ("Mensajes perdidos por corrida", "Reanuncios de hileras por corrida")):
        for mec in mecs:
            sub = d[d["mecanismo"].astype(str) == mec]
            if met in sub.columns:
                _linea_ic(ax, sub, x, met, mec, escala_x=100)
        ax.set_title(tit, fontsize=10)
        ax.set_xlabel("Pérdida de mensajes (%)")
        ax.set_ylabel(ETIQUETA[met])
        ax.set_ylim(bottom=0)
    if mecs:
        fig.legend(handles=_leyenda_mecanismos(mecs, marcador=True), loc="outside lower center",
                   ncols=len(mecs))
    n = int(d.groupby(["mecanismo", x]).size().min()) if len(d) else 0
    _titulo_fig(fig, "Robustez de la comunicación ante la pérdida de mensajes",
                f"Media de {n} semillas por punto; banda: IC 95 % de la media · "
                + _condiciones_comunes(d))
    return fig


def _condiciones_comunes(df):
    partes = []
    for col, fmt in (("hectareas", "{:g} ha"), ("n_tractores", "N = {:g}")):
        if col in df.columns:
            vals = pd.unique(pd.to_numeric(df[col], errors="coerce").dropna())
            if len(vals) == 1:
                partes.append(fmt.format(vals[0]))
    return " · ".join(partes)


def hileras_por_tractor(ax, corrida, titulo=True):
    """Hileras equivalentes trabajadas por tractor (celdas trabajadas ÷ largo de la hilera),
    separadas por implemento. Muestra el balance de carga."""
    tabla = tabla_hileras(corrida)
    fig, ax = _nueva(ax, (7.5, 1.2 + 0.5 * len(tabla)))
    izq = _barras_apiladas(ax, tabla, ["Surcado", "Sembrado"],
                           [COLOR_CELDA["surcada"], COLOR_CELDA["sembrada"]], list(tabla.index))
    ax.set_xlim(0, max(izq.max(), 1e-9) * 1.15)
    ax.set_xlabel("Hileras equivalentes trabajadas (celdas ÷ largo de hilera)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncols=2, borderaxespad=0.2)
    if titulo:
        r = corrida.get("resumen", {})
        bal = _num(r.get("balance_carga"))
        t = f"Hileras por tractor · balance de carga {bal:.1f} hileras (mismo rol)" \
            if not np.isnan(bal) else "Hileras por tractor"
        _titulo_ax(ax, t, _texto_corrida(corrida), tam=10.5, extra=22)
    return fig


def tabla_hileras(corrida):
    """Hileras equivalentes trabajadas por tractor: columnas «Surcado» y «Sembrado»."""
    pasos = corrida["pasos"]
    campo = corrida["campo"]
    largo = int(campo["y1"]) - int(campo["y0"]) + 1
    trab = pasos[pasos["estado"].astype(str) == "trabajando"]
    tabla = trab.groupby(["agente", "implemento"]).size().unstack(fill_value=0) / largo
    agentes = sorted(pd.unique(pasos["agente"].astype(str)), key=_orden_agente)
    tabla = tabla.reindex(index=agentes, columns=["surcador", "sembradora"], fill_value=0).fillna(0)
    return tabla.rename(columns={"surcador": "Surcado", "sembradora": "Sembrado"})


def hileras_comparadas(corridas, fig=None):
    """Hileras equivalentes por tractor para varias corridas (un panel por corrida, misma escala)."""
    corridas = [c for c in _como_lista(corridas) if c.get("pasos") is not None]
    tablas = [tabla_hileras(c) for c in corridas]
    filas = [max(1, len(t)) for t in tablas]
    if fig is None:
        fig = plt.figure(figsize=(9.5, 1.1 + sum(0.34 * k + 0.6 for k in filas)), layout="constrained")
    axs = fig.subplots(len(corridas), 1, sharex=True, squeeze=False,
                       gridspec_kw={"height_ratios": [k + 0.6 for k in filas]})[:, 0]
    xmax = max(float(t.sum(axis=1).max()) for t in tablas) if tablas else 1.0
    for ax, c, t in zip(axs, corridas, tablas):
        _barras_apiladas(ax, t, ["Surcado", "Sembrado"], [COLOR_CELDA["surcada"], COLOR_CELDA["sembrada"]],
                         list(t.index))
        bal = _num(c["resumen"].get("balance_carga"))
        ax.set_title(f"{_etiqueta_corrida(c)} · balance de carga {bal:.1f} hileras{_texto_fuera_servicio(c)}",
                     loc="left", fontsize=9.5)
    axs[0].set_xlim(0, xmax * 1.15)
    axs[-1].set_xlabel("Hileras equivalentes trabajadas (celdas trabajadas ÷ largo de la hilera)")
    fig.legend(handles=[Patch(color=COLOR_CELDA["surcada"], label="Surcado"),
                        Patch(color=COLOR_CELDA["sembrada"], label="Sembrado")],
               loc="outside lower center", ncols=2)
    escs = {escenario_de(c) for c in corridas}
    sub = "Balance de carga: diferencia entre el tractor más cargado y el menos cargado del mismo rol"
    if len(escs) == 1 and corridas:
        r0 = {k: v for k, v in corridas[0]["resumen"].items() if k not in ("mecanismo",)}
        sub = texto_parametros(r0, escs.pop()) + " · " + sub[0].lower() + sub[1:]
    _titulo_fig(fig, "Hileras trabajadas por tractor (balance de carga)", sub)
    return fig


def _series_por_corrida(corridas, columna, ylabel, titulo, fig, nota_cero=None):
    corridas = _como_lista(corridas)
    n = len(corridas)
    if fig is None:
        fig = plt.figure(figsize=(10, 0.6 + 1.75 * n), layout="constrained")
    axs = fig.subplots(n, 1, sharex=True, sharey=True, squeeze=False)[:, 0]
    vmax = 0.0
    for ax, c in zip(axs, corridas):
        s = c["serie"]
        h = s["t"].to_numpy(dtype=float) * _paso_h(c["resumen"])
        v = s[columna].to_numpy(dtype=float)
        vmax = max(vmax, float(np.nanmax(v, initial=0)))
        mec = str(c["resumen"].get("mecanismo"))
        ax.fill_between(h, 0, v, step="post", color=_color_mecanismo(mec), alpha=0.12, lw=0)
        ax.step(h, v, where="post", color=_color_mecanismo(mec), lw=1.2)
        etiqueta = f"{_etiqueta_corrida(c)} · {escenario_de(c) or ''}"
        if np.nanmax(v, initial=0) == 0:
            etiqueta += f" · {nota_cero}"
        else:
            etiqueta += f" · máximo {np.nanmax(v):g}, media {np.nanmean(v):.2f}"
        ax.set_title(etiqueta, fontsize=8.5, fontweight="normal", color=TINTA, loc="left", pad=3)
        ax.set_ylabel(ylabel, fontsize=8.5)
    for ax in axs:
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
    axs[0].set_ylim(0, max(1.0, vmax) * 1.18)
    axs[-1].set_xlabel("Tiempo (h)")
    _titulo_fig(fig, titulo, texto_parametros(
        {k: v for k, v in corridas[0]["resumen"].items() if k not in ("mecanismo",)}) if n == 1 else
        "Un panel por corrida; mismo eje vertical en todos los paneles")
    return fig


def serie_estacion(corridas, fig=None):
    """Tractores en la fila de la estación de carga a lo largo del tiempo (un panel por corrida)."""
    return _series_por_corrida(corridas, "fila_estacion", "En fila\n(tractores)",
                               "Largo de la fila de la estación de carga", fig,
                               nota_cero="la fila estuvo vacía toda la corrida")


def serie_reservas(corridas, fig=None):
    """Entradas activas en la tabla de reservas de Cooperative A* (un panel por corrida)."""
    return _series_por_corrida(corridas, "reservas_activas", "Reservas\n(celda-paso)",
                               "Entradas activas en la tabla de reservas de Cooperative A* (blackboard)",
                               fig, nota_cero="sin tabla de reservas")


def _tabla_mensajes(mensajes):
    m = mensajes.copy()
    m["ronda"] = pd.to_numeric(m["ronda"], errors="coerce").fillna(-1).astype(int)
    m["x"] = pd.to_numeric(m["x"], errors="coerce").fillna(-1).astype(int)
    m["perdido"] = m["perdido"].map(_bool)
    m["performativa"] = m["performativa"].astype(str)
    for c in ("emisor", "receptor"):
        m[c] = m[c].astype(str)
    for c in ("evento", "tipo_tarea"):
        m[c] = m[c].fillna("").astype(str).replace("nan", "") if c in m.columns else ""
    return m


def elegir_ronda(mensajes):
    """Ronda de subasta más ilustrativa del log: con varios postores y, si los hay, con mensajes
    perdidos (su reanuncio se agrega en ``mensajes_subasta``). ``None`` si el log no tiene
    subastas."""
    m = _tabla_mensajes(mensajes)
    m = m[m["ronda"] >= 0]
    if len(m) == 0:
        return None
    g = pd.DataFrame({
        "ronda": m["ronda"],
        "acepta": (m["performativa"] == "accept-proposal") & ~m["perdido"],
        "rechaza": m["performativa"] == "reject-proposal",
        "perdido": m["perdido"],
        "cfp_a": m["receptor"].where(m["performativa"] == "cfp"),
    }).groupby("ronda").agg(acepta=("acepta", "any"), rechaza=("rechaza", "any"),
                            perdidos=("perdido", "sum"), n=("perdido", "size"),
                            postores=("cfp_a", "nunique"))
    g = g.assign(con_perdidos=g["perdidos"] > 0, varios=g["postores"] >= 2)
    g = g.sort_values(["varios", "con_perdidos", "acepta", "rechaza", "n"], ascending=False,
                      kind="stable")
    return int(g.index[0])


def mensajes_subasta(mensajes, ronda, timeout=None):
    """Mensajes de una ronda más su contexto en el log: los ``inform`` de inicio y fin de los
    ganadores sobre las hileras adjudicadas y, si la adjudicación no llegó, la ronda que la
    reanuncia al mismo tractor. Devuelve (mensajes ordenados, rondas incluidas)."""
    m = _tabla_mensajes(mensajes)
    rondas = [int(ronda)]
    sel = m[m["ronda"] == ronda]
    if len(sel) == 0:
        return sel, rondas
    t0 = int(sel["t_envio"].min())
    # Reanuncio: si se perdió una adjudicación (o el cfp / la oferta), la siguiente ronda que
    # vuelve a anunciar a ese tractor (y, si se conoce, por la misma hilera).
    falto = sel[(sel["perdido"]) & sel["performativa"].isin(["cfp", "propose", "accept-proposal"])]
    if len(falto):
        afectados = set(falto["receptor"]) | set(falto["emisor"])
        afectados.discard("DEP")
        hileras_perdidas = {int(x) for x in falto["x"] if int(x) >= 0}
        posteriores = m[(m["ronda"] > ronda) & (m["t_envio"] >= t0)]
        cand = posteriores[(posteriores["performativa"] == "cfp") & posteriores["receptor"].isin(afectados)]
        if hileras_perdidas:
            con_x = posteriores[posteriores["x"].isin(hileras_perdidas)
                                & posteriores["performativa"].isin(["propose", "accept-proposal"])]
            if len(con_x):
                cand = con_x
        if len(cand):
            r2 = int(cand["ronda"].min())
            rondas.append(r2)
            sel = pd.concat([sel, m[m["ronda"] == r2]])
    acept = sel[(sel["performativa"] == "accept-proposal") & ~sel["perdido"]]
    pares = set(zip(acept["receptor"], acept["x"]))
    if pares:
        inf = m[(m["performativa"] == "inform") & ~m["ronda"].isin(rondas) & (m["t_envio"] >= t0)
                & m["evento"].isin(["inicio", "fin"])]
        inf = inf.loc[np.array([(e, x) in pares for e, x in zip(inf["emisor"], inf["x"])], dtype=bool)]
        inf = inf.sort_values("t_envio", kind="stable").drop_duplicates(subset=["emisor", "x", "evento"])
        sel = pd.concat([sel, inf])
    orden_perf = {p: i for i, p in enumerate(PERFORMATIVAS)}
    sel = sel.assign(_o=sel["performativa"].map(orden_perf).fillna(9))
    sel = sel.sort_values(["t_envio", "_o", "receptor"], kind="stable").drop(columns="_o")
    return sel, rondas


def linea_tiempo_subasta(ax, mensajes, ronda=None, resumen=None, max_mensajes=40):
    """Diagrama de secuencia de una subasta real del log (DEP y tractores como carriles)."""
    resumen = resumen or {}
    if ronda is None and len(mensajes):
        ronda = elegir_ronda(mensajes)
    if ronda is None:
        fig, ax = _nueva(ax, (9.5, 2.5))
        _sin_datos(ax, "La corrida no tiene subastas (M0 no envía mensajes).")
        return fig
    sel, rondas = mensajes_subasta(mensajes, ronda, resumen.get("timeout_ofertas"))
    sel = sel.head(max_mensajes)
    fig, ax = _nueva(ax, (9.5, max(3.8, 2.0 + 0.42 * len(sel))))
    hileras = sorted({int(x) for x in sel["x"] if int(x) >= 0})
    actores = pd.unique(pd.concat([sel["emisor"], sel["receptor"]]).astype(str))
    carriles = (["DEP"] if "DEP" in actores else []) + sorted([a for a in actores if a != "DEP"],
                                                              key=_orden_agente)
    xpos = {a: i for i, a in enumerate(carriles)}
    n = len(sel)
    for a, i in xpos.items():
        ax.plot([i, i], [-0.6, n - 0.4], color=EJE, lw=1.0, zorder=1)
        ax.text(i, -0.9, a if a != "DEP" else "DEP (depósito)", ha="center", va="bottom",
                fontsize=9, fontweight="semibold", color=TINTA,
                bbox=dict(boxstyle="round,pad=0.3", fc=FONDO_TARJETA, ec="none"))
    ticks, etiquetas, t_prev = [], [], None
    for k, (_, msg) in enumerate(sel.iterrows()):
        x0, x1 = xpos[str(msg["emisor"])], xpos[str(msg["receptor"])]
        perdido = _bool(msg["perdido"])
        retraso = max(0, int(msg["t_entrega"]) - int(msg["t_envio"]))
        y0, y1 = k, k + min(retraso, 3) * 0.12
        perf = str(msg["performativa"])
        texto = perf
        if perf == "inform" and msg.get("evento", ""):
            texto += f" {msg['evento']}"
        if perf == "cfp" and msg.get("tipo_tarea", ""):
            texto += f" ({msg['tipo_tarea']})"
        if int(msg["x"]) >= 0:
            texto += f" x = {int(msg['x'])}"
        if perf == "propose" and not np.isnan(_num(msg.get("u"))):
            texto += f", u = {_num(msg['u']):.0f}"
        if len(rondas) > 1 and int(msg["ronda"]) == rondas[1]:
            texto += " [reanuncio]"
        if perdido:
            xf = x0 + (x1 - x0) * 0.82
            yf = y0 + (y1 - y0) * 0.82
            ax.plot([x0, xf], [y0, yf], color=ROJO_PERDIDO, lw=1.3, ls=(0, (1.5, 1.5)), zorder=3)
            ax.plot([xf], [yf], marker="x", ms=7, mew=1.8, color=ROJO_PERDIDO, zorder=4)
            texto += " · perdido"
        else:
            ax.annotate("", xy=(x1, y1), xytext=(x0, y0), zorder=3,
                        arrowprops=dict(arrowstyle="-|>", color=TINTA_2, lw=1.1, shrinkA=0, shrinkB=2,
                                        mutation_scale=9))
        ax.annotate(texto, ((x0 + x1) / 2, (y0 + y1) / 2), xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=7.5, color=TINTA, path_effects=_HALO, zorder=5)
        ticks.append(k)
        t_env = int(msg["t_envio"])
        etiquetas.append(f"t = {t_env:,}" if t_env != t_prev else "")
        t_prev = t_env
    ax.set_yticks(ticks, etiquetas)
    ax.set_ylim(n - 0.2, -1.6)
    ax.set_xlim(-0.6, len(carriles) - 0.4)
    ax.set_xticks([])
    ax.grid(False)
    for s in ("bottom", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    paso_s = _num(resumen.get("paso_s"))
    ax.set_ylabel("Paso de envío" + (f" (1 paso ≈ {paso_s:.0f} s)" if not np.isnan(paso_s) else ""))
    perdidos = int(sel["perdido"].sum())
    handles = [Line2D([], [], color=TINTA_2, lw=1.1, marker=">", ms=5, label="Mensaje entregado")]
    if perdidos:
        handles.append(Line2D([], [], color=ROJO_PERDIDO, lw=1.3, ls=(0, (1.5, 1.5)), marker="x",
                              ms=6, mew=1.6, label="Mensaje perdido (punteado: no llegó a su receptor)"))
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0, -0.01), ncols=2)
    txt_h = ("hilera x = " + str(hileras[0])) if len(hileras) == 1 else \
        ("hileras x = " + ", ".join(map(str, hileras)) if hileras else "sin hilera")
    txt_r = f"ronda {rondas[0]}" + (f" y su reanuncio (ronda {rondas[1]})" if len(rondas) > 1 else "")
    _titulo_ax(ax, f"Subasta de la {txt_r} · {txt_h} · {n} mensajes, {perdidos} perdidos",
               texto_parametros(resumen) + " · tomada del log de mensajes de la corrida")
    return fig


# ========================================================================= panel experimental

def curvas_costo(df_barrido, metrica="costo_ha", fig=None):
    """Costo por hectárea contra N, un panel por tamaño de campo, una línea por mecanismo con
    banda de IC 95 % y el mínimo de cada mecanismo marcado."""
    d = df_barrido.copy()
    d["hectareas"] = pd.to_numeric(d["hectareas"], errors="coerce")
    d["n_tractores"] = pd.to_numeric(d["n_tractores"], errors="coerce")
    tam = sorted(d["hectareas"].dropna().unique())
    ncols = min(3, max(1, len(tam)))
    nrows = math.ceil(len(tam) / ncols) if tam else 1
    if fig is None:
        fig = plt.figure(figsize=(4.4 * ncols, 3.5 * nrows + 0.6), layout="constrained")
    axs = fig.subplots(nrows, ncols, squeeze=False).ravel()
    mecs = _mecanismos(d)
    desp = {m: (i - (len(mecs) - 1) / 2) * 0.08 for i, m in enumerate(mecs)}
    for ax, ha in zip(axs, tam):
        sub = d[d["hectareas"] == ha]
        ns = sorted(sub["n_tractores"].dropna().unique())
        mejor = None
        for mec in mecs:
            s = sub[sub["mecanismo"].astype(str) == mec]
            if len(s) == 0:
                continue
            r = _linea_ic(ax, s, "n_tractores", metrica, mec, dx=desp[mec])
            i = int(r["media"].idxmin())
            ax.plot([r.loc[i, "n_tractores"] + desp[mec]], [r.loc[i, "media"]], marker="o", ms=8,
                    mfc=_color_mecanismo(mec), mec=SUPERFICIE, mew=1.5, ls="", zorder=5)
            if mejor is None or r.loc[i, "media"] < mejor[2]:
                mejor = (mec, r.loc[i, "n_tractores"], r.loc[i, "media"])
        if mejor:
            mec, n, v = mejor
            ha_txt = "left" if n == min(ns) else ("right" if n == max(ns) else "center")
            ax.annotate(f"mínimo: {mec}, N = {n:g}\n{_dinero(v)}/ha · {n / ha:.3f} tractores/ha",
                        (n + desp[mec], v), xytext=(0, -14), textcoords="offset points", ha=ha_txt,
                        va="top", fontsize=7.5, color=TINTA, path_effects=_HALO)
        ax.set_xticks(ns, [f"{v:g}" for v in ns])
        ax.set_xlim(min(ns) - 0.4, max(ns) + 0.4)
        ax.set_title(f"Campo de {ha:g} ha", fontsize=10)
        ax.set_xlabel("Número de tractores N")
        _formato_dinero(ax)
        lo, hi = ax.get_ylim()
        ax.set_ylim(lo - (hi - lo) * 0.18, hi)
    for i, ax in enumerate(axs):
        if i < len(tam) and i % ncols == 0:
            ax.set_ylabel(ETIQUETA.get(metrica, metrica))
    for ax in axs[len(tam):]:
        ax.set_visible(False)
    handles = _leyenda_mecanismos(mecs, marcador=True) + [
        Line2D([], [], marker="o", ls="", ms=8, mfc=TINTA_3, mec=SUPERFICIE, mew=1.5,
               label="Mínimo de cada mecanismo")]
    if len(tam) < len(axs):
        axs[len(tam)].set_visible(True)
        axs[len(tam)].set_axis_off()
        axs[len(tam)].legend(handles=handles, loc="center left")
    else:
        fig.legend(handles=handles, loc="outside lower center", ncols=len(handles))
    n = int(d.groupby(["hectareas", "n_tractores", "mecanismo"]).size().min()) if len(d) else 0
    _titulo_fig(fig, "¿Cuántos tractores por hectárea? Costo por hectárea contra número de tractores",
                f"Media de {n} semillas por punto; banda: IC 95 % de la media; cada panel tiene su "
                "propia escala vertical; los mecanismos se desplazan un poco en x para no taparse")
    return fig


def _nombre_escenario(df, esc):
    if "escenario_nombre" in df.columns:
        n = df.loc[df["escenario"].astype(str) == esc, "escenario_nombre"].dropna()
        if len(n):
            return str(n.iloc[0])
    return esc


def _orden_escenarios(df, escenarios=None):
    presentes = list(pd.unique(df["escenario"].astype(str)))
    if escenarios is None:
        return presentes
    return [e for e in escenarios if e in presentes]


def barras_escenarios(df_esc, metrica, escenarios=None, fig=None):
    """Media por escenario y mecanismo con barras de error IC 95 % (un panel por escenario,
    cada uno con su escala desde cero)."""
    esc = _orden_escenarios(df_esc, escenarios)
    n = len(esc)
    ncols = min(3, max(1, n))
    nrows = math.ceil(n / ncols) if n else 1
    if fig is None:
        fig = plt.figure(figsize=(4.1 * ncols, 2.9 * nrows + 0.6), layout="constrained")
    axs = fig.subplots(nrows, ncols, squeeze=False).ravel()
    mecs = _mecanismos(df_esc)
    for i, (ax, e) in enumerate(zip(axs, esc)):
        sub = df_esc[df_esc["escenario"].astype(str) == e]
        r = resumen_por_grupo(sub, "mecanismo", metrica)
        r = r.set_index("mecanismo").reindex([m for m in mecs if m in set(r["mecanismo"])])
        xs = np.array([mecs.index(m) for m in r.index], dtype=float)
        ax.bar(xs, r["media"], width=0.32, color=[_color_mecanismo(m) for m in r.index],
               edgecolor="none")
        ax.errorbar(xs, r["media"], yerr=[r["media"] - r["ic_bajo"], r["ic_alto"] - r["media"]],
                    fmt="none", ecolor=TINTA_2, elinewidth=1.0, capsize=3, capthick=1.0)
        dec = DECIMALES.get(metrica, 1)
        for x, (_m, fila) in zip(xs, r.iterrows()):
            ax.annotate(f"{fila['media']:,.{dec}f}", (x, fila["ic_alto"]), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", fontsize=8, color=TINTA)
        ax.set_xticks(range(len(mecs)), mecs)
        ax.set_xlim(-0.6, len(mecs) - 0.4)
        top = float(np.nanmax(r["ic_alto"])) if len(r) else 1.0
        ax.set_ylim(0, (top if top > 0 else 1.0) * 1.22)
        ax.grid(axis="x", visible=False)
        ax.set_title("\n".join(textwrap.wrap(_nombre_escenario(df_esc, e), 34)), fontsize=9.5)
        if i % ncols == 0:
            ax.set_ylabel(ETIQUETA.get(metrica, metrica))
        if metrica in ("costo_ha", "J"):
            _formato_dinero(ax)
    for ax in axs[n:]:
        ax.set_visible(False)
    fig.legend(handles=[Patch(color=_color_mecanismo(m), label=NOMBRE_MECANISMO.get(m, m)) for m in mecs],
               loc="outside lower center", ncols=len(mecs))
    nsem = int(df_esc.groupby(["escenario", "mecanismo"]).size().min()) if len(df_esc) else 0
    _titulo_fig(fig, f"¿Qué mecanismo funciona mejor? {ETIQUETA.get(metrica, metrica)} por escenario",
                f"Barra: media de {nsem} semillas; línea: IC 95 % de la media; cada panel tiene su "
                "propia escala desde cero")
    return fig


def diferencias_pareadas(df, metrica, referencia="M0", escenarios=None, fig=None):
    """Diferencia pareada por semilla contra el mecanismo de referencia, con IC 95 %."""
    esc = _orden_escenarios(df, escenarios)
    mecs = [m for m in _mecanismos(df) if m != referencia]
    if fig is None:
        fig = plt.figure(figsize=(8.5, 1.4 + 0.5 * len(esc)), layout="constrained")
    ax = fig.subplots()
    esc_ = ESCALA.get(metrica, 1)
    y = np.arange(len(esc))[::-1].astype(float)
    off = np.linspace(0.16, -0.16, len(mecs)) if len(mecs) > 1 else [0.0]
    for j, mec in enumerate(mecs):
        for yi, e in zip(y, esc):
            sub = df[df["escenario"].astype(str) == e]
            a = sub[sub["mecanismo"].astype(str) == mec].set_index("semilla")[metrica]
            b = sub[sub["mecanismo"].astype(str) == referencia].set_index("semilla")[metrica]
            dif = (pd.to_numeric(a, errors="coerce") - pd.to_numeric(b, errors="coerce")).dropna() * esc_
            if len(dif) == 0:
                continue
            media, lo, hi = ic95(dif)
            ax.errorbar([media], [yi + off[j]], xerr=[[media - lo], [hi - media]], fmt="o", ms=5,
                        color=_color_mecanismo(mec), mec=SUPERFICIE, mew=1.2, elinewidth=1.5,
                        capsize=0)
    ax.axvline(0, color=TINTA_3, lw=1.0, zorder=1)
    ax.set_yticks(y, ["\n".join(textwrap.wrap(_nombre_escenario(df, e), 38)) for e in esc])
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(f"Diferencia contra {referencia} en {ETIQUETA.get(metrica, metrica)}"
                  " (negativo = menor que la referencia)")
    if metrica in ("costo_ha", "J"):
        _formato_dinero(ax, "x")
    ax.legend(handles=[Line2D([], [], marker="o", ls="", ms=5, color=_color_mecanismo(m),
                              label=f"{NOMBRE_MECANISMO.get(m, m)} − {referencia}") for m in mecs],
              loc="lower left", bbox_to_anchor=(0, 1.0), ncols=len(mecs))
    _titulo_fig(fig, f"Diferencia pareada por semilla contra {referencia}: {ETIQUETA.get(metrica, metrica)}",
                "Punto: media de las diferencias (mismas semillas); línea: IC 95 %; si la línea no "
                "cruza el cero la diferencia es distinta de cero al 95 %")
    return fig


def curvas_cobertura(df_curvas, escenario, ax=None, columna="sembrado_frac", n_puntos=200,
                     nombre=None):
    """% del área sembrada contra horas: media por mecanismo con banda IC 95 % entre semillas.

    Cada semilla se interpola a una malla común de tiempo y conserva su valor final después de
    terminar."""
    d = df_curvas[df_curvas["escenario"].astype(str) == str(escenario)]
    fig, ax = _nueva(ax, (8.5, 4.6))
    if len(d) == 0:
        _sin_datos(ax, f"No hay curvas para el escenario {escenario}.")
        return fig
    nsem = _dibujar_cobertura(ax, d, columna, n_puntos)
    ax.legend(loc="lower right")
    _titulo_ax(ax, f"¿Cómo avanza la siembra? {nombre or escenario}",
               f"Escenario {escenario} · media de {min(nsem) if nsem else 0} semillas; banda: IC 95 % "
               "de la media; cada semilla conserva su valor final después de terminar")
    return fig


def cobertura_por_escenario(df_curvas, escenarios=None, nombres=None, columna="sembrado_frac",
                            fig=None):
    """Pequeños múltiplos de % sembrado contra horas, un panel por escenario (escala de tiempo
    propia en cada panel)."""
    esc = _orden_escenarios(df_curvas, escenarios)
    nombres = nombres or {}
    n = len(esc)
    ncols = min(3, max(1, n))
    nrows = math.ceil(n / ncols) if n else 1
    if fig is None:
        fig = plt.figure(figsize=(4.3 * ncols, 2.9 * nrows + 0.7), layout="constrained")
    axs = fig.subplots(nrows, ncols, sharey=True, squeeze=False).ravel()
    nsem, mecs = [], []
    for i, (ax, e) in enumerate(zip(axs, esc)):
        d = df_curvas[df_curvas["escenario"].astype(str) == e]
        nsem += _dibujar_cobertura(ax, d, columna, 150)
        mecs += [m for m in _mecanismos(d) if m not in mecs]
        ax.set_title("\n".join(textwrap.wrap(nombres.get(e, e), 40)), fontsize=9.5)
        ax.set_xlabel("Tiempo (h)")
        if i % ncols:
            ax.set_ylabel("")
    for ax in axs[n:]:
        ax.set_visible(False)
    fig.legend(handles=_leyenda_mecanismos(_ordenar_mecs(mecs)), loc="outside lower center",
               ncols=max(1, len(mecs)))
    _titulo_fig(fig, "¿Cómo avanza la siembra? Área sembrada contra tiempo en cada escenario",
                f"Media de {min(nsem) if nsem else 0} semillas o más; banda: IC 95 % de la media; cada "
                "panel tiene su propia escala de tiempo")
    return fig


def _dibujar_cobertura(ax, d, columna, n_puntos):
    t_max = float(pd.to_numeric(d["t_h"]).max()) if len(d) else 1.0
    malla = np.linspace(0, t_max, n_puntos)
    mecs = _mecanismos(d) if len(d) else []
    nsem = []
    for mec in mecs:
        curvas = []
        for _s, g in d[d["mecanismo"].astype(str) == mec].groupby("semilla"):
            g = g.sort_values("t_h")
            f = g[columna].to_numpy(dtype=float) * 100
            curvas.append(np.interp(malla, g["t_h"].to_numpy(dtype=float), f, left=0, right=f[-1]))
        if not curvas:
            continue
        a = np.vstack(curvas)
        media = a.mean(axis=0)
        if len(a) > 1:
            h = stats.t.ppf(0.975, len(a) - 1) * a.std(axis=0, ddof=1) / math.sqrt(len(a))
        else:
            h = np.zeros_like(media)
        c = _color_mecanismo(mec)
        ax.fill_between(malla, np.maximum(media - h, 0), np.minimum(media + h, 100), color=c,
                        alpha=0.12, lw=0)
        ax.plot(malla, media, color=c, lw=1.5, label=NOMBRE_MECANISMO.get(mec, mec))
        nsem.append(len(a))
    ax.set_ylim(0, 102)
    ax.set_xlim(0, t_max if t_max > 0 else 1.0)
    ax.set_xlabel("Tiempo desde el inicio de la siembra (h)")
    ax.set_ylabel("Área sembrada (%)" if columna == "sembrado_frac" else "Área surcada (%)")
    return nsem


def histograma_T(df, escenario=None, metrica="T_h", fig=None, bins=12):
    """Distribución de ``metrica`` (por defecto T en horas) entre semillas, un panel por mecanismo."""
    d = df if escenario is None or "escenario" not in df.columns else \
        df[df["escenario"].astype(str) == str(escenario)]
    mecs = _mecanismos(d) if len(d) else []
    if fig is None:
        fig = plt.figure(figsize=(8.5, 0.8 + 1.5 * max(1, len(mecs))), layout="constrained")
    axs = fig.subplots(max(1, len(mecs)), 1, sharex=True, sharey=True, squeeze=False)[:, 0]
    vals = pd.to_numeric(d[metrica], errors="coerce").dropna() * ESCALA.get(metrica, 1)
    if len(vals) == 0:
        _sin_datos(axs[0], "Sin datos para el histograma.")
        return fig
    lo, hi = float(vals.min()), float(vals.max())
    if hi - lo < 1e-9:
        lo, hi = lo - 0.5, hi + 0.5
    bordes = np.linspace(lo, hi, bins + 1)
    dec = DECIMALES.get(metrica, 1)
    for ax, mec in zip(axs, mecs):
        v = pd.to_numeric(d.loc[d["mecanismo"].astype(str) == mec, metrica], errors="coerce").dropna() \
            * ESCALA.get(metrica, 1)
        ax.hist(v, bins=bordes, color=_color_mecanismo(mec), edgecolor=SUPERFICIE, linewidth=1.5)
        media = float(v.mean())
        de = float(v.std(ddof=1)) if len(v) > 1 else np.nan
        ax.axvline(media, color=TINTA, lw=1.0)
        derecha = (media - lo) / (hi - lo) > 0.6
        ax.annotate(f"media {media:,.{dec}f} · DE {de:,.{dec}f} · n = {len(v)}", (media, 1),
                    xycoords=("data", "axes fraction"), xytext=(-4 if derecha else 4, -2),
                    textcoords="offset points", va="top", ha="right" if derecha else "left",
                    fontsize=8, color=TINTA, path_effects=_HALO)
        ax.set_title(NOMBRE_MECANISMO.get(mec, mec), fontsize=9, fontweight="normal", loc="left", pad=3)
        ax.set_ylabel("Semillas")
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
        ax.grid(axis="x", visible=False)
    axs[0].set_ylim(0, axs[0].get_ylim()[1] * 1.25)
    axs[-1].set_xlabel(ETIQUETA.get(metrica, metrica))
    _titulo_fig(fig, "¿Qué tan variable es el resultado? Distribución entre semillas"
                + (f" · {escenario}" if escenario else ""),
                "Un panel por mecanismo con los mismos intervalos; línea vertical: media")
    return fig


def _normalizar_sens_eco(df, n_tractores=None):
    """Lleva la tabla de sensibilidad económica a una fila por (parámetro[, mecanismo,
    hectáreas]) con valor_bajo/alto, costo_bajo/base/alto y n_opt_bajo/base/alto.

    Acepta la salida larga de ``metricas.sensibilidad_economica`` (``parametro, nivel, valor,
    mecanismo, hectareas, n_tractores, costo_ha_media, n_optimo``). Con ``n_tractores=None`` el
    costo de cada nivel es el de la flota óptima (mínimo sobre N); con un número, el de esa flota.
    """
    d = df.copy()
    if {"costo_bajo", "costo_alto"} <= set(d.columns):
        return d
    if "nivel" not in d.columns:
        raise ValueError("Formato de sensibilidad económica no reconocido: se esperan columnas "
                         "costo_bajo/costo_alto o nivel + costo_ha_media")
    costo = next(c for c in ("costo_ha_media", "costo_ha", "costo") if c in d.columns)
    d[costo] = pd.to_numeric(d[costo], errors="coerce")
    llaves = [c for c in ("parametro", "mecanismo", "hectareas") if c in d.columns]
    if "n_tractores" in d.columns:
        if n_tractores is not None:
            d = d[pd.to_numeric(d["n_tractores"], errors="coerce") == float(n_tractores)]
        else:
            d = d.dropna(subset=[costo])
            d = d.loc[d.groupby(llaves + ["nivel"])[costo].idxmin()]
    filas = []
    for clave, g in d.groupby(llaves, sort=False):
        clave = clave if isinstance(clave, tuple) else (clave,)
        fila = dict(zip(llaves, clave))
        for niv in ("bajo", "base", "alto"):
            gg = g[g["nivel"].astype(str) == niv]
            fila[f"costo_{niv}"] = float(gg[costo].mean()) if len(gg) else np.nan
            fila[f"valor_{niv}"] = gg["valor"].iloc[0] if "valor" in gg.columns and len(gg) else ""
            if "n_tractores" in gg.columns and len(gg):
                fila[f"n_opt_{niv}"] = int(gg["n_tractores"].iloc[0])
        filas.append(fila)
    return pd.DataFrame(filas)


def _fmt_valor(v):
    x = _num(v)
    if np.isnan(x):
        return str(v)
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    return f"{x:g}"


NOMBRE_PARAMETRO_ECO = {
    "precio_tractor": "Precio del tractor ($)",
    "dias_laborables": "Días laborables (fracción)",
    "jornada_h": "Jornada (h/día)",
    "precio_maiz": "Precio del maíz ($/t)",
    "perdida_dia": "Pérdida por día de retraso (fracción)",
    "ventana_dias": "Duración de la ventana (días)",
    "temporadas_vida": "Vida útil (temporadas)",
    "precio_diesel": "Precio del diésel ($/L)",
    "rendimiento_t_ha": "Rendimiento (t/ha)",
}


def tornado(df_sens_eco, mecanismo=None, hectareas=None, n_tractores=None, ax=None):
    """Cambio del costo por hectárea al mover cada parámetro a su valor bajo y alto.

    Recibe la salida de ``metricas.sensibilidad_economica``. Con ``n_tractores=None`` compara el
    costo de la flota óptima en cada nivel (y anota el N óptimo); con un número, el de esa flota.
    """
    d = df_sens_eco
    if mecanismo is not None and "mecanismo" in d.columns:
        d = d[d["mecanismo"].astype(str) == str(mecanismo)]
    if hectareas is not None and "hectareas" in d.columns:
        d = d[pd.to_numeric(d["hectareas"], errors="coerce") == float(hectareas)]
    d = _normalizar_sens_eco(d, n_tractores)
    d = d.drop_duplicates(subset=["parametro"]).copy()
    d["d_bajo"] = d["costo_bajo"] - d["costo_base"]
    d["d_alto"] = d["costo_alto"] - d["costo_base"]
    d["rango"] = (d[["d_bajo", "d_alto"]].abs()).max(axis=1).fillna(0)
    d = d.sort_values("rango", ascending=True, kind="stable").reset_index(drop=True)
    fig, ax = _nueva(ax, (10, 1.5 + 0.5 * len(d)))
    con_n = "n_opt_base" in d.columns
    for i, fila in d.iterrows():
        for lado, dy in (("bajo", 0.19), ("alto", -0.19)):
            v = fila[f"d_{lado}"]
            if np.isnan(v):
                continue
            col = AZUL_DIV if v < -1e-9 else (ROJO_DIV if v > 1e-9 else GRIS_DIV)
            ax.barh(i + dy, v, height=0.34, color=col, edgecolor="none")
            etiqueta = f"{lado}: {_fmt_valor(fila.get(f'valor_{lado}', ''))} → {_dinero(v)}"
            if abs(v) <= 1e-9:
                etiqueta = f"{lado}: {_fmt_valor(fila.get(f'valor_{lado}', ''))} → sin cambio"
            n_lado, n_base = _num(fila.get(f"n_opt_{lado}")), _num(fila.get("n_opt_base"))
            if con_n and not np.isnan(n_lado) and n_lado != n_base:
                etiqueta += f" · el óptimo cambia a N = {int(n_lado)}"
            ax.annotate(etiqueta, (v, i + dy), xytext=(4 if v >= 0 else -4, 0),
                        textcoords="offset points", ha="left" if v >= 0 else "right", va="center",
                        fontsize=7.5, color=TINTA_2)
    ax.axvline(0, color=TINTA_3, lw=1.0, zorder=3)
    nombres = []
    for _i, fila in d.iterrows():
        corto = _base_parametro(fila["parametro"])
        nombre = NOMBRE_PARAMETRO_ECO.get(corto, corto.replace("_", " "))
        nombres.append(f"{nombre}\nbase {_fmt_valor(fila.get('valor_base', ''))}")
    ax.set_yticks(np.arange(len(d)), nombres)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", visible=False)
    lim = float(np.nanmax(d["rango"])) if len(d) and np.nanmax(d["rango"]) > 0 else 1.0
    ax.set_xlim(-lim * 2.1, lim * 2.1)
    ax.set_ylim(-0.6, len(d) - 0.4)
    _formato_dinero(ax, "x")
    ax.set_xlabel("Cambio del costo por hectárea contra el caso base ($/ha)")
    base = float(d["costo_base"].iloc[0]) if len(d) else np.nan
    ax.legend(handles=[Patch(color=AZUL_DIV, label="Baja el costo"),
                       Patch(color=ROJO_DIV, label="Sube el costo")],
              loc="lower left", bbox_to_anchor=(0, 1.0), ncols=2, borderaxespad=0.2)
    partes = []
    if mecanismo is not None:
        partes.append(NOMBRE_MECANISMO.get(str(mecanismo), str(mecanismo)))
    if hectareas is not None:
        partes.append(f"{_num(hectareas):g} ha")
    if n_tractores is None and con_n:
        partes.append(f"flota óptima en cada nivel (base N* = {int(d['n_opt_base'].iloc[0])})")
    elif n_tractores is not None:
        partes.append(f"N = {n_tractores}")
    partes.append(f"costo base {_dinero(base)}/ha")
    ax.set_title("¿Qué parámetro pesa más? Sensibilidad del costo por hectárea", loc="left",
                 pad=40, fontsize=11)
    ax.annotate(" · ".join(partes) + " · un parámetro a la vez, los demás en su valor base",
                xy=(0, 1), xycoords="axes fraction", xytext=(0, 26), textcoords="offset points",
                fontsize=8, color=TINTA_2, va="bottom")
    return fig


def sens_arquitectura(df_sens_arq, metricas=None, fila_costo=True, fig=None):
    """Un panel por parámetro de arquitectura con su métrica relevante contra el valor; con
    ``fila_costo`` agrega una segunda fila con el costo por hectárea."""
    metricas = {**METRICA_ARQ, **(metricas or {})}
    d = df_sens_arq.copy()
    d["_p"] = d["parametro"].astype(str).map(_base_parametro)
    params = [p for p in NOMBRE_PARAMETRO_ARQ if p in set(d["_p"])] + \
             sorted(p for p in set(d["_p"]) if p not in NOMBRE_PARAMETRO_ARQ)
    filas = [None, "costo_ha"] if fila_costo else [None]
    if fig is None:
        fig = plt.figure(figsize=(3.7 * max(1, len(params)), 3.0 * len(filas) + 0.7), layout="constrained")
    axs = fig.subplots(len(filas), max(1, len(params)), squeeze=False)
    todos = []
    for j, p in enumerate(params):
        sub = d[d["_p"] == p].copy()
        sub["valor"] = pd.to_numeric(sub["valor"], errors="coerce")
        esc_x = 100 if p == "perdida_mensajes" else 1
        for i, fm in enumerate(filas):
            ax = axs[i, j]
            met = metricas.get(p, "T_h") if fm is None else fm
            for mec in _mecanismos(sub):
                s = sub[sub["mecanismo"].astype(str) == mec]
                if met in s.columns and len(s):
                    _linea_ic(ax, s, "valor", met, mec, escala_x=esc_x)
                    if mec not in todos:
                        todos.append(mec)
            vals = sorted(sub["valor"].dropna().unique() * esc_x)
            ax.set_xticks(vals, [f"{v:g}" for v in vals])
            ax.set_ylabel(ETIQUETA.get(met, met))
            if met in ("costo_ha", "J"):
                _formato_dinero(ax)
            if i == 0:
                ax.set_title(NOMBRE_PARAMETRO_ARQ.get(p, p), fontsize=9.5)
            if i == len(filas) - 1:
                ax.set_xlabel(NOMBRE_PARAMETRO_ARQ.get(p, p))
    if todos:
        todos = _ordenar_mecs(todos)
        fig.legend(handles=_leyenda_mecanismos(todos, marcador=True), loc="outside lower center",
                   ncols=len(todos))
    n = int(d.groupby(["_p", "valor", "mecanismo"]).size().min()) if len(d) else 0
    _titulo_fig(fig, "Sensibilidad de la arquitectura: cada parámetro contra la métrica que debería mover",
                f"Media de {n} semillas por punto; banda: IC 95 % · " + _condiciones_comunes(d))
    return fig


# ============================================================ modelo sustituto (machine learning)

# N es ordinal: una sola tonalidad de claro (1 tractor) a oscuro (6 tractores)
_COLORES_N = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#0d366b", "#081f3d")
_TICKS_HA = (10, 20, 40, 80, 160, 320)


def color_n(n):
    """Color del número de tractores N (rampa de azules)."""
    n = int(n)
    return _COLORES_N[min(max(n, 1), len(_COLORES_N)) - 1]


def _tinta_sobre(n):
    return SUPERFICIE if int(n) >= 4 else TINTA


def _eje_hectareas(ax, ha_min, ha_max):
    ax.set_xscale("log")
    ticks = [t for t in _TICKS_HA if ha_min * 0.99 <= t <= ha_max * 1.01]
    ax.set_xticks(ticks, [f"{t:g}" for t in ticks])
    ax.xaxis.set_minor_locator(mpl.ticker.NullLocator())
    ax.set_xlim(ha_min, ha_max)


_TICKS_DINERO = (1000, 1500, 2000, 3000, 5000, 7500, 10000, 15000, 20000, 30000, 50000)


def _ticks_dinero(eje, lo, hi):
    """Marcas legibles en un eje logarítmico de pesos."""
    eje.set_major_locator(mpl.ticker.FixedLocator([t for t in _TICKS_DINERO if lo <= t <= hi]))
    eje.set_major_formatter(FuncFormatter(lambda v, _p: _dinero(v)))
    eje.set_minor_locator(mpl.ticker.NullLocator())


def _leyenda_n(ns, extra=()):
    return [Patch(fc=color_n(n), ec="none", label=f"N = {n}") for n in ns] + list(extra)


def sustituto_optimo(optimo, cruces=None, observado=None, fig=None):
    """Probabilidad de que cada N sea el óptimo contra el tamaño de campo (área apilada), una fila
    por mecanismo, con los cambios de N óptimo (línea y banda IC 95 %) y el óptimo observado en
    los tamaños del barrido.

    ``optimo``: tabla ``optimo`` de ``siembra.sustituto.analizar``; ``cruces``: tabla ``cruces``;
    ``observado``: ``metricas.optimo_por_campo(barrido)`` (opcional).
    """
    d = optimo.copy()
    mecs = _mecanismos(d)
    pcols = sorted((c for c in d.columns if c.startswith("p_N")), key=lambda c: int(c[3:]))
    ns_todos = [int(c[3:]) for c in pcols]
    if fig is None:
        fig = plt.figure(figsize=(10, 2.35 * len(mecs) + 1.0), layout="constrained")
    axs = fig.subplots(len(mecs), 1, sharex=True, squeeze=False).ravel()
    ha_min, ha_max = float(d["hectareas"].min()), float(d["hectareas"].max())
    usados = set()
    for ax, mec in zip(axs, mecs):
        g = d[d["mecanismo"].astype(str) == mec].sort_values("hectareas")
        ha = g["hectareas"].to_numpy(dtype=float)
        ps = np.array([g[c].to_numpy(dtype=float) for c in pcols])
        visibles = [i for i in range(len(pcols)) if ps[i].max() > 0.005]
        usados |= {ns_todos[i] for i in visibles}
        ax.stackplot(ha, ps[visibles], colors=[color_n(ns_todos[i]) for i in visibles], lw=0)
        # Etiqueta "N = k" en el centro de cada tramo donde k es el óptimo
        n_opt = g["n_optimo"].to_numpy(dtype=int)
        cortes = np.flatnonzero(np.diff(n_opt)) + 1
        for tramo in np.split(np.arange(len(ha)), cortes):
            if len(tramo) < 3:
                continue
            i = tramo[len(tramo) // 2]
            n = n_opt[i]
            j = ns_todos.index(n)
            y = ps[:j, i].sum() + ps[j, i] / 2
            ax.text(math.sqrt(ha[tramo[0]] * ha[tramo[-1]]), y, f"N = {n}", ha="center", va="center",
                    fontsize=9, fontweight="semibold", color=_tinta_sobre(n))
        if cruces is not None and len(cruces):
            nivel, previo = 0, None
            cm = cruces[cruces["mecanismo"].astype(str) == mec].sort_values("hectareas")
            for _, c in cm.iterrows():
                # Etiquetas escalonadas cuando dos cambios quedan a menos de ~25 % de distancia
                cerca = previo is not None and math.log(c["hectareas"] / previo) < 0.22
                nivel = (nivel + 1) % 4 if cerca else 0
                previo = c["hectareas"]
                ax.axvspan(c["ic_bajo"], c["ic_alto"], color=TINTA, alpha=0.14, lw=0, zorder=3)
                ax.axvline(c["hectareas"], color=TINTA, lw=1.0, ls=(0, (4, 2)), zorder=4)
                ax.annotate(f"{int(c['n_de'])} a {int(c['n_a'])}: {c['hectareas']:.0f} ha",
                            (c["hectareas"], 0.97 - 0.13 * nivel),
                            xytext=(3, 0), textcoords="offset points", ha="left", va="top", fontsize=7.5,
                            color=TINTA, path_effects=_HALO, zorder=5)
        if observado is not None and len(observado):
            o = observado[observado["mecanismo"].astype(str) == mec]
            for _, r in o.iterrows():
                ax.plot([r["hectareas"]], [1.07], marker="v", ms=7, mfc=color_n(r["n_optimo"]), mec=TINTA,
                        mew=0.8, ls="", clip_on=False, zorder=6)
                ax.annotate(f"{int(r['n_optimo'])}", (r["hectareas"], 1.07), xytext=(0, 5), textcoords="offset points",
                            ha="center", va="bottom", fontsize=7.5, color=TINTA, annotation_clip=False)
        ax.set_ylim(0, 1)
        ax.set_yticks([0, 0.5, 1], ["0", "50 %", "100 %"])
        ax.set_ylabel("P(N es el óptimo)")
        ax.grid(False)
        _titulo_ax(ax, NOMBRE_MECANISMO.get(mec, mec), tam=10, extra=22)
    _eje_hectareas(axs[-1], ha_min, ha_max)
    axs[-1].set_xlabel("Tamaño del campo (ha, escala logarítmica)")
    extra = [Patch(fc=TINTA, alpha=0.14, ec="none", label="Cambio de N óptimo (IC 95 %)")]
    if observado is not None and len(observado):
        extra.append(Line2D([], [], marker="v", ls="", ms=7, mfc=FONDO_TARJETA, mec=TINTA, mew=0.8,
                            label="Óptimo observado en el barrido"))
    fig.legend(handles=_leyenda_n(sorted(usados), extra), loc="outside lower center",
               ncols=min(8, len(usados) + len(extra)))
    _titulo_fig(fig, "¿Cuántos tractores por hectárea? N óptimo según el modelo sustituto",
                "Probabilidad de que cada N tenga el menor costo por hectárea, a partir de las muestras del "
                "modelo (árboles del Random Forest o posterior del proceso gaussiano); las etiquetas marcan el "
                "N con menor costo esperado")
    return fig


def sustituto_costos(curva, observados=None, fig=None):
    """Costo por hectárea predicho contra el tamaño de campo, una línea por N (banda IC 95 %),
    un panel por mecanismo, con los puntos simulados encima. Las N que el modelo no ha visto
    simuladas para ese mecanismo van punteadas.

    ``observados``: tabla de ``siembra.sustituto.preparar`` (``costo_obs`` y ``costo_obs_ic``).
    """
    d = curva.copy()
    mecs = _mecanismos(d)
    if fig is None:
        fig = plt.figure(figsize=(4.3 * len(mecs), 4.3), layout="constrained")
    axs = fig.subplots(1, len(mecs), sharey=True, squeeze=False).ravel()
    ns = sorted(int(n) for n in d["n_tractores"].unique())
    env = d.groupby(["mecanismo", "hectareas"])["costo_ha"].min()
    lo, hi = env.min() * 0.92, env.max() * 1.35
    ha_min, ha_max = float(d["hectareas"].min()), float(d["hectareas"].max())
    for ax, mec in zip(axs, mecs):
        g = d[d["mecanismo"].astype(str) == mec]
        for n in ns:
            s = g[g["n_tractores"] == n].sort_values("hectareas")
            if len(s) == 0:
                continue
            ext = bool(s["extrapolado"].astype(str).str.lower().eq("true").any())
            ax.fill_between(s["hectareas"], s["ic_bajo"], s["ic_alto"], color=color_n(n), alpha=0.25, lw=0)
            ax.plot(s["hectareas"], s["costo_ha"], color=color_n(n), lw=1.6, ls=(0, (3, 2)) if ext else "-")
        e = env.loc[mec]
        ax.plot(e.index, e.values, color=TINTA, lw=0.9, zorder=4)
        if observados is not None and len(observados):
            o = observados[observados["mecanismo"].astype(str) == mec]
            for n in ns:
                oo = o[o["n_tractores"] == n]
                if len(oo):
                    ax.errorbar(oo["hectareas"], oo["costo_obs"], yerr=oo["costo_obs_ic"].fillna(0), fmt="o", ms=4,
                                mfc=color_n(n), mec=TINTA, mew=0.6, ecolor=TINTA_2, elinewidth=0.8, zorder=5)
        ax.set_yscale("log")
        ax.set_ylim(lo, hi)
        _ticks_dinero(ax.yaxis, lo, hi)
        _eje_hectareas(ax, ha_min, ha_max)
        ax.set_xlabel("Tamaño del campo (ha)")
        ax.set_title(NOMBRE_MECANISMO.get(mec, mec), fontsize=10)
    axs[0].set_ylabel(ETIQUETA["costo_ha"] + ", escala log")
    extra = [Line2D([], [], color=TINTA, lw=0.9, label="Mínimo sobre N"),
             Line2D([], [], color=TINTA_3, lw=1.6, ls=(0, (3, 2)), label="N sin corridas en el entrenamiento"),
             Line2D([], [], marker="o", ls="", ms=4, mfc=FONDO_TARJETA, mec=TINTA, mew=0.6,
                    label="Simulado (media ± IC 95 %)")]
    fig.legend(handles=_leyenda_n(ns, extra), loc="outside lower center", ncols=min(6, len(ns) + len(extra)))
    _titulo_fig(fig, "Costo por hectárea predicho por el modelo sustituto",
                "Línea: costo esperado; banda: IC 95 % del modelo; el eje vertical está recortado alrededor "
                "del mínimo para que se vean los cruces")
    return fig


def sustituto_evaluacion(detalle, verificacion=None, fig=None):
    """Costo predicho contra observado en corridas que el modelo no vio: un panel por modelo
    (solo barrido, barrido + activo) y, si se pasa, la verificación prospectiva del aprendizaje
    activo (predicción hecha antes de simular cada punto)."""
    paneles = [(m, detalle[detalle["modelo"] == m]) for m in pd.unique(detalle["modelo"])]
    if verificacion is not None and len(verificacion):
        paneles.append(("verificación prospectiva (aprendizaje activo)", verificacion))
    if fig is None:
        fig = plt.figure(figsize=(4.0 * len(paneles), 4.2), layout="constrained")
    axs = fig.subplots(1, len(paneles), squeeze=False).ravel()
    todos = pd.concat([p[["costo_obs", "costo_pred"]] for _, p in paneles])
    lo, hi = np.nanmin(todos.values) * 0.9, np.nanmax(todos.values) * 1.1
    for ax, (titulo, p) in zip(axs, paneles):
        p = p.dropna(subset=["costo_obs", "costo_pred"])
        ax.plot([lo, hi], [lo, hi], color=EJE, lw=1, zorder=1)
        for mec in _mecanismos(p):
            q = p[p["mecanismo"].astype(str) == mec]
            yerr = np.vstack([q["costo_pred"] - q["ic_bajo"], q["ic_alto"] - q["costo_pred"]]).clip(min=0)
            ax.errorbar(q["costo_obs"], q["costo_pred"], yerr=yerr, fmt="o", ms=3.5, color=_color_mecanismo(mec),
                        mec=SUPERFICIE, mew=0.4, elinewidth=0.6, alpha=0.85, zorder=3)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
        for eje in (ax.xaxis, ax.yaxis):
            _ticks_dinero(eje, lo, hi)
        ax.set_xlabel("Costo simulado ($/ha)")
        error = p["error_pct"].abs().mean()
        cob = p["dentro_ic"].astype(str).str.lower().eq("true").mean()
        ax.text(0.03, 0.97, f"error absoluto medio {error:.1f} %\ndentro del IC 95 %: {100 * cob:.0f} %\n"
                f"{len(p)} puntos", transform=ax.transAxes, ha="left", va="top", fontsize=8, color=TINTA,
                bbox=dict(boxstyle="round,pad=0.35", fc=FONDO_TARJETA, ec="none"))
        ax.set_title(titulo.capitalize(), fontsize=10)
    axs[0].set_ylabel("Costo predicho ($/ha)")
    fig.legend(handles=_leyenda_mecanismos(_mecanismos(detalle), marcador=True), loc="outside lower center",
               ncols=3)
    _titulo_fig(fig, "¿Qué tan bien predice el modelo sustituto? Predicho contra simulado",
                "Corridas que el modelo no usó para entrenar; barra vertical: IC 95 % predicho; línea gris: "
                "predicción perfecta")
    return fig


def sustituto_mapa(mapa, parametro, base=None, fig=None):
    """N óptimo según el tamaño de campo y un parámetro económico, un panel por mecanismo.

    ``mapa``: tabla ``mapa`` de ``siembra.sustituto.analizar``; ``base``: valor del caso base
    (se marca con una línea)."""
    d = mapa[mapa["parametro"] == parametro]
    mecs = _mecanismos(d)
    if fig is None:
        fig = plt.figure(figsize=(4.3 * len(mecs), 3.4), layout="constrained")
    axs = fig.subplots(1, len(mecs), sharey=True, squeeze=False).ravel()
    ns = sorted(int(n) for n in d["n_optimo"].unique())
    cmap = mcolors.ListedColormap([color_n(n) for n in range(1, max(ns) + 1)])
    norm = mcolors.BoundaryNorm(np.arange(0.5, max(ns) + 1.5), cmap.N)
    corto = parametro.split(".")[-1]
    for ax, mec in zip(axs, mecs):
        g = d[d["mecanismo"].astype(str) == mec].pivot_table(index="valor", columns="hectareas", values="n_optimo")
        ha, val = g.columns.to_numpy(dtype=float), g.index.to_numpy(dtype=float)
        dv = np.diff(val).mean() if len(val) > 1 else 1.0
        ax.pcolormesh(np.r_[ha, ha[-1] + 1] - 0.5, np.r_[val - dv / 2, val[-1] + dv / 2], g.values,
                      cmap=cmap, norm=norm, shading="flat")
        if base is not None:
            ax.axhline(base, color=TINTA, lw=1, ls=(0, (4, 2)))
        _eje_hectareas(ax, ha.min(), ha.max())
        ax.grid(False)
        ax.set_xlabel("Tamaño del campo (ha)")
        ax.set_title(NOMBRE_MECANISMO.get(mec, mec), fontsize=10)
    axs[0].set_ylabel(NOMBRE_PARAMETRO_ECO.get(corto, corto))
    extra = [Line2D([], [], color=TINTA, lw=1, ls=(0, (4, 2)), label="Caso base")] if base is not None else []
    fig.legend(handles=_leyenda_n(ns, extra), loc="outside lower center", ncols=len(ns) + len(extra))
    _titulo_fig(fig, f"N óptimo según el tamaño de campo y {NOMBRE_PARAMETRO_ECO.get(corto, corto).lower()}",
                "Costo esperado del modelo sustituto; el parámetro solo cambia la función de costo, así que no "
                "hace falta volver a simular")
    return fig
