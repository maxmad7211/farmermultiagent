"""Genera `notebooks/dashboard.ipynb` y, si se pide, lo ejecuta y lo exporta a HTML.

Uso (desde la raíz del proyecto, con el entorno virtual):

    python herramientas/construir_dashboard.py                    # solo escribe el notebook
    python herramientas/construir_dashboard.py --ejecutar         # lo escribe y lo ejecuta
    python herramientas/construir_dashboard.py --ejecutar --html  # además: resultados/dashboard.html
    python herramientas/construir_dashboard.py --ejecutar --resultados otra/carpeta

El notebook lee los datos de `resultados/` (o de la carpeta en la variable de entorno
`SIEMBRA_RESULTADOS`, que `--resultados` fija) y guarda cada figura en `<resultados>/figuras/`.
"""

import argparse
import os
import sys
import textwrap
import time
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

RAIZ = Path(__file__).resolve().parent.parent
NOTEBOOK = RAIZ / "notebooks" / "dashboard.ipynb"


def _md(texto):
    return new_markdown_cell(textwrap.dedent(texto).strip())


def _py(texto):
    return new_code_cell(textwrap.dedent(texto).strip())


def celdas():
    """Celdas del dashboard, en orden."""
    c = []

    # ------------------------------------------------------------------ portada
    c.append(_md("""
        # Dashboard: flota autónoma de tractores para la siembra de maíz

        TC2008B Sistemas Multiagentes · reto John Deere. Este tablero resume las corridas de la
        simulación (AgentPy) de una flota de tractores que surcan y siembran un campo dividido en
        celdas de 10 × 10 m. Busca cuántos tractores por hectárea minimizan el costo por hectárea y
        compara tres mecanismos de coordinación:

        | Mecanismo | Coordinación |
        |---|---|
        | **M0** | Franjas fijas, sin comunicación |
        | **M1** | Contract Net (subasta de hileras) |
        | **M2** | Contract Net + broadcast + blackboard (fila de la estación y tabla de reservas de Cooperative A*) |

        **Cómo regenerarlo** (desde la raíz del proyecto, con el entorno virtual activo):

        ```
        python -m siembra.experimentos --modo rapido
        python herramientas/construir_dashboard.py --ejecutar --html
        ```

        **De dónde salen los datos.** Todo se lee de la carpeta de resultados (`resultados/`, o la
        indicada en la variable de entorno `SIEMBRA_RESULTADOS`): `barrido.csv`, `escenarios.csv`,
        `sens_arquitectura.csv`, `curvas.csv` y las corridas detalladas de `corridas/<id>/`
        (`meta.json`, `pasos.csv`, `mensajes.csv`, `serie.csv`, `celdas.npz`). Ninguna cifra está
        escrita a mano: cada tabla y cada gráfica se calcula en su celda. Las figuras se guardan en
        `resultados/figuras/` para el reporte y la presentación.

        **Secciones.** 0 · Datos y condiciones de cada experimento · 1 · Panel del entorno ·
        2 · Panel de indicadores · 3 · Panel de comunicación · 4 · Panel experimental.

        Colores fijos en todo el tablero: M0 azul, M1 naranja, M2 aqua; actividades y estados de
        celda según `docs/contrato_datos.md`.
    """))

    c.append(_py("""
        import json
        import os
        import sys
        from datetime import datetime
        from pathlib import Path

        RAIZ = Path.cwd().resolve()
        while not (RAIZ / "siembra" / "__init__.py").exists() and RAIZ.parent != RAIZ:
            RAIZ = RAIZ.parent
        if str(RAIZ) not in sys.path:
            sys.path.insert(0, str(RAIZ))

        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd
        from IPython.display import HTML, Markdown, display

        from siembra import metricas, viz
        from siembra.config import cargar_config
        from siembra.telemetria import cargar_corrida

        %matplotlib inline
        viz.estilo()
        pd.set_option("display.max_columns", 60)
        pd.set_option("display.width", 220)
        pd.set_option("display.max_colwidth", 90)

        RESULTADOS = Path(os.environ.get("SIEMBRA_RESULTADOS", RAIZ / "resultados")).resolve()
        FIGURAS = RESULTADOS / "figuras"
        print(f"Carpeta de resultados: {RESULTADOS}")
    """))

    c.append(_py("""
        # Si no hay datos, el dashboard se detiene aquí con instrucciones.
        ARCHIVOS = {"barrido": "barrido.csv", "escenarios": "escenarios.csv",
                    "sens_arq": "sens_arquitectura.csv", "curvas": "curvas.csv"}
        CARPETA_CORRIDAS = RESULTADOS / "corridas"
        IDS = sorted(p.name for p in CARPETA_CORRIDAS.iterdir() if (p / "meta.json").exists()) \\
            if CARPETA_CORRIDAS.is_dir() else []
        if not any((RESULTADOS / f).exists() for f in ARCHIVOS.values()) and not IDS:
            raise FileNotFoundError(
                f"No hay resultados en {RESULTADOS}.\\n"
                "Genera los datos y vuelve a construir el dashboard desde la raíz del proyecto:\\n"
                "    python -m siembra.experimentos --modo rapido\\n"
                "    python herramientas/construir_dashboard.py --ejecutar --html")
    """))

    c.append(_py("""
        def leer(nombre):
            ruta = RESULTADOS / ARCHIVOS[nombre]
            return pd.read_csv(ruta) if ruta.exists() else None


        barrido, esc, sens_arq, curvas = (leer(k) for k in ARCHIVOS)
        _cache = {}


        def corrida(cid):
            \"\"\"Corrida detallada con el formato del contrato (None si no existe).\"\"\"
            if cid not in _cache:
                carpeta = CARPETA_CORRIDAS / cid
                if (carpeta / "meta.json").exists():
                    _cache[cid] = cargar_corrida(carpeta)
                    _cache[cid]["id"] = cid
                else:
                    _cache[cid] = None
            return _cache[cid]


        def corridas(*ids):
            \"\"\"Las corridas de la lista que existen, en el mismo orden.\"\"\"
            return [c for c in (corrida(i) for i in ids) if c is not None]


        def primera(*ids):
            \"\"\"La primera corrida de la lista que existe.\"\"\"
            return next(iter(corridas(*ids)), None)


        def trio(escenario):
            return corridas(*(f"{escenario}_{m}_s0" for m in ("M0", "M1", "M2")))


        def aviso(texto):
            display(Markdown(f"> **Falta información:** {texto}"))


        def mostrar(fig, nombre):
            \"\"\"Guarda la figura en <resultados>/figuras/<nombre>.png y la muestra.\"\"\"
            viz.guardar(fig, nombre, FIGURAS)
            display(fig)
            plt.close(fig)


        def nombres_escenarios():
            if esc is None or "escenario_nombre" not in esc.columns:
                return {}
            return dict(esc.drop_duplicates("escenario")[["escenario", "escenario_nombre"]].values)
    """))

    # ------------------------------------------------------------------ 0. datos
    c.append(_md("""
        ## 0. Datos y condiciones de cada experimento

        Archivos encontrados, versión de los parámetros y del esquema, y las condiciones con las
        que se corrió cada experimento. Revisa la tabla de control de calidad antes de interpretar
        cualquier gráfica: una corrida que no cubrió todo el campo o que se estancó cambia los
        promedios.
    """))
    c.append(_py("""
        filas = []
        for nombre, archivo in ARCHIVOS.items():
            ruta = RESULTADOS / archivo
            df = {"barrido": barrido, "escenarios": esc, "sens_arq": sens_arq, "curvas": curvas}[nombre]
            filas.append({"archivo": archivo, "existe": ruta.exists(),
                          "filas": 0 if df is None else len(df),
                          "modificado": datetime.fromtimestamp(ruta.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                          if ruta.exists() else ""})
        filas.append({"archivo": "corridas/ (detalladas)", "existe": bool(IDS), "filas": len(IDS),
                      "modificado": ""})
        display(pd.DataFrame(filas).set_index("archivo"))

        cfg_actual = cargar_config()
        version_esquema, version_param = "", ""
        if IDS:
            with open(CARPETA_CORRIDAS / IDS[0] / "meta.json", encoding="utf-8") as f:
                meta = json.load(f)
            version_esquema = meta.get("version_esquema", "")
            version_param = meta.get("parametros", {}).get("version_parametros", "")
        display(Markdown(
            f"Versión del esquema de las corridas detalladas: **{version_esquema or 'sin corridas detalladas'}** · "
            f"versión de parámetros con que se corrieron: **{version_param or 'desconocida'}** · "
            f"versión actual de `config/parametros.json`: **{cfg_actual.get('version_parametros', '')}**"))
    """))
    c.append(_md("""
        ### Parámetros base

        Valores de la configuración con la que se corrieron las corridas detalladas (si no hay,
        los de `config/parametros.json`) y la fuente de cada uno. Cada experimento cambia solo
        los parámetros que se ven en las tablas de condiciones de abajo.
    """))
    c.append(_py("""
        base = primera(*IDS) if IDS else None
        cfg_base = base["parametros"] if base is not None else cfg_actual
        display(viz.tabla_parametros(cfg_base).set_index("parámetro"))
    """))
    c.append(_md("""
        ### Condiciones de cada experimento

        Valores distintos de cada parámetro dentro de cada grupo de corridas, mecanismos y
        semillas usadas.
    """))
    c.append(_py("""
        if esc is not None:
            display(Markdown("**Escenarios** (`escenarios.csv`)"))
            display(viz.tabla_condiciones(esc, "escenario"))
        else:
            aviso("no existe escenarios.csv.")
        if barrido is not None:
            display(Markdown("**Barrido de la proporción** (`barrido.csv`), por tamaño de campo"))
            display(viz.tabla_condiciones(barrido, "hectareas"))
        else:
            aviso("no existe barrido.csv.")
        if sens_arq is not None:
            display(Markdown("**Sensibilidad de la arquitectura** (`sens_arquitectura.csv`), por parámetro"))
            display(viz.tabla_condiciones(sens_arq, "parametro"))
        else:
            aviso("no existe sens_arquitectura.csv.")
        if IDS:
            display(Markdown("**Corridas detalladas** (`corridas/`)"))
            display(pd.DataFrame([{"corrida": i, "condiciones": viz.texto_parametros(corrida(i)["resumen"],
                                                                                   viz.escenario_de(corrida(i)))}
                                  for i in IDS]).set_index("corrida"))
        else:
            aviso("no hay corridas detalladas en corridas/.")
    """))
    c.append(_md("""
        ### Control de calidad

        Grupos con al menos una corrida que no sembró todo el campo (cobertura menor a 100 %) o
        que terminó por estancamiento o por el límite de pasos.
    """))
    c.append(_py("""
        partes = []
        for etiqueta, df, por in (("barrido", barrido, ["hectareas", "n_tractores"]),
                                  ("escenarios", esc, ["escenario"]),
                                  ("sens_arquitectura", sens_arq, ["parametro", "valor"])):
            if df is not None:
                cc = viz.control_calidad(df, por)
                if len(cc):
                    partes.append(cc.reset_index().assign(archivo=etiqueta))
        if partes:
            display(pd.concat(partes, ignore_index=True).set_index("archivo"))
        else:
            display(Markdown("Todas las corridas cubrieron el 100 % del campo y ninguna se estancó."))
    """))

    # ------------------------------------------------------------------ 1. entorno
    c.append(_md("""
        ## 1. Panel del entorno

        Representación 2D del campo dividido en celdas: patio del depósito (fila inferior),
        cabeceras (primera y última fila del campo), área de trabajo, obstáculos y depósito. Cada
        tractor se dibuja con su implemento (triángulo blanco: surcador, apunta a su rumbo; círculo
        negro: sembradora), su etiqueta, su intención y su trayectoria reciente. Las celdas cambian
        de color al pasar de libre a surcada y de surcada a sembrada.
    """))
    c.append(_py("""
        ID_BASE = next((i for i in ("normal_20ha_2t_M1_s0", "normal_20ha_2t_M2_s0", "normal_20ha_2t_M0_s0")
                        if corrida(i) is not None), IDS[0] if IDS else None)
        if ID_BASE is None:
            aviso("no hay corridas detalladas para el panel del entorno.")
        else:
            c_base = corrida(ID_BASE)
            T = int(c_base["resumen"].get("T_pasos") or c_base["serie"]["t"].max())
            mostrar(viz.mapa_campo(None, c_base, int(0.4 * T)), "entorno_mapa_campo")
    """))
    c.append(_md("""
        Qué mirar: dónde va el surcador respecto a la sembradora (la sembradora solo avanza
        sobre celdas surcadas) y la línea punteada de cada tractor hacia su celda objetivo, que
        muestra su intención en ese paso.
    """))
    c.append(_py("""
        if ID_BASE is not None:
            mostrar(viz.secuencia_estados(c_base), "entorno_secuencia_estados")
    """))
    c.append(_md("""
        ### Animación de la corrida

        La misma corrida paso a paso (80 cuadros equiespaciados entre el inicio y el último paso).
        También se guarda como GIF en `resultados/figuras/animacion_campo.gif`.
    """))
    c.append(_py("""
        if ID_BASE is not None:
            # dpi bajo en el notebook para que no pese demasiado; el GIF lleva más resolución
            anim = viz.animacion(c_base, n_cuadros=80)
            viz.guardar_gif(anim, FIGURAS / "animacion_campo.gif", fps=10, dpi=80)
            display(HTML(viz.animacion_html(anim, dpi=60)))
            plt.close(anim._fig)
    """))
    c.append(_md("""
        ### Campo con obstáculos

        Escenario de 40 ha con 2 obstáculos (poste y árbol). Qué mirar: cómo rodean los tractores
        los obstáculos y si quedan celdas sin sembrar a su alrededor.
    """))
    c.append(_py("""
        c_obst = corrida("normal_40ha_3t_obst_M2_s0")
        if c_obst is None:
            aviso("falta la corrida detallada normal_40ha_3t_obst_M2_s0.")
        else:
            T = int(c_obst["resumen"].get("T_pasos") or c_obst["serie"]["t"].max())
            mostrar(viz.mapa_campo(None, c_obst, int(0.5 * T)), "entorno_mapa_obstaculos")
    """))
    c.append(_md("""
        ### Trayectorias completas

        Recorrido de cada tractor durante toda la corrida, coloreado por actividad (verde
        trabajando, violeta traslado; los puntos marcan dónde estuvo detenido). Qué mirar: qué
        hileras recorrió cada tractor (franjas contiguas en M0, repartidas en M1 y M2), cuántos
        traslados hizo al depósito y, en el escenario de falla, dónde se detuvo el tractor que falla.
    """))
    c.append(_py("""
        lista = trio("falla_20ha_4t") or trio("normal_20ha_2t")
        if not lista:
            aviso("faltan las corridas detalladas de falla_20ha_4t y normal_20ha_2t.")
        for c_ in lista:
            mostrar(viz.mapa_trayectorias(None, c_), f"entorno_trayectorias_{c_['id']}")
    """))
    c.append(_md("""
        ### Mapas de calor: compactación y edad del cultivo

        Pasadas por celda (cuántas veces entró un tractor; más oscuro = más compactación) y día de
        siembra de cada celda en días desde la fecha óptima (más oscuro = sembrada más tarde). Los
        paneles de cada figura comparten escala de color. Qué mirar: cabeceras y caminos al depósito
        más cargados de pasadas; franjas sembradas mucho después que el resto; celdas sin sembrar.
    """))
    c.append(_py("""
        lista = trio("normal_20ha_2t")
        if lista:
            mostrar(viz.mapas_comparados(lista, "pasadas"), "entorno_pasadas_normal_20ha_2t")
            mostrar(viz.mapas_comparados(lista, "edad"), "entorno_edad_normal_20ha_2t")
        else:
            aviso("faltan las corridas detalladas de normal_20ha_2t.")
        lista = trio("falla_20ha_4t")
        if lista:
            mostrar(viz.mapas_comparados(lista, "edad"), "entorno_edad_falla_20ha_4t")
        else:
            aviso("faltan las corridas detalladas de falla_20ha_4t.")
        if c_obst is not None:
            mostrar(viz.mapa_pasadas(None, c_obst), "entorno_pasadas_obstaculos")
    """))

    # ------------------------------------------------------------------ 2. indicadores
    c.append(_md("""
        ## 2. Panel de indicadores

        Indicadores de desempeño de cada corrida, siempre con sus parámetros (mecanismo,
        hectáreas, número de tractores, semilla y escenario) a la vista. El costo por hectárea es
        la propiedad de la flota más la función de costo J (retraso de siembra, reparación por
        horas de motor, diésel, colisiones y superficie no sembrada), dividido entre las hectáreas
        sembrables.
    """))
    c.append(_py("""
        if ID_BASE is not None:
            mostrar(viz.tarjetas_kpi(c_base["resumen"], viz.escenario_de(c_base)), "indicadores_tarjetas")
        else:
            aviso("no hay corridas detalladas para las tarjetas de indicadores.")
    """))
    c.append(_md("""
        Los mismos indicadores para todas las corridas detalladas (una fila por corrida):
    """))
    c.append(_py("""
        if IDS:
            display(viz.tabla_kpi(corridas(*IDS)))
    """))
    c.append(_md("""
        ### Horas por tractor según actividad

        Horas-tractor hasta el tiempo total T, apiladas por actividad: trabajando, traslado,
        estación (fila, recarga y cambio de implemento), esperas (por celda o por surco) y ocio
        (sin tarea o negociando). Qué mirar: la parte no verde de cada barra es tiempo que no
        siembra; compara su tamaño entre mecanismos con la misma escala.
    """))
    c.append(_py("""
        for escenario in ("normal_20ha_2t", "falla_20ha_4t"):
            lista = trio(escenario)
            if lista:
                mostrar(viz.actividad_comparada(lista), f"indicadores_actividad_{escenario}")
            else:
                aviso(f"faltan las corridas detalladas de {escenario}.")
    """))
    c.append(_md("""
        ### Indicadores por escenario y mecanismo

        Media ± semiancho del intervalo de confianza del 95 % entre semillas (n = número de
        corridas del grupo).
    """))
    c.append(_py("""
        KPIS = ["costo_ha", "T_h", "cobertura", "colisiones", "W_ocio_h", "W_espera_h", "W_conflicto_h",
                "mensajes_total", "dispersion_dias", "diesel_l", "eficiencia_campo", "tiempo_computo_s"]
        if esc is not None:
            display(viz.tabla_comparativa(esc, KPIS, por=["escenario", "mecanismo"]))
        else:
            aviso("no existe escenarios.csv.")
    """))

    # ------------------------------------------------------------------ 3. comunicación
    c.append(_md("""
        ## 3. Panel de comunicación

        Mensajes FIPA-ACL entre el depósito gestor (DEP) y los tractores: anuncios (`cfp`),
        ofertas (`propose`), adjudicaciones (`accept-proposal`), rechazos (`reject-proposal`) y
        avisos (`inform`). M0 no envía mensajes.
    """))
    c.append(_py("""
        lista = corridas("falla_20ha_4t_M1_s0", "falla_20ha_4t_M2_s0") or \\
            corridas("normal_20ha_2t_M1_s0", "normal_20ha_2t_M2_s0")
        if lista:
            mostrar(viz.serie_performativas(lista), "comunicacion_performativas")
        else:
            aviso("faltan corridas detalladas de M1 o M2.")
    """))
    c.append(_md("""
        Qué mirar: la pendiente de cada curva es el ritmo de mensajes; los saltos coinciden con
        rondas de subasta (al inicio y cuando se libera una hilera) y, en M2, con los avisos de
        recarga y de falla.
    """))
    c.append(_md("""
        ### Mensajes perdidos y reanuncios

        Sensibilidad a la pérdida de mensajes (20 ha, 4 tractores). Qué mirar: cuántos reanuncios
        provoca cada nivel de pérdida en M1 y M2.
    """))
    c.append(_py("""
        if sens_arq is not None and sens_arq["parametro"].astype(str).str.endswith("perdida_mensajes").any():
            mostrar(viz.perdidos_y_reanuncios(sens_arq), "comunicacion_perdidos_reanuncios")
            d = sens_arq[sens_arq["parametro"].astype(str).str.endswith("perdida_mensajes")]
            display(viz.tabla_comparativa(d, ["mensajes_total", "mensajes_perdidos", "reanuncios", "T_h"],
                                          por=["valor", "mecanismo"]))
        else:
            aviso("sens_arquitectura.csv no tiene la sensibilidad a la pérdida de mensajes.")
    """))
    c.append(_md("""
        ### Hileras por tractor (balance de carga)

        Hileras equivalentes que trabajó cada tractor (celdas trabajadas ÷ largo de la hilera),
        separadas en surcado y sembrado. Qué mirar: la diferencia entre tractores del mismo rol;
        en el escenario de falla, cómo se reparten las hileras del tractor que se detiene.
    """))
    c.append(_py("""
        for escenario in ("falla_20ha_4t", "normal_20ha_2t"):
            lista = trio(escenario)
            if lista:
                mostrar(viz.hileras_comparadas(lista), f"comunicacion_hileras_{escenario}")
            else:
                aviso(f"faltan las corridas detalladas de {escenario}.")
    """))
    c.append(_md("""
        ### Fila de la estación y tabla de reservas

        Tractores esperando en la fila de la estación de carga y entradas activas en la tabla de
        reservas de Cooperative A* (solo M2 la usa). Qué mirar: cuándo se forma fila y cuánto dura;
        cuántas celdas tiene reservadas la flota en cada momento.
    """))
    c.append(_py("""
        lista = trio("falla_20ha_4t") or trio("normal_20ha_2t")
        if lista:
            mostrar(viz.serie_estacion(lista), "comunicacion_fila_estacion")
        lista = corridas("normal_20ha_2t_M2_s0", "falla_20ha_4t_M2_s0", "normal_40ha_3t_obst_M2_s0")
        if lista:
            mostrar(viz.serie_reservas(lista), "comunicacion_reservas")
        else:
            aviso("faltan corridas detalladas de M2.")
    """))
    c.append(_md("""
        ### Línea de tiempo de una subasta

        Diagrama de secuencia de una subasta real tomada del log de mensajes (se elige
        automáticamente una ronda con varios postores y, si la hay, con mensajes perdidos; si la
        adjudicación se perdió, se agrega la ronda que la reanuncia). Los mensajes perdidos se
        dibujan punteados en rojo y terminan en una cruz porque no llegaron a su receptor.
    """))
    c.append(_py("""
        c_sub = primera("perdida30_20ha_4t_M1_s0", "falla_20ha_4t_M1_s0", "normal_20ha_2t_M1_s0",
                        "normal_20ha_2t_M2_s0")
        if c_sub is None or c_sub.get("mensajes") is None or len(c_sub["mensajes"]) == 0:
            aviso("no hay una corrida detallada de M1 o M2 con mensajes.")
        else:
            mostrar(viz.linea_tiempo_subasta(None, c_sub["mensajes"], None, c_sub["resumen"]),
                    "comunicacion_subasta")
    """))

    # ------------------------------------------------------------------ 4. experimental
    c.append(_md("""
        ## 4. Panel experimental

        ### ¿Cuántos tractores por hectárea?

        Costo por hectárea contra el número de tractores, un panel por tamaño de campo y una línea
        por mecanismo, con la banda del intervalo de confianza del 95 %. El punto grande marca el
        mínimo de cada mecanismo. Qué mirar: en qué N está el mínimo de cada tamaño de campo y si
        las bandas de los mecanismos se separan.
    """))
    c.append(_py("""
        if barrido is not None:
            mostrar(viz.curvas_costo(barrido), "experimental_curvas_costo")
            opt = metricas.optimo_por_campo(barrido)
            display(opt[["mecanismo", "hectareas", "n_optimo", "n", "media", "ic_bajo", "ic_alto",
                         "ha_por_tractor", "en_borde"]]
                    .rename(columns={"n_optimo": "N óptimo", "n": "semillas", "media": "costo medio ($/ha)",
                                     "ic_bajo": "IC 95 % bajo", "ic_alto": "IC 95 % alto",
                                     "ha_por_tractor": "ha por tractor", "en_borde": "óptimo en el borde"})
                    .round(1).set_index(["hectareas", "mecanismo"]).sort_index())
        else:
            aviso("no existe barrido.csv.")
    """))
    c.append(_md("""
        ### ¿Qué mecanismo funciona mejor?

        Media por escenario y mecanismo con barras de error (IC 95 %). Cada panel tiene su propia
        escala desde cero, así que compara las barras dentro de cada panel. Debajo, la diferencia
        pareada por semilla contra M0 (mismas semillas en los tres mecanismos) y las pruebas
        pareadas.
    """))
    c.append(_py("""
        if esc is not None:
            for metrica in ("costo_ha", "T_h", "W_ocio_h", "W_espera_h", "W_conflicto_h", "cobertura"):
                if metrica in esc.columns:
                    mostrar(viz.barras_escenarios(esc, metrica), f"experimental_escenarios_{metrica}")
        else:
            aviso("no existe escenarios.csv.")
    """))
    c.append(_py("""
        if esc is not None:
            for metrica in ("costo_ha", "T_h"):
                mostrar(viz.diferencias_pareadas(esc, metrica), f"experimental_diferencias_{metrica}")
            pruebas = pd.concat([metricas.prueba_pareada(esc, m, a, b, por="escenario")
                                 for m in ("costo_ha", "T_h", "W_ocio_h", "W_espera_h", "W_conflicto_h")
                                 for a, b in (("M0", "M1"), ("M0", "M2"), ("M1", "M2"))], ignore_index=True)
            display(pruebas.round(4).set_index(["metrica", "escenario", "a", "b"]))
    """))
    c.append(_md("""
        En la tabla, `diferencia_media` es b − a (negativa: b es menor), `p_t` es la t pareada,
        `p_wilcoxon` la prueba de Wilcoxon y `prueba_sugerida` la que corresponde según la prueba
        de normalidad de las diferencias.

        ### ¿Cómo avanza la siembra?

        Porcentaje del área sembrada contra el tiempo, media entre semillas con su banda IC 95 %.
        Qué mirar: la pendiente (ritmo de siembra), las mesetas (nadie siembra: recargas, esperas,
        falla) y la hora en que cada mecanismo llega al 100 %.
    """))
    c.append(_py("""
        if curvas is not None and len(curvas):
            mostrar(viz.cobertura_por_escenario(curvas, nombres=nombres_escenarios()), "experimental_cobertura")
        else:
            aviso("no existe curvas.csv.")
    """))
    c.append(_md("""
        ### ¿Qué tan variable es el resultado?

        Distribución del tiempo total T entre semillas, un panel por mecanismo con los mismos
        intervalos. Qué mirar: el ancho de cada distribución y si se traslapan.
    """))
    c.append(_py("""
        if esc is not None:
            for escenario in ("normal_20ha_2t", "falla_20ha_4t"):
                if (esc["escenario"] == escenario).any():
                    mostrar(viz.histograma_T(esc, escenario), f"experimental_histograma_T_{escenario}")
                else:
                    aviso(f"escenarios.csv no tiene {escenario}.")
    """))
    c.append(_md("""
        ### ¿Qué parámetro pesa más?

        Sensibilidad económica sin volver a simular (`metricas.sensibilidad_economica`): cada
        parámetro se mueve a su valor bajo y alto, uno a la vez, y se recalcula el costo por
        hectárea de la flota óptima. Las barras azules bajan el costo y las rojas lo suben; la
        etiqueta indica si cambia el número óptimo de tractores. La tabla de abajo muestra el N
        óptimo en cada nivel y tamaño de campo.
    """))
    c.append(_py("""
        if barrido is not None:
            sens_eco = metricas.sensibilidad_economica(barrido, cfg_base)
            tamanos = sorted(barrido["hectareas"].unique())
            ha_t = 20 if 20 in tamanos else tamanos[len(tamanos) // 2]
            for mec in viz._mecanismos(barrido):
                mostrar(viz.tornado(sens_eco, mec, ha_t), f"experimental_tornado_{mec}_{ha_t:g}ha")
            tabla_n = (sens_eco.drop_duplicates(["parametro", "nivel", "mecanismo", "hectareas"])
                       .pivot_table(index=["mecanismo", "parametro", "nivel"], columns="hectareas",
                                    values="n_optimo", aggfunc="first"))
            display(Markdown("**N óptimo por nivel de cada parámetro** (columnas: hectáreas)"))
            display(tabla_n)
        else:
            aviso("no existe barrido.csv.")
    """))
    c.append(_md("""
        ### Sensibilidad de la arquitectura

        Cada parámetro de diseño contra la métrica que debería mover: tiempo límite de ofertas
        contra W_ocio, pérdida de mensajes contra T, ventana de reservas contra W_conflicto y
        margen de recarga anticipada contra W_espera; la segunda fila muestra el costo por
        hectárea. Qué mirar: dónde cambia la pendiente y qué valores dejan la métrica más baja.
    """))
    c.append(_py("""
        if sens_arq is not None:
            mostrar(viz.sens_arquitectura(sens_arq), "experimental_sens_arquitectura")
            display(viz.tabla_comparativa(sens_arq, ["T_h", "W_ocio_h", "W_espera_h", "W_conflicto_h", "costo_ha"],
                                          por=["parametro", "valor", "mecanismo"]))
        else:
            aviso("no existe sens_arquitectura.csv.")
    """))
    c.append(_md("""
        ---
        Figuras guardadas para el reporte y la presentación:
    """))
    c.append(_py("""
        guardadas = sorted(p.name for p in FIGURAS.glob("*")) if FIGURAS.exists() else []
        print(f"{len(guardadas)} archivos en {FIGURAS}")
        print("\\n".join(guardadas))
    """))
    return c


