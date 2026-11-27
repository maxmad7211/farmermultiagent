# Contrato de datos entre módulos

Este documento fija qué produce cada módulo y en qué formato, para que la simulación, los experimentos, la telemetría y el dashboard puedan desarrollarse por separado. Si cambias un nombre aquí, cámbialo en todos los módulos.

## Estructura y responsables

| Ruta | Contenido |
|---|---|
| `config/parametros.json` | Todos los parámetros con su fuente (`_fuentes`) |
| `siembra/config.py` | `cargar_config`, `aplicar`, `validar`, `derivados` |
| `siembra/campo.py`, `planificador.py`, `comunicacion.py`, `agentes.py`, `modelo.py` | Simulación (AgentPy) |
| `siembra/metricas.py` | Función de costo J, costo por hectárea, intervalos de confianza, pruebas pareadas, sensibilidad económica |
| `siembra/telemetria.py` | Guardar y cargar corridas detalladas, exportar JSON para Unity |
| `siembra/experimentos.py` | Definición de experimentos y ejecución en paralelo (CLI) |
| `siembra/viz.py` | Paleta y funciones de gráficas (Matplotlib) |
| `herramientas/construir_dashboard.py` | Genera y ejecuta `notebooks/dashboard.ipynb` |
| `resultados/` | Salidas generadas (nunca se editan a mano) |

## API de la simulación

```python
from siembra.config import cargar_config, aplicar
from siembra.modelo import simular

cfg = aplicar(cargar_config(), {"campo.hectareas": 20, "flota.n_tractores": 2, "mecanismo": "M1", "semilla": 3})
res = simular(cfg, detalle=False)
```

`simular(cfg, detalle=False) -> dict` con estas llaves:

| Llave | Siempre | Tipo |
|---|---|---|
| `resumen` | sí | `dict` plano (ver abajo). Ya incluye los costos de `metricas.costos` |
| `parametros` | sí | el `cfg` usado |
| `derivados` | sí | salida de `config.derivados(cfg)` |
| `campo` | sí | `dict`: `ancho`, `alto`, `y0`, `y1`, `deposito` `[x, y]`, `obstaculos` `[[x, y, ancho, alto, tipo], ...]`, `celda_m` |
| `serie` | sí | `DataFrame`, una fila cada paso si `detalle`, cada 10 pasos si no |
| `celdas` | sí | `dict` de arreglos numpy, forma `(ancho, alto)`, índice `[x, y]` |
| `pasos` | solo `detalle` | `DataFrame`, una fila por tractor por paso |
| `mensajes` | solo `detalle` | `DataFrame`, una fila por mensaje enviado (incluye perdidos) |

### Geometría del grid

- `x` va de 0 a `ancho - 1` (oeste a este) y `y` de 0 a `alto - 1` (sur a norte). `alto = ancho + 3`.
- Fila `y = 0`: patio del depósito (no se siembra). Fila `y = 1`: cabecera sur. Filas `y0 = 2` a `y1 = ancho + 1`: área de trabajo. Fila `alto - 1`: cabecera norte.
- Una **hilera** de la simulación es una columna `x` del área de trabajo (10 m de ancho).

### `celdas`

| Arreglo | dtype | Significado |
|---|---|---|
| `tipo_base` | int8 | 0 patio, 1 cabecera, 2 trabajo, 5 obstáculo |
| `t_surcado` | int32 | paso en que se surcó; -1 si nunca |
| `t_sembrado` | int32 | paso en que se sembró; -1 si nunca |
| `pasadas` | int32 | veces que un tractor entró a la celda (compactación) |

El estado de una celda en el paso `t` se reconstruye así: sembrada si `0 <= t_sembrado <= t`, surcada si `0 <= t_surcado <= t`, si no libre.

### `serie` (columnas)

`t`, `surcado_frac`, `sembrado_frac` (0 a 1 del área de trabajo), `fila_estacion` (tractores en estado `en_fila`), `en_servicio` (0 o 1), `reservas_activas` (entradas en la tabla de reservas, solo M2, 0 en otros), `mensajes_acum`, `perdidos_acum`.

