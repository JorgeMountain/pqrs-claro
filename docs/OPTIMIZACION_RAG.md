# Seguimiento de optimización del RAG

El proyecto usa el recuperador híbrido del paso 9. Combina el índice léxico
con búsqueda semántica exacta sobre los fragmentos autorizados y devuelve
hasta 24 candidatos por pregunta. Los ensayos de los pasos 10 a 12 y los
selectores de C07/P11 y C14/V05 quedaron archivados. El punto de entrada es
el [servicio de fuentes](../src/pqrs_claro/source_service.py), que invoca el
[recuperador](../src/pqrs_claro/source_retrieval.py) con el
[índice semántico](../src/pqrs_claro/source_semantic.py).

## Comprobar el buscador desde un clon

Con Python 3.12 y uv instalados, prepara el entorno en la raíz del repositorio
con `.\scripts\setup.ps1`. Luego ejecuta estas pruebas desde PowerShell.
Usan fragmentos ficticios y vectores de prueba para comprobar permisos, citas,
selección y reutilización del índice. Se pueden ejecutar sin credenciales de
API y sin descargar el modelo E5.

```powershell
.\scripts\dev-python.ps1 -m pytest -q tests/test_scoped_lexical_statistics.py tests/test_scoped_passage_adjacency.py tests/test_semantic_selection.py
```

Las mediciones históricas que siguen se hicieron con el corpus y el modelo
indicados en cada ensayo. La copia local de trabajo conserva los informes
detallados y sus datos en `../experiments/`, y registros de pruebas en
`output/qa/`. Esas rutas se expresan desde la raíz de `pqrs-claro` y son
opcionales al clonar el repositorio. Repetir los tiempos publicados requiere
las copias originales autorizadas del corpus.

## Pasos completados

El seguimiento comenzó el 6 de noviembre de 2026. La primera entrega comprende
los pasos 1 a 5.

- [x] 1. Preparar una copia aislada con peticiones y fuentes fijas.
- [x] 2. Medir tiempos, memoria y candidatos del código anterior a los cambios.
- [x] 3. Reutilizar la matriz semántica con presupuesto de memoria y alcance vigente.
- [x] 4. Seleccionar los mejores resultados sin ordenar todo el corpus, conservando empates.
- [x] 5. Verificar equivalencia de candidatos, citas y ámbito; comparar tiempo y memoria.
- [x] 6. Preparar y reutilizar fechas y contexto en el índice, bajo demanda.
- [x] 7. Reutilizar estadísticas y estructuras del índice léxico por ámbito.
- [x] 8. Preparar relaciones ordenadas entre documentos, fragmentos y respuestas contiguas.
- [x] 9. Validar conjuntamente tiempos, memoria, cobertura e invalidación por cambios.
- [x] 10. Decidir mediante comparación si conviene incorporar BM25S. Se conserva el índice actual.
- [x] 11. Decidir mediante comparación si conviene incorporar HNSW/FAISS o Qdrant. Se conserva la búsqueda vectorial exacta.
- [x] 12. Evaluar contexto adicional para citas ausentes. Se conserva el buscador actual y el prototipo queda en el ensayo.

## Primera entrega implementada y comparada

Los pasos 1 a 5 están verificados. En aquella primera medición, la etapa semántica
redujo su tiempo un 22,97 %, pero la recuperación completa tardó un 4,05 % más.
La primera medición quedó como referencia. Más abajo se registran la comparación
del paso 6 y la validación conjunta del paso 9.

Se conservó el código anterior y una copia del corpus congelado del ensayo de
octubre en `../experiments/rag-semantic-20261106/`, fuera del repositorio público.
La comparación usa el modelo semántico local real, sin red ni llamadas a Luna,
y compara candidatos completos con sus citas, orden y metadatos.

La implementación aumenta a 512 MiB el presupuesto predeterminado de
matrices reutilizables y permite configurarlo entre 0 y 1024 MiB. Expulsa entradas
antes de reservar reemplazos y conserva la búsqueda exacta mediante selección
parcial con desempates estables. Véase [configuración y límites](busqueda-semantica-local.md).

