"""Corre todo el proyecto de punta a punta: experimentos, modelo sustituto, dashboard y pruebas.

Uso (desde la raíz del proyecto):

    .venv/Scripts/python correr_todo.py                  # modo rápido
    .venv/Scripts/python correr_todo.py --modo completo  # lo de la propuesta (tarda horas)
    .venv/Scripts/python correr_todo.py --nucleos 6 --semillas 3

Pasos:
1. `python -m siembra.experimentos --modo <modo>` (barrido, escenarios, sensibilidad, detalladas).
2. `python -m siembra.sustituto --modo <modo>` (modelo sustituto y aprendizaje activo) y
   `herramientas/comparar_modelos.py` (comparación con los métodos del curso).
3. `herramientas/construir_dashboard.py --ejecutar` (si todavía no existe, avisa y sigue).
4. `pytest -q`.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DASHBOARD = RAIZ / "herramientas" / "construir_dashboard.py"


def _titulo(texto):
    print(f"\n{'=' * 72}\n{texto}\n{'=' * 72}", flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description="Experimentos, modelo sustituto, dashboard y pruebas en un solo comando.")
    p.add_argument("--modo", choices=("rapido", "completo"), default="rapido")
    p.add_argument("--nucleos", type=int, default=None, help="procesos en paralelo (por defecto núcleos - 1)")
    p.add_argument("--semillas", type=int, default=None, help="sobrescribe el número de semillas del modo")
    p.add_argument("--salida", default=None, help="carpeta de resultados (por defecto resultados/)")
    args = p.parse_args(argv)

    inicio = time.perf_counter()
    codigos = {}

    _titulo(f"1/4 Experimentos (modo {args.modo})")
    from siembra import experimentos

    argumentos = ["--modo", args.modo]
    for nombre in ("nucleos", "semillas", "salida"):
        valor = getattr(args, nombre)
        if valor is not None:
            argumentos += [f"--{nombre}", str(valor)]
    codigos["experimentos"] = experimentos.main(argumentos)

    _titulo(f"2/4 Modelo sustituto (modo {args.modo})")
    from siembra import sustituto

    argumentos = ["--modo", args.modo]
    for nombre in ("nucleos", "salida"):
        valor = getattr(args, nombre)
        if valor is not None:
            argumentos += [f"--{nombre}", str(valor)]
    codigos["sustituto"] = sustituto.main(argumentos)
    if codigos["sustituto"] in (0, 1):
        # Comparación con los métodos de regresión del curso (justifica el modelo elegido)
        cmd = [sys.executable, str(RAIZ / "herramientas" / "comparar_modelos.py")]
        if args.salida is not None:
            cmd += ["--salida", str(args.salida)]
        codigos["comparacion"] = subprocess.run(cmd, cwd=RAIZ).returncode

    _titulo("3/4 Dashboard")
    if DASHBOARD.exists():
        codigos["dashboard"] = subprocess.run([sys.executable, str(DASHBOARD), "--ejecutar"], cwd=RAIZ).returncode
    else:
        print(f"Aviso: no existe {DASHBOARD.relative_to(RAIZ)} todavía; se omite el dashboard.", flush=True)
        codigos["dashboard"] = None

    _titulo("4/4 Pruebas")
    codigos["pruebas"] = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=RAIZ).returncode

    _titulo(f"Resumen ({time.perf_counter() - inicio:.0f} s)")
    textos = {0: "ok", 1: "con errores", 2: "no se pudo correr", None: "omitido"}
    for paso, codigo in codigos.items():
        print(f"  {paso:<13} {textos.get(codigo, f'código {codigo}')}", flush=True)
    return max((c for c in codigos.values() if c is not None), default=0)


if __name__ == "__main__":
    sys.exit(main())