### `pasos` (columnas)

`t`, `agente` (`"T1"`...), `x`, `y`, `theta` (0 este, 90 norte, 180 oeste, 270 sur), `estado`, `implemento` (`"surcador"` o `"sembradora"`), `intencion` (texto corto: `"surcar"`, `"sembrar"`, `"recargar"`, `"cambiar"`, `"ofertar"`, `"esperar"`, `"estacionar"`, `"ninguna"`), `objetivo_x`, `objetivo_y` (-1 si no hay), `tarea_x` (hilera asignada, -1 si no hay), `carga` (fracción de tolva 0 a 1; NaN si es surcador), `diesel_frac`.

Valores de `estado` (máquina de estados de la figura 2, más `ruta_deposito`):

| Estado | Grupo de actividad (para gráficas) |
|---|---|
| `trabajando` | Trabajando |
| `en_ruta`, `ruta_deposito` | Traslado |
| `en_fila`, `recargando`, `cambiando_implemento` | Estación |
| `esperando_celda`, `esperando_surco` | Esperas |
| `sin_tarea`, `negociando` | Ocio |
| `terminado`, `fuera_servicio` | (fuera del análisis) |

### `mensajes` (columnas)

`t_envio`, `t_entrega`, `performativa` (FIPA-ACL: `cfp`, `propose`, `accept-proposal`, `reject-proposal`, `inform`), `emisor`, `receptor` (`"DEP"` es el depósito gestor), `evento` (solo en `inform`: `inicio`, `fin`, `casi_libre`, `liberada`, `disponible`, `falla`, `recarga`, `implemento`, `fin_tipo`; vacío en otros), `tipo_tarea` (`surcar` o `sembrar`, vacío si no aplica), `x` (hilera, -1 si no aplica), `ronda` (id de subasta, -1 si no aplica), `u` (mejor utilidad ofertada en `propose`, NaN si no aplica), `perdido` (bool).

### `resumen` (llaves)

Identificación: `mecanismo`, `hectareas`, `ha_sembrables`, `ancho`, `n_tractores`, `n_surcadores`, `semilla`, `n_obstaculos`, `perdida_mensajes`, `timeout_ofertas`, `ventana_reservas`, `margen_recarga_hileras`, `tolva_ha`, `falla_activa`, `jornada_h`, `dias_laborables`, `celda_m`.

Escala: `paso_s`, `pasos_dia`.

Tiempo: `T_pasos` (paso de la última celda sembrada), `T_h`, `T_dias` (jornadas), `pasos_simulados`, `estancado` (bool: terminó por falta de avance o por límite de pasos).

Distancia y seguridad: `D_celdas`, `D_por_agente`, `colisiones`, `intercambios`, `vetos` (movimientos bloqueados por la capa reactiva).

Tiempos por estado en horas-tractor, sumados sobre la flota y contados hasta `T_pasos`: `trabajo_h`, `traslado_h`, `W_ocio_h` (incluye negociación), `W_negociacion_h`, `W_espera_h` (en fila), `W_servicio_h` (recargando o cambiando implemento), `W_conflicto_h` (esperando celda), `W_precedencia_h` (esperando surco), `fuera_servicio_h`.

Motor: `H_motor_h` (horas con el tractor en movimiento), `diesel_l`, `recargas`.

Cobertura: `n_celdas_trabajo`, `n_surcadas`, `n_sembradas`, `n_no_sembradas` (incluye las inaccesibles), `celdas_inaccesibles` (celdas de trabajo sin sembrar que quedaron bajo un tractor descompuesto), `cobertura` (0 a 1), `suma_t_siembra_pasos` (suma del paso de siembra de cada celda sembrada), `t_primera_siembra`, `t_ultima_siembra`, `dispersion_dias` (jornadas entre la primera y la última celda sembrada), `q00`, `q05`, ..., `q100` (21 cuantiles del paso de siembra).