Se compararon 17 peticiones de dos casos, cada una en dos pasadas: 34 consultas por
versión. Las 816 apariciones de candidatos conservaron exactamente contenido,
orden, citas y metadatos. Las huellas de las tres bases copiadas no cambiaron.
Esto demuestra conservación del paquete de evidencia, no su relevancia o suficiencia.

| Medición sobre las 34 consultas | Antes | Después | Cambio |
| --- | ---: | ---: | ---: |
| Recuperación local completa, acumulada | 225,60 s | 234,73 s | 4,05 % más tiempo |
| Etapa semántica, acumulada | 60,46 s | 46,57 s | 22,97 % menos tiempo |
| Mediana de recuperación por consulta | 6,19 s | 5,85 s | Menor |
| Percentil 95 de recuperación por consulta | 19,02 s | 22,36 s | Mayor |

En el caso grande, de 244.962 fragmentos, la matriz pasó de construirse 20 veces
a construirse una vez y reutilizarse 19 veces. La caché estimada ocupó 388,73 MiB;
el RSS final del proceso pasó de 4,257 a 4,519 GiB (unos 269 MiB adicionales), y
su pico de memoria informado por Windows pasó de 4,635 a 4,721 GiB. El presupuesto
de caché no limita la RAM total de la aplicación. En el caso pequeño, ambos brazos
ya reutilizaban su matriz y la mejora semántica medida fue del 14,38 %.

La búsqueda por fechas y la construcción de contexto documental siguen consumiendo
tiempo importante. Sus tiempos también aumentaron aunque su código no cambió;
la causa no quedó aislada. Por ello, estas cifras no permiten atribuir toda la
variación global al parche ni anunciar que el RAG completo sea más rápido.

La segunda pasada repite las mismas preguntas y reutiliza también sus embeddings.
No se vacía la caché de disco del sistema operativo. La carga del corpus de prueba
no incluye leer y verificar todos los PDF originales; tampoco se mide evaluación,
redacción, interfaz ni tiempo completo de la aplicación. La muestra es pequeña y
los percentiles son descriptivos, no una garantía de rendimiento general.

La primera ejecución del medidor agotó memoria al construir un JSON de todo el
corpus para calcular su huella, antes de medir consultas. Se conserva como intento
fallido y se excluye de las cifras; el medidor calcula ahora esa huella por partes.

Otro intento se interrumpió porque la protección del experimento bloqueó el
dispositivo nulo de Windows de una dependencia; se ajustó esa excepción y se
verificó el modelo antes de iniciar la comparación válida. Durante la preparación
del caso grande optimizado hubo una demora anómala de causa desconocida:
esa preparación no se utiliza para atribuir rendimiento al cambio. Se conservan
los incidentes y todas las consultas válidas, incluidas las que fueron más lentas.

El protocolo, las versiones comparadas, `summary.json` y `INFORME.md` quedan en
`../experiments/rag-semantic-20261106/`, tomando como base la raíz del repositorio.
Esa entrega dejó como siguiente paso reutilizar la preparación de fechas y contexto,
manteniendo la equivalencia de resultados y midiendo el coste adicional de memoria.

## Paso 6 implementado y verificado

La recuperación completa de la muestra tardó un **15,40 % menos**. Sin embargo,
el total que incluye carga y preparación tardó un **6,81 % más** en el control
principal: todavía no se demuestra una aceleración desde el arranque del proceso.

Los canales de calendario y contenido documental reutilizan los términos del
índice léxico para calcular los conteos normalizados del cuerpo. Se restan los
términos del título y se transforma cada término distinto con su frecuencia,
obteniendo los mismos conteos que al volver a normalizar todo el texto. Si faltan
términos preparados para ese contenido, se tokeniza el cuerpo como alternativa.
El ranking consume un conteo por fragmento, sin retener simultáneamente los conteos
de todos los candidatos ni crear copias normalizadas de sus cuerpos.

