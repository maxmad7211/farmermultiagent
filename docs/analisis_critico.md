# Análisis crítico, sensibilidad y limitaciones

Este documento interpreta los resultados de la simulación y discute qué se puede concluir de ellos y qué no. Sigue los puntos de la sección 7 de la rúbrica.

Los números salen del modo completo: 20 semillas, 1,200 corridas del barrido (10 a 160 ha, 1 a 4 tractores, 3 mecanismos), 540 de escenarios y 290 de sensibilidad de arquitectura. Las tablas completas están en el [anexo B](#anexo-b-tablas-completas-de-resultados-modo-completo-20-semillas) y las gráficas en el dashboard (`notebooks/dashboard.ipynb`, `resultados/figuras/`).

**Cómo leer las comparaciones.** Cada comparación entre mecanismos se reporta con la diferencia promedio, su intervalo de confianza del 95 % y el valor p de la prueba pareada (t pareada, o Wilcoxon si las diferencias no son normales), pareando por `semilla`. Antes de leer un valor p muy bajo, revisar la sección 4.1: la variación entre semillas es pequeña por diseño y una diferencia puede ser estadísticamente significativa sin ser importante en pesos.

Todos los cálculos analíticos de este documento usan el mismo método que la estimación previa de la propuesta y se pueden repetir con el código del [anexo A](#anexo-a-revisión-de-la-estimación-previa-de-la-propuesta).

---

## 1. Qué se puede concluir

### 1.1 Pregunta central: cuántos tractores por hectárea

El costo por hectárea tiene dos términos que dependen de la flota en sentidos opuestos:

- **Propiedad**: N × $39,750 ÷ A. Crece con N y baja con el tamaño del campo A.
- **Penalización por retraso R**: $195.54 por ha·día. Baja con N (se siembra más rápido) y crece con A.

H (reparación) y diésel suman unos $394 por ha (≈ 1.12 h de motor por ha con las dos labores) y casi no cambian con N, porque el trabajo total es el mismo. Mueven el nivel de todas las curvas pero no la posición del mínimo. Por eso la simulación solo puede cambiar la respuesta de la estimación previa por dos vías: la **eficiencia real de la flota** (vueltas, traslados, recargas y esperas, que cambian la rapidez de siembra y con ella R) y los **costos de coordinación que crecen con N** (fila en la estación, conflictos en cabecera, ocio por negociación).

Hipótesis que salen de la estimación previa recalculada (anexo A): 1 tractor conviene hasta unas 60 ha, 2 tractores entre 60 y 170 ha, y 4 tractores arriba de 170 ha. Con roles fijos, 3 tractores no deberían ganar nunca (sección 4.1).

**Resultado.** Número de tractores con el menor costo medio por hectárea (`metricas.optimo_por_campo` sobre `barrido.csv`; gráfica `experimental_curvas_costo.png`). Ninguna de las 1,200 corridas del barrido quedó estancada ni con cobertura menor a 100 %.

| Campo | M0 | M1 | M2 | Costo en el óptimo (M2) | Sobrecosto del segundo mejor N (M2, pareado) |
|---|---|---|---|---|---|
| 10 ha | 1 | 1 | 1 | $4,316/ha | 2 tractores: +$3,798/ha |
| 20 ha | 1 | 1 | 1 | $2,535/ha | 2 tractores: +$1,797/ha |
| 40 ha | 1 | 1 | 1 | $1,973/ha | 2 tractores: +$670/ha |
| 80 ha | 2 | 2 | 2 | $1,787/ha | 1 tractor: +$167/ha (IC 95 % $165 a $168) |
| 160 ha | 4* | 4* | 3 | $2,103/ha | 4 tractores: +$276/ha |

\* En el borde del barrido: con M0 y M1 el óptimo de 160 ha podría estar en 5 o más tractores, que no se probaron.

Todas las diferencias contra el segundo mejor N tienen p < 10⁻¹². Son muy grandes en campos chicos (la propiedad domina) y se achican conforme crece el campo: en 80 ha elegir 1 tractor en lugar de 2 cuesta solo $112 a $167 por ha, según el mecanismo. En términos de la pregunta de la propuesta: **una flota dedicada conviene con 1 tractor hasta 40 ha, 2 tractores en 80 ha (0.025 tractores/ha) y 3 o 4 en 160 ha (0.019 a 0.025 tractores/ha)**.

**Dónde quedan los cruces.** El cruce de 1 a 2 tractores cae entre 40 y 80 ha con los tres mecanismos, compatible con las ~60 ha de la estimación previa (el barrido no tiene puntos intermedios para ubicarlo mejor). El cruce de 2 a 4 sí se movió: la estimación lo ponía en 170 ha, así que en 160 ha esperaba 2 tractores, y la simulación da 3 o 4. La razón está en la eficiencia de campo simulada (`eficiencia_campo`): entre 10 y 80 ha queda en 0.63 a 0.73 con 1, 2 o 4 tractores, cerca del 65 % que supone la estimación, y por eso el primer cruce no se mueve; en 160 ha baja a 0.49 a 0.53, porque cada viaje al depósito cruza hasta 126 celdas (casi media hora a 13 s por celda). Con menos eficiencia la siembra tarda más, R pesa más y conviene agregar tractores antes: el cruce se mueve a campos más chicos, como predice el anexo A.3. Ojo: parte de esa baja eficiencia es un artefacto de escala (los traslados están sobreestimados unas 3 veces, sección 5.3), así que el corrimiento del segundo cruce es la conclusión menos firme.

**¿Depende del mecanismo?** No entre 10 y 80 ha: los tres mecanismos eligen el mismo N. Solo en 160 ha difieren (M2 elige 3; M0 y M1, 4), y en esa misma configuración el ranking de mecanismos cambia con N (la gráfica de 160 ha cruza líneas). El mecanismo sí cambia el nivel del costo: en 80 ha con 2 tractores M2 cuesta $1,787/ha contra $1,952 de M0 (−8.5 %), su mayor ventaja en el barrido. En 160 ha con 2 tractores pasa lo contrario: M2 cuesta 21 % más que M0 (sección 4.4).

Alcance de la conclusión: la proporción óptima que salga es válida para una flota **dedicada** a esta siembra (sección 5.1) y con el surcado dentro de la ventana (sección 5.2). Si alguno de esos dos supuestos no se cumple, la respuesta cambia más que con cualquier parámetro económico (sección 3.1).

### 1.2 Por mecanismo

Criterios de éxito fijados en la propuesta, antes de ver los resultados:

| Pregunta de la propuesta | Comparación | Escenario (`escenarios.csv`) | Métrica (columna) | Criterio de éxito | Resultado | ¿Se cumple? |
|---|---|---|---|---|---|---|
| 2. ¿Cuánto reduce Contract Net el ocio y el costo? | M1 contra M0 | `normal_40ha_3t_obst`; barrido con 3 y 4 tractores | `W_ocio_h`, `T_h`, `costo_ha` | `W_ocio_h` ≥ 20 % menor y `T_h` ≥ 5 % menor, p < 0.05 | `T_h` +3.6 % en `normal_40ha_3t_obst` (IC +0.4 a +1.2 h, p = 0.001); en el barrido −5 a −7 % solo con 3 tractores en 10 y 20 ha, y +2 a +19 % en el resto. `W_ocio_h` sube de 0 a 0.4–4.5 h. `costo_ha` +0.05 a +15 % | **No.** Contract Net no reduce ni el ocio ni el tiempo (sección 4.3) |
| 3a. ¿Broadcast y blackboard reducen la espera en la estación? | M2 contra M1 | `tolva_mitad_20ha_4t`, `limite_4t_10ha` | `W_espera_h` | ≥ 30 % menor | −26 % con tolva a la mitad (0.38 → 0.28 h, IC −0.16 a −0.04 h, p = 0.001); −4 % en 10 ha con 4 tractores (p = 0.29) | **Parcial.** Reduce la espera, pero no llega al 30 % y la espera es de minutos |
| 3b. ¿Cooperative A* reduce los conflictos en cabecera? | M2 contra M1 | Barrido con 3 y 4 tractores; `limite_4t_10ha` | `W_conflicto_h`, `vetos` | Menor que M1 | `W_conflicto_h` −96 a −99.6 % en las 10 combinaciones (p < 0.05); `vetos` de 28–1,459 por corrida a ~0 | **Sí** |
| 3c. ¿Justifica los mensajes extra? | M2 contra M1 | Todos | `mensajes_total`, `tiempo_computo_s` contra `costo_ha` y `T_h` | Ahorro con IC que no cruza 0 | M2 manda 1 a 24 % **menos** mensajes que M1 en 8 de 9 escenarios (recarga anticipada = menos hileras liberadas y reanunciadas) y es 3 a 25 % más rápido en 8 de 9; su costo es tiempo de cómputo (+48 a +150 %). Excepción: 1 tractor en 160 ha, donde M2 es 26 % más lento y 24 % más caro | **Sí**, salvo con 1 tractor en campos grandes |
| 3d. Seguridad | Todos | Todas las corridas | `colisiones`, `intercambios` | 0 en todas las corridas | 0 por construcción (sección 4.1) | Sí, pero no discrimina |
| 4a. Robustez ante falla | M0, M1, M2 | `falla_20ha_4t` | `cobertura`, `n_no_sembradas`, `costo_no_sembrada`, `T_h`, `reanuncios` | M1 y M2 siembran todo lo accesible; M2 con menor `T_h` que M1 | M0 siembra 82.5 % (pierde de 7 a 28 % según qué tractor falla) y cuesta $16,742/ha; M1 y M2 siembran todo salvo la celda bajo el tractor descompuesto (~0.6 celdas) y cuestan $8,264 y $8,226/ha. M2 tarda 17 % menos que M1 (8.4 → 7.0 h, p = 0.006) | **Sí** |
| 4b. Robustez ante pérdida de mensajes | M1, M2 contra M0 | `perdida10_20ha_4t`, `perdida30_20ha_4t` | `reanuncios`, `ofertas_tardias`, `T_h`, `costo_ha` | La ventaja sobre M0 se mantiene con 10 % | Con 10 %: M1 +27 % de `T_h` (IC +1.6 a +2.2 h) y M2 +17 % (IC +0.7 a +1.7 h) contra M0. Con 30 %: +127 % y +110 %. `costo_ha` sube 0.6 a 3.3 % | **No.** Con 10 % de pérdida M0 ya es el más rápido |

Las pruebas son pareadas por semilla (`metricas.prueba_pareada`); los porcentajes son la diferencia media entre la media del mecanismo de referencia. Gráficas: `experimental_escenarios_*.png` y `experimental_diferencias_*.png`.

**Resumen de la sección.** M2 cumple lo que prometía la arquitectura: elimina los conflictos en cabecera, recupera la falla más rápido que M1 y es el más rápido en 8 de 9 escenarios y en 14 de 20 combinaciones del barrido. Las excepciones son 40 y 160 ha, sección 4.3. M1 no cumple su criterio: Contract Net con utilidad basada solo en la distancia reparte peor que las franjas fijas. Ninguno de los dos aguanta pérdida de mensajes: con 10 % ya conviene M0, que no se comunica. En pesos las diferencias son pequeñas, porque la propiedad domina el costo (sección 2.1), salvo con falla, donde la diferencia es de 2 a 1.

---

## 2. Por qué ganan ciertos escenarios

### 2.1 Dónde puede un mecanismo mover el costo por hectárea

La parte de R en el costo por hectárea (propiedad + R, estimación previa) dice cuánto puede cambiar el costo un mecanismo que siembra más rápido. Donde la propiedad domina, ningún mecanismo puede mover el costo por hectárea de forma apreciable:

| Campo | 1 tractor | 2 tractores | 4 tractores |
|---|---|---|---|
| 10 ha | R = $165/ha (4 %) | $55/ha (1 %) | $27/ha (0.2 %) |
| 20 ha | $330/ha (14 %) | $110/ha (3 %) | $55/ha (1 %) |
| 40 ha | $660/ha (40 %) | $220/ha (10 %) | $110/ha (3 %) |
| 80 ha | $1,319/ha (73 %) | $440/ha (31 %) | $220/ha (10 %) |
| 160 ha | $2,639/ha (91 %) | $880/ha (64 %) | $440/ha (31 %) |

Consecuencia para leer los resultados: en el escenario `limite_4t_10ha`, aunque M2 redujera R a la mitad, el costo por hectárea bajaría unos $14 de $15,927. Lo mismo pasa con los escenarios adversos y la sensibilidad de arquitectura, que usan 20 ha con 4 tractores: ahí R es cerca del 1 % del costo. En esos casos la comparación entre mecanismos se tiene que hacer con `T_h`, `W_*_h` y mensajes, no con `costo_ha`. Las diferencias de costo entre mecanismos solo pueden ser grandes en campos grandes con pocos tractores.

**Descomposición simulada** (`barrido.csv`, promedio de los tres mecanismos, $/ha y porcentaje del total):

| Campo y flota | Propiedad | R (retraso) | H (reparación) | Diésel | Total |
|---|---|---|---|---|---|
| 10 ha, 1 tractor | $3,882 (90 %) | $142 (3 %) | $58 | $247 | $4,328 |
| 20 ha, 1 tractor | $1,963 (77 %) | $287 (11 %) | $60 | $255 | $2,564 |
| 40 ha, 1 tractor | $1,002 (51 %) | $596 (31 %) | $67 | $286 | $1,950 |
| 80 ha, 1 tractor | $502 (25 %) | $1,179 (58 %) | $66 | $282 | $2,029 |
| 80 ha, 2 tractores | $1,004 (53 %) | $536 (28 %) | $66 | $284 | $1,890 |
| 160 ha, 1 tractor | $250 (7 %) | $2,795 (80 %) | $81 | $347 | $3,474 |
| 160 ha, 4 tractores | $1,002 (45 %) | $780 (35 %) | $82 | $353 | $2,216 |

La parte de R se parece a la de la tabla de arriba cuando la flota es chica: con 1 tractor, R simulado es $596/ha en 40 ha y $2,795 en 160 ha, contra $660 y $2,639 estimados. Con flotas grandes en campos grandes la simulación da bastante más R que la estimación (160 ha con 4 tractores: $780 contra $440), porque ahí se acumulan las pérdidas de coordinación y la baja eficiencia de la sección 1.1. H y diésel suman $305 a $435/ha y casi no cambian con N, como se esperaba; el diésel pesa 4 a 5 veces más que la reparación.

### 2.2 En qué se va el tiempo de la flota

Las horas-tractor por estado (`trabajo_h`, `traslado_h`, `W_espera_h`, `W_servicio_h`, `W_conflicto_h`, `W_precedencia_h`, `W_ocio_h`) explican de dónde sale cada ventaja. Mecanismos que esperamos ver, y qué columna los confirma o los descarta:

| Mecanismo esperado | Dónde debería verse | Columna que lo confirma |
|---|---|---|
| Contract Net reparte mejor cuando las hileras no son iguales (obstáculos que acortan hileras, recargas que detienen una franja, falla) | `normal_40ha_3t_obst`, `falla_20ha_4t` | `balance_carga`, `W_ocio_h`, `T_h` (M1 contra M0) |
| La oferta anticipada evita que la negociación deje al tractor parado | Todos los escenarios con M1 y M2 | `W_negociacion_h` cercano a 0 |
| La recarga anticipada y la fila en blackboard evitan que dos sembradoras se vacíen a la vez | `tolva_mitad_20ha_4t`, `limite_4t_10ha` | `W_espera_h`, `recargas`, serie `fila_estacion` |
| Cooperative A* resuelve los cruces en cabecera sin esperar | Flotas de 3 y 4 tractores | `W_conflicto_h`, `vetos` |
| Con 1 surcador, las sembradoras esperan surco sin importar el mecanismo | `normal_20ha_2t`, `normal_40ha_3t_obst` | `W_precedencia_h` |
| La coordinación cuesta más de lo que aporta cuando sobra flota | `limite_4t_10ha` | `mensajes_total`, `tiempo_computo_s` contra la nula diferencia en `costo_ha` |

**Lo que se observó** (horas-tractor promedio del barrido por mecanismo y tamaño de flota; gráficas `indicadores_actividad_*.png`):

| Horas-tractor | M0 (N = 2 / 3 / 4) | M1 (N = 2 / 3 / 4) | M2 (N = 2 / 3 / 4) |
|---|---|---|---|
| Espera de surco (`W_precedencia_h`) | 0.1 / 13.8 / 0.0 | 10.3 / 29.5 / 7.5 | 0.0 / 0.1 / 0.0 |
| Espera por conflicto (`W_conflicto_h`) | 0.6 / 1.1 / 1.1 | 0.2 / 1.4 / 1.7 | 0.0 / 0.0 / 0.0 |
| Ocio (`W_ocio_h`) | 0 / 0 / 0 | 0.7 / 2.4 / 1.1 | 0.7 / 2.8 / 1.1 |
| Traslado (`traslado_h`) | 21.5 / 21.5 / 21.3 | 20.5 / 22.3 / 20.9 | 26.9 / 30.3 / 27.0 |
| Visitas al depósito (`recargas`) | 34 / 34 / 33 | 34 / 34 / 34 | 46 / 45 / 45 |

Contra la tabla de mecanismos esperados:

- **Contract Net repartiendo mejor:** no se observó. Lo que domina en M1 es la espera de surco. La explicación más probable es que la utilidad solo mide distancia: la sembradora gana la hilera más cercana aunque su surco vaya muy atrás, mientras que en M0 sigue a su surcador en orden. En `normal_20ha_2t` M1 tarda 2.2 h más que M0 (15.1 contra 12.9 h), y 1.7 de esas horas son espera de surco.
- **Oferta anticipada:** el ocio de M1 y M2 se queda en 0.7 a 2.8 h-tractor por corrida, poco frente a 20 o más horas de trabajo. Funciona, pero no elimina por completo el costo de negociar.
- **Recarga anticipada y fila en blackboard:** M2 visita el depósito unas 12 veces más que M0 y M1 (recarga antes de empezar una hilera que no alcanzaría a terminar) y gasta 5 a 8 h-tractor más en traslados, pero a cambio elimina casi toda la espera de surco y de conflicto. El balance le favorece: en `normal_40ha_3t_obst` tarda 16.8 h contra 21.6 de M0 y 22.3 de M1.
- **Cooperative A* en cabecera:** confirmado (pregunta 3b). M0 y M1 acumulan 1 a 2 h-tractor de espera por conflicto con 3 y 4 tractores; M2, prácticamente 0.
- **Esperas de surco con un solo surcador:** confirmado para M0 y M1 con 3 tractores (13.8 y 29.5 h). M2 casi no las tiene. La diferencia más probable con M1 es que las sembradoras de M2 nunca sueltan una hilera a la mitad, porque recargan antes de empezarla: no quedan hileras de siembra reanunciadas a media tarea que obliguen a esperar surco. Las visitas extra al depósito también las retrasan respecto al surcador. Para confirmarlo hace falta la ablación de la mejora 10.
- **Coordinación que no paga:** confirmado en `limite_4t_10ha`. Los tres mecanismos terminan en 3.1 a 3.2 h y cuestan lo mismo (±$8/ha), pero M1 y M2 mandan unos 465 mensajes para lograrlo.

**Curvas de avance** (`experimental_cobertura.png`, de `curvas.csv`). En `falla_20ha_4t` la curva de M0 se aplana en 82.5 % en promedio después de la falla, mientras M1 y M2 llegan a 100 % (M2 en 7.0 h y M1 en 8.4 h). En `normal_20ha_2t` las tres llegan a 100 %, en el orden M2 (11.7 h), M0 (12.9 h) y M1 (15.1 h).

---

## 3. Parámetros más sensibles

### 3.1 Parámetros económicos

En la estimación previa, el tamaño de campo donde conviene pasar de N a 2N tractores es

```
A_cruce(N → 2N) ∝ √( propiedad por tractor × capacidad por día calendario ÷ peso de R )
                = √( (precio_tractor ÷ temporadas_vida) × (velocidad × ancho × eficiencia × jornada × dias_laborables) ÷ (rendimiento × perdida_dia × precio_maiz) )
```

Todos los parámetros entran con exponente ½: un cambio de 4× en un parámetro mueve el cruce 2×. Lo que decide cuál pesa más es qué tan ancho es su rango de incertidumbre. Con los rangos de la sensibilidad planeada en la propuesta:

| Parámetro | Rango | Cruce 1 → 2 | Cruce 2 → 4 | Comentario |
|---|---|---|---|---|
| Caso base | — | 60 ha | 170 ha | |
| Pérdida por día | 0.2 % a 0.6 % | 85 a 49 ha | 241 a 139 ha | El más sensible; además la fuente es de otra región (sección 5.4) |
| Días laborables | 60 % a 100 % | 47 a 60 ha | 132 a 170 ha | |
| Jornada | 8 a 14 h | 54 a 71 ha | 152 a 201 ha | |
| Vida útil | 15 a 25 temporadas | 69 a 54 ha | 196 a 152 ha | |
| Precio del maíz | $5,200 a $7,200 por t | 65 a 55 ha | 183 a 156 ha | |
| Precio del tractor | $750,000 a $840,000 | 58 a 62 ha | 165 a 175 ha | El menos sensible: su rango es de ±6 % |
| Eficiencia de campo | 50 % a 75 % | 53 a 65 ha | 149 a 183 ha | La da la simulación, no es un parámetro |
| Duración de la ventana | 20 a 40 días | sin cambio | sin cambio | No entra en J (ver abajo) |
| Capacidad de tolva | ±50 % | — | — | No entra en la fórmula; solo actúa a través de la simulación (recargas y fila) |

**La duración de la ventana no cambia el costo.** R empieza a contar en la fecha óptima (día 0) y sigue creciendo al mismo ritmo después del cierre, así que la ventana solo cambia `pct_en_ventana`, que es un indicador y no entra en J. La propuesta la incluye en la sensibilidad económica, pero con esta función de costo variarla no puede mover la proporción óptima. Si se quiere que la ventana importe, la pérdida tiene que acelerarse después del cierre (mejora 8).

**Supuestos estructurales que pesan más que cualquier parámetro.** Con la misma fórmula:

| Supuesto | Valor base | Alternativa | Cruce 1 → 2 |
|---|---|---|---|
| Fracción de la propiedad que se carga a esta siembra (sección 5.1) | 100 % | 50 % / 15 % / 5 % | 43 / 23 / 13 ha |
| Surcado dentro de la ventana (sección 5.2) | Sí | Surcos hechos antes del día 0 | 120 ha (y 2 → 4 en 240 ha) |
| Rendimiento | 8.08 t/ha (riego nacional) | La mitad, por ejemplo temporal | ≈ 85 ha |
| Ancho de la sembradora | 4 surcos (3.04 m) | 8 surcos (6.08 m) | ≈ 85 ha |

**Sensibilidad económica simulada** (`metricas.sensibilidad_economica` sobre el barrido, sin volver a simular; gráficas `experimental_tornado_*.png`). Cambio del costo por hectárea en el N óptimo del caso base al mover cada parámetro a su extremo bajo / alto (M2):

| Parámetro | 20 ha (N = 1, $2,535) | 80 ha (N = 2, $1,787) | 160 ha (N = 3, $2,103) |
|---|---|---|---|
| Vida útil (15 a 25 temporadas) | +$654 / −$393 | +$335 / −$201 | +$250 / −$150 |
| Días laborables (60 % a 100 %) | +$185 / $0 | +$305 / $0 | +$576 / $0 |
| Pérdida por día (0.2 % a 0.6 %) | −$139 / +$139 | −$229 / +$229 | −$432 / +$432 |
| Jornada (8 a 14 h) | +$69 / −$79 | +$114 / −$131 | +$216 / −$247 |
| Precio del maíz ($5,200 a $7,200) | −$39 / +$53 | −$64 / +$87 | −$121 / +$164 |
| Precio del tractor ($750k a $840k) | −$114 / +$114 | −$60 / +$60 | −$48 / +$48 |
| Duración de la ventana (20 a 40 días) | $0 / $0 | $0 / $0 | $0 / $0 |

El N óptimo solo cambia en 80 ha, que es el campo más cercano a un cruce: con pérdida de 0.2 %/día, vida útil de 15 temporadas o jornadas de 14 h conviene **1 tractor** en lugar de 2, con los tres mecanismos. En 160 ha, M0 bajaría a 2 tractores con pérdida de 0.2 %. En 10, 20 y 40 ha ningún extremo cambia la respuesta.

Esto confirma la tabla analítica con un matiz: el parámetro que más pesa **depende del tamaño del campo**. En campos chicos manda la vida útil, porque la propiedad es casi todo el costo. En campos grandes mandan los días laborables y la pérdida por día, porque R es casi todo el costo. El precio del tractor es el menos sensible en campos grandes y la duración de la ventana no mueve el costo en ningún caso: solo cambia `pct_en_ventana` (99.4 % con 20 días, 100 % con 30 y 40), como se anticipó.

**Capacidad de tolva** (`tolva_mitad_20ha_4t` contra 20 ha y 4 tractores del barrido, mismas semillas): con la mitad de tolva las visitas al depósito se duplican (9 → 19 en M0; 10 → 21.5 en M2), el tiempo total sube 31 a 36 % (M0 6.9 → 9.5 h; M2 6.0 → 7.9 h) y el costo apenas 0.4 a 0.8 %. La espera en la fila casi no crece (0.30 → 0.36 h en M0): con dos sembradoras la estación no llega a saturarse. M2 sigue siendo el más rápido.

### 3.2 Parámetros de la arquitectura

Lo que esperábamos ver (propuesta) y dónde se mide. Fuente: `resultados/sens_arquitectura.csv` (base de 20 ha y 4 tractores), filtrando por la columna `parametro` y usando `valor` como eje x. Como en esa base R es cerca del 1 % del costo (sección 2.1), los efectos se leen en horas, mensajes y cómputo, no en `costo_ha`.

| Parámetro | Valores | Qué esperamos | Columnas |
|---|---|---|---|
| `timeout_ofertas` | 1, 3, 5, 10 pasos | Muy corto pierde ofertas válidas (más `ofertas_tardias` y `reanuncios`); muy largo deja hileras paradas (más `W_negociacion_h`) | `ofertas_tardias`, `reanuncios`, `W_negociacion_h`, `T_h`, `costo_ha` |
| `perdida_mensajes` | 0 a 50 % | Desde algún nivel M1 y M2 pierden su ventaja sobre M0, que no usa mensajes | `reanuncios`, `T_h`, `costo_ha` de M1 y M2 contra la línea plana de M0 |
| `ventana_reservas` (solo M2) | 5, 10, 20 pasos | Ventanas cortas reaccionan tarde en cabecera; largas cuestan cómputo | `W_conflicto_h`, `vetos`, `tiempo_computo_s` |
| `margen_recarga_hileras` (solo M2) | 0, 1, 2 hileras | Más margen = más viajes al depósito pero menos huecos y menos fila | `recargas`, `W_espera_h`, `traslado_h`, `costo_ha` |

**Resultados** (base de 20 ha y 4 tractores, 10 semillas; gráfica `experimental_sens_arquitectura.png`):

- **Pérdida de mensajes.** Sin pérdida, M2 es 0.9 h más rápido que M0 (IC −1.0 a −0.9 h) y M1 0.2 h más lento (IC +0.1 a +0.3 h). Con 10 % M2 ya pierde contra M0 (+0.9 h, IC +0.7 a +1.1) y la desventaja crece rápido: con 30 % M1 tarda +8.8 h y M2 +8.1 h; con 50 %, +38 h y +30 h, es decir 6.5 y 5.3 veces lo que tarda M0. Casi todo ese tiempo es ocio: tractores esperando subastas o adjudicaciones que se perdieron. M0 no cambia porque no usa mensajes. La diferencia M1 − M0 nunca deja de ser significativa: es positiva desde 0 % de pérdida.
- **Tiempo límite de ofertas.** El mejor es 3 pasos (M2 5.99 h), seguido de cerca por 5 (6.04 h). Con 1 paso se pierden ofertas que sí iban a llegar (los mensajes tardan de 0 a 1 paso por tramo) y el tiempo sube 20 % (M2 7.18 h, con 4 h de ocio). Con 10 pasos las hileras esperan su adjudicación y sube 7 % (6.44 h).
- **Ventana de reservas.** Con 5, 10 o 20 pasos el resultado es idéntico (5.99 h, espera por conflicto prácticamente 0), mientras el tiempo de cómputo sube de 0.26 a 0.43 s por corrida (+65 %). En esta configuración una ventana de 5 basta y 20 no se justifica. La razón es que el modelo replanea en cada paso con prioridad estricta: los conflictos se resuelven a corta distancia.
- **Margen de recarga anticipada.** El mejor es 0 hileras: 5.99 h y $8,203/ha. Con 1 o 2 hileras de margen el tiempo sube 25 % (7.5 h) por los viajes extra, y con 2 la fila desaparece (`W_espera_h` = 0) sin compensar esos viajes.

**Comparación de magnitudes.** Los parámetros de arquitectura mueven mucho el tiempo (hasta 6 veces con 50 % de pérdida) pero poco el costo por hectárea en esta base: como máximo +10 % ($9,033 contra $8,227/ha con 50 % de pérdida en M1), porque ahí R es cerca del 1 % del costo. Los económicos mueven el costo entre 10 y 30 % y, cerca de un cruce, cambian la respuesta. Para la pregunta central pesan más los económicos; para elegir mecanismo pesan más los de arquitectura, sobre todo la pérdida de mensajes.

---

## 4. Fallos y comportamientos inesperados

### 4.1 Detectados por diseño, antes de correr

Estos comportamientos se siguen de las reglas del modelo y hay que tenerlos presentes al leer cualquier gráfica.

**Las colisiones valen 0 por construcción.** La capa reactiva no deja entrar a una celda ocupada al inicio del paso, así que `colisiones` e `intercambios` son siempre 0 en los tres mecanismos. El término λ₃·N_col de J nunca pesa y no sirve para comparar mecanismos. Los conflictos se miden con `vetos` (movimientos bloqueados) y `W_conflicto_h`. Que haya 0 colisiones demuestra que la regla de seguridad funciona, no que un mecanismo sea más seguro que otro.

**Con 2 tractores, M0 y M1 casi no difieren.** Con un surcador y una sembradora, cada "franja fija" es el campo completo y Contract Net no tiene nada que repartir entre tractores del mismo rol; solo cambian el orden de las hileras y el costo de negociar. El escenario `normal_20ha_2t` no puede mostrar la ventaja de Contract Net, y el criterio de éxito del problema 1 (20 % menos ocio, 5 % menos tiempo) no se puede cumplir ahí. La comparación M1 contra M0 tiene sentido con 3 o más tractores, con obstáculos o con falla; por eso los escenarios adversos usan 4 tractores.

**Con roles fijos, 3 tractores no deberían convenir.** Surcador y sembradora avanzan al mismo ritmo. Con 3 tractores el reparto por defecto es 1 surcador y 2 sembradoras, y ninguna flota siembra más rápido de lo que su único surcador abre surcos: el ritmo de siembra es el mismo que con 2 tractores. Con el reparto 2 + 1 el cuello de botella pasa a la única sembradora y el resultado es el mismo. Lo único que 3 tractores pueden ganar sobre 2 es el rezago de la sembradora detrás del surcador cuando va a recargar, y para que convenga ese rezago tendría que valer más que la propiedad extra ($994/ha en 40 ha, $248/ha en 160 ha). Esperamos `W_precedencia_h` alto con N = 3, y el escenario `normal_40ha_3t_obst` medirá sobre todo esa espera. Ver la mejora 4 (roles dinámicos).

**Con 1 tractor no hay coordinación.** Los tres mecanismos solo difieren en el orden de las hileras y en la recarga (anticipada en M2). Diferencias grandes entre mecanismos con N = 1 indicarían un error.

**La variación entre semillas es pequeña.** Sin obstáculos, sin pérdida de mensajes y sin falla, la única aleatoriedad es la duración de los servicios (±20 %) y el retraso de los mensajes (ver [`modelo.md`](modelo.md#11-aleatoriedad-y-reproducibilidad-d18)). En esos escenarios los intervalos de confianza serán estrechos y casi cualquier diferencia saldrá significativa. Hay que juzgar si la diferencia importa en pesos o en horas, no solo si p < 0.05. La propuesta no declaraba fuentes de aleatoriedad; si la simulación hubiera sido determinista, las 20 semillas habrían dado el mismo resultado y la prueba pareada no habría tenido sentido.

**Celdas sin sembrar que parecían gratis.** En la función de costo de la propuesta una celda que nunca se siembra no paga nada (no tiene día de siembra, así que no genera R). M0 con falla, que deja parte de una franja sin sembrar, habría salido más barato que M1. Se agregó `costo_no_sembrada` (100 % de la cosecha de esa celda, $48,884 por ha). Efecto secundario: en `falla_20ha_4t`, si el tractor descompuesto queda sobre una celda sin sembrar, esa celda no se puede sembrar con ningún mecanismo y paga $489 de todos modos, así que la comparación entre mecanismos en ese escenario debe hacerse sobre `n_no_sembradas − celdas_inaccesibles`.

**Una corrida que se atora parece barata en tiempo y carísima en costo.** Si una corrida se corta por `estancado = True`, `T_h` es el paso de la última celda sembrada (pequeño) y las celdas que faltaban pagan como no sembradas (enorme). Promediar esas corridas con las demás distorsiona tanto `T_h` como `costo_ha`; hay que contarlas y reportarlas aparte.

### 4.2 Fallos que aparecieron al construir el modelo

Durante la integración aparecieron bloqueos que obligaron a cambiar reglas. Son evidencia de que el comportamiento colectivo no se sigue directamente de las reglas individuales, y cada uno dejó una regla en el modelo (detalle en [`modelo.md`](modelo.md#14-resumen-de-desviaciones)):

| Fallo observado | Causa | Regla que lo corrige |
|---|---|---|
| Dos tractores de frente en una hilera se bloqueaban para siempre | Con el movimiento lateral prohibido dentro del área de trabajo, cada hilera era un carril de una celda | Cruzar hileras se permite pero cuesta 4.0 (D3) |
| Un tractor se quedaba quieto para siempre frente a celdas sembradas, o iba y venía hasta vaciar el tanque | El costo de esperar en Cooperative A* estaba fuera del intervalo que hace preferible esperar a retroceder | Costo de esperar 1.5, entre 1.0 y 2.0 (D12) |
| Un tractor que debía rodear un tramo prohibido oscilaba | La distancia Manhattan no ve el rodeo | Distancia real del mapa con Reverse Resumable A* (D12) |
| En M2 los tractores de la fila de la estación se bloqueaban mutuamente esperando turno | Cada uno comparaba su hora de llegada actualizada contra horas viejas de los demás | La hora de llegada se anota una sola vez (D12) |
| Un surcador esperaba miles de pasos sin trabajo | El aviso `fin_tipo` llegaba mientras cargaba diésel y se perdía | El aviso se recuerda hasta que el tractor queda libre (D23) |
| En M0 con 2 tractores la sembradora esperaba surco horas | Recorría su franja en sentido contrario al surcador | La sembradora sigue el orden del surcador (sección 7.1 de `modelo.md`) |
| Corridas de 40 ha o más con 3 o 4 tractores se cortaban por estancamiento | Combinación de los anteriores | Ya no ocurre con las reglas actuales en las corridas de prueba |

La lección para el análisis: las comparaciones entre mecanismos dependen de estas reglas de bajo nivel tanto como del mecanismo de coordinación. Un M1 "peor" puede ser un M1 con una regla de tránsito mal calibrada.

### 4.3 Comportamientos que hay que explicar

En las corridas de prueba (una semilla, sin experimentos formales) aparecieron estos comportamientos. Aquí van las explicaciones posibles y la columna que permite distinguirlas; los experimentos dirán cuál es la correcta.

**Con falla, M0 pierde una parte grande del campo y M1 y M2 recuperan todo.** Es lo esperado por diseño, y el tamaño de la pérdida de M0 se puede anticipar: con 4 tractores cada franja de M0 es la mitad del campo, y si la falla llega al 50 % de cobertura a la franja afectada le falta más o menos la mitad. Si falla el surcador, su sembradora tampoco puede sembrar lo que no se surcó; si falla la sembradora, su surcador termina pero nadie siembra detrás. En los dos casos M0 debería perder del orden de un cuarto del campo. Columnas: `n_no_sembradas`, `celdas_inaccesibles`, `tractor_fallado`.

**Con 30 % de mensajes perdidos, M1 y M2 tardan mucho más.** Cada mensaje perdido cuesta tiempo de forma distinta: un `cfp` o un `propose` perdido cuesta una ronda (3 pasos de tiempo límite y hasta 15 de reintento); un `accept-proposal` perdido deja la hilera adjudicada sin dueño hasta que vence su plazo (distancia × 2 + 38 pasos), mientras el tractor espera en `negociando` hasta rendirse y volver a ofertar; un `inform inicio` o `fin` perdido provoca un reanuncio de una hilera que alguien sí está trabajando. Los plazos son fijos y generosos (`holgura_tell = 2`), así que recuperar es lento. M0 no usa mensajes y no se afecta. Columnas: `reanuncios`, `ofertas_tardias`, `W_negociacion_h`, `W_ocio_h`; la sensibilidad de `perdida_mensajes` (0 a 50 %) dice desde qué nivel M0 es mejor.

**M1 a veces es más lento que M0.** No es lo que la propuesta esperaba. Explicaciones posibles: (1) el costo de negociar, si la oferta anticipada no alcanza a cubrir el tiempo de la subasta (`W_negociacion_h`); (2) la utilidad solo usa distancia, así que una sembradora puede ganar la hilera más cercana aunque su surco vaya muy atrás, mientras que en M0 la sembradora sigue a su surcador en orden (`W_precedencia_h`); (3) hileras que cambian de dueño cuando una sembradora va a recargar o se cansa de esperar surco (`reanuncios`, `traslado_h`); (4) con 2 tractores M1 no tiene nada que repartir y solo agrega costo (sección 4.1).

**M2 es el más rápido con 3 y 4 tractores.** Es lo esperado, pero no dice qué componente aporta más (recarga anticipada, fila, Cooperative A* o broadcast). Para saberlo hacen falta las ablaciones de la mejora 10.

**Con 1 tractor los tres mecanismos dan casi lo mismo.** Es lo esperado (sección 4.1) y sirve como comprobación del modelo.

**La eficiencia de campo simulada cae en el rango de ASABE.** Hay que leerlo con cuidado: puede deberse a que los errores de escala se compensan (sección 5.3).

**Lo que confirmaron los experimentos:**

- **Falla.** M0 pierde en promedio el 17.5 % del campo (entre 7.2 y 28.1 % según la semilla), menos que el cuarto esperado. La falla ocurre cuando ya está sembrada la mitad del campo, pero las franjas no avanzan parejo, y cuánto le falta a la franja afectada depende de qué tractor falla y de cuánto llevaba. En la mitad de las corridas de M0 (10 de 20) la sembradora de la franja afectada se queda esperando un surco que nunca llega y la corrida termina por estancamiento: es el comportamiento "sin reacción" que define a M0, no un error.
- **Pérdida de mensajes.** M0 supera a M2 desde 10 % de pérdida y a M1 desde 0 % (sección 3.2). Los reanuncios pasan de 1 (M2) o 14 (M1) sin pérdida a 124 y 146 con 30 %; las ofertas tardías se quedan en 0, así que el costo viene de adjudicaciones e `inform` perdidos que hay que esperar a que venzan, no de ofertas que llegan tarde.
- **M1 más lento que M0.** Pasa en 16 de las 20 combinaciones del barrido. M1 solo es más rápido con 3 tractores en 10 y 20 ha (−0.3 y −0.7 h) y con 1 tractor en 160 ha (−5.1 h). Domina la explicación (2): la espera de surco de M1 es de 10.3 h-tractor con 2 tractores y 29.5 h con 3, contra 0.1 y 13.8 en M0. La (1), negociar, pesa poco (0.5 a 2.4 h de ocio). La peor combinación es 160 ha con 2 tractores: M1 tarda 37 h más que M0.
- **M2 el más rápido con 3 y 4 tractores.** Solo en parte. M2 es el más rápido en 14 de las 20 combinaciones del barrido y en 8 de los 9 escenarios. Con 3 tractores gana siempre (13 a 25 % menos tiempo que M0). Pero en 40 y 160 ha pierde contra M0 con 1, 2 y 4 tractores: +9 a +13 % de tiempo en 40 ha y +23 a +34 % en 160 ha. En 160 ha la recarga anticipada explica buena parte (ver 4.4). En 40 ha la causa no está identificada: ahí la tolva solo desperdicia el 5.5 % de su capacidad (3 hileras de 63 celdas en 200), así que hay que separar componentes con la ablación de la mejora 10 antes de atribuirlo.
- **Con 1 tractor los mecanismos casi no difieren.** No del todo. Hasta 80 ha difieren entre 3 y 9 % en tiempo: M2 es más rápido en 10, 20 y 80 ha y más lento en 40 ha. Esto es más de lo esperado para una flota sin nada que coordinar, y viene de las reglas de recarga y del orden de las hileras, no de la coordinación. En 160 ha la diferencia es grande: M2 tarda 26 % más que M1 y cuesta 24 % más (ver 4.4).
- **Eficiencia de campo.** El promedio del barrido es 0.61, dentro del rango de ASABE, pero 236 de 1,200 corridas quedan fuera: todas las de 160 ha (0.43 a 0.53, por los traslados largos al depósito), las de 3 tractores en 40 y 80 ha (0.51 a 0.54, por la espera de surco del reparto 1 + 2) y algunas de 10 y 20 ha que pasan apenas de 0.75 (máximo 0.77). La corrida de 160 ha con 4 tractores y M2 da 0.45 en promedio.

### 4.4 Observados en las corridas

**Corridas estancadas o incompletas.** En el barrido, 0 de 1,200. En escenarios, 11 de 540: las 10 de M0 con falla (esperadas, ver arriba) y 1 de M1 con 30 % de pérdida. En la sensibilidad, 3 de 290, todas de M1 con 20, 30 y 50 % de pérdida. Esas 4 corridas de M1 son las únicas que, sin falla, dejan celdas sin sembrar: la última hilera queda atrapada en ciclos de adjudicación y reanuncio cuyos mensajes se pierden una y otra vez, hasta que se corta por 3,000 pasos sin avance. M2 no tuvo ninguna en estas corridas.

**El comportamiento inesperado más importante: M2 con 1 tractor en 160 ha.** Tarda 254 h contra 202 de M1 y siembra solo el 60 % dentro de la ventana de 30 días (M0 y M1, 82 a 88 %). La causa es la recarga anticipada combinada con la geometría: la tolva rinde 200 celdas y cada hilera mide 126, así que después de cada hilera quedan 74 celdas de semilla, que no alcanzan para la siguiente, y M2 regresa al depósito. Hace 140 visitas contra 92 y pasa 102 h en traslado contra 63 a 69. Con 2 y 4 tractores en 160 ha la misma regla afecta a cada sembradora, y M2 tarda 34 y 32 % más que M0. Es un caso en que una regla diseñada para evitar filas en la estación empeora el resultado cuando no hay con quién hacer fila. La mejora es que la recarga anticipada se active solo si hay más de una sembradora, o que la sembradora pueda empezar una hilera y recargar a medio camino cuando el depósito queda cerca.

**Filas en la estación.** Ningún escenario promedia más de 0.4 h de espera en la fila. La fila emergente que preveía la propuesta casi no aparece porque con 4 tractores solo 2 son sembradoras, y los surcadores solo van por diésel una vez cada 6 h aproximadamente.

**Recargas.** En 20 ha con 4 tractores (2 sembradoras), el área entre la tolva da unas 10 recargas de semilla (20.25 ha ÷ 2 ha), y se observaron 9 en M0 y 10 en M2, más las de diésel. Con tolva a la mitad, 19 a 21.5. Coinciden con lo esperado.

**Distancia entre corridas de un mismo caso.** Sin obstáculos ni pérdida de mensajes los intervalos de confianza son muy estrechos (en el barrido, el IC del costo óptimo es de ±$1 a ±$25/ha). Como se advirtió en 4.1, eso hace que casi cualquier diferencia salga significativa: varias diferencias de M0 contra M1 con p < 0.001 valen menos de $30/ha.

---

## 5. Limitaciones del modelo

### 5.1 El costo de propiedad se carga completo a una sola labor en un solo campo

El modelo cobra $39,750 por tractor por temporada (precio ÷ 20 temporadas) completo a la siembra de ese campo. En 10 ha con 1 tractor la propiedad sola son $3,975 por ha, el 96 % del costo.

En la realidad un tractor hace otras labores (barbecho, rastreo, fertilización, cultivo, acarreo) y trabaja otros campos, o la siembra se contrata por maquila. La propia propuesta lo supone sin decirlo: una vida útil de 12,000 h en 10 años son 1,200 h por año, unas 600 h por temporada, y sembrar con un tractor ocupa solo una parte:

| Campo | Horas de un tractor para surcar y sembrar (65 % de eficiencia) | Fracción de 600 h |
|---|---|---|
| 10 ha | 11 h | 2 % |
| 20 ha | 22 h | 4 % |
| 40 ha | 45 h | 7.5 % |
| 80 ha | 90 h | 15 % |
| 160 ha | 180 h | 30 % |

Cargarle a la siembra el 100 % de la temporada sesga fuerte hacia flotas pequeñas. En el otro extremo, si la propiedad se cargara por hora de uso, el total de horas-tractor casi no cambia con N y agregar tractores saldría casi gratis: el óptimo sería siempre la flota más grande. La respuesta real está entre los dos extremos y depende de cuánto más trabaje el tractor. Con una fracción de uso del 15 %, el cruce de 1 a 2 tractores bajaría de 60 a 23 ha (sección 3.1).

Mejora: un escenario con fracción de uso del tractor como parámetro, o con costo de maquila o renta por hora o por hectárea. Hay que verificar las tarifas de maquila de siembra en la región antes de usarlas.

Tampoco se incluyen el surcador ni la sembradora en la propiedad (la propuesta lo reconoce). Con más tractores habría que comprar más implementos, lo que también favorece flotas pequeñas.

### 5.2 El surcado está dentro de la ventana de siembra

El modelo arranca el surcado el día 0 (fecha óptima). En riego por gravedad los surcos suelen hacerse antes del riego de presiembra, así que el surcado no estaría en la ruta crítica de la siembra. Si el surcado se adelantara:

- Con 1 tractor la siembra iría del día 0 a A/r en vez de A/r a 2A/r, y R bajaría a un tercio.
- Con N tractores todos sembrarían, no solo la mitad.
- Los cruces se moverían de 60 a 120 ha (1 → 2) y de 170 a 240 ha (2 → 4).

Esto cambia la respuesta a la pregunta central más que cualquier parámetro económico. Hay que justificar el supuesto con la agenda técnica del INIFAP para Nuevo León (calendario de preparación del terreno, riego de presiembra y siembra) o correrlo como escenario.

### 5.3 Escala de la celda contra el implemento

La celda mide 10 m y la sembradora 3.04 m, así que una "hilera" del modelo son unas 3.3 pasadas reales. Dos errores van en sentidos opuestos:

- **Las vueltas en cabecera quedan subrepresentadas**: el modelo da una vuelta por cada 3.3 que daría un tractor real en el mismo ancho.
- **Los traslados quedan sobrerrepresentados**: un paso de 13.16 s por 10 m equivale a 2.7 km/h, contra 9 km/h trabajando y más en traslado. Un traslado simulado tarda unas 3.3 veces lo que tardaría a velocidad de trabajo. La propuesta dice que esto "sobreestima un poco" los traslados; en realidad es un factor de 3.

Por eso la validación de la eficiencia de campo contra el rango de ASABE (50 a 75 %) puede pasar porque los dos errores se compensan, no porque cada uno esté bien calibrado. Además ASABE da la eficiencia de una sola operación, y la eficiencia simulada mezcla surcado y siembra.

La cabecera mide una celda (10 m); una cabecera real suele ser más ancha para que dé vuelta el tractor con el implemento, y se siembra al final. El modelo no siembra cabeceras.

### 5.4 Parámetros que vienen de otras regiones o de estimaciones

La propuesta ya reconoce estas limitaciones; aquí se dice qué efecto tiene cada una sobre la conclusión:

| Parámetro | Problema | Efecto |
|---|---|---|
| Pérdida de 0.4 % por día | Viene de un estudio de Bayer en el norte de las Grandes Llanuras de EE. UU. | Es el parámetro más sensible (sección 3.1). Con 0.2 % el cruce 1 → 2 sube a 85 ha; con 0.6 % baja a 49 ha |
| Rendimiento de 8.08 t/ha | Es el promedio nacional de riego; en Nuevo León predomina el temporal, con rendimientos mucho menores | Con menor rendimiento R pesa menos y convienen flotas más pequeñas (la mitad del rendimiento sube el cruce 1 → 2 a unas 85 ha) |
| Precio del tractor | Sale de un anuncio en Mercado Libre, no de una lista oficial | Poco efecto: su rango es de ±6 % |
| Consumo de diésel | Ecuación de ASABE con la potencia a la toma de fuerza por confirmar | No cambia con N, no mueve el óptimo |
| Ancho de trabajo, velocidad, tolva, tanque | Supuestos hasta tener las fichas técnicas | El ancho y la velocidad definen el paso y con él R: una sembradora de 8 surcos movería el cruce 1 → 2 a unas 85 ha |
| Tiempos de recarga y de cambio de implemento | Supuestos | Afectan las recargas y la fila; se miden con `W_servicio_h` y `W_espera_h` |

### 5.5 Función de costo

- **R es lineal.** La literatura (Purdue) muestra que la pérdida diaria crece con el retraso. Con R lineal la penalización es conservadora para retrasos largos, lo que favorece a las flotas pequeñas en campos grandes.
- **La ventana no entra en J** (sección 3.1). Variarla solo cambia `pct_en_ventana`.
- **La dispersión de siembra no se cobra.** La propuesta argumenta que la maduración desigual cuesta cosecha (hasta 1,789 kg/ha en el estudio de la UNSL), pero `dispersion_dias` se reporta sin peso en J. Como la dispersión crece con T, ese costo también favorecería a flotas más grandes.
- **El ocio no se cobra** ($0), porque un tractor parado ya se paga en R. Es coherente, pero un mecanismo que deja tractores ociosos no se castiga si de todos modos termina igual de rápido.
- **N_col no discrimina** (sección 4.1).
- **Celdas no sembradas.** El 100 % de pérdida es un supuesto agregado; en la realidad el productor resembraría o mandaría otra máquina, con un costo menor que perder la cosecha.

### 5.6 Agentes y coordinación

- **Roles fijos.** Un surcador nunca se vuelve sembradora aunque termine antes; con N impar el reparto queda desbalanceado (sección 4.1).
- **Asignación voraz.** La subasta adjudica por utilidad de mayor a menor; no es la asignación óptima del conjunto. La utilidad solo considera la distancia. M2 además descarta las hileras que la sembradora no alcanza a terminar con su semilla, pero ningún mecanismo considera cuánto falta para que la hilera esté surcada.
- **Cruzar hileras no hace daño.** Para rodear a otro tractor el modelo permite cruzar a la hilera de al lado con un costo de planeación de 4.0, pero no registra ningún daño a los surcos ni a la semilla; en campo, pasar de lado sobre surcos abiertos o sembrados los deforma.
- **Un solo gestor.** En M1 y M2 todas las subastas pasan por el depósito. El depósito no puede fallar en el modelo; en la realidad es un punto único de falla.
- **Una sola estación** en el depósito, sin camión nodriza que lleve la semilla al campo.
- **Una sola falla, programada**: siempre al 50 % de la siembra, siempre definitiva, siempre de un tractor con hilera asignada (solo cuál tractor es aleatorio). No hay fallas aleatorias con su frecuencia real, ni reparaciones.

### 5.7 Esquema del JSON para Unity

El esquema de la propuesta no tenía campo de implemento ni descripción del terreno (se agregaron `implemento` y el bloque `escena`), y el campo `confianza` vale siempre 1.0 porque el modelo no tiene incertidumbre de estado. Se conserva por compatibilidad, pero no aporta información; si se quisiera usar, tendría que venir de un modelo de error de posicionamiento (sección 6).

---

## 6. Simulación contra realidad

Los resultados de la simulación son **comparaciones relativas** entre mecanismos y tamaños de flota bajo los mismos supuestos. No predicen los costos de una explotación real ni los tiempos absolutos de siembra.

| Aspecto | En el modelo | En campo | Efecto esperado sobre las conclusiones |
|---|---|---|---|
| Terreno | Plano, rectangular, cuadrado | Pendiente, forma irregular, varias parcelas | Tiempos reales mayores; más traslados entre parcelas que favorecen flotas con mejor reparto |
| Clima | No existe; días laborables fijos | Lluvia que detiene la siembra en días correlacionados, humedad del suelo | R real mayor y más variable; más días perdidos favorecen flotas grandes |
| Velocidad | Constante; traslado igual de lento que el trabajo | Variable con el suelo; traslado más rápido | Ver sección 5.3 |
| Fallas mecánicas | Una sola, programada, en un escenario | Aleatorias, con reparación, en cualquier tractor | La robustez medida es un caso, no una tasa |
| Comunicación | Pérdida independiente por mensaje y retraso de 0 a `retraso_max` pasos | Pérdidas en ráfagas por distancia, obstáculos o interferencia; caídas del enlace | Los resultados con pérdida son optimistas para M1 y M2 |
| Personas | No hay | Operadores, supervisores y trabajadores en el campo | Las reglas de seguridad reales detendrían la flota más seguido |
| Posicionamiento | Exacto (celda conocida) | GNSS con corrección RTK, con errores y pérdidas de señal | El modelo no puede evaluar el traslape o los huecos entre pasadas |
| Percepción | Exacta: estado de las celdas vecinas y mensajes | Sensores con errores; el estado "surcado" se infiere | La estigmergia real necesita registrar lo hecho (mapa de cobertura compartido) |
| Compactación | Se cuentan las pasadas por celda, sin efecto | Afecta la emergencia y el rendimiento | El costo de pasar sobre lo sembrado no está en J |
| Logística de semilla | Una estación fija en la orilla | Camión nodriza, varias tolvas, bolsas | La espera en la estación puede estar sobreestimada |
| Agronomía | Pérdida lineal por día, ventana fija | Depende del híbrido, la región y el ciclo | Ver sección 5.4 |

**Qué haría falta comprobar en campo.** La eficiencia de campo real de la flota (por ejemplo, con la telemetría de los tractores del socio formador), los tiempos de recarga y de cambio de implemento, el consumo real de diésel, la pérdida por día de retraso con ensayos locales (INIFAP), el calendario real de surcado y siembra en la región, y la pérdida y latencia de la red de radio en un campo real.

---

## 7. Situaciones en las que las conclusiones no valen

1. **Tractores que hacen otras labores o siembra por maquila.** La proporción óptima supone una flota comprada solo para esta siembra (sección 5.1). Con tractores compartidos, el óptimo se mueve hacia flotas más grandes.
2. **Surcos hechos antes de la fecha óptima.** Si el surcado no está en la ruta crítica (riego por gravedad con presiembra), el cruce de 1 a 2 tractores se duplica (de 60 a 120 ha) y el de 2 a 4 sube de 170 a 240 ha (sección 5.2).
3. **Siembra directa o labranza de conservación sin surcado.** Todo el problema de precedencia surcador-sembradora desaparece y el modelo no aplica.
4. **Temporal.** La ventana depende de la lluvia, los días laborables son aleatorios y correlacionados, y el rendimiento es menor. Ninguno de los tres se modela así.
5. **Fuera de los rangos simulados.** Campos de más de 160 ha, flotas de más de 4 tractores, o sembradoras de otro ancho: no se puede extrapolar la curva de costo.
6. **Campos irregulares, con pendiente o con muchos obstáculos.** El modelo solo prueba hasta 2 obstáculos en un cuadrado plano.
7. **Comunicación poco confiable o caída del depósito.** M1 y M2 dependen de un gestor central y de mensajes con pérdidas independientes. Con pérdidas en ráfagas o si cae el depósito, M0 (que no usa mensajes) podría ser el más robusto.
8. **Pérdida por día distinta o no lineal.** Es el parámetro más sensible y viene de otra región. Si la pérdida real se acelera con el retraso, convienen flotas más grandes de lo que dice el modelo.
9. **Diferencias que son significativas pero pequeñas.** Una diferencia de pocos pesos por hectárea entre mecanismos, con valor p muy bajo, refleja la poca variación entre semillas (sección 4.1), no una ventaja que vaya a notarse en campo.

---

## 8. Mejoras propuestas

Cada mejora dice qué problema resuelve, por qué está justificada y cómo se probaría.

| # | Mejora | Justificación | Cómo probarla |
|---|---|---|---|
| 1 | Fracción de uso del tractor o costo de maquila como parámetro | Es el supuesto con más peso en la respuesta (sección 5.1); con 15 % de uso el cruce 1 → 2 baja de 60 a 23 ha | Parámetro `economia.fraccion_uso` (0 a 1) que multiplica la propiedad; se recalcula con `metricas.costos` sin volver a simular. Para maquila, verificar tarifas regionales primero |
| 2 | Escenario con surcado previo | El surcado puede no estar en la ruta crítica (sección 5.2); el cruce 1 → 2 pasaría de 60 a 120 ha | Arrancar con todas las celdas surcadas y todos los tractores como sembradoras; comparar la proporción óptima |
| 3 | Duración de paso distinta para trabajar y para trasladarse, y costo de vuelta en cabecera | Los traslados duran 3.3 veces de más y las vueltas están subrepresentadas (sección 5.3) | Paso de traslado = paso de trabajo × ancho ÷ celda (≈ 0.3); tiempo fijo por vuelta en cabecera de ASABE o medido. Revalidar la eficiencia contra ASABE |
| 4 | Roles dinámicos | Con roles fijos, 3 tractores no aceleran la siembra (sección 4.1) y los surcadores terminan antes y quedan sin trabajo | Que un surcador que termina, o una sembradora que espera surco mucho tiempo, cambie de implemento si la subasta lo justifica; medir `W_precedencia_h` y el óptimo con N = 3 |
| 5 | Asignación óptima y utilidad más completa | La adjudicación voraz no es óptima y la utilidad solo usa distancia | Comparar contra el algoritmo húngaro en cada ronda; agregar a la utilidad la semilla restante y la espera esperada por surco. Medir `T_h` y `balance_carga` |
| 6 | Camión nodriza o segunda estación | Una sola estación fija exagera la fila (sección 5.6) | Parámetro de número de estaciones o una estación móvil que se acerca a la cabecera; medir `W_espera_h` |
| 7 | Gestor redundante o subasta distribuida | El depósito es punto único de falla en M1 y M2 | Escenario con falla del depósito; versión en la que el adjudicatario reanuncia (como decía la propuesta) |
| 8 | Pérdida no lineal y costo de dispersión | La pérdida real crece con el retraso y la dispersión cuesta cosecha (sección 5.5); hoy la ventana no afecta el costo | Pérdida por tramos (0.4 %/día dentro de la ventana, más fuera); peso para `dispersion_dias` con la fuente de la UNSL |
| 9 | Fallas aleatorias con reparación | La falla única y programada no mide una tasa de robustez | Tiempo entre fallas exponencial por tractor y tiempo de reparación; reportar costo esperado |
| 10 | Ablaciones de M2 | Si M2 gana, no se sabe qué componente aporta | M2 sin Cooperative A* y M2 sin recarga anticipada (ya previstas en la propuesta) |
| 11 | Más variabilidad realista | La poca variación entre semillas hace que todo salga significativo (sección 4.1) | Velocidad variable por celda (tipo de suelo) y días laborables aleatorios en vez de una fracción fija |
| 12 | Validación con datos reales | La simulación solo se valida contra el rango de eficiencia de ASABE | Comparar eficiencia, tiempos de recarga y consumo con registros de tractores reales del socio formador |
| 13 | Acuse de recibo y plazos adaptativos en Contract Net | Con pérdida de mensajes alta, M1 y M2 dependen de plazos fijos y lentos para recuperarse (sección 4.3) | Reenviar `accept-proposal` hasta recibir `inform inicio`; plazos proporcionales al retraso medido. Repetir la sensibilidad de `perdida_mensajes` y ver si se mueve el nivel en que M0 gana |

---

## Anexo A. Revisión de la estimación previa de la propuesta

### A.1 Método

El mismo que la propuesta: eficiencia de campo de 65 % (capacidad efectiva 2.736 × 0.65 = 1.778 ha/h), jornadas de 10 h (r = 17.78 ha por jornada), días continuos, sin esperas, y solo propiedad más R. Con 1 tractor surca todo (días 0 a A/r) y después siembra (A/r a 2A/r); con 2, uno surca y otro siembra detrás; con 4, dos y dos.

```
propiedad/ha = N × 39,750 / A
R/ha         = 195.54 × día promedio de siembra
día promedio = 1.5 · A / r                 (1 tractor)
             = A / (2 · sembradoras · r)   (N ≥ 2, sembradoras = N / 2)
```

### A.2 Tabla de la propuesta contra la recalculada

Costo por hectárea en pesos (propiedad + R). El piso es la propiedad sola (N × 39,750 ÷ A): ningún valor puede quedar debajo porque R ≥ 0.

| Campo | Propuesta 1 / 2 / 4 | Recalculada 1 / 2 / 4 | Piso 1 / 2 / 4 |
|---|---|---|---|
| 10 ha | 4,049 / **7,819** / **15,555** | 4,140 / 8,005 / 15,927 | 3,975 / 7,950 / 15,900 |
| 20 ha | 2,293 / 4,036 / **7,907** | 2,317 / 4,085 / 8,005 | 1,988 / 3,975 / 7,950 |
| 40 ha | 1,638 / 2,163 / 3,993 | 1,653 / 2,207 / 4,085 | 994 / 1,988 / 3,975 |
| 80 ha | 1,811 / 1,421 / 2,183 | 1,816 / 1,434 / 2,207 | 497 / 994 / 1,988 |
| 160 ha | 2,907 / 1,380 / 1,429 | 2,887 / 1,376 / 1,434 | 248 / 497 / 994 |

En negritas, las tres celdas de la propuesta que quedan debajo del piso, lo cual es imposible: 10 ha con 2 tractores ($7,819 < $7,950), 10 ha con 4 tractores ($15,555 < $15,900) y 20 ha con 4 tractores ($7,907 < $7,950). Las demás diferencias son de redondeo. Los cruces de la propuesta sí cuadran: 1 → 2 en 60.1 ha y 2 → 4 en 170.1 ha.

### A.3 Afirmaciones de la propuesta que no se sostienen

- **"La simulación alarga T y mueve los cruces hacia campos más chicos."** No está garantizado. La estimación ya supone 65 % de eficiencia, que incluye vueltas, traslados y recargas. Si la eficiencia simulada sale mayor que 65 %, T baja y los cruces se mueven hacia campos *más grandes* (con 75 %, el cruce 1 → 2 pasa a 65 ha). Hay que comparar contra `eficiencia_campo`.
- **"1 tractor en 80 ha no cumple la ventana."** La misma estimación dice que 1 tractor surca y siembra 80 ha en unas 9 jornadas, dentro de los 30 días. Por eso, además de `limite_1t_80ha`, se agregó el escenario `limite_1t_160ha_lluvia`: 160 ha con 60 % de días laborables, que necesita 18 jornadas ÷ 0.6 ≈ 30 días calendario y queda justo en el límite. Si la eficiencia simulada es menor que 65 %, se sale de la ventana.
- **Presupuesto de cómputo.** La propuesta cuenta 7 escenarios × 3 mecanismos × 20 semillas = 420 corridas y 1,620 en total, pero la pérdida de mensajes tiene 2 niveles (10 % y 30 %), así que son 8 configuraciones (9 con el escenario límite agregado), y no contaba las corridas de la sensibilidad de arquitectura. Con lo implementado, el modo completo son 2,038 corridas: 1,200 del barrido, 540 de escenarios, 290 de sensibilidad (con 10 semillas) y 8 detalladas.
- **Roles con N tractores.** La estimación usa "con 4, dos surcan y dos siembran", pero la propuesta no dice cómo se reparten 3 tractores. Con 3, el reparto 1 + 2 o 2 + 1 cambia el resultado y, con roles fijos, ninguno siembra más rápido que 2 tractores (sección 4.1).

### A.4 Código para repetir los números

```python
import math

r = 9 * 3.04 / 10 * 0.65 * 10       # ha por jornada (65 % de eficiencia, 10 h)
w = 8.08 * 0.004 * 6050             # $ por ha·día
prop = 795000 / 20                  # $ por tractor por temporada

def costo_ha(A, N, surcado_previo=False):
    if N == 1:
        dia = (0.5 if surcado_previo else 1.5) * A / r
    else:
        sembradoras = N if surcado_previo else N // 2
        dia = A / (2 * sembradoras * r)
    return prop * N / A + w * dia

for A in (10, 20, 40, 80, 160):
    print(A, [round(costo_ha(A, N)) for N in (1, 2, 4)])
print("cruce 1->2:", math.sqrt(prop * r / w), "cruce 2->4:", math.sqrt(8 * prop * r / w))
```

<!-- Nota interna: los números de las secciones 2.1, 3.1, 5.1, 5.2 y del anexo A salen de la fórmula de A.4 y no dependen de la simulación. Si cambian los parámetros base en config/parametros.json, hay que recalcularlos. -->


## Anexo B. Tablas completas de resultados (modo completo, 20 semillas)

Corridas: barrido 1200, escenarios 540, sensibilidad de arquitectura 290. Colisiones: 0. Intercambios: 0. Corridas estancadas en el barrido: 0.

### Costo medio por hectárea ($/ha) según tamaño de campo, tractores y mecanismo

|          |    M0 |    M1 |    M2 |
|:---------|------:|------:|------:|
| (10, 1)  |  4332 |  4335 |  4316 |
| (10, 2)  |  8131 |  8136 |  8114 |
| (10, 3)  | 11996 | 12060 | 12045 |
| (10, 4)  | 15859 | 15867 | 15861 |
| (20, 1)  |  2579 |  2579 |  2535 |
| (20, 2)  |  4374 |  4392 |  4331 |
| (20, 3)  |  6317 |  6342 |  6329 |
| (20, 4)  |  8227 |  8246 |  8203 |
| (40, 1)  |  1930 |  1947 |  1973 |
| (40, 2)  |  2606 |  2645 |  2643 |
| (40, 3)  |  3558 |  3583 |  3536 |
| (40, 4)  |  4478 |  4502 |  4515 |
| (80, 1)  |  2091 |  2042 |  1954 |
| (80, 2)  |  1952 |  1930 |  1787 |
| (80, 3)  |  2324 |  2386 |  2218 |
| (80, 4)  |  2659 |  2674 |  2565 |
| (160, 1) |  3387 |  3155 |  3878 |
| (160, 2) |  2271 |  2732 |  2751 |
| (160, 3) |  2223 |  2555 |  2103 |
| (160, 4) |  2063 |  2206 |  2379 |

### Número óptimo de tractores (mínimo costo medio)

| mecanismo   |   hectareas |   n_optimo |   media |   ic95 |   ha_por_tractor |
|:------------|------------:|-----------:|--------:|-------:|-----------------:|
| M0          |          10 |          1 |  4332.2 |    0.4 |             10   |
| M0          |          20 |          1 |  2578.7 |    0.5 |             20   |
| M0          |          40 |          1 |  1930   |    0.7 |             40   |
| M0          |          80 |          2 |  1952.3 |    1.8 |             40   |
| M0          |         160 |          4 |  2063.1 |    2.7 |             40   |
| M1          |          10 |          1 |  4335.2 |    0.8 |             10   |
| M1          |          20 |          1 |  2578.8 |    0.5 |             20   |
| M1          |          40 |          1 |  1947   |    0.8 |             40   |
| M1          |          80 |          2 |  1930.2 |    8.7 |             40   |
| M1          |         160 |          4 |  2206.4 |   24.5 |             40   |
| M2          |          10 |          1 |  4315.8 |    0.7 |             10   |
| M2          |          20 |          1 |  2534.9 |    0.8 |             20   |
| M2          |          40 |          1 |  1972.7 |    1.3 |             40   |
| M2          |          80 |          2 |  1786.8 |    0.9 |             40   |
| M2          |         160 |          3 |  2103.5 |    1.7 |             53.3 |

### Eficiencia de campo simulada (validación contra ASABE, 50 a 75 %)

Media 0.61, mínimo 0.37, máximo 0.77; corridas fuera de 0.50–0.75: 236 de 1200.

### Escenarios (medias por mecanismo)

|                                  |     T_h |   cobertura |   costo_ha |   W_ocio_h |   W_espera_h |   W_conflicto_h |   W_precedencia_h |   mensajes_total |   reanuncios |   pct_en_ventana |
|:---------------------------------|--------:|------------:|-----------:|-----------:|-------------:|----------------:|------------------:|-----------------:|-------------:|-----------------:|
| ('falla_20ha_4t', 'M0')          |   6.338 |       0.825 |   16742.2  |      0     |        0.294 |           0.024 |             0.507 |             0    |         0    |            0.825 |
| ('falla_20ha_4t', 'M1')          |   8.369 |       1     |    8263.7  |      0.344 |        0.333 |           0.285 |             0.217 |           802.5  |        14.7  |            1     |
| ('falla_20ha_4t', 'M2')          |   6.964 |       1     |    8225.73 |      0.326 |        0.332 |           0.005 |             0.221 |           713.4  |         4.35 |            1     |
| ('limite_1t_160ha_lluvia', 'M0') | 206.919 |       1     |    5207.11 |      0     |        0     |           0     |             0     |             0    |         0    |            0.816 |
| ('limite_1t_160ha_lluvia', 'M1') | 201.798 |       1     |    4828.72 |      1.234 |        0     |           0     |             0     |          3057.65 |        92.55 |            0.884 |
| ('limite_1t_160ha_lluvia', 'M2') | 253.75  |       1     |    5974.87 |      1.851 |        0     |           0     |             0     |          3520.15 |        14.3  |            0.598 |
| ('limite_1t_80ha', 'M0')         |  92.69  |       1     |    2090.89 |      0     |        0     |           0     |             0     |             0    |         0    |            1     |
| ('limite_1t_80ha', 'M1')         |  93.002 |       1     |    2042.29 |      0.611 |        0     |           0     |             0     |          1753.7  |        45.9  |            1     |
| ('limite_1t_80ha', 'M2')         |  85.629 |       1     |    1953.71 |      0.688 |        0     |           0     |             0     |          1567.45 |         6    |            1     |
| ('limite_4t_10ha', 'M0')         |   3.126 |       1     |   15859.5  |      0     |        0.274 |           0.006 |             0.026 |             0    |         0    |            1     |
| ('limite_4t_10ha', 'M1')         |   3.184 |       1     |   15867.2  |      0.391 |        0.256 |           0.093 |             0     |           468.2  |         5.35 |            1     |
| ('limite_4t_10ha', 'M2')         |   3.097 |       1     |   15861    |      0.471 |        0.246 |           0.004 |             0     |           461.8  |         1.2  |            1     |
| ('normal_20ha_2t', 'M0')         |  12.916 |       1     |    4373.9  |      0     |        0     |           0.03  |             0.08  |             0    |         0    |            1     |
| ('normal_20ha_2t', 'M1')         |  15.12  |       1     |    4391.62 |      0.284 |        0.176 |           0.037 |             1.678 |           738.1  |        20.8  |            1     |
| ('normal_20ha_2t', 'M2')         |  11.729 |       1     |    4331.42 |      0.207 |        0.003 |           0.001 |             0     |           660.7  |         1    |            1     |
| ('normal_40ha_3t_obst', 'M0')    |  21.565 |       1     |    3561.86 |      0     |        0.274 |           0.2   |             8.599 |             0    |         0    |            1     |
| ('normal_40ha_3t_obst', 'M1')    |  22.341 |       1     |    3589.35 |      1.894 |        0.098 |           0.941 |            12.416 |          1419.4  |        73.75 |            1     |
| ('normal_40ha_3t_obst', 'M2')    |  16.786 |       1     |    3542.47 |      2.879 |        0.311 |           0.019 |             0     |          1074.9  |         3.05 |            1     |
| ('perdida10_20ha_4t', 'M0')      |   6.927 |       1     |    8227.32 |      0     |        0.298 |           0.055 |             0.026 |             0    |         0    |            1     |
| ('perdida10_20ha_4t', 'M1')      |   8.792 |       1     |    8303.83 |      5.533 |        0.16  |           0.379 |             0     |           880.55 |        52.15 |            1     |
| ('perdida10_20ha_4t', 'M2')      |   8.116 |       1     |    8276.25 |      5.242 |        0.287 |           0.009 |             0     |           848.8  |        35.75 |            1     |
| ('perdida30_20ha_4t', 'M0')      |   6.927 |       1     |    8227.32 |      0     |        0.298 |           0.055 |             0.026 |             0    |         0    |            1     |
| ('perdida30_20ha_4t', 'M1')      |  15.713 |       0.999 |    8501.72 |     27.161 |        0.158 |           0.458 |             0.034 |          1443.5  |       146    |            0.999 |
| ('perdida30_20ha_4t', 'M2')      |  14.515 |       1     |    8438.77 |     24.295 |        0.239 |           0.022 |             0     |          1396.25 |       126.6  |            1     |
| ('tolva_mitad_20ha_4t', 'M0')    |   9.449 |       1     |    8293.79 |      0     |        0.362 |           0.056 |             0.026 |             0    |         0    |            1     |
| ('tolva_mitad_20ha_4t', 'M1')    |   9.466 |       1     |    8299.08 |      0.505 |        0.384 |           0.4   |             0     |           876.65 |        22.2  |            1     |
| ('tolva_mitad_20ha_4t', 'M2')    |   7.867 |       1     |    8239.3  |      0.452 |        0.283 |           0.006 |             0     |           840.85 |         0.7  |            1     |

### Pruebas pareadas del tiempo total T (h) por escenario


M1 contra M0 (diferencia = M1 − M0; negativo = M1 más rápido)

| escenario              |   n |   diferencia_media |   ic_bajo |   ic_alto |    p_t |   p_wilcoxon |
|:-----------------------|----:|-------------------:|----------:|----------:|-------:|-------------:|
| falla_20ha_4t          |  20 |             2.0312 |    1.2825 |    2.78   | 0      |       0      |
| limite_1t_160ha_lluvia |  20 |            -5.121  |   -5.3856 |   -4.8564 | 0      |       0.0001 |
| limite_1t_80ha         |  20 |             0.3118 |    0.1623 |    0.4613 | 0.0003 |       0.0006 |
| limite_4t_10ha         |  20 |             0.0587 |   -0.0298 |    0.1471 | 0.1812 |       0.8813 |
| normal_20ha_2t         |  20 |             2.2034 |    2.1124 |    2.2944 | 0      |       0      |
| normal_40ha_3t_obst    |  20 |             0.7761 |    0.3728 |    1.1794 | 0.0007 |       0.0019 |
| perdida10_20ha_4t      |  20 |             1.8642 |    1.5764 |    2.1521 | 0      |       0      |
| perdida30_20ha_4t      |  20 |             8.7853 |    8.0208 |    9.5498 | 0      |       0      |
| tolva_mitad_20ha_4t    |  20 |             0.0172 |   -0.1169 |    0.1513 | 0.7915 |       0.695  |


M2 contra M1 (diferencia = M2 − M1; negativo = M2 más rápido)

| escenario              |   n |   diferencia_media |   ic_bajo |   ic_alto |    p_t |   p_wilcoxon |
|:-----------------------|----:|-------------------:|----------:|----------:|-------:|-------------:|
| falla_20ha_4t          |  20 |            -1.4055 |   -2.3463 |   -0.4647 | 0.0056 |       0.0153 |
| limite_1t_160ha_lluvia |  20 |            51.9519 |   51.6862 |   52.2177 | 0      |       0      |
| limite_1t_80ha         |  20 |            -7.373  |   -7.5257 |   -7.2203 | 0      |       0.0001 |
| limite_4t_10ha         |  20 |            -0.0874 |   -0.1559 |   -0.0189 | 0.0152 |       0.0076 |
| normal_20ha_2t         |  20 |            -3.3911 |   -3.481  |   -3.3011 | 0      |       0      |
| normal_40ha_3t_obst    |  20 |            -5.555  |   -5.9448 |   -5.1653 | 0      |       0      |
| perdida10_20ha_4t      |  20 |            -0.676  |   -1.397  |    0.0451 | 0.0646 |       0.0017 |
| perdida30_20ha_4t      |  20 |            -1.1976 |   -2.2747 |   -0.1204 | 0.0312 |       0.0266 |
| tolva_mitad_20ha_4t    |  20 |            -1.599  |   -1.7273 |   -1.4708 | 0      |       0      |


M2 contra M0 (diferencia = M2 − M0; negativo = M2 más rápido)

| escenario              |   n |   diferencia_media |   ic_bajo |   ic_alto |    p_t |   p_wilcoxon |
|:-----------------------|----:|-------------------:|----------:|----------:|-------:|-------------:|
| falla_20ha_4t          |  20 |             0.6257 |    0.0038 |    1.2476 | 0.0487 |       0.1327 |
| limite_1t_160ha_lluvia |  20 |            46.831  |   46.7179 |   46.944  | 0      |       0      |
| limite_1t_80ha         |  20 |            -7.0612 |   -7.2062 |   -6.9162 | 0      |       0      |
| limite_4t_10ha         |  20 |            -0.0287 |   -0.0682 |    0.0108 | 0.1446 |       0.1312 |
| normal_20ha_2t         |  20 |            -1.1877 |   -1.2545 |   -1.1208 | 0      |       0      |
| normal_40ha_3t_obst    |  20 |            -4.7789 |   -4.8902 |   -4.6676 | 0      |       0      |
| perdida10_20ha_4t      |  20 |             1.1882 |    0.6674 |    1.7091 | 0.0001 |       0.0001 |
| perdida30_20ha_4t      |  20 |             7.5877 |    6.894  |    8.2815 | 0      |       0      |
| tolva_mitad_20ha_4t    |  20 |            -1.5819 |   -1.6354 |   -1.5283 | 0      |       0      |

### Sensibilidad de arquitectura (medias)

|                                                    |    T_h |   W_ocio_h |   W_espera_h |   reanuncios |   mensajes_perdidos |   cobertura |
|:---------------------------------------------------|-------:|-----------:|-------------:|-------------:|--------------------:|------------:|
| ('comunicacion.margen_recarga_hileras', 0.0, 'M2') |  5.987 |      0.436 |        0.266 |          1   |                 0   |       1     |
| ('comunicacion.margen_recarga_hileras', 1.0, 'M2') |  7.508 |      0.567 |        0.355 |          7.2 |                 0   |       1     |
| ('comunicacion.margen_recarga_hileras', 2.0, 'M2') |  7.545 |      0.569 |        0     |         12.1 |                 0   |       1     |
| ('comunicacion.perdida_mensajes', 0.0, 'M0')       |  6.927 |      0     |        0.291 |          0   |                 0   |       1     |
| ('comunicacion.perdida_mensajes', 0.0, 'M1')       |  7.118 |      0.41  |        0.339 |         14   |                 0   |       1     |
| ('comunicacion.perdida_mensajes', 0.0, 'M2')       |  5.987 |      0.436 |        0.266 |          1   |                 0   |       1     |
| ('comunicacion.perdida_mensajes', 0.1, 'M0')       |  6.927 |      0     |        0.291 |          0   |                 0   |       1     |
| ('comunicacion.perdida_mensajes', 0.1, 'M1')       |  8.997 |      5.552 |        0.126 |         53.6 |                91.4 |       1     |
| ('comunicacion.perdida_mensajes', 0.1, 'M2')       |  7.822 |      4.75  |        0.305 |         34.7 |                86   |       1     |
| ('comunicacion.perdida_mensajes', 0.2, 'M0')       |  6.927 |      0     |        0.291 |          0   |                 0   |       1     |
| ('comunicacion.perdida_mensajes', 0.2, 'M1')       | 11.718 |     14.782 |        0.163 |         93.7 |               226.5 |       0.998 |
| ('comunicacion.perdida_mensajes', 0.2, 'M2')       | 10.657 |     12.115 |        0.269 |         75.1 |               221.6 |       1     |
| ('comunicacion.perdida_mensajes', 0.3, 'M0')       |  6.927 |      0     |        0.291 |          0   |                 0   |       1     |
| ('comunicacion.perdida_mensajes', 0.3, 'M1')       | 15.724 |     26.091 |        0.21  |        145.8 |               432.2 |       0.998 |
| ('comunicacion.perdida_mensajes', 0.3, 'M2')       | 15.051 |     25.816 |        0.192 |        124.2 |               412.9 |       1     |
| ('comunicacion.perdida_mensajes', 0.5, 'M0')       |  6.927 |      0     |        0.291 |          0   |                 0   |       1     |
| ('comunicacion.perdida_mensajes', 0.5, 'M1')       | 44.83  |    124.538 |        0.048 |        341.8 |              1697.5 |       0.996 |
| ('comunicacion.perdida_mensajes', 0.5, 'M2')       | 36.635 |    104.839 |        0.101 |        296.1 |              1529.6 |       1     |
| ('comunicacion.timeout_ofertas', 1.0, 'M1')        |  8.091 |      4.254 |        0.191 |         10.8 |                 0   |       1     |
| ('comunicacion.timeout_ofertas', 1.0, 'M2')        |  7.18  |      4.047 |        0.314 |          0.2 |                 0   |       1     |
| ('comunicacion.timeout_ofertas', 3.0, 'M1')        |  7.118 |      0.41  |        0.339 |         14   |                 0   |       1     |
| ('comunicacion.timeout_ofertas', 3.0, 'M2')        |  5.987 |      0.436 |        0.266 |          1   |                 0   |       1     |
| ('comunicacion.timeout_ofertas', 5.0, 'M1')        |  7.055 |      0.647 |        0.325 |         14.2 |                 0   |       1     |
| ('comunicacion.timeout_ofertas', 5.0, 'M2')        |  6.042 |      0.615 |        0.236 |          2.1 |                 0   |       1     |
| ('comunicacion.timeout_ofertas', 10.0, 'M1')       |  7.522 |      1.55  |        0.37  |         20.3 |                 0   |       1     |
| ('comunicacion.timeout_ofertas', 10.0, 'M2')       |  6.443 |      1.575 |        0.272 |          8.1 |                 0   |       1     |
| ('comunicacion.ventana_reservas', 5.0, 'M2')       |  5.987 |      0.436 |        0.266 |          1   |                 0   |       1     |
| ('comunicacion.ventana_reservas', 10.0, 'M2')      |  5.987 |      0.436 |        0.266 |          1   |                 0   |       1     |
| ('comunicacion.ventana_reservas', 20.0, 'M2')      |  5.987 |      0.436 |        0.266 |          1   |                 0   |       1     |

### Sensibilidad económica: N óptimo con valor bajo / base / alto (M2)

|                                        |   alto |   bajo |   base |
|:---------------------------------------|-------:|-------:|-------:|
| ('agronomia.perdida_dia', 10)          |      1 |      1 |      1 |
| ('agronomia.perdida_dia', 20)          |      1 |      1 |      1 |
| ('agronomia.perdida_dia', 40)          |      1 |      1 |      1 |
| ('agronomia.perdida_dia', 80)          |      2 |      1 |      2 |
| ('agronomia.perdida_dia', 160)         |      3 |      3 |      3 |
| ('agronomia.ventana_dias', 10)         |      1 |      1 |      1 |
| ('agronomia.ventana_dias', 20)         |      1 |      1 |      1 |
| ('agronomia.ventana_dias', 40)         |      1 |      1 |      1 |
| ('agronomia.ventana_dias', 80)         |      2 |      2 |      2 |
| ('agronomia.ventana_dias', 160)        |      3 |      3 |      3 |
| ('economia.precio_maiz', 10)           |      1 |      1 |      1 |
| ('economia.precio_maiz', 20)           |      1 |      1 |      1 |
| ('economia.precio_maiz', 40)           |      1 |      1 |      1 |
| ('economia.precio_maiz', 80)           |      2 |      2 |      2 |
| ('economia.precio_maiz', 160)          |      3 |      3 |      3 |
| ('economia.precio_tractor', 10)        |      1 |      1 |      1 |
| ('economia.precio_tractor', 20)        |      1 |      1 |      1 |
| ('economia.precio_tractor', 40)        |      1 |      1 |      1 |
| ('economia.precio_tractor', 80)        |      2 |      2 |      2 |
| ('economia.precio_tractor', 160)       |      3 |      3 |      3 |
| ('economia.temporadas_vida', 10)       |      1 |      1 |      1 |
| ('economia.temporadas_vida', 20)       |      1 |      1 |      1 |
| ('economia.temporadas_vida', 40)       |      1 |      1 |      1 |
| ('economia.temporadas_vida', 80)       |      2 |      1 |      2 |
| ('economia.temporadas_vida', 160)      |      3 |      3 |      3 |
| ('escala_tiempo.dias_laborables', 10)  |      1 |      1 |      1 |
| ('escala_tiempo.dias_laborables', 20)  |      1 |      1 |      1 |
| ('escala_tiempo.dias_laborables', 40)  |      1 |      1 |      1 |
| ('escala_tiempo.dias_laborables', 80)  |      2 |      2 |      2 |
| ('escala_tiempo.dias_laborables', 160) |      3 |      3 |      3 |
| ('escala_tiempo.jornada_h', 10)        |      1 |      1 |      1 |
| ('escala_tiempo.jornada_h', 20)        |      1 |      1 |      1 |
| ('escala_tiempo.jornada_h', 40)        |      1 |      1 |      1 |
| ('escala_tiempo.jornada_h', 80)        |      1 |      2 |      2 |
| ('escala_tiempo.jornada_h', 160)       |      3 |      3 |      3 |
