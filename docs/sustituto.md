# Modelo sustituto y aprendizaje activo (componente de machine learning)

Este documento explica el componente de machine learning del proyecto: para qué sirve, cómo está hecho, cómo se evaluó y qué respondió. El código está en [`siembra/sustituto.py`](../siembra/sustituto.py), la comparación con los métodos del curso en [`herramientas/comparar_modelos.py`](../herramientas/comparar_modelos.py), las gráficas en la sección 5 del dashboard y los datos en `resultados/sustituto/`.

El modelo por defecto es un **Random Forest**. Un **proceso gaussiano** sigue disponible con `--modelo gp`. Los números de este documento salen de la corrida con Random Forest del 23 de noviembre de 2026 (`resultados/sustituto/sustituto.json`: modo completo, modelo `rf`, 130 s; se corrió con 9 procesos). Si se vuelve a correr con otros parámetros o con otro modelo, los números cambian y la fuente válida pasa a ser esa carpeta. Los resultados anteriores con proceso gaussiano están respaldados fuera del repositorio y se reproducen con `python -m siembra.sustituto --modelo gp`.

## 1. Para qué sirve

La pregunta central del proyecto es cuántos tractores por hectárea minimizan el costo por hectárea. El barrido la responde solo en 5 tamaños de campo (10, 20, 40, 80 y 160 ha) y con 1 a 4 tractores. Eso deja tres huecos, que ya reconocía el [análisis crítico](analisis_critico.md#11-pregunta-central-cuántos-tractores-por-hectárea):

1. El cambio de 1 a 2 tractores "cae entre 40 y 80 ha", sin más precisión.
2. En 160 ha el óptimo de M0 y M1 quedó en el borde (4 tractores): podía ser 5 o más.
3. La sensibilidad económica solo movía cada parámetro a dos extremos.

El modelo sustituto aprende de las corridas para predecir el resultado de la simulación en cualquier tamaño de campo y con cualquier N en milisegundos, con su incertidumbre. Así se obtiene una curva continua de N óptimo contra tamaño de campo y se ubican los cambios de N con su intervalo. El modelo no reemplaza a la simulación: elige dónde vale la pena simular, y las conclusiones se confirman con corridas reales.

## 2. Cómo está hecho

### 2.1 Qué aprende (salidas)

Un modelo por mecanismo y por salida. Las salidas son físicas, no el costo:

| Salida | Definición | Por qué así |
|---|---|---|
| `y_retraso` | log(t_medio · N / ha), con t_medio = paso medio de siembra de las celdas | El retraso crece casi proporcional a hectáreas por tractor. Normalizado por esa regla, `y_retraso` casi no cambia (≈ 5.0 a 6.0). Un modelo que fuera de los datos devuelve una constante, como los árboles, devuelve en realidad esa regla física |
| `H_ha` | Horas de motor por hectárea sembrable | El diésel es exactamente 10.5 L por hora de motor (`consumo_lh`), así que con esta salida basta |

Solo se entrena con corridas válidas, es decir, sin estancarse y con el campo completo sembrado (`sustituto.validas`). Las corridas se agrupan por (mecanismo, hectáreas, N): cada configuración es un punto con la media de sus semillas (`sustituto.preparar`).

### 2.2 Entradas

| Entrada | Por qué |
|---|---|
| log(ha) | Tamaño del campo |
| log(N) | Tendencia común a todos los N |
| 1 / hileras por tolva | Cuántas hileras completas siembra una tolva llena (200 celdas ÷ largo de hilera: 6 en 10 ha, 4 en 20, 3 en 40, 2 en 80, 1 en 160; pasa de 2 a 1 en 102 ha). M2 recarga antes de empezar una hilera que no puede terminar, así que su número de viajes al depósito salta cuando cambia ese entero |
| N en codificación one-hot (N = 1 a 6) | Permite que cada N se aparte de la tendencia. El caso típico es N = 3 con roles fijos (1 surcador y 2 sembradoras), que en M0 y M1 casi no mejora a N = 2 |

Las dos clases de modelo usan exactamente las mismas entradas (`sustituto.caracteristicas`).

### 2.3 Del modelo al costo

El costo por hectárea **no se aprende**: se calcula con la función de costo del proyecto (`metricas.agregar_costos`). Esa función es lineal en el retraso y en las horas de motor (costo_ha = a + b · t_medio + c · H_ha), y `coeficientes_costo` obtiene a, b y c evaluándola en tres puntos. El retraso se recupera con t_medio = exp(y_retraso) · ha / N. Hay dos consecuencias:

- El modelo no gasta datos en aprender una fórmula que ya conocemos.
- Cambiar un precio, la jornada o los días laborables no requiere simular ni reentrenar.

El costo se calcula muestra por muestra (árbol por árbol en Random Forest, muestra de la posterior en el proceso gaussiano). Así la incertidumbre del costo sale directamente de la de las dos salidas.

### 2.4 Random Forest y cómo da incertidumbre

`SustitutoRF` entrena un `RandomForestRegressor` de scikit-learn por mecanismo y por salida: 300 árboles, `random_state = 0` y el resto con los valores por defecto (cada árbol se entrena con una muestra bootstrap de los puntos, sin límite de profundidad y con todas las entradas en cada corte). No se ajustó ningún hiperparámetro.

La incertidumbre sale de la **dispersión entre árboles**:

- Cada árbol es una predicción posible. El árbol i de `y_retraso` y el árbol i de `H_ha` se toman juntos como una muestra.
- Con esa muestra se calcula el costo de cada tamaño y cada N. Como un árbol da una curva completa, las muestras son coherentes entre tamaños y entre N.
- **P(N óptimo)** en un tamaño = fracción de los 300 árboles en que gana cada N.
- El intervalo del 95 % es el rango entre los percentiles 2.5 y 97.5 de los 300 árboles.

Dos rasgos de los árboles que hay que tener presentes:

- **No interpolan:** sus predicciones de `y_retraso` y `H_ha` son por escalones. Entre dos tamaños simulados, la forma de la curva de costo la pone la normalización física (ha / N) y la geometría del campo, no los datos.
- **Fuera de los datos devuelven valores ya vistos.** Para N = 5 y 6, que el barrido no tiene, los árboles asignan valores de `y_retraso` y `H_ha` de N ya simulados. Como `y_retraso` está normalizado por hectáreas por tractor, el costo predicho sigue esa regla.

### 2.5 El proceso gaussiano como alternativa

`SustitutoGP` (`--modelo gp`) usa un proceso gaussiano de scikit-learn por mecanismo y por salida, con las mismas entradas y salidas. Su kernel, en breve:

```
f(ha, N) = tendencia(log ha, log N, 1/hileras) + desviación_N(log ha, 1/hileras, N one-hot) + ruido
```

- **Tendencia:** comparte información entre todos los N, así que permite estimar N no simulados.
- **Desviación por N:** dos N distintos quedan a distancia fija en la parte one-hot, así que cada N puede comportarse distinto.
- **Ruido:** el ruido conocido de cada punto (la varianza de la media entre semillas) más un ruido blanco pequeño que se aprende.

scikit-learn no tiene kernels que elijan columnas. Se logra con escalas de longitud por dimensión, fijando en un valor enorme las de las columnas que cada parte no debe ver (`_kernel`). Los hiperparámetros se ajustan por máxima verosimilitud con 3 reinicios. Cuando se corre con `--modelo gp`, quedan en `sustituto.json` (`hiperparametros`). La incertidumbre son 300 muestras conjuntas de la posterior.

Este kernel se eligió entre tres variantes: N continuo con ruido blanco libre, N continuo con ruido acotado y N categórico. Con N continuo, el ruido blanco "alisaba" el efecto de N impar: en M2 con 160 ha el modelo decía 4 tractores, cuando el barrido observó 3 con 20 semillas. La comparación se hizo contra el conjunto de prueba (ver el riesgo de fuga en la sección 2.8).

### 2.6 Probabilidad del N óptimo y cambios de N

Sobre una rejilla de tamaños (cada hectárea entera de 10 a 160) y N = 1 a 6 se toman 300 muestras (los 300 árboles, o 300 muestras de la posterior con el proceso gaussiano). En cada muestra se calcula el costo y qué N gana. Con eso se obtiene:

- **P(N es el óptimo)** en cada tamaño de campo, y la entropía de esas probabilidades (qué tanto duda el modelo).
- **N óptimo:** el de menor costo esperado.
- **Cambios de N óptimo:** dónde cambia el N óptimo, con su intervalo del 95 %, que es el rango de tamaños donde cruzan los costos de los dos N en el 95 % central de las muestras.

### 2.7 Aprendizaje activo

En cada ronda, para cada mecanismo:

1. Se calcula la entropía de P(N óptimo) en todos los tamaños de 10 a 160 ha, excepto los del conjunto de prueba.
2. Se eligen hasta 3 tamaños con más entropía, con entropía de al menos 0.05 y separados entre sí al menos un 8 %.
3. En cada uno se simulan, con 5 semillas, los N con probabilidad de ser el óptimo de al menos 10 % (como mínimo los dos más probables) que todavía no se hayan simulado.
4. Se guarda la predicción de cada punto **antes** de simularlo (verificación prospectiva) y se reentrena.

Se hacen 4 rondas, o menos si el modelo ya no duda en ningún tamaño. En la corrida de referencia, Random Forest hizo las 4 rondas: 75 puntos (22, 18, 18 y 17 por ronda) y 375 corridas (`activo.csv`). Nunca propuso 5 o 6 tractores: solo simuló flotas de 1 a 4.

### 2.8 Evaluación

- **Conjunto de prueba:** 10 tamaños de campo al azar (uniformes en escala logarítmica, semilla fija 12345, distintos de los del barrido: 17, 19, 24, 25, 30, 53, 65, 91, 136 y 139 ha) × N = 1 a 6 × 3 mecanismos × 3 semillas = 540 corridas (`prueba.csv`). **Nunca se usan para entrenar** los modelos que se evalúan. Quedan 179 configuraciones con corridas válidas: M0 con 136 ha y 3 tractores se atoró en las 3 semillas.
- **Dos modelos evaluados:** el que solo conoce el barrido (60 puntos) y el que además tiene las corridas del aprendizaje activo (135 puntos).
- **Métricas:**
  - error absoluto medio del costo por hectárea;
  - cobertura del intervalo del 95 %, ampliado con el error de la media observada, porque esta es un promedio de solo 3 semillas;
  - acierto del N óptimo en cada tamaño de prueba (entre los N con corridas válidas);
  - **sobrecosto de seguir la recomendación del modelo:** el costo simulado del N que recomienda menos el del mejor N simulado. Es la métrica que importa para decidir.
- **Modelo final:** para la curva, los cambios de N y los mapas se reentrena con todas las corridas válidas (barrido + activo + prueba = 314 puntos), como se hace antes de usar un modelo. Las métricas de arriba no usan ese modelo.

**Riesgo de fuga.** La elección de las entradas (en particular 1 / hileras por tolva y N en one-hot) y la del kernel del proceso gaussiano se hicieron comparando variantes contra el conjunto de prueba de una corrida anterior. Ese conjunto tiene los mismos 10 tamaños, porque la semilla es la misma. Por eso la prueba no es del todo independiente de esas decisiones, y sus errores pueden ser algo optimistas, sobre todo para el proceso gaussiano. Los hiperparámetros de Random Forest no se ajustaron, y en la comparación de la sección 3.2 ningún modelo se ajustó mirando la prueba. La verificación prospectiva no usa la prueba.

## 3. Resultados

### 3.1 Qué tan bien predice

Conjunto de prueba (`evaluacion.csv`):

| Modelo | Mecanismo | Error absoluto medio | Error máximo | Dentro del IC 95 % | Acierto del N óptimo | Sobrecosto medio de seguirlo |
|---|---|---|---|---|---|---|
| Solo barrido | M0 | 0.70 % | 2.8 % | 76 % | 10 de 10 | $0/ha |
| Solo barrido | M1 | 2.17 % | 18.4 % | 78 % | 9 de 10 | $23/ha |
| Solo barrido | M2 | 0.90 % | 4.5 % | 83 % | 10 de 10 | $0/ha |
| Barrido + activo | M0 | 0.74 % | 3.7 % | 64 % | 10 de 10 | $0/ha |
| Barrido + activo | M1 | 1.76 % | 17.3 % | 75 % | 9 de 10 | $23/ha |
| Barrido + activo | M2 | 0.68 % | 3.5 % | 87 % | 10 de 10 | $0/ha |

- El error en costo es chico (0.7 a 2.2 %) aunque el error en el retraso sea mayor. La propiedad de la flota pesa mucho en el costo por hectárea y diluye el error del retraso.
- El promedio de los tres mecanismos baja de 1.26 % a 1.06 % con el aprendizaje activo. Pero la mejora no es pareja: el error baja en M1 y M2, M0 empeora un poco (0.70 → 0.74 %) y la cobertura baja en M0 (76 → 64 %) y en M1 (78 → 75 %). Solo M2 mejora en las dos cosas. En la corrida anterior con proceso gaussiano, el aprendizaje activo bajó el error en los tres mecanismos: con Random Forest ayudó menos.
- Los intervalos de Random Forest se quedan cortos: cubren 64 a 87 % de los puntos de prueba, no el 95 % nominal. No se inflaron a mano: se reportan así.
- **El único error de decisión es M1 en 91 ha**, igual en los dos modelos. El modelo recomienda 2 tractores y la simulación da 1 como el más barato ($2,120 contra $2,346 con 2; 10.7 % de sobrecosto). Es también el error máximo: con barrido + activo predijo $1,941 para 2 tractores (17.3 % abajo); con solo el barrido, $1,913 (18.4 % abajo). M1 es el mecanismo más irregular: en el barrido, con 160 ha y 2 tractores, la desviación estándar del paso medio de siembra entre semillas es de 6.3 %, contra 1 % en M0 y 0.2 % en M2.

**Verificación prospectiva** (`verificacion.csv`, predicción hecha antes de simular cada punto que eligió el modelo):

| Ronda | Puntos | Error absoluto medio | Dentro del IC 95 % |
|---|---|---|---|
| 1 | 22 | 3.98 % | 82 % |
| 2 | 18 | 2.38 % | 83 % |
| 3 | 18 | 1.35 % | 100 % |
| 4 | 17 | 0.79 % | 94 % |

El error de la verificación es mayor que el de la prueba porque el modelo elige justo los puntos donde más duda. Los errores más grandes fueron de M2 con 2 tractores entre 92 y 111 ha (17 a 18 %), alrededor del salto de M2 en 102 ha. El error baja ronda tras ronda, lo que es consistente con que el modelo aprende lo que le faltaba. No es una prueba estricta, porque cada ronda mide puntos distintos.

### 3.2 Comparación con los métodos del curso y por qué Random Forest

`herramientas/comparar_modelos.py` entrena los métodos de regresión del documento del curso ("13 Métodos Completos de ML para Tractores Agrícolas", Prof. Luis Alberto Muñoz) con los mismos datos (barrido + aprendizaje activo de Random Forest), las mismas entradas y salidas, la misma función de costo y el mismo conjunto de prueba (`comparacion_modelos.csv`). Ninguno se ajustó mirando la prueba: Ridge con α = 1, Lasso con α = 0.001, árbol de profundidad máxima 6, HistGradientBoosting con mínimo 3 puntos por hoja y lo demás con valores por defecto. XGBoost no se probó porque no está instalado.

| Núm. en el documento | Modelo | Error medio | Error máximo | Acierto del N óptimo | Incertidumbre | Dentro del IC 95 % | Semiancho medio del IC |
|---|---|---|---|---|---|---|---|
| 5 | Árbol de decisión | 0.84 % | 17.5 % | 29 de 30 | No | — | — |
| 7 | Gradient Boosting | 0.89 % | 16.8 % | 29 de 30 | No | — | — |
| 6 | **Random Forest** | 1.05 % | 17.3 % | 29 de 30 | Dispersión entre árboles | 75 % | ±1.4 % |
| — | Proceso gaussiano (no está en el documento) | 1.10 % | 17.7 % | 29 de 30 | Posterior | 90 % | ±2.5 % |
| 9 | LightGBM (HistGradientBoosting de scikit-learn) | 1.15 % | 18.7 % | 29 de 30 | No | — | — |
| 3 | Ridge (L2) | 1.71 % | 28.2 % | 29 de 30 | No | — | — |
| 1 | Regresión lineal | 1.72 % | 29.6 % | 29 de 30 | No | — | — |
| 4 | Lasso (L1) | 1.72 % | 29.8 % | 29 de 30 | No | — | — |

Los 8 tienen el mismo sobrecosto medio ($7.5/ha): fallan en el mismo caso, M1 en 91 ha. El error de Random Forest aquí (1.05 %) difiere un poco del de `evaluacion.csv` (1.06 %) porque la comparación calcula el costo con la predicción media de cada salida, mientras que `evaluacion.csv` promedia el costo de cada árbol. Promediar por mecanismo o los 179 puntos juntos casi no cambia el resultado (1.06 % en los dos casos).

**Por qué Random Forest:**

- Está en el documento del curso y es el único de esa lista que da incertidumbre. El aprendizaje activo la necesita: sin P(N óptimo) no hay entropía para elegir dónde simular, ni intervalos para los cambios de N.
- Los más precisos de la lista (árbol de decisión y Gradient Boosting) no dan incertidumbre.
- La precisión entre los mejores difiere poco y depende de qué puntos se simularon. Con los puntos que eligió Random Forest, el árbol fue el más preciso y el proceso gaussiano quedó cuarto (1.10 %). En la corrida anterior, con los puntos que eligió el proceso gaussiano, el proceso gaussiano fue el más preciso: 0.79 % contra 1.25 % de Random Forest. En esta comparación, además, los 8 toman las mismas decisiones correctas.
- **Su debilidad:** con estos datos (barrido + activo), sus intervalos son más estrechos y menos calibrados. En esta comparación cubren 75 % de los puntos de prueba con un semiancho medio de ±1.4 %; los del proceso gaussiano, 90 % con ±2.5 %.

Lo que **no** se puede afirmar es que solo el proceso gaussiano sabe dónde no sabe, o que Random Forest se cree más seguro lejos de los datos en general. Con flotas de 5 y 6 tractores, que el barrido nunca simuló (modelos entrenados solo con el barrido, 60 puntos de prueba), Random Forest tuvo menos error (0.59 % contra 0.94 %) y una duda parecida (semiancho medio ±1.24 % contra ±1.36 %). La diferencia está en cómo cambia esa duda: el proceso gaussiano la ensancha donde no tiene datos (de ±0.41 % con 4 tractores a ±1.33 % con 5 y ±1.39 % con 6), mientras que la de Random Forest sigue bajando (±1.86, ±1.39 y ±1.08 %). Random Forest no marca que esas flotas nunca se simularon. Tampoco es general que sus intervalos sean más estrechos que los del proceso gaussiano. Con solo el barrido, en los 179 puntos de prueba, los de Random Forest son más anchos (semiancho medio ±2.7 % contra ±0.9 %) y cubren un poco más (79 % contra 75 %). Se estrechan al agregar los puntos del aprendizaje activo (±1.4 %), y ahí su cobertura baja a 75 %.

### 3.3 Respuesta a la pregunta central

Cambios del número óptimo de tractores (`cruces.csv`, modelo final):

| Mecanismo | De N | A N | Tamaño del cambio | IC 95 % |
|---|---|---|---|---|
| M0 | 1 | 2 | 68.3 ha | 68.0 a 69.5 ha |
| M0 | 2 | 4 | 138.3 ha | 135.9 a 140.0 ha |
| M1 | 1 | 2 | 76.0 ha | 71.9 a 77.3 ha |
| M1 | 2 | 1 | 85.5 ha | 76.2 a 99.0 ha |
| M1 | 1 | 2 | 99.3 ha | 86.0 a 106.1 ha |
| M1 | 2 | 4 | 118.7 ha | 115.7 a 123.0 ha |
| M2 | 1 | 2 | 69.0 ha | 68.3 a 69.6 ha |
| M2 | 2 | 3 | 101.3 ha | 100.1 a 101.8 ha |

Qué se puede concluir:

- **1 tractor conviene hasta unas 68 a 69 ha** con M0 y M2. Es mucho más preciso que el "entre 40 y 80 ha" del barrido. La estimación previa de la propuesta decía ~60 ha.
- **En cualquier tamaño hay una respuesta con su intervalo** (`curva.csv`, `optimo.csv`). Por ejemplo, en 57 ha con M0 conviene 1 tractor: $1,925/ha (IC 1,896 a 1,964) contra $2,160/ha (IC 2,138 a 2,180) con 2. En 125 ha conviene 2 tractores con M0, 4 con M1 (P = 0.96) y 3 con M2.
- **En M1, entre 76 y 100 ha, el N óptimo cambia dos veces:** 2 tractores de 76 a 85 ha, 1 de 86 a 99 ha y otra vez 2 desde 100 ha. Los intervalos de esos cambios son anchos y se traslapan. El tramo de 1 tractor es el menos firme. El modelo le da a 1 tractor solo 0.60 a 0.69 de probabilidad de ser el óptimo. Además, entre 82 y 117 ha la única corrida de M1 es la de 91 ha (prueba), donde 1 tractor costó $2,120/ha contra $2,346 con 2. Es la zona donde M1 es irregular y donde falló la recomendación (sección 3.1).
- **El cambio de 2 a 4 tractores llega a 138 ha con M0 y a 119 ha con M1.** La estimación previa lo ponía en ~170 ha. Como explica el análisis crítico (§1.1), la baja eficiencia de campo en campos grandes adelanta el cambio.
- **M2 pasa de 2 a 3 tractores entre 101 y 102 ha.** En 102 ha la tolva deja de alcanzar para 2 hileras completas y solo alcanza para 1. A partir de ahí la recarga anticipada de M2 manda a cada sembradora al depósito después de cada hilera. El tercer tractor es una segunda sembradora (1 surcador y 2 sembradoras) y compensa esos viajes. Es un efecto discreto de la geometría, no una tendencia suave, y por eso el intervalo es tan estrecho.
- **¿5 o más tractores? En los tamaños probados, no.** En la prueba, con 136 y 139 ha, 5 y 6 tractores siempre cuestan más que el mejor N, en los tres mecanismos. Por ejemplo, M0 con 139 ha: $2,094/ha con 4, $2,350 con 5 y $2,518 con 6. En M1 la diferencia es menor: con 139 ha, $2,357 con 4 contra $2,388 con 5.
- **En 160 ha el modelo final da 4 tractores con M0 y 3 con M2**, con probabilidad de 1.00 y 0.997. En M1 el óptimo esperado también es 4, pero el modelo todavía da a 5 tractores entre 10 y 41 % de probabilidad de 146 a 160 ha (28 % en 160 ha). No hay corridas con 5 o 6 tractores arriba de 139 ha, porque el aprendizaje activo de Random Forest no las propuso. Así que en 160 ha la respuesta sale del modelo, apoyada en las corridas de 136 y 139 ha, y en M1 la duda no está cerrada.

### 3.4 Sensibilidad económica sin simular

Como el costo se calcula después del modelo, `mapa.csv` tiene el N óptimo en cada tamaño de campo para 9 valores de cada parámetro de la sensibilidad de la propuesta (salvo la duración de la ventana, que no entra en el costo). En 80 ha, que es el tamaño del barrido más cercano a un cambio:

- Con pérdida de 0.2 %/día, vida útil de 15 temporadas o jornada de 14 h, conviene **1 tractor** en vez de 2, con los tres mecanismos.
- Con precio del maíz de $5,200/t sigue conviniendo 2 tractores.
- El precio del tractor y los días laborables no cambian la respuesta en todo su rango.

Esto coincide con la sensibilidad calculada directamente sobre las corridas del barrido en el [análisis crítico §3.1](analisis_critico.md#31-parámetros-económicos). Como 80 ha es un tamaño del barrido, es una comprobación de que el modelo reproduce la simulación ahí, no una prueba independiente. Los mapas del dashboard (`ml_mapa_*.png`) muestran cómo se mueve el cambio de N en todo el rango de tamaños.

### 3.5 Hallazgo: la simulación se atora fuera del barrido

Al explorar tamaños y flotas que el barrido no probó aparecieron **13 configuraciones con corridas estancadas** (`atorados.csv`): 18 corridas atoradas de las 915 nuevas (540 de prueba y 375 del aprendizaje activo). En el barrido no se atoró ninguna de las 1,200. Algunos casos:

- M0 con 136 ha y 3 tractores se atora en las 3 semillas, con 78 % de cobertura como mínimo.
- M0 con 134 y 135 ha y 4 tractores se atora en 1 de 5 semillas, en 45 %.
- M1 con 136 ha y 5 tractores se atora en 1 de 3 semillas, en 18 %.
- M2 con 136 y 139 ha y 6 tractores se atora en 2 y 1 de 3 semillas, en 22 %.

El barrido original reportaba 0 corridas estancadas solo porque probó 5 tamaños con 1 a 4 tractores. Estas corridas no se usan para entrenar, porque miden un bloqueo de la simulación y no el desempeño de la flota. Pero son un problema real de robustez del modelo multiagente.

**Diagnóstico.** Una revisión del código de la simulación encontró 6 causas, cada una verificada de forma independiente:

1. La regla de ocupación de la estación en `_paso_deposito` (`siembra/agentes.py`).
2. `_ceder` empuja al tractor en línea hasta una esquina.
3. En M1, una sembradora se reasigna su propia hilera.
4. En M2, la fila del blackboard puede quedar imposible de cumplir.
5. WHCA* no deja libre la celda que otro tractor ocupa en t+1.
6. En M1 quedan tareas fantasma cuando la tolva se vacía en la última celda de una hilera.

Las correcciones **no se han aplicado** al repositorio. Para reproducir un caso:

```python
from siembra.config import cargar_config, aplicar
from siembra.modelo import simular
r = simular(aplicar(cargar_config(), {"campo.hectareas": 136, "flota.n_tractores": 3, "mecanismo": "M0"}))["resumen"]
print(r["estancado"], r["cobertura"])
```

## 4. Limitaciones

- **Alcance:** el modelo solo vale en las condiciones del barrido: campo sin obstáculos, sin falla, sin pérdida de mensajes, con los parámetros de `config/parametros.json`, de 10 a 160 ha y de 1 a 6 tractores. Fuera de ese rango no se usa.
- **Cambios en la simulación:** si cambian los parámetros de la simulación (tolva, velocidad, tiempos de recarga), hay que volver a correr el barrido y el modelo. Los parámetros económicos sí se pueden cambiar sin reentrenar. Si se corrigen las causas de los atascos (sección 3.5), también hay que volver a simular: hoy, por ejemplo, no hay datos válidos de M0 con 136 ha y 3 tractores.
- **Calibración:** los intervalos de Random Forest entrenado con barrido + activo cubren 64 %, 75 % y 87 % de los puntos de prueba (M0, M1, M2), no el 95 % nominal. Con esos mismos datos, los del proceso gaussiano están mejor calibrados (90 % contra 75 % en la comparación). Con solo el barrido, los dos cubren parecido (79 % y 75 %).
- **Los árboles no interpolan:** entre dos tamaños simulados, la forma de la curva sale de la normalización física y no de los datos. Un cambio de N que cae entre dos tamaños lejanos se ubica con menos precisión que con el proceso gaussiano. En las pruebas con un simulador de costo conocido, la tolerancia de Random Forest es de 3 % en el costo y 6 ha en el cambio de N, contra 1 a 2 % y 1 ha del proceso gaussiano.
- **Aprendizaje activo:** con Random Forest ayudó menos que con el proceso gaussiano. M0 empeoró un poco y la cobertura bajó en M0 y M1. Además, nunca propuso 5 o 6 tractores, así que la duda entre 4 y 5 tractores en M1 de 146 a 160 ha sigue abierta.
- **Riesgo de fuga:** las entradas y el kernel del proceso gaussiano se eligieron mirando la prueba de una corrida anterior (sección 2.8).
- **Irregularidad de M1:** M1 es el mecanismo menos predecible. Su recomendación falló en 1 de 10 tamaños, con un sobrecosto de 10.7 %.
- **Hereda las limitaciones de la simulación:** el modelo aprende la simulación, no la realidad. Todas las limitaciones de la simulación ([análisis crítico §5](analisis_critico.md#5-limitaciones-del-modelo)) se heredan. Por ejemplo, los traslados sobreestimados unas 3 veces afectan sobre todo a los campos grandes y, con ellos, al cambio de 2 a 4 tractores.

## 5. Cómo correrlo

```bash
python -m siembra.sustituto                     # Random Forest, modo completo: ~2 min con 9 procesos
python -m siembra.sustituto --modelo gp         # proceso gaussiano
python -m siembra.sustituto --modo rapido       # 2 rondas, menos tamaños y semillas
python -m siembra.sustituto --iteraciones 0     # sin aprendizaje activo
python -m siembra.sustituto --prueba-ha 0       # sin conjunto de prueba
python -m siembra.sustituto --help
python herramientas/comparar_modelos.py         # comparación con los métodos del curso
```

Necesita `resultados/barrido.csv` (`python -m siembra.experimentos --solo barrido`). Las dos clases de modelo escriben en la misma carpeta, `resultados/sustituto/`, así que la última corrida reemplaza a la anterior. Para conservar las dos, usa `--salida otra/carpeta` con una copia de `barrido.csv` dentro.

`herramientas/comparar_modelos.py` se corre después de `siembra.sustituto`: usa el `activo.csv` y el `prueba.csv` de la última corrida (`--salida` para otra carpeta). `correr_todo.py` corre los dos en el paso 2 de 4, siempre con Random Forest y con el modo de `correr_todo` (rápido por defecto).

### Modelo guardado e interfaz para probarlo

`python -m siembra.sustituto` guarda el modelo final en `resultados/sustituto/modelo.joblib` (3.6 MB, comprimido con joblib). Es el mismo modelo que escribió `curva.csv` y `optimo.csv`: con Random Forest, consultado de nuevo, da exactamente esos números (con el proceso gaussiano, una consulta de un solo tamaño puede variar un poco, porque sus muestras son aleatorias). Para regenerarlo sin simular, a partir de los CSV que ya existen (barrido + activo + prueba, unos 2 s), con la misma clase de modelo y el mismo archivo de parámetros de la última corrida (los guarda `sustituto.json`):

```bash
python -m siembra.sustituto --guardar-modelo
```

El archivo solo carga con la misma versión de scikit-learn (1.9.1, fija en `requirements.txt`). `cargar_modelo` avisa si la versión cambió. No se versiona en git (`.gitignore`), porque se regenera igual en segundos.

Para probarlo con valores propios:

```bash
python -m siembra.interfaz                 # abre http://127.0.0.1:8421 en el navegador
python -m siembra.interfaz --puerto 9000 --no-abrir
```

Levanta un servidor local que solo escucha en la propia computadora. Si no existe `modelo.joblib`, lo regenera con los CSV. La página (`siembra/interfaz.html`) deja elegir:

- el tamaño del campo (de 1 a 1,000 ha; fuera de 10–160 ha avisa que el modelo no extrapola);
- el mecanismo;
- los precios y supuestos del costo: maíz, rendimiento, pérdida por día de retraso, diésel, precio y vida del tractor, jornada y días laborables.

Muestra el N recomendado con su costo por hectárea y su rango 95 %, el porcentaje de árboles que vota por él, la segunda opción, una tabla con 1 a 6 tractores y una franja con el N recomendado en cada tamaño de 10 a 160 ha con esos precios. Cambiar los precios no requiere simular, porque solo entran en la función de costo. La dirección acepta `?ha=91&mecanismo=M1` para abrir un caso directo.

Los precios y supuestos no tienen el problema de los tamaños fuera de rango: no entran al Random Forest, sino a la fórmula de costo, que es lineal y exacta. La jornada y los días laborables tampoco cambian la simulación (los agentes no los usan); solo convierten pasos simulados en días. El "rango estudiado" que muestra la página es el del análisis de sensibilidad del proyecto, no un límite del modelo. Lo que sí hay que vigilar con valores extremos es que la fórmula siga siendo realista: no tiene topes, así que con una pérdida por día muy alta puede cobrar más de 100 % de la cosecha. La página avisa cuando la recomendación es el tope de 6 tractores.

Desde Python:

```python
from siembra import sustituto
from siembra.config import cargar_config
import pandas as pd

cfg = cargar_config()
barrido = pd.read_csv("resultados/barrido.csv")
modelo = sustituto.crear("rf", cfg).ajustar(barrido)      # o "gp"; sustituto.Sustituto es SustitutoRF
media, bajo, alto = sustituto.predecir_costo(modelo, "M2", [57, 57], [1, 2])   # 57 ha con 1 y 2 tractores
an = sustituto.analizar(modelo)          # curva, optimo, cruces

final = sustituto.cargar_modelo("resultados/sustituto/modelo.joblib")         # el modelo final guardado
r = sustituto.consultar(final, "M1", 91, {"economia.precio_maiz": 7000})       # N recomendado, costos y votos
franja = sustituto.n_optimo_por_tamano(final, "M1")                            # N recomendado en cada hectárea
```

| Archivo en `resultados/sustituto/` | Una fila por |
|---|---|
| `prueba.csv` | Corrida del conjunto de prueba (mismas columnas que `barrido.csv`) |
| `activo.csv` | Corrida del aprendizaje activo (+ `iteracion`) |
| `verificacion.csv` | Punto elegido por el aprendizaje activo: predicción previa y costo simulado |
| `evaluacion.csv` | Modelo y mecanismo: métricas en el conjunto de prueba |
| `evaluacion_detalle.csv` | Modelo, mecanismo, tamaño y N de prueba: costo simulado y predicho |
| `curva.csv` | Mecanismo, tamaño (cada hectárea) y N: costo esperado e IC 95 % |
| `optimo.csv` | Mecanismo y tamaño: N óptimo, P(N óptimo) de cada N y entropía |
| `cruces.csv` | Cambio de N óptimo con su IC 95 % |
| `mapa.csv` | Mecanismo, parámetro económico, valor y tamaño: N óptimo |
| `atorados.csv` | Configuración con al menos una corrida estancada |
| `comparacion_modelos.csv` | Método de regresión: error en la prueba, aciertos del N óptimo, sobrecosto y, para Random Forest y el proceso gaussiano, cobertura y semiancho del IC (lo escribe `herramientas/comparar_modelos.py`) |
| `sustituto.json` | Configuración de la corrida, modelo usado, puntos de entrenamiento, versiones e hiperparámetros |
| `modelo.joblib` | El modelo final entrenado (no es tabla; lo cargan `cargar_modelo` y la interfaz) |

Pruebas: `tests/test_sustituto.py` tiene 28 funciones de prueba. 13 de ellas se corren con los dos modelos (Random Forest y proceso gaussiano), con tolerancias propias de cada uno, así que pytest cuenta 41 casos. Usan un simulador analítico cuyo costo verdadero se conoce y corren en segundos. Comprueban que:

- el costo se reconstruye exactamente con la función de costo del proyecto;
- el modelo recupera el N óptimo y los cambios de N verdaderos;
- las muestras de Random Forest son sus árboles y el modelo por defecto es Random Forest;
- el aprendizaje activo elige tamaños cerca de un cambio de N y no vuelve a proponer puntos ya simulados;
- las corridas atoradas se descartan;
- el flujo completo escribe todos los archivos;
- el modelo guardado da las mismas respuestas que el original y que `curva.csv`, y regenerarlo con los CSV da el mismo modelo;
- la interfaz responde lo mismo que `consultar` y rechaza peticiones inválidas.

`herramientas/comparar_modelos.py` no tiene pruebas propias. `tests/test_viz.py` lo corre para generar los datos del dashboard, pero no revisa sus números.