Los metadatos sí conservan texto normalizado y conteos en una caché LRU con un
presupuesto estimado de 64 MiB por índice, configurable en Python mediante
`context_cache_bytes`; 0 desactiva su retención. Los cuerpos no desplazan esos
metadatos. El presupuesto no incluye la caché de ventanas de fechas, que ya existía,
ni los índices y resultados temporales. No representa un límite de RAM de la aplicación.
Las ventanas de fechas se comparten por texto idéntico, conservando los formatos,
distancias, desempates y comportamiento Unicode anteriores.

La preparación es bajo demanda durante cada ejecución, después del filtro de
ámbito. No se añade una preparación persistente al incorporar documentos. Las
claves dependen del contenido y los resultados utilizan citas y metadatos actuales.
Las estadísticas BM25 se calculan sobre el subconjunto de cada consulta; compartir
texto preparado no comparte permisos, puntuaciones ni estadísticas entre ámbitos.

La comparación del paso 6 usa como base la versión con los pasos 1 a 5 ya aplicados,
en `../experiments/rag-dates-20261106/`. Mide construcción del índice, primera
pasada, repetición y suma de preparación y recuperación, además de equivalencia y
memoria. La preparación bajo demanda se cobra dentro del tiempo de consulta.

| Medición, 17 peticiones en dos pasadas | Antes del paso 6 | Después | Cambio |
| --- | ---: | ---: | ---: |
| Recuperación completa, 34 ejecuciones | 218,24 s | 184,64 s | 15,40 % menos tiempo |
| Carga, preparación y las 34 ejecuciones | 248,70 s | 265,63 s | 6,81 % más tiempo |
| CPU de carga, preparación y consultas | 249,45 s | 231,31 s | Menor trabajo de CPU |

En el caso grande, de 244.962 fragmentos, la recuperación bajó de 190,89 a 156,95 s
(17,78 %). En el pequeño, de 22.413 fragmentos, pasó de 27,35 a 27,70 s: no mejoró.
Las 816 apariciones de candidatos conservaron exactamente contenido, puntuaciones,
orden, citas y metadatos. Las tres bases congeladas conservaron sus huellas.
Esto no evalúa relevancia ni suficiencia de las fuentes.

La caché de metadatos del caso grande se estabilizó en 40,53 MiB estimados, con
18.994 cálculos y 362.306 reutilizaciones. Los cuerpos aprovecharon términos
léxicos preparados en 67.968 ocasiones, sin recurrir a la tokenización alternativa.
En la consulta de fechas más costosa, el canal bajó de 32,49 a 23,43 s en la
primera pasada y de 14,75 a 7,01 s en la repetición. Su tiempo de CPU también bajó.

La RAM libre del equipo aumentó durante el ensayo. Por ello se añadió un control
del código anterior, elegido como referencia principal antes de ejecutarlo. Se
conserva también la referencia inicial: frente a ella, la recuperación bajó un
19,91 % y el total con preparación bajó un 10,25 %. La inversión del resultado
total impide declarar una mejora robusta desde el arranque. La carga y preparación
semántica no cambiaron de código, pero sus tiempos variaron; no se eliminan esas
fases ni se atribuye su variación automáticamente al parche.

Frente al control principal, el caso grande registró un pico Windows de 4,712 →
4,702 GiB y un RSS final de 4,515 → 4,677 GiB (unos 166 MiB más). No se demuestra
un ahorro de memoria total. El benchmark no controla cachés de disco ni otras
actividades del equipo, y no incluye verificación completa de los PDF originales,
evaluación por API, redacción o interfaz. Los resultados describen esta muestra.

`INFORME.md`, `summary.json`, `summary-initial-baseline.json`, el protocolo y los
ejecutores quedan en `../experiments/rag-dates-20261106/`. El paso 7 retomó la
reutilización de estadísticas y estructuras léxicas por ámbito y comprobó el
tiempo con carga y preparación.

Pasaron 186 pruebas: 158 de recuperación/preparación (incluidas 45 nuevas de
contexto) y 28 de integración HTTP con IA simulada. Los registros de esta entrega
están en `output/qa/rag-dates-20261106/`. Un primer intento de pruebas no pudo crear
temporales fuera del workspace; se usó un directorio aislado dentro del proyecto.
También se actualizó una comprobación de diagnósticos para admitir los contadores
nuevos conservando sus aserciones sobre términos léxicos. Ruff y `git diff --check`
pasaron. No se ejecutó la suite completa del proyecto.

