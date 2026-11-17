# Validación del inventario y los pendientes

Fecha de artefactos: 17 de noviembre de 2026 UTC (16 de noviembre en Bogotá).
Carpeta local: `output/qa/rag-inventario-pendientes-20261117`.

## Diseño del ensayo

La referencia es el código de trabajo aceptado al comenzar esta continuación, con
el auditor de procedimientos apagado. No es un checkout limpio de `master`: incluye
las correcciones generales de contexto, cobertura y unidades de la tarea anterior.
Se congelaron 98 módulos de referencia; el candidato añade el módulo de
incertidumbres. Cada variante tiene su fotografía de código y manifiesto de hashes.

Primera tanda: tres expedientes enteramente ficticios, seis preguntas, seis PDFs y
siete fragmentos. Incluye autoridades distintas, alternativas documentales, datos
ya aportados, conflicto para aplicar un plazo, comparación sólo descriptiva, copia
localizada pendiente de cotejo y copia firmada no localizada. La rúbrica tiene 27
criterios y se congeló antes de las llamadas. No se envía al modelo.

Se utiliza el servicio de fuentes y el grafo de borrador con índice preparado,
bases independientes, las cinco preguntas concurrentes configuradas y el lector
habitual Fast. La identificación de preguntas se fija y coteja literalmente: esta
prueba no evalúa la identificación automática desde el PDF. El tiempo hasta cita y
el tiempo hasta borrador comprobado se distinguen; no incluyen revisión humana ni
la interfaz del navegador.

Durante parte de las variantes también se ejecutó la suite local en el mismo
equipo. Por ello, además de tener una sola generación por variante, no se aisló
la carga de la máquina. Los tiempos son trazas observadas para detectar costes
y errores; no prueban una mejora o regresión causal de rendimiento. No se evaluó
agotamiento del top 24 ni cinco preguntas a plena concurrencia con este corpus.

Además se reproducen tres fallos anteriores sobre entradas capturadas. Estos
replays no vuelven a medir recuperación: dos ejecutan el lector sobre candidatos
fijos y el tercero planifica y comprueba un borrador anterior, con una sola
reparación posible. Se conservan errores, intentos descartados y controles abiertos.

## Referencia y primer candidato descartado

| Métrica | Referencia | Primer candidato, auditor apagado |
| --- | ---: | ---: |
| Criterios de contenido conservados | 27/27 | 22/27 |
| Preguntas válidas, considerando controles | 6/6 | 3/6 |
| Apariciones de respaldos seleccionados | 8 | 8 |
| Citas literales de unidades | 24 | 23 |
| Errores de ejecución | 0 | 1 |
| Llamadas registradas | 24 | 24 |
| Media hasta finalizar el intento por expediente | 51,97 s | 70,86 s |

El tiempo de un intento fallido no representa una respuesta validada. Los 9
controles de las preguntas que produjeron borrador permanecieron intactos; los
otros 3 pertenecen a la pregunta sin borrador y no se cuentan como cierres ni como
conservación demostrada en la salida.

El primer candidato preservó las autoridades y alternativas de las dos preguntas
del primer expediente. Falló en tres puntos: duplicó el control material de
aplicabilidad, abrió una duda de identidad innecesaria para una denominación
documental no reconocida y exigió inventariar contenido cuando sólo se pedía una
copia firmada y el candidato era un borrador. Se conservan las auditorías
`audit-candidate-off.md` y `comparison-candidate-off.md`; no se toma ese candidato
como una mejora válida.

Los replays iniciales corrigieron el pendiente antes ausente y el falso
`search_incomplete` de una copia. Detectaron además una cita de un pasaje incidental
que no justificaba una afirmación sobre entrada en vigor. En C07/P3 se repusieron
las dos autoridades como alternativas, sin cambiar citas por párrafo ni pendientes;
la comprobación final dejó un reparo de atribución en otro párrafo. Ese resultado
no se registra como aprobación completa.

## Segundo candidato

La segunda variante recuperó **27/27 criterios** en las seis preguntas y conservó
los ocho respaldos, 27 citas literales de unidades y **9/9 controles heredados**.
No tuvo errores de API ni de ejecución. Cinco de las seis respuestas completaron
la comprobación; la restante conservaba el contenido, pero anunciaba un cotejo
material que no aparecía como pendiente específico. No se contó como aprobación.
Fueron 26 llamadas; la media por expediente hasta finalizar el intento fue
81,86 s. Estos tiempos son observacionales, con una generación por variante.

