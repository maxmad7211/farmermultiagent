# Flota autónoma de tractores para la siembra de maíz

Simulación multiagente en Python (AgentPy) de una flota de tractores autónomos idénticos que surcan y siembran un campo de maíz en Nuevo León. Cada tractor lleva un implemento intercambiable (surcador o sembradora), comparte una sola estación de carga de semilla y diésel, y no puede chocar con los demás. El objetivo es encontrar cuántos tractores por hectárea dan el menor costo por hectárea, sumando la compra de los tractores, la reparación, el diésel y la cosecha que se pierde por cada día que la siembra se aleja de la fecha óptima. Los resultados se analizan en un dashboard de Jupyter y cada corrida detallada se exporta a JSON para reproducirla en Unity.

Proyecto del curso TC2008B Sistemas Multiagentes (Tecnológico de Monterrey), con John Deere como socio formador. Equipo: Rodrigo Martinez, Maximo Cruz, Erick Ureña, Hector Fernandez y Emiliano Cabrera. El documento de diseño es [`Propuesta.pdf`](Propuesta.pdf).

## Pregunta central y mecanismos

**¿Cuántos tractores por hectárea minimizan el costo por hectárea en campos de 10, 20, 40, 80 y 160 ha?** Se responde con un barrido de 1 a 4 tractores por tamaño de campo, con cada uno de tres mecanismos de coordinación y las mismas semillas aleatorias:

| Mecanismo | Reparto de hileras | Recarga | Cabeceras y colisiones | Falla de un tractor |
|---|---|---|---|---|
| **M0** Franjas fijas | Cada tractor tiene una franja fija; sin mensajes | Al vaciarse la tolva | A* individual + capa reactiva | Nadie reacciona |
| **M1** Contract Net | Subasta de hileras (el depósito es el gestor) | Al vaciarse la tolva | A* individual + capa reactiva | Reanuncio por tiempo límite |
| **M2** Contract Net + broadcast + blackboard | Subasta de hileras | Anticipada, fila en blackboard, aviso por broadcast | Cooperative A* con ventana (tabla de reservas) | Broadcast inmediato y reanuncio |

Además se corren 9 escenarios (normales, adversos y límite) y una sensibilidad de los parámetros de la arquitectura. El detalle está en [`docs/modelo.md`](docs/modelo.md).

## Requisitos

- Python 3.12 o más reciente (probado con Python 3.14.0 en Windows 11).
- Las dependencias de [`requirements.txt`](requirements.txt), con versiones fijadas.

## Instalación

### Windows (PowerShell)

```powershell
cd C:\ruta\al\proyecto\Agentes
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
```