La repetición final de pruebas HTTP usó una carpeta temporal nueva: el ejecutor
aislado había rechazado la limpieza del directorio anterior porque Windows lo
expresó con un prefijo de ruta extendida. El rechazo ocurrió antes de las pruebas,
no en la aplicación. La ejecución posterior completó las 28 pruebas correctamente.

El primer candidato medido del paso 6 se descartó: en el caso grande redujo la
recuperación de 203,19 a 190,14 s, pero el total con preparación subió de 263,70 a
270,22 s y el RSS final aumentó unos 326 MiB. La consulta P4 volvió a calcular
46.306 entradas en ambas pasadas, señal de expulsión repetida de cuerpos y
metadatos dentro de la misma caché. El candidato final separa ese trabajo como
se describe arriba. El resultado inicial, su código y las entradas permanecen
en el experimento; no se ejecutó su caso pequeño porque la causa ya estaba medida.

## Paso 7. Reutilización del índice léxico por ámbito

Verificado el 7 de noviembre de 2026. En 17 preguntas de dos expedientes, cada
una ejecutada dos veces, la recuperación de fuentes tardó un **8,34 % menos**
frente al paso 6. Al repetir la referencia del expediente grande, el ahorro
de recuperación fue del **6,63 %**.

| Trabajo medido en 34 ejecuciones | Referencia del paso 6 | Paso 7 | Reducción de tiempo |
| --- | ---: | ---: | ---: |
| Búsquedas, comparación inicial | 179,534 s | 164,566 s | 8,34 % |
| Carga, preparación y búsquedas, comparación inicial | 247,230 s | 195,066 s | 21,10 % |
| Búsquedas, control posterior | 176,255 s | 164,566 s | 6,63 % |
| Carga, preparación y búsquedas, control posterior | 204,057 s | 195,066 s | 4,41 % |

La preparación del caso grande tardó 63,18 s con la primera referencia, 25,90 s
con el paso 7 y 23,29 s al repetir la referencia. La lectura previa de las bases
fue idéntica y la RAM disponible varió. El control posterior permite comparar
tiempos de preparación más cercanos. El ensayo mide recuperación local después
de leer secuencialmente las bases. La evaluación por IA y la redacción quedan
fuera del tiempo publicado.

Cada petición vuelve a filtrar las fuentes autorizadas y obtiene una vez las
estadísticas BM25 de ese conjunto ordenado. La búsqueda general, las variantes
de contexto, el correo y los filtros por tema o fecha comparten esas estadísticas.
Cada variante se puntúa por separado. Cuando un canal selecciona menos fragmentos,
calcula la relevancia con las frecuencias de ese subconjunto.

Las búsquedas dentro del cuerpo de documentos y pasajes fechados pueden reutilizar
las longitudes y posiciones por término si reciben las mismas citas en el mismo
orden. El resultado toma la fuente, versión, página y líneas de los registros
actuales. Si cambia el título, el nombre del archivo o la cita de un oficio, el
índice vuelve a evaluar su identidad documental. La caché de estadísticas de
cuerpos tiene un presupuesto estimado de 64 MiB por instancia. Su lista de citas,
vocabulario y arrays cuentan para ese límite. Una entrada mayor se usa durante
la consulta y se libera. En Python, `body_statistics_cache_bytes=0` desactiva su
retención. El uso total de RAM incluye también el modelo y las demás estructuras.

Las llamadas a las estadísticas del índice léxico compartido bajaron de 180 a 102.
En el caso grande, la caché de cuerpos registró 59 reutilizaciones y 7 construcciones.
Retuvo 27,86 MiB estimados. Dos construcciones excedieron el presupuesto y sirvieron
solo para la consulta que las solicitó. El pico de memoria del proceso en ese caso
fue unos 40 MiB mayor que en la referencia inicial y unos 7 MiB mayor que en el
control posterior.