En los replays, el conflicto ya seleccionó el pasaje correcto de la segunda página
y mantuvo un solo control de aplicabilidad, sin duplicarlo en `missing`. La copia
quedó localizada con procedencia y entrega pendientes. C07 repuso autoridades y
alternativa sin cambiar pendientes ni citas; la última comprobación señaló una
condición de entrevista verbal/colectiva. No hubo una segunda reparación para
buscar una aprobación. El recorte de una cita de la copia también se conserva
como limitación observada, aunque el respaldo completo está disponible.

La revisión independiente encontró cuatro defectos anteriores de identidad
documental: confundir año y número, tomar el año de otra norma citada, aceptar
otro sufijo y reducir dos objetos de copia al primero. Se corrigieron antes de
ensayar una tercera variante; los cinco negativos originales quedaron como pruebas
de regresión. No se presentan como defectos nuevos del inventario.

## Resultado final

El candidato V3 quedó congelado en 99 módulos. En las seis preguntas iniciales
obtuvo **26/27 criterios y 4/6 resultados válidos** frente a 27/27 y 6/6 de la
referencia. No se acepta como sustituto general de la referencia a partir de ese
resultado. Se mantiene apagado el auditor de procedimientos.

El conflicto ya conserva un control específico sin duplicado; las autoridades y
alternativas se mantienen. El cotejo material antes mencionado sólo en la prosa
ya tiene registro. Quedan dos defectos observados: confundir la integridad del
archivo disponible con la autenticidad de su reproducción, y omitir que una fecha
de sesión era propuesta mientras queda una referencia interna en la prosa. El
segundo caso permanece bloqueado por el comprobador; el primero demuestra que un
`passed` no basta para aceptar la variante.

No se perdió ningún respaldo seleccionado en la referencia: V3 conserva los ocho
y añade dos para contexto de ámbito y exclusión de una versión de otro año. Los
**10/10 controles heredados** permanecen exactamente en los borradores; no hubo
errores de ejecución ni citas ajenas al ámbito autorizado. El número de citas de
unidades fue 23 frente a 24, sin perder respaldos: el conteo de unidades depende
de su agrupación, por lo que no sustituye el examen de cada afirmación.

La media hasta finalizar el intento por expediente fue 71,13 s, con 30 llamadas
frente a 24, y tres reparaciones. El último expediente no alcanzó un resultado
válido completo; no se le asigna una latencia de respuesta validada. No se estimó
dinero sin tarifa configurada ni se presenta este cambio como una aceleración.

La tanda final reservada añadió dos dominios, cuatro preguntas, seis PDFs y ocho
fragmentos, con 22 criterios sellados antes de conocer el candidato. En ella V3
mejoró de dos a tres respuestas válidas: conservó el pendiente del ejemplar firmado
exacto y dejó de declarar simultáneamente que no hacía falta otra copia. Persistió
el bloqueo genérico de vigencia en la comparación descriptiva acompañada de una
solicitud de copia.

En conjunto, las diez preguntas dieron **48/49 → 47/49 criterios** y **8/10 → 7/10
resultados válidos**. Se conservaron todos los respaldos de referencia (14 → 17),
el orden recuperado fue idéntico en las diez preguntas y los **20/20 controles
heredados** permanecieron intactos. Esto demuestra conservación, no ausencia de
controles innecesarios. Hubo 37 → 47 llamadas, sin reintentos HTTP. No se ejecutó
el modo ON porque la variante OFF no superó el control de calidad.

La suite completa V3 terminó con **2.306 pruebas aprobadas** y Ruff aprobado. La
suite V2 había terminado con 2.292 aprobadas. No se suman estas tandas ni las de
módulos individuales. Las pruebas mecánicas no anulan los fallos semánticos de la
comparación. La revisión independiente de identidad cerró los cuatro defectos con
sus cinco negativos y controles positivos; ninguna prueba equivale a una garantía
para todo formato documental futuro.