Si PowerShell no deja activar el entorno ("la ejecución de scripts está deshabilitada"), habilítalo solo para esa ventana con `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, o no actives el entorno y llama a su Python directamente: `.\.venv\Scripts\python.exe -m pytest -q`.

En Git Bash el entorno se activa con `source .venv/Scripts/activate`.

### macOS y Linux

```bash
cd /ruta/al/proyecto/Agentes
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
```

Todos los comandos de este README se corren **desde la raíz del proyecto** y con el entorno activado.

## Cómo correr todo

```bash
python correr_todo.py --modo rapido
```

Hace tres pasos y al final imprime un resumen con el resultado de cada uno:

1. Corre los experimentos (`python -m siembra.experimentos`) y escribe los CSV en `resultados/`.
2. Genera y ejecuta el dashboard (`herramientas/construir_dashboard.py --ejecutar`).
3. Corre las pruebas (`python -m pytest -q`).

Opciones: `--modo rapido|completo`, `--nucleos K` (procesos en paralelo; por defecto el número de núcleos menos 1), `--semillas N` (sobrescribe las del modo) y `--salida carpeta` (por defecto `resultados/`). Termina con código 0 si todo salió bien.

El modo `rapido` sirve para revisar que todo funciona; el modo `completo` es el diseño experimental de la propuesta.

| | `rapido` | `completo` |
|---|---|---|
| Campos del barrido | 10, 20, 40, 80 ha | 10, 20, 40, 80, 160 ha |
| Semillas (barrido y escenarios) | 5 (2 en `limite_1t_160ha_lluvia`) | 20 |
| Semillas (sensibilidad de arquitectura) | 5 | 10 |
| Corridas del barrido | 240 | 1,200 |
| Corridas de escenarios | 126 | 540 |
| Corridas de sensibilidad | 145 | 290 |
| Corridas detalladas | 8 | 8 |
| **Total** | **519** | **2,038** |
| Tiempo medido (Windows 11, Python 3.14, 12 procesos en paralelo) | 1 min 2 s | 6 min 37 s |

El modo rápido no incluye el campo de 160 ha, así que no puede mostrar el cruce de 2 a 4 tractores (que la estimación previa ubica cerca de 170 ha). Para las conclusiones finales hay que usar el modo completo.

## Cada pieza por separado

### Experimentos

```bash
python -m siembra.experimentos --modo rapido
python -m siembra.experimentos --modo completo --solo barrido escenarios --nucleos 6
python -m siembra.experimentos --solo detalladas --salida resultados_prueba
python -m siembra.experimentos --help
```

| Opción | Qué hace |
|---|---|
| `--modo rapido\|completo` | Tamaños de campo y semillas (tabla de arriba). Por defecto `rapido` |
| `--solo EXP [EXP ...]` | Corre solo algunos experimentos: `barrido`, `escenarios`, `sens`, `detalladas`. Por defecto todos |
| `--semillas N` | Número de semillas (0 a N − 1) para todos los experimentos, salvo las detalladas, que siempre usan la semilla 0 |
| `--nucleos K` | Procesos en paralelo. Por defecto núcleos − 1 |
| `--salida carpeta` | Dónde escribir los resultados. Por defecto `resultados/` |
| `--config archivo.json` | Archivo de parámetros base. Por defecto `config/parametros.json` |

Si una corrida falla, el error (id, cambios y traceback) se agrega a `resultados/errores.log` y las demás siguen. El comando termina con código 1 si alguna falló.

### Dashboard

```bash
python herramientas/construir_dashboard.py --ejecutar --html
jupyter lab notebooks/dashboard.ipynb
```

El primer comando genera `notebooks/dashboard.ipynb` a partir de los CSV de `resultados/`, lo ejecuta (unos 2 minutos), guarda las figuras en `resultados/figuras/` y exporta `resultados/dashboard.html`, que se abre en cualquier navegador sin instalar nada. El notebook nunca tiene números escritos a mano: todas las tablas y gráficas salen de los archivos de resultados.

Opciones de `herramientas/construir_dashboard.py`:

| Opción | Qué hace |
|---|---|
| (ninguna) | Solo genera el notebook, sin ejecutarlo |
| `--ejecutar` | Lo ejecuta y guarda sus salidas |
| `--html` | Además exporta `resultados/dashboard.html` (implica `--ejecutar`) |
| `--resultados DIR` | Lee los datos de otra carpeta (también se puede usar la variable `SIEMBRA_RESULTADOS`) |
| `--salida RUTA` | Escribe el notebook en otra ruta |
| `--timeout S` | Segundos máximos por celda |

### Pruebas

```bash
python -m pytest -q
```

Hay que usar `python -m pytest` (no solo `pytest`) para que Python encuentre el paquete `siembra` desde la raíz del proyecto.

| Archivo | Qué prueba |
|---|---|
| `tests/test_config.py` | Carga de parámetros, notación de puntos, validación de entradas (N < 1, probabilidades, precios negativos, depósito fuera del campo, obstáculos en cabecera) y escala de tiempo |
| `tests/test_metricas.py` | Función de costo, intervalos de confianza, pruebas pareadas y sensibilidad económica |
| `tests/test_telemetria.py` | Guardar y cargar corridas, JSON para Unity y sus checksums |
| `tests/test_experimentos.py` | Armado y ejecución de los experimentos |
| `tests/test_reglas.py` | Reglas de la simulación con los tres mecanismos: cobertura completa, sin colisiones, sin intercambios, un paso por celda y sin pisar obstáculos, recargas solo en el depósito, siembra solo sobre surcos, estados de celda que no retroceden, misma semilla = misma corrida, reasignación tras una falla, cobertura con pérdida de mensajes y obstáculos que se rodean |

## Una corrida suelta desde Python

```python
from siembra.config import cargar_config, aplicar
from siembra.modelo import simular
from siembra import telemetria

cfg = aplicar(cargar_config(), {"campo.hectareas": 20, "flota.n_tractores": 2, "mecanismo": "M1", "semilla": 3})
res = simular(cfg, detalle=False)
r = res["resumen"]
print(r["costo_ha"], r["T_dias"], r["cobertura"], r["eficiencia_campo"])