Pasaron 196 pruebas de esta entrega, 168 de recuperación y preparación y 28 de
integración del servicio. Cubren cambios de permisos, texto, identidad, orden y
metadatos, además de la expulsión de entradas. Los resultados de pytest están en
`output/qa/rag-lexical-step7/`.

Las 816 apariciones de candidatos coincidieron en ambas versiones, incluyendo
puntuaciones, orden, canales y citas. Las tres bases congeladas conservaron sus
huellas. El protocolo, el informe y las dos comparaciones están en
`../experiments/rag-lexical-step7/` desde la raíz del proyecto.

## Paso 8. Localizar respuestas contiguas dentro de una fuente

Al buscar la respuesta que sigue a una pregunta, la recuperación recorría todos
los fragmentos autorizados por cada pregunta candidata. Ahora agrupa esos
fragmentos por archivo y versión una vez por petición. Cuando necesita leer una
continuación, ordena solo los fragmentos de esa fuente por página y línea.
Si dos fragmentos tienen las mismas coordenadas, conserva su orden de entrada.
La búsqueda dentro del cuerpo de un documento aprovecha los mismos grupos.

Cada petición aplica sus permisos y usa las citas y coordenadas vigentes. Una
continuación se detiene al encontrar otra pregunta, una sección o un salto de
más de una página. Conserva el límite de siete fragmentos posteriores y 6500
caracteres en total, incluida la pregunta.

Se compararon el paso 7 y el paso 8 con el modelo local, las mismas 17 peticiones
de dos casos históricos y dos pasadas por petición. El cronómetro incluye la
construcción de los grupos. En el total se añade la carga de datos y la
preparación de los índices. La medición termina al devolver las citas candidatas.

| Tiempo medido | Paso 7 | Paso 8 | Reducción |
| --- | ---: | ---: | ---: |
| 34 búsquedas completas | 180,46 s | 159,52 s | 11,61 % |
| Carga, preparación y 34 búsquedas | 211,49 s | 190,55 s | 9,90 % |
| Mediana por búsqueda | 4,83 s | 3,82 s | 20,93 % |

Las 112 llamadas que localizaron una posible continuación pasaron de 3,510 s
a 0,006 s acumulados. La búsqueda en el cuerpo de documentos pasó de 14,62 s a
5,44 s. El pico de memoria del proceso en el caso grande fue unos 19 MiB menor
en esta medición. La preparación sumó 31,03 s en el paso 7 y 31,04 s en el paso 8.

Las 816 apariciones de candidatos coincidieron en texto, orden, citas, metadatos
y puntuaciones. Las tres bases conservaron sus huellas. Pasaron 192 pruebas de
recuperación y preparación y 28 del servicio HTTP, incluidas comprobaciones con
fuentes revocadas y coordenadas modificadas. Los XML están en
`output/qa/rag-adjacency-step8/`. El protocolo, las mediciones por petición y el
informe están en `../experiments/rag-adjacency-step8/`.

## Paso 9. Validación conjunta del RAG

Se comparó directamente el código anterior al paso 1 con el código final del
paso 9. En dos expedientes y 34 búsquedas, la recuperación bajó de **247,21 a
158,35 s (35,95 %)**. Con carga y preparación bajó de **278,29 a 188,79 s
(32,16 %)**. La mediana por consulta bajó de 6,66 a 3,84 s. En el expediente
grande, el proceso terminó con 322,36 MiB más de memoria residente y su pico fue
39,24 MiB menor en esta ejecución. Se conservaron las dos mediciones originales
de referencia y se repitieron ambos expedientes con el código final.

Las 816 apariciones de candidatos coincidieron en orden, puntuaciones, citas y
metadatos. También se comprobó cobertura contra referencias documentales previas.
Con los 24 candidatos, admisiones recuperó el texto que respalda los 13 datos o
grupos de datos de sus diez preguntas. Con cinco candidatos solo tres preguntas
reunieron todo el respaldo esperado. En el otro expediente, los documentos de
los cuatro pares etiquetados aparecieron entre los 24, con dos coincidencias
literales. Los dos pasajes pendientes corresponden a P4. Las otras cinco
preguntas del expediente carecían de etiqueta en esa referencia.

