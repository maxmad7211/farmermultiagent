"""Vista 2D de una corrida con el coordinador supervisor (M3) o de su par en M2.

Corre una corrida detallada de un escenario de M3 (o carga una ya guardada) y escribe en la
carpeta de salida
- `<id>.gif` — animación del campo con el fuego, la zona prohibida, la pipa y la grúa en acción,
  y a la derecha los últimos avisos y decisiones del coordinador.
- `<id>_mapa.png` — el campo en el momento más interesante (fuego más grande o remolque).
- `<id>_registro.csv` — el registro completo (eventos del mundo, avisos y decisiones con su motivo).
- `../corridas/<id>/` — la corrida guardada, junto a las demás corridas detalladas (se puede volver a
  abrir con --corrida).

Uso (desde la raíz del proyecto)
    python herramientas/vista_m3.py                          # incendio, M3, semilla 0
    python herramientas/vista_m3.py --escenario falla --mecanismo M2
    python herramientas/vista_m3.py --escenario obstaculo --semilla 3 --cuadros 150
    python herramientas/vista_m3.py --corrida resultados/corridas/m3_incendio_M3_s0
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import matplotlib.pyplot as plt  # noqa — E402
import numpy as np  # noqa — E402

from siembra import telemetria, viz  # noqa — E402
from siembra.config import aplicar, cargar_config  # noqa — E402
from siembra.experimentos import escenarios_m3  # noqa — E402
from siembra.modelo import simular  # noqa — E402

SALIDA = RAIZ / "resultados" / "m3"


def _momento(corrida):
    """Paso más ilustrativo — cuando más celdas arden; si no hubo fuego, a la mitad de un remolque o
    cuando aparece el obstáculo; si nada de eso, el final."""
    ev = corrida.get("eventos") or {}
    tq = np.asarray(ev.get("t_quemado", []))
    if tq.size and (tq >= 0).any():
        tf = np.asarray(ev["t_fin_fuego"])
        ts = np.unique(tq[tq >= 0])
        fin = int(tf.max()) if (tf >= 0).any() else int(ts.max())
        mejor, n_mejor = int(ts[0]), -1
        for t in np.linspace(int(ts[0]), fin, 60).astype(int):
            n = int(((tq >= 0) & (tq <= t) & ((tf < 0) | (tf > t))).sum())
            if n > n_mejor:
                mejor, n_mejor = int(t), n
        return mejor
    pasos = corrida.get("pasos")
    if pasos is not None and len(pasos):
        rem = pasos[(pasos["implemento"].astype(str) == "grua") & (pasos["intencion"].astype(str) == "remolcar")]
        if len(rem):
            return int(rem["t"].iloc[len(rem) // 2])
    obs = ev.get("obstaculos_nuevos") or []
    if obs:
        return int(obs[0][4]) + 40
    return None


def main(argv=None):
    p = argparse.ArgumentParser(prog="python herramientas/vista_m3.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--escenario", default="incendio",
                   choices=[k.replace("m3_", "") for k in escenarios_m3()],
                   help="escenario de la comparación M2 contra M3 (por defecto incendio)")
    p.add_argument("--mecanismo", default="M3", choices=("M2", "M3"))
    p.add_argument("--semilla", type=int, default=0)
    p.add_argument("--corrida", default=None, help="carpeta de una corrida guardada (en lugar de simular)")
    p.add_argument("--cuadros", type=int, default=120, help="cuadros de la animación (por defecto 120)")
    p.add_argument("--salida", default=str(SALIDA), help=f"carpeta de salida (por defecto {SALIDA})")
    a = p.parse_args(argv)
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    viz.estilo()

    if a.corrida:
        corrida = telemetria.cargar_corrida(a.corrida)
        ident = Path(a.corrida).name
    else:
        nombre, cambios, _tipo = escenarios_m3()[f"m3_{a.escenario}"]
        cfg = aplicar(cargar_config(), {**cambios, "mecanismo": a.mecanismo, "semilla": a.semilla})
        print(f"Simulando {nombre} · {a.mecanismo} · semilla {a.semilla} ...", flush=True)
        corrida = simular(cfg, detalle=True)
        ident = f"m3_{a.escenario}_{a.mecanismo}_s{a.semilla}"
        telemetria.guardar_corrida(corrida, salida.parent / "corridas" / ident)

    t = _momento(corrida)
    fig = viz.mapa_campo(None, corrida, t=t)
    viz.guardar(fig, f"{ident}_mapa", salida)
    plt.close(fig)
    anim = viz.animacion(corrida, n_cuadros=a.cuadros, dpi=70)
    ruta_gif = viz.guardar_gif(anim, salida / f"{ident}.gif", fps=10)
    plt.close("all")
    reg = viz.registro_coordinador(corrida)
    reg.to_csv(salida / f"{ident}_registro.csv", index=False)

    r = corrida["resumen"]
    print(f"Listo, {ruta_gif}")
    print(f"  cobertura {r['cobertura']:.1%} · {r['T_h']:.1f} h · colisiones {r['colisiones']}"
          f" · entradas a zona prohibida {r.get('entradas_prohibidas', 0)}")
    decisiones = reg[reg["tipo"].isin(["decision", "plan"]) | (reg["fuente"] == "mundo")]
    if len(decisiones):
        print("\nEventos y decisiones del coordinador:")
        for _i, f in decisiones.head(40).iterrows():
            motivo = f" (motivo, {f['motivo']})" if f["motivo"] else ""
            print(f"  {f['hora']:6.2f} h  {f['texto']}{motivo}")
        if len(decisiones) > 40:
            print(f"  ... {len(decisiones) - 40} más en {ident}_registro.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