Una segunda lectura humana del replay C07 considera que el veto de entrevista
puede ser excesivo: el tramo es idéntico antes y después de reparar autoridades y
mantiene la estructura condicional de la fuente. Se conservaron ambos estados del
comprobador, sin reemplazar `needs_changes` por una aprobación. En la copia también
se anotó que pedir conocer entregas anteriores puede ser un bloqueo excesivo cuando
sólo se pretende preparar una copia nueva. La petición admite más de una lectura;
no se cerró ese control de forma automática.

## Corrección determinista posterior: mandatos negados

La auditoría del bloqueo de vigencia encontró una causa reproducible: la frase
«No determinen cuál se aplica hoy» activaba el detector por la palabra «hoy».
La política V4 se comprobó por separado con los mismos diez resultados crudos del
lector, sin red ni bases vivas, para aislar el efecto de Python. Sólo la pregunta
afectada dejó de generar sus dos controles genéricos de vigencia. Los respaldos,
citas, orden, cobertura, incertidumbres y acciones permanecieron exactos en las
diez entradas; también los pendientes de las otras nueve. En la pregunta afectada
se conservaron procedencia y entrega futura. No se cerraron controles guardados.

La comprobación amplia final de fuentes y servicio pasó **299 pruebas** y la
revisión independiente, **242**, incluidos 17 negativos/positivos nuevos de
negación, preguntas reales, contraste afirmativo y controles materiales. Estas
tandas se solapan: no se suman. La suite completa de 2.306 corresponde al candidato
V3 anterior a este último ajuste; para V4 se ejecutaron las pruebas pertinentes
de los componentes afectados. Ruff y los controles de espacios también pasan.

Se incrementaron análisis de fuentes a 23 y suficiencia a 4 para invalidar también
resultados intermedios. El esquema y las instrucciones del lector no cambian.
No se sustituyen retroactivamente las métricas V3. La prueba API V4 se limitó
al expediente afectado, con sus dos preguntas: ambas completaron la comprobación,
con **11/11 criterios y 2/2 resultados válidos**, sin error permanente ni reparación
de párrafos. Desaparecieron los bloqueos de vigencia; permanecieron
procedencia, cotejo del original y preparación/entrega. La copia de dos páginas
quedó localizada y el ejemplar firmado no localizado conservó su búsqueda exacta,
sin sustituirlo con una propuesta. No hubo cierres de controles vivos.

Se conservaron cuatro respaldos, siete citas literales de unidades y **6/6
controles heredados**, con un cotejo legítimo nuevo. La primera cita llegó a
9,92 s y ambas respuestas comprobadas a 128,30 s, en nueve llamadas. No representa
una mejora acreditada de velocidad. El detalle está en
`comparison-candidate-v4-off-partial.md` del holdout final y la trazabilidad del
cotejo, en `candidate-v4-off-control-trace.json`.

La generación añade una actuación específica de entrega junto a la genérica,
ambas no bloqueantes: es una variación observada también en la referencia y no
se presenta como eliminación universal de duplicados. Un control etiquetado
`source_identity` describe cotejar la reproducción con el original; en esta salida
no declara que el archivo localizado sea inexistente ni una identidad ambigua.
La revisión considera descripción, fundamento y objeto, no sólo la etiqueta.

Esta comprobación parcial no equivale a volver a probar las diez preguntas con V4
ni elimina las limitaciones semánticas observadas en los otros expedientes. El
auditor de procedimientos no se activó y el candidato no se declara aprobado
globalmente. Código, pruebas y documentación quedan locales para continuar su
validación; no se hizo commit, push ni fusión en esta tarea.

## Integridad y artefactos

La verificación final confirmó el piloto efectivo en `false`, los 99 módulos
iguales al snapshot V4 y **25 tablas de cuatro bases reales sin cambios**, frente a
la fotografía inicial. No se recalcularon expedientes vivos ni se alteraron
permisos reales. Las comprobaciones de corrección de fuentes, revocación y
conservación del texto humano se hicieron por API local y bases aisladas; no se
afirma haber probado actualización visual en el navegador en esta tarea.

Los artefactos reproducibles incluyen `baseline-code.json`, `candidate*-code.json`,
las rúbricas selladas, `qa-v3-overall.md`, `audit-regressions-candidate-v2.md`,
`audit-application-scope-offline.md`, los registros crudos del observador API y
`final-verification.json`. El holdout final reservado está en
`output/qa/rag-inventario-pendientes-holdout-final-20261117`.