Comunicación: `mensajes_total`, `mensajes_perdidos`, `msg_cfp`, `msg_propose`, `msg_accept`, `msg_reject`, `msg_inform`, `subastas`, `reanuncios`, `ofertas_tardias`.

Carga y eficiencia: `hileras_max`, `hileras_min`, `balance_carga` (hileras equivalentes trabajadas por el tractor más cargado menos el menos cargado, mismo rol), `eficiencia_campo` (pasos trabajando ÷ pasos activos), `tiempo_computo_s`.

Falla: `t_falla` (paso en que se descompuso un tractor; -1 si no hubo falla), `tractor_fallado` (nombre, `"T1"`...; vacío si no hubo falla).

Costos (los agrega `metricas.costos`): `R_ha_dia`, `costo_R`, `costo_H`, `costo_colisiones`, `costo_diesel`, `costo_no_sembrada`, `J`, `costo_propiedad`, `costo_ha`, `pct_en_ventana`, `T_dias_calendario`.

### M3 y eventos (opcional)

Solo cuando `mecanismo` es `"M3"` o hay algún evento activo (`eventos.incendio.activo`, `eventos.obstaculo_nuevo.activo` o `coordinador.tasa_reporte_falso` > 0). Sin eso `simular` devuelve exactamente lo de arriba. El detalle está en [`m3.md`](m3.md).

- `eventos` (dict) con `t_quemado`, `t_fin_fuego` (arreglos `(ancho, alto)`, -1 si no aplica), `apagadas`, `origen_incendio`, `t_incendio`, `t_fuego_extinto`, `obstaculos_nuevos` (`[x, y, ancho, alto, t]`) y `zonas` (`[{"t", "celdas", "fuego"}]`, cada cambio de la zona prohibida).
- `registro` (DataFrame) con `t`, `fuente` (`mundo` o `coordinador`), `tipo` (`evento`, `aviso`, `decision`, `plan`, `subasta`), `evento`, `tractor`, `texto` y `motivo`.
- En `pasos`, `implemento` vale `pipa` o `grua` mientras el tractor lleva esa herramienta, `estado` puede valer `emergencia` (grupo Traslado) e `intencion` puede valer `apagar`, `remolcar`, `enganchar`, `revisar`, `alejarse`, `enganchar pipa`, `enganchar grua`, `llenar pipa` o `regresar herramienta`. Solo pasa en M3.
- En `mensajes`, el coordinador es `"SUP"`; además de las performativas de arriba usa `request` y `query-if`. Los eventos nuevos de `inform` son `latido`, `reporte`, `zona`, `descartado`, `objetivo`, `mision_inicio`, `mision_fin`, `apague`, `sin_fuego`, `verificacion`, `entregado`, `reparado`, `rechazo`.
- El resumen agrega `t_incendio`, `t_obstaculo_nuevo`, `t_fuego_extinto`, `t_deteccion_*`, `t_respuesta_*`, `dt_*`, `t_remolque_entregado`, `t_reparado`, `celdas_quemadas`, `area_quemada_ha`, `celdas_apagadas`, `area_perdida_ha`, `celdas_reasignadas`, `reasignadas_ya_hechas`, `area_doble_ha`, `entradas_fuego`, `entradas_peligro`, `entradas_prohibidas`, `entradas_sin_aviso`, `toques_obstaculo`, `frenadas_fuego`, `emergencia_h`, `reportes_total`, `reportes_reales`, `reportes_falsos`, `falsos_descartados`, `falsos_confirmados`, `reales_descartados`, `reportes_verificados`, `reportes_sin_decidir`, `subastas_urgentes`, `replanes` y `decisiones_coordinador`. Con `falla.activa` también se agregan en M0, M1 y M2 (sin cambiar ningún valor existente).
- `corridas/<id>/` puede traer además `eventos.json` y `registro.csv`; `cargar_corrida` los devuelve como `eventos` y `registro`. `unity.json` no cambia.
- `resultados/m3.csv` (una fila por corrida del experimento `m3`, con `dt_deteccion` y `dt_respuesta` del evento de cada escenario) y `resultados/m3_resumen.csv` (media e IC 95 % por escenario y mecanismo).