# Con detalle=True la corrida trae una fila por tractor por paso y una por mensaje
det = simular(cfg, detalle=True)
carpeta = telemetria.guardar_corrida(det, "resultados/corridas/prueba_20ha_2t_M1_s3")
print(telemetria.validar_unity(carpeta / "unity.json"))   # (True, []) si el JSON es válido
```

`aplicar` cambia parámetros con notación de puntos sin tocar el archivo. `simular` valida la configuración antes de correr y se detiene con un mensaje que lista cada problema (por ejemplo, `flota.n_tractores debe ser un entero >= 1, no 0`). Las llaves del resumen, las columnas de cada tabla y la geometría del grid están en [`docs/contrato_datos.md`](docs/contrato_datos.md).

## Estructura de carpetas

| Ruta | Contenido |
|---|---|
| `Propuesta.pdf` | Documento de diseño del equipo |
| `config/parametros.json` | Todos los parámetros, con su fuente en `_fuentes` |
| `siembra/config.py` | `cargar_config`, `aplicar`, `validar`, `derivados` (escala de tiempo) |
| `siembra/campo.py` | Grid: patio, cabeceras, área de trabajo, obstáculos y estados de celda |
| `siembra/planificador.py` | A* con costos por tipo de celda y Cooperative A* con ventana (WHCA*) |
| `siembra/comunicacion.py` | Mensajes FIPA-ACL con pérdida y retraso |
| `siembra/agentes.py` | Tractor (agente híbrido) y gestor de subastas del depósito |
| `siembra/modelo.py` | Modelo AgentPy, capa reactiva, falla, resumen y `simular` |
| `siembra/metricas.py` | Función de costo J, costo por hectárea, IC, pruebas pareadas, óptimo por campo, sensibilidad económica |
| `siembra/telemetria.py` | Guardar y cargar corridas, exportar y validar el JSON para Unity |
| `siembra/experimentos.py` | Barrido, escenarios, sensibilidad y corridas detalladas, en paralelo (CLI) |
| `siembra/viz.py` | Paleta y funciones de gráficas (mapas, animación, barras, curvas, tornado) |
| `herramientas/construir_dashboard.py` | Genera y ejecuta `notebooks/dashboard.ipynb` |
| `notebooks/dashboard.ipynb` | Dashboard (generado; no se edita a mano) |
| `correr_todo.py` | Experimentos, dashboard y pruebas en un solo comando |
| `tests/` | Pruebas automáticas (pytest) |
| `docs/` | Modelo, contrato de datos, análisis crítico y mapa de la rúbrica |
| `resultados/` | Salidas generadas (nunca se editan a mano) |

## Parámetros

Todos los parámetros viven en [`config/parametros.json`](config/parametros.json). Nada está escrito en el código.

| Sección | Ejemplos |
|---|---|
| `campo` | `hectareas`, `celda_m`, `deposito_x`, `n_obstaculos`, `obstaculos` |
| `flota` | `n_tractores`, `n_surcadores` (null = mitad y mitad) |
| `escala_tiempo` | `ancho_trabajo_m`, `velocidad_kmh`, `jornada_h`, `dias_laborables` |
| `agente` | `tolva_ha`, `tanque_l`, `consumo_lh`, tiempos de recarga y cambio de implemento, `paciencia_pasos` |
| `comunicacion` | `perdida_mensajes`, `retraso_max`, `timeout_ofertas`, `ventana_reservas`, `margen_recarga_hileras`, `oferta_anticipada` |
| `economia` | `precio_tractor`, `temporadas_vida`, `vida_h`, `precio_diesel`, `rendimiento_t_ha`, `precio_maiz` |
| `agronomia` | `perdida_dia`, `ventana_dias` |
| `falla` | `activa`, `cobertura_disparo` |
| `simulacion` | `max_estancado_pasos`, `max_pasos_factor` (límites para cortar una corrida atorada) |

La sección `_fuentes` dice de dónde sale cada valor (ASABE D497, Profeco, SIAP, INIFAP, Bayer, anuncio de Mercado Libre) o si es un supuesto por confirmar. Para cambiar el caso base edita el JSON y sube `version_parametros`. Para probar un cambio sin tocar el archivo usa `aplicar` (ejemplo de arriba) o `--config otro_archivo.json`. Un valor fuera de rango detiene el programa con un mensaje claro al cargar.

La escala de tiempo se deriva de los parámetros (`config.derivados`): con 9 km/h y 3.04 m de ancho, un paso (una celda de 10 × 10 m trabajada) dura 13.16 s y una jornada de 10 h son 2,736 pasos.

## Qué sale en `resultados/`

| Archivo | Una fila por | Se versiona |
|---|---|---|
| `barrido.csv` | Corrida del barrido (todas las llaves del resumen, incluidos los costos) | Sí |
| `escenarios.csv` | Corrida de escenario (+ `escenario`, `escenario_nombre`) | Sí |
| `curvas.csv` | Punto de la curva de avance de cada corrida de escenario (máximo 200 por corrida) | Sí |
| `sens_arquitectura.csv` | Corrida de la sensibilidad (+ `parametro`, `valor`) | Sí |
| `errores.log` | Corrida que falló, con su traceback | No (bitácora local de cada ejecución) |
| `corridas/<escenario>_<mecanismo>_s0/` | Corrida detallada: `meta.json`, `pasos.csv`, `mensajes.csv`, `serie.csv`, `celdas.npz`, `unity.json` | No (pesa mucho; se regenera) |
| `figuras/` | 36 figuras PNG del dashboard y la animación `animacion_campo.gif`, para el reporte y la presentación | Sí |
| `dashboard.html` | El dashboard ejecutado, para verlo sin Python | Sí |

Las corridas detalladas son 8, todas con semilla 0: `normal_20ha_2t` (M0, M1, M2), `falla_20ha_4t` (M0, M1, M2), `normal_40ha_3t_obst` (M2) y `perdida30_20ha_4t` (M1).

Los costos de cada corrida se pueden recalcular con otros precios sin volver a simular: `metricas.agregar_costos(df, cfg)`.

## Reproducibilidad

- **Semillas fijas.** Cada experimento usa las semillas 0 a N − 1, las mismas para los tres mecanismos, así que las comparaciones son pareadas. Misma semilla y mismos parámetros dan exactamente la misma corrida, se corra en serie o en paralelo. Las fuentes de aleatoriedad están en [`docs/modelo.md`](docs/modelo.md#11-aleatoriedad-y-reproducibilidad-d18).
- **Parámetros versionados.** `version_parametros` (hoy `0.1.0`) viaja dentro de `meta.json` y de `unity.json` de cada corrida detallada, junto con los parámetros completos.
- **Esquema versionado.** `VERSION_ESQUEMA` (hoy `1.0`, en `siembra/__init__.py`) va en cada archivo de corrida y en cada mensaje del JSON para Unity. Cada mensaje lleva un checksum SHA-256 y el archivo uno de todos los cuadros; `telemetria.validar_unity` hace la misma revisión que Unity al cargar.
- **Dependencias fijadas** en `requirements.txt`.
- **Validación de entradas** al cargar la configuración (`config.validar`).
- **Resultados regenerables.** El dashboard se construye solo a partir de los CSV; las corridas detalladas se regeneran con `python -m siembra.experimentos --solo detalladas`.

## Documentación

| Documento | Contenido |
|---|---|
| [`docs/modelo.md`](docs/modelo.md) | El modelo como quedó implementado, regla por regla, y cada desviación respecto a la propuesta |
| [`docs/contrato_datos.md`](docs/contrato_datos.md) | Qué produce cada módulo: API de `simular`, columnas de cada tabla, función de costo, archivos y colores |
| [`docs/analisis_critico.md`](docs/analisis_critico.md) | Qué se puede concluir, sensibilidad, fallos, limitaciones, simulación contra realidad y mejoras |
| [`docs/rubrica.md`](docs/rubrica.md) | Dónde se cubre cada criterio de la rúbrica |

## Problemas comunes

| Síntoma | Causa y solución |
|---|---|
| `ModuleNotFoundError: No module named 'siembra'` | Estás fuera de la raíz del proyecto, o corriste `pytest` en vez de `python -m pytest` |
| `ErrorConfig: Configuración inválida: ...` | Un parámetro está fuera de rango; el mensaje dice cuál y por qué |
| El modo completo tarda mucho | Usa `--nucleos` con los núcleos disponibles, o corre por partes con `--solo` |
| Algunas corridas terminan con `estancado = True` | La corrida dejó de avanzar `simulacion.max_estancado_pasos` pasos; revisar en `resultados/corridas/` o en el análisis crítico (sección 4) |