La validación descubrió y corrigió un empate que podía cambiar la primera cita
al combinar vectores nuevos con otros ya guardados. Los cinco controles de
reapertura conservaron la primera cita tras la corrección. Pasaron **136 pruebas
dirigidas**, incluidas 33 comparaciones de índices reutilizados frente a nuevos
dentro de un mismo ensayo de cambios de permisos, contenido y versiones. La
medición de tiempo llega hasta la entrega de candidatos locales a la IA.
El informe local es `../experiments/rag-validation-step9/INFORME.md`.

## Paso 10. Comparación con BM25S

Se conserva el buscador léxico del paso 9. En la comparación directa de 17
preguntas de dos expedientes, ejecutadas dos veces, el índice actual tardó
**190,32 s** en cargar las fuentes, preparar los índices y buscar. El adaptador
con BM25S 0.3.16 tardó **208,02 s** en la misma tarea, un **9,30 % más**.
La recuperación por sí sola pasó de 159,38 a 177,29 s. En el expediente grande
el pico de memoria del proceso subió unos 330 MiB. En el pequeño, el tiempo
con preparación bajó de 30,68 a 30,20 s.

En un control separado del expediente grande, con ambos índices preparados y
el orden de ejecución alternado, las 20 llamadas al canal léxico pasaron de
14,031 a 10,472 s (25,37 % menos). Esa ganancia local no se trasladó al tiempo
total del flujo evaluado.

Las 816 apariciones de candidatos coincidieron en texto, orden, puntuaciones,
canales y citas. Ambos brazos recuperaron el respaldo completo de las diez
preguntas de admisiones entre los primeros 24 candidatos. En el otro expediente
recuperaron los documentos correspondientes a los cuatro pares etiquetados y
dos de sus cuatro pasajes literales. El prototipo y sus dependencias se probaron
en una carpeta aislada. El informe local es
`../experiments/rag-bm25s-step10/INFORME.md`.

## Paso 11. Búsqueda vectorial aproximada

Se conserva la búsqueda semántica exacta del proyecto. Se probaron FAISS HNSW
y E5 en el mismo proceso, sobre las 17 preguntas históricas y dos pasadas. Con
carga, preparación y devolución de las fuentes, el método exacto tardó
**191,89 s** frente a **207,69 s con HNSW (8,23 % más)**. Construir el grafo
del expediente grande tomó 25,82 s y su pico de memoria subió 28,88 MiB.
Con los índices ya preparados, la segunda pasada sí mejoró, de 58,54 a 56,16 s.

Antes de combinar los canales, HNSW conservó el 61,50 % de los 40 vecinos
exactos en el expediente grande y el 98,93 % en el pequeño. Después de la
combinación, las 17 preguntas conservaron sus primeros cinco candidatos.
Quince conservaron los 24. En C01/P8 y C01/P10 cambió el fragmento del puesto
24. La cobertura de los pasajes etiquetados fue la misma y se verificaron las
citas contra los fragmentos vigentes y autorizados de cada petición.

La alternativa se probó en una copia aislada. Qdrant como servicio persistente
queda sin medición directa. El control local de reapertura de FAISS en C07 está
en el informe local `../experiments/rag-vector-step11/INFORME.md`.

## Paso 12. Recuperar una cita cuando el oficio ya apareció

En C07/P4 el buscador situaba los documentos correctos en los puestos 1 y 2,
pero solo uno de los 24 fragmentos contenía una de las tres citas esperadas.
Se probó recuperar una respuesta marcada junto a una pregunta reproducida y leer
la continuación de un encabezado temático del mismo oficio.

El prototipo recuperó las tres citas en los puestos 12, 19 y 21. Los primeros
18 puestos se conservaron. Entre los seis que cambiaron salió una explicación
del oficio sobre las actas de aprobación. En otras once preguntas del expediente,
los 264 fragmentos y sus puestos fueron idénticos. En diez de esas preguntas,
con objetivos distintos de P4, ambos motores recuperaron 12 de los 13 pasajes
esperados. En C01 también coincidieron los 480 candidatos de las dos pasadas.