def construir(ruta=NOTEBOOK):
    """Escribe el notebook (sin ejecutar) y lo devuelve."""
    nb = new_notebook(cells=celdas())
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nb.metadata["language_info"] = {"name": "python"}
    nbformat.validate(nb)
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, str(ruta))
    return nb


def _entorno_kernel(resultados):
    """Variables de entorno que hereda el kernel: raíz del proyecto en PYTHONPATH y carpeta de
    resultados en SIEMBRA_RESULTADOS."""
    if resultados is not None:
        os.environ["SIEMBRA_RESULTADOS"] = str(Path(resultados).resolve())
    rutas = [str(RAIZ)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    os.environ["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(rutas))


def ejecutar(nb, ruta=NOTEBOOK, resultados=None, timeout=3600, preludio=None):
    """Ejecuta el notebook con el kernel `python3` y lo guarda con sus salidas.

    `preludio`: código opcional que se ejecuta antes de la primera celda y no se guarda (para
    pruebas).
    """
    from nbconvert.preprocessors import ExecutePreprocessor

    _entorno_kernel(resultados)
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    nb_exec = nbformat.from_dict(nb)
    if preludio:
        nb_exec.cells.insert(0, new_code_cell(preludio))
    ep = ExecutePreprocessor(timeout=timeout, kernel_name="python3")
    ep.preprocess(nb_exec, {"metadata": {"path": str(Path(ruta).resolve().parent)}})
    if preludio:
        nb_exec.cells.pop(0)
    nbformat.write(nb_exec, str(ruta))
    return nb_exec


def exportar_html(nb, ruta):
    """Exporta el notebook (ya ejecutado) a un HTML autocontenido."""
    from nbconvert import HTMLExporter

    cuerpo, _ = HTMLExporter().from_notebook_node(nb)
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(cuerpo, encoding="utf-8")
    return ruta


def _main(argv=None):
    p = argparse.ArgumentParser(description="Genera notebooks/dashboard.ipynb (y lo ejecuta o exporta).")
    p.add_argument("--ejecutar", action="store_true", help="ejecuta el notebook y guarda sus salidas")
    p.add_argument("--html", action="store_true",
                   help="exporta <resultados>/dashboard.html (implica --ejecutar)")
    p.add_argument("--resultados", default=None,
                   help="carpeta de resultados (por defecto resultados/ o $SIEMBRA_RESULTADOS)")
    p.add_argument("--salida", default=str(NOTEBOOK), help="ruta del notebook a escribir")
    p.add_argument("--timeout", type=int, default=3600, help="segundos máximos por celda")
    a = p.parse_args(argv)

    salida = Path(a.salida)
    nb = construir(salida)
    print(f"Notebook escrito en {salida}")
    if a.ejecutar or a.html:
        inicio = time.perf_counter()
        nb = ejecutar(nb, salida, a.resultados, a.timeout)
        print(f"Notebook ejecutado en {time.perf_counter() - inicio:.0f} s")
    if a.html:
        carpeta = Path(os.environ.get("SIEMBRA_RESULTADOS", RAIZ / "resultados"))
        ruta = exportar_html(nb, carpeta / "dashboard.html")
        print(f"HTML exportado en {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