## Función de costo (`metricas.costos(resumen, cfg) -> dict`)

Se calcula solo con el resumen y los parámetros, para poder repetirla con otros precios sin volver a simular.

```
celda_ha        = celda_m² / 10 000
pasos_dia       = jornada_h · 3600 / paso_s
dias(t)         = t / pasos_dia / dias_laborables            # días calendario desde la fecha óptima
R_ha_dia        = celda_ha · suma_t_siembra_pasos / pasos_dia / dias_laborables
costo_R         = rendimiento · perdida_dia · precio_maiz · R_ha_dia          ($195 por ha·día en el caso base)
costo_H         = precio_tractor · reparacion_frac / vida_h · H_motor_h       ($66.25 por h)
costo_colisiones= penaliza_colision · colisiones
costo_diesel    = precio_diesel · diesel_l
costo_no_sembrada = n_no_sembradas · celda_ha · rendimiento · precio_maiz · perdida_no_sembrada_frac
J               = costo_R + costo_H + costo_colisiones + 0·W_ocio + costo_diesel + costo_no_sembrada
costo_propiedad = n_tractores · precio_tractor / temporadas_vida
costo_ha        = (costo_propiedad + J) / ha_sembrables
pct_en_ventana  = fracción del área de trabajo sembrada a más tardar en el día ventana_dias
                  (se interpola con los cuantiles q00..q100 del paso de siembra)
T_dias_calendario = dias(T_pasos)
```

## Archivos en `resultados/`

| Archivo | Una fila por | Columnas |
|---|---|---|
| `barrido.csv` | corrida | todas las del resumen + `grupo="barrido"` |
| `escenarios.csv` | corrida | resumen + `grupo="escenario"`, `escenario` (id), `escenario_nombre` |
| `sens_arquitectura.csv` | corrida | resumen + `grupo="sens_arq"`, `parametro`, `valor` |
| `curvas.csv` | punto de la serie | `grupo`, `escenario`, `mecanismo`, `semilla`, `t`, `t_h`, `sembrado_frac`, `surcado_frac` (máximo 200 puntos por corrida) |
| `corridas/<id>/` | corrida detallada | `meta.json`, `pasos.csv`, `mensajes.csv`, `serie.csv`, `celdas.npz`, `unity.json` |

`meta.json` contiene `version_esquema`, `parametros`, `resumen`, `campo`, `derivados`. `telemetria.cargar_corrida(carpeta)` devuelve el mismo `dict` que `simular(..., detalle=True)`.

Ids de corridas detalladas: `<escenario>_<mecanismo>_s<semilla>`, por ejemplo `normal_20ha_2t_M1_s0`.

## Convenciones de color (todas las gráficas)

| Qué | Valores |
|---|---|
| Mecanismo | M0 `#2a78d6` (azul), M1 `#eb6834` (naranja), M2 `#1baf7a` (aqua) |
| Grupo de actividad | Trabajando `#008300`, Traslado `#6250d6`, Estación `#eda100`, Esperas `#e87ba4`, Ocio `#c3c2b7` |
| Estado de celda | patio `#e1e0d9`, cabecera `#c3c2b7`, libre `#f3ead7`, surcada `#a0784f`, sembrada `#3f8f3f`, obstáculo `#383835` |
| Implemento (marcadores en el mapa) | surcador: triángulo blanco con borde negro; sembradora: círculo negro con borde blanco |
| Magnitud (mapas de calor) | una sola tonalidad: pasadas en azules, día de siembra en verdes |

Estas paletas pasaron el validador de daltonismo de la guía de visualización (mecanismos: todos los pares; actividades: pares adyacentes en el orden de la tabla).