Se conserva el buscador del paso 9. La mejora literal quedó concentrada en la
pregunta de diseño. En 34 consultas, el prototipo tardó 204,09 s con carga y
preparación. El buscador actual tardó 191,89 s en la referencia inicial y
232,98 s al repetir el expediente grande y conservar la medición del pequeño.
La variación impide atribuir una mejora de velocidad al prototipo. El ensayo
llega hasta los candidatos que recibe el evaluador de fuentes.
El informe local es `../experiments/rag-context-step12/INFORME.md`.

### Seguimiento de C07/P11

- [x] Rastrear la cita ausente desde el documento autorizado hasta la selección final.

La diapositiva con la cita estaba en el puesto 2 del canal de correo exacto. Al
llegar su turno, el canal de identificadores había ocupado los puestos 23 y 24.
En un ensayo aislado, alternar esos dos canales recuperó la diapositiva en el
puesto 24 y conservó la otra cita de P11 en los puestos 13 y 21. El buscador
del proyecto sigue con la configuración del paso 9.
El diagnóstico local se conserva en `../experiments/rag-c07-p11/INFORME.md`.

- [x] Comparar el ajuste de un cupo con el buscador actual en preguntas nuevas de otros expedientes.

En ocho preguntas redactadas para C10, C14 y C08, ambos buscadores recuperaron
10 de 15 respaldos. Cubrieron por completo cinco de las siete preguntas con
evidencia positiva. La octava evaluaba si la IA reconocía que faltaba prueba de
una entrega individual. El ajuste solo intercambió dos puestos de una lista.
Con el índice preparado y el vector de cada pregunta calculado en el momento,
16 búsquedas sumaron 13,238 s con el buscador actual y 13,130 s con el ajuste.
La diferencia cambió de signo entre pasadas. Se conserva el buscador actual.
El evaluador habitual del proyecto interpretó y citó los ocho datos de C10.
En C14 y C08, el lector local produjo cinco lecturas distintas. Ninguna pasó
la validación de citas y estructura, incluso después del reintento.
El informe local es `../experiments/rag-one-slot-validation/INFORME.md`.

### Seguimiento de C14/V05

- [x] Probar un selector de adjuntos, revisar qué fragmento sale y medir la búsqueda con el índice preparado.

El selector experimental recuperó en el puesto 20 la primera página de la
notificación, que identifica el oficio y el certificado. Salió una cita de una
línea que solo contenía el número del oficio, aún presente en los puestos 1 y 15.
Los demás 23 puestos de V05 se conservaron. En las ocho preguntas del banco
la cobertura pasó de 10/15 a 12/15 respaldos. Los diez previos conservaron su
puesto. Con el índice preparado y el vector de pregunta calculado en cada llamada,
la mediana de V05 pasó de 1,368 a 1,458 s (ocho observaciones por versión).
El ensayo se cerró con la decisión de conservar el buscador del paso 9.
El selector de adjuntos de C14/V05 queda archivado como experimento.
El informe local es `../experiments/rag-c14-v05/INFORME.md`.

## Pruebas de la primera entrega (pasos 1 a 5)

Se aprobaron 121 pruebas acotadas: 93 de recuperación, selección, caché,
preparación semántica y configuración, más 28 de integración HTTP del servicio
de fuentes. Incluyen el modelo local real para una paráfrasis ficticia y dobles
explícitos de IA para el servicio. No se ejecutó la suite completa del proyecto.
Ruff de los módulos y pruebas modificados, y `git diff --check`, pasaron.

El entorno restringido bloqueó el `socketpair` interno de Python en Windows antes
de iniciar las pruebas HTTP. Se repitieron con un ejecutor que permite únicamente
ese canal interno y bloquea red externa, acceso a los datos vivos y escrituras
fuera del directorio de pruebas. Se ajustó además la ubicación del log de pytest
al directorio aislado. La advertencia restante es una deprecación de AnyIO usada
por Starlette. Los XML y el ejecutor quedan en `output/qa/rag-semantic-20261106/`.
