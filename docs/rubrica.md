# Mapa de la rúbrica

Dónde se cubre cada criterio de la "Rúbrica de evaluación del Reto John Deere" (TC2008B) en el proyecto: archivo, función, gráfica o sección del notebook.

**De qué texto partimos.** Solo tenemos el texto de las secciones 7 y 8 (10 puntos cada una). Las demás secciones se infieren de la propuesta, que se escribió siguiendo la rúbrica y el plan de cuatro semanas del curso; su número y su redacción hay que confirmarlos con la rúbrica oficial. Por la misma razón, la sección 6 aparece como inferida: como la sección 7 parte de "interpretar los resultados", lo más probable es que la 6 cubra los resultados experimentales y su visualización.

Estados: **Listo** (existe y está probado o revisado), **Parcial** (existe la estructura, faltan resultados o una parte), **Pendiente** (no existe todavía).

## Sección 7. Análisis crítico, sensibilidad y limitaciones (10 pts)

> El equipo deberá interpretar los resultados y discutir qué puede concluirse a partir de ellos. Se espera un análisis que vaya más allá de describir las gráficas.

| Lo que pide | Dónde se cubre | Estado |
|---|---|---|
| Interpretar los resultados y qué se puede concluir | [`analisis_critico.md` §1](analisis_critico.md#1-qué-se-puede-concluir); `metricas.optimo_por_campo`, `metricas.prueba_pareada`; gráfica `viz.curvas_costo` | Parcial: hipótesis y criterios listos; faltan los números del barrido completo |
| Explicar por qué ciertos escenarios producen mejores resultados | [§2](analisis_critico.md#2-por-qué-ganan-ciertos-escenarios); `viz.barras_actividad`, `viz.curvas_cobertura`; `escenarios.csv`, `curvas.csv` | Parcial: §2.1 (dónde puede moverse el costo) listo; §2.2 espera resultados |
| Identificar parámetros especialmente sensibles | [§3](analisis_critico.md#3-parámetros-más-sensibles); `metricas.sensibilidad_economica` + `viz.tornado`; `sens_arquitectura.csv` + `viz.sens_arquitectura` | Parcial: sensibilidad analítica completa; falta la simulada |
| Analizar fallos y comportamientos inesperados | [§4](analisis_critico.md#4-fallos-y-comportamientos-inesperados); columnas `estancado`, `vetos`, `celdas_inaccesibles`; `resultados/corridas/*/pasos.csv`; `resultados/errores.log` | Parcial: escritos los fallos detectados por diseño (§4.1), los que obligaron a cambiar reglas (§4.2) y las explicaciones posibles de lo observado en pruebas (§4.3); faltan las magnitudes de los experimentos (§4.4) |
| Reconocer las limitaciones del modelo | [§5](analisis_critico.md#5-limitaciones-del-modelo) | Listo |
| Diferenciar resultados simulados de evidencia real | [§6](analisis_critico.md#6-simulación-contra-realidad) | Listo |
| Situaciones en las que las conclusiones podrían no ser válidas | [§7](analisis_critico.md#7-situaciones-en-las-que-las-conclusiones-no-valen) | Listo |
| Proponer mejoras técnicamente justificadas | [§8](analisis_critico.md#8-mejoras-propuestas) | Listo |
| Cuestionar el propio modelo | [Anexo A](analisis_critico.md#anexo-a-revisión-de-la-estimación-previa-de-la-propuesta) (errores de la estimación previa) y las 23 desviaciones de [`modelo.md`](modelo.md#14-resumen-de-desviaciones) | Listo |
| Sección del dashboard | Panel experimental del notebook (diferencias pareadas, tornado económico, sensibilidad de arquitectura) y tabla de control de calidad de la sección 0, que lista las corridas incompletas o estancadas; el texto interpretativo está en [`analisis_critico.md`](analisis_critico.md) | Listo |

## Sección 8. Reproducibilidad, documentación y presentación (10 pts)

> El proyecto deberá entregarse de manera que otra persona pueda comprenderlo y ejecutarlo.

| Lo que pide (y lo que prometió la propuesta, p. 20) | Dónde se cubre | Estado |
|---|---|---|
| README con estructura, dependencias y cómo correr todo | [`README.md`](../README.md) | Listo (faltan los tiempos medidos por modo) |
| Archivo de dependencias | [`requirements.txt`](../requirements.txt), versiones fijadas | Listo |
| Módulos separados: configuración, modelo y agentes, comunicación, experimentos, telemetría, visualización | `siembra/config.py`, `campo.py`, `agentes.py`, `modelo.py`, `planificador.py`, `comunicacion.py`, `experimentos.py`, `metricas.py`, `telemetria.py`, `viz.py` | Listo |
| Un archivo de configuración con todos los parámetros y su fuente | `config/parametros.json` (`_fuentes`) | Parcial: 20 parámetros no tienen fuente; la mayoría son variables del experimento, pero `reserva_diesel_frac`, `paciencia_pasos`, `reintento_cfp`, `holgura_tell`, `valor_hilera`, `margen_recarga_hileras`, `perdida_mensajes` y `cobertura_disparo` deberían decir "Propuesta" o "Supuesto" |
| Semillas aleatorias fijas y listadas | `siembra/experimentos.py` (semillas 0 a N − 1, iguales para los tres mecanismos); fuentes de aleatoriedad en [`modelo.md` §11](modelo.md#11-aleatoriedad-y-reproducibilidad-d18) | Listo |
| Un comando que corre todo | `correr_todo.py` | Listo |
| Notebook que regenera tablas y gráficas desde los CSV | `herramientas/construir_dashboard.py`, `notebooks/dashboard.ipynb` (ejecutado con los datos del modo completo), `resultados/dashboard.html` | Listo |
| Versión del esquema en cada JSON exportado | `siembra.VERSION_ESQUEMA`, `telemetria.exportar_unity`, `telemetria.validar_unity`; `tests/test_telemetria.py` | Listo |
| Validación de entradas con mensaje claro | `config.validar` (lo llama `simular`); `tests/test_config.py` | Listo |
| Pruebas automáticas por regla: sin colisiones, sin intercambios, cobertura completa, recargas solo en el depósito, siembra solo sobre surcadas, estados de celda que no retroceden | `tests/test_reglas.py` (con los tres mecanismos; además reproducibilidad con la misma semilla, reasignación tras falla, pérdida de mensajes y obstáculos); `modelo._verificar_seguridad` cuenta colisiones e intercambios en cada corrida | Listo |
| Contrato de datos entre módulos | [`contrato_datos.md`](contrato_datos.md) | Listo |
| Descripción del modelo implementado | [`modelo.md`](modelo.md) | Listo |
| Resultados versionados | `resultados/*.csv` se versionan; `resultados/corridas/` se regenera (`.gitignore`) | Listo |
| Video de demostración (corrida 2D, dashboard y Unity) | — | Fuera de alcance (decisión del equipo) |
| Presentación | — | Pendiente |

## Secciones inferidas de la propuesta

Número y texto por confirmar con la rúbrica oficial.

| Criterio inferido | Dónde se cubre | Estado |
|---|---|---|
| Definición del problema, escenario y supuestos | `Propuesta.pdf` pp. 1–3; [`modelo.md` §2–3](modelo.md#2-escala-de-tiempo-y-espacio); `siembra/campo.py`, `config.derivados` | Listo |
| Diseño del agente: percepciones, acciones, tipo de agente, arquitectura híbrida, máquina de estados | `Propuesta.pdf` pp. 4–5; [`modelo.md` §4 y §9](modelo.md#9-estados-del-tractor-d14); `agentes.Tractor` (`decidir`, `actuar`), `modelo.ModeloSiembra._resolver` (capa reactiva) | Listo |
| Comunicación y coordinación: Contract Net, estigmergia, blackboard, broadcast | [`modelo.md` §7](modelo.md#7-mecanismos-de-coordinación); `comunicacion.Bus`, `agentes.Gestor`, `planificador.TablaReservas`; `mensajes.csv` de las corridas detalladas | Listo |
| Algoritmos: A* con costos por tipo de celda, Cooperative A* con ventana, cobertura en zigzag | `planificador.astar`, `planificador.whca`, `planificador.DistanciaReal` (Reverse Resumable A*), `campo.PESO`, `campo.PESO_CRUCE` | Parcial: falta la prueba sobre mapas con ruta óptima conocida |
| Métricas y función de costo | `metricas.costos`, `metricas.agregar_costos`; [`contrato_datos.md`](contrato_datos.md#función-de-costo-metricascostosresumen-cfg---dict); `tests/test_metricas.py` | Listo |
| Diseño experimental: barrido, escenarios, 20 semillas, IC del 95 %, pruebas pareadas | `experimentos.py`; `metricas.resumen_ic`, `metricas.prueba_pareada`; `tests/test_experimentos.py` | Parcial: código listo; faltan las corridas del modo completo |
| (6) Visualización 2D, animaciones y dashboards | `viz.py` (tabla de abajo), `notebooks/dashboard.ipynb`, `resultados/dashboard.html`, `resultados/figuras/` (36 figuras y la animación) | Listo |
| Integración con Unity: JSON precalculado, versión de esquema, checksum, validación al cargar | `telemetria.exportar_unity`, `telemetria.validar_unity`, `resultados/corridas/*/unity.json`; `tests/test_telemetria.py` | Lado de Python listo (exportación y validación del JSON); el proyecto de Unity quedó fuera de alcance (decisión del equipo) |
| Ontología y ética (IEEE 1872, 1873, 7007) | `comunicacion.ONTOLOGIA` (`siembra-maiz-v1`) | Pendiente: el mapeo a IEEE 1872 y 7007 sigue en "Pendientes por investigar" de la propuesta |
| Reflexión con las preguntas de la clase | `Propuesta.pdf` pp. 21–22 | Listo en la propuesta; conviene actualizarla con los resultados |

### Visualización: panel por panel

Paneles que prometió la propuesta (pp. 16–17) y la función de `siembra/viz.py` que los dibuja. Todas están en `notebooks/dashboard.ipynb`, ordenadas por panel.

| Panel | Elemento | Función | Datos |
|---|---|---|---|
| Entorno | Grid 2D con estado de celdas | `viz.mapa_campo` | Corrida detallada |
| Entorno | Tractores con implemento, intención y trayectoria | `viz.mapa_trayectorias` | `pasos.csv` |
| Entorno | Animación paso a paso | `viz.animacion`, `viz.guardar_gif` | `pasos.csv`, `celdas.npz` |
| Entorno | Mapa de calor de pasadas (compactación) | `viz.mapa_pasadas` | `celdas["pasadas"]` |
| Entorno | Mapa de calor de la edad del cultivo | `viz.mapa_edad` | `celdas["t_sembrado"]` |
| Indicadores | Costo, tiempo, cobertura, colisiones, ocio, esperas, mensajes, dispersión, diésel, cómputo, con los parámetros a la vista | `viz.tarjetas_kpi`, `viz.tabla_comparativa`, `viz.tabla_parametros`, `viz.tabla_condiciones`, `viz.horas_por_actividad` | Resumen |
| Comunicación | Mensajes por performativa en el tiempo | `viz.serie_performativas` | `mensajes.csv` |
| Comunicación | Mensajes perdidos y reanuncios por mecanismo y nivel de pérdida | `viz.perdidos_y_reanuncios` | `escenarios.csv`, `sens_arquitectura.csv` |
| Comunicación | Hileras adjudicadas por tractor (balance de carga) | `viz.hileras_por_tractor` | `mensajes.csv`, `pasos.csv` |
| Comunicación | Fila de la estación y celdas reservadas en el tiempo | `viz.serie_estacion`, `viz.serie_reservas` | `serie.csv` |
| Comunicación | Línea de tiempo de una subasta (como la figura 3) | `viz.elegir_ronda`, `viz.linea_tiempo_subasta` | `mensajes.csv` |
| Experimental | ¿Cuántos tractores por hectárea? | `viz.curvas_costo` | `barrido.csv` |
| Experimental | ¿Qué mecanismo funciona mejor? | `viz.barras_escenarios`, `viz.diferencias_pareadas` | `escenarios.csv` |
| Experimental | ¿Cómo avanza la siembra? | `viz.curvas_cobertura` | `curvas.csv` |
| Experimental | ¿Qué tan variable es el resultado? | `viz.histograma_T` | `escenarios.csv` |
| Experimental | ¿En qué se va el tiempo de la flota? | `viz.barras_actividad` | `escenarios.csv` |
| Experimental | ¿Qué parámetro pesa más? | `viz.tornado`, `viz.sens_arquitectura` | `metricas.sensibilidad_economica`, `sens_arquitectura.csv` |

## Competencias ("Qué queremos aprender", propuesta p. 15)

| Habilidad | Cómo dijimos que la demostraríamos | Evidencia | Estado |
|---|---|---|---|
| A* con costos variables por tipo de celda (implementación algorítmica) | Pruebas sobre mapas con ruta óptima conocida | `planificador.astar`, `campo.PESO` | Parcial: falta la prueba |
| Cobertura boustrophedon con N agentes (implementación algorítmica) | Gráfica de porcentaje cubierto contra tiempo | `curvas.csv`, `viz.curvas_cobertura` | Parcial: faltan las corridas |
| Contract Net y estigmergia contra franjas fijas (modelado matemático) | 20 semillas, IC y conteo de mensajes | `experimentos.py`, `metricas.prueba_pareada`, columnas `msg_*` | Parcial: faltan las corridas |
| Esquema de mensajes versionado con checksum (arquitectura de software) | Log validado al cargar en Unity | `telemetria.exportar_unity`, `telemetria.validar_unity`, `tests/test_telemetria.py` | Listo del lado de Python; Unity fuera de alcance |
| Ontología IEEE 1872; combustible y pasadas por celda (ontología y análisis ético) | Telemetría por corrida | `diesel_l`, `diesel_frac`, `celdas["pasadas"]`, `viz.mapa_pasadas` | Parcial: falta el mapeo a la ontología |
