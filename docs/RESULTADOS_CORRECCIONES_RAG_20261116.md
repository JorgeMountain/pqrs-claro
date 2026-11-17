# Correcciones generales del RAG y validación

La corrección modifica el recorrido común de fuentes, lectura, redacción y revisión.
No utiliza los identificadores, números de norma ni respuestas esperadas del corpus
para decidir en producción. El punto de comparación es `master` en
`f7f9ce06332807b52c050508f172ce6402450ba7`. Al finalizar el ensayo del 16 de
noviembre de 2026, el trabajo permanecía local, sin commit ni push y sin aprobación
automática de expedientes. El estado de integración posterior se documenta en
[INTEGRACION_CORRECCIONES_RAG_20261117.md](INTEGRACION_CORRECCIONES_RAG_20261117.md).

## Cambios implementados

| Problema | Corrección general | Límite que permanece |
| --- | --- | --- |
| Se pierde el ámbito del PDF | Contexto literal con página/líneas, prioridad de la petición seleccionada y firma de las páginas originales | Los originales largos tienen selección acotada y declaran truncamiento |
| La norma o continuación queda fuera de los 24 candidatos | Se conserva la selección base; hasta cuatro incorporaciones protegidas, búsqueda corporal por nombre o ámbito explícito y prioridad de listas contiguas | La selección no prueba exhaustividad ni aplicabilidad |
| Un inciso queda sin respuesta ni pendiente | Checklist por inciso en lector, borrador y revisión; exige cita o brecha específica abierta | Una comprobación semántica del modelo puede pasar por alto detalles implícitos |
| Se piden archivos no solicitados | Se separa consultar requisitos de ordenar la entrega; se conservan negaciones y preguntas mixtas | La intención ambigua sigue necesitando revisión |
| La categoría normativa impide ofrecer una copia | Una norma identificada puede respaldar su copia, con controles de original, versión, hash y permisos | Localizar o preparar la copia no equivale a enviarla ni autenticarla |
| Se combinan trámites distintos con citas exactas | Comprobación compartida de objeto, supuesto, etapa, población, autoridad y efecto | Detectar el defecto no acredita su corrección; la aprobación sigue siendo humana |

Los controles de procedencia, transcripción, identidad, contradicción, vigencia,
aplicabilidad y entrega se conservan separados de una brecha de contenido. Un error
de análisis, una extracción incompleta o una búsqueda sin resultados no acreditan
inexistencia. Un pendiente cerrado tampoco sustituye una respuesta que falta.

El checklist inválido admite una única reparación estructural con el mismo texto
y las mismas fuentes. Una omisión semántica por sí sola no activa reintentos para
obtener una aprobación. Las versiones nuevas invalidan resultados antiguos y
preservan el texto humano: hay que recalcular y comprobar antes de aprobar.

## Comparación de las 40 preguntas originales

Se releyeron tanto las salidas originales como las corregidas con el mismo criterio.
Se distingue responder correctamente el núcleo de la pregunta de conservar todos
los puntos de su rúbrica. Los controles documentales legítimos no se cuentan como
falta de contenido; la preparación para aprobar sigue siendo una medida aparte.

| Medida independiente | Master original | Corrección final |
| --- | ---: | ---: |
| Contenido principal correcto y respaldado | 26/40 | **37/40** |
| Todos los puntos de la rúbrica conservados | 19/40 | **28/40** |

El 26/40 de esta tabla procede de la relectura comparable del contenido principal.
No se compara directamente con el criterio exhaustivo de la segunda fila ni se
asume equivalencia entre etiquetas de informes anteriores.

| Expediente ficticio | Núcleo correcto final | Rúbrica completa final |
| --- | ---: | ---: |
| 01 · Credencial y admisión | 5/5 | 5/5 |
| 02 · Avales y anexos | 5/5 | 3/5 |
| 03 · Cancelación y reingreso | 5/5 | 3/5 |
| 04 · Revisión de evaluaciones | 4/5 | 4/5 |
| 05 · Programación académica | 5/5 | 5/5 |
| 06 · Permanencia y reconocimiento de cursos | 4/5 | 3/5 |
| 07 · Evaluación y deberes profesorales | 5/5 | 3/5 |
| 08 · Resolución y programa académico | 4/5 | 2/5 |

No se considera un cierre completo del problema semántico. Permanecen, entre otros:

- **C04/P4:** el texto mezcla dos procedimientos. La comprobación final lo detecta
  y exige cambios; encontrar la norma directa no convirtió el borrador en correcto.
- **C06/P2:** las disposiciones recuperadas contienen duraciones diferentes. Queda
  un pendiente específico de contradicción/aplicabilidad, no un documento faltante.
- **C08/P1:** copia localizada y consulta técnica al original demostrada; el borrador
  ofrece preparar la consulta, pero no acredita que se haya facilitado o entregado
  al solicitante ficticio. No se contó como cumplimiento completo.
- Faltan detalles en algunas respuestas: envío general único y rótulos, remisiones
  y actuaciones posteriores, equivalencias entre escalas, integración de informes
  y principios de los deberes profesorales. No todos quedaron señalados por la IA.
- **Regresión explícita C08/P4:** master incluía el estudio de costos y la respuesta
  corregida lo omite. También se documentan compensaciones entre detalles en C02/P4.

Las pruebas reducen fallos conocidos y añaden barreras verificables; no autorizan
a afirmar que cualquier documento futuro quedará respondido de forma exhaustiva.

## Pruebas con documentos nuevos

Tres expedientes ficticios nuevos, con nueve preguntas y 19 incisos, recorrieron
los servicios reales de fuentes y redacción con la API configurada. La auditoría
confirmó los nueve resultados, sus citas y sus pendientes. Incluyen políticas de
ámbitos opuestos, copia e información en la misma pregunta, corrección de fuente
y retirada de permiso. No se proporcionó la rúbrica al modelo.

Se comprobó además la revisión real de tres respuestas: siete incisos correctos,
texto y pendientes conservados y ninguna aprobación. En una prueba adversarial
posterior, el comprobador detectó tres mezclas de procedimientos —una del corpus y
dos ficticias nuevas— y aceptó las dos versiones que distinguían correctamente las
vías. Fueron cinco llamadas, una por ejemplo, sin modificar los textos.

Detalles: `VALIDACION_RAG_CONTEXTOS_NUEVOS_20261116.md` y
`QA_MEZCLA_PROCEDIMIENTOS_20261116.md`.

## Integridad, permisos y datos reales

La auditoría del conjunto final de 40 preguntas verificó 54 fragmentos seleccionados
y 92 citas de afirmaciones: sin errores de literalidad, coordenadas, versión, hash
o ámbito autorizado. Eso no equivale a comprobar toda la interpretación semántica.

La consulta local de la resolución solicitada devolvió el PDF íntegro de tres
páginas y el hash del catálogo. Tras retirar el permiso de la colección, el endpoint
del original y su vista previa respondieron 404 sin contenido; al restaurarlo,
volvió a devolver los mismos bytes. Fue una prueba de API aislada, sin navegador,
entrega externa ni validación criptográfica de firmas.

El fingerprint de cuatro bases reales y 25 tablas seleccionadas quedó idéntico al
inicial. Esta comparación fue de contenido lógico en modo lectura; no pretende ser
una auditoría de todos los archivos y cachés del equipo.

## Verificación automática

- Suite general: **1.898 pruebas aprobadas**, una advertencia de deprecación de una
  dependencia, 730,65 s. Esta ejecución precede a las dos últimas reglas del selector
  y al refuerzo final del prompt de comprobación.
- Selector final: **198 pruebas focales aprobadas**, incluidas 28 nuevas.
- Comprobación final de borrador/revisión: **156 pruebas aprobadas**.
- Frontend existente: **234 pruebas aprobadas**; esta corrección no cambia su código.
- Ruff y comprobación de espacios del diff: sin errores.

## Rendimiento y alcance de la evidencia

La recuperación final de 40 consultas tardó 352,25 s, con mediana 7,58 s por pregunta,
excluyendo preparación y lectura/redacción de IA. La corrida anterior de master
registraba mediana 5,37 s y total 413,35 s. Son procesos, órdenes y cargas distintos:
la mediana mayor señala posible latencia adicional, pero no permite atribuirla al
cambio; el total menor tampoco demuestra aceleración. Falta comparación controlada
de tiempo integral antes de hacer una afirmación de rendimiento.

Se conservan las iteraciones descartadas: redistribuir agresivamente los 24 cupos
y usar todo el contexto en la consulta semántica perdía respaldos útiles. La versión
final usa la pregunta atómica para E5 y limita las sustituciones. El único soporte
anterior desplazado cuyo texto ya no aparece corresponde al acta histórica C04/P4;
entra una norma directa y su interpretación se revisa expresamente, sin asumir que
el reemplazo conserva cada conclusión del acta.

El conjunto final `lectura/accepted-v3-2` es una evaluación compuesta documentada:
22 lecturas reutilizadas tras comprobar identidad del payload y del lector, y
18 lecturas nuevas. No es una corrida nueva cronometrada de las 40 preguntas.
Los artefactos originales y sus tiempos se conservan. La nueva comprobación de
C04/P4 vive aparte y lo deja en `needs_changes`; su borrador original no se alteró.

Las evidencias locales, scripts, huellas, auditorías independientes y manifiestos
están en `output/qa/rag-general-correcciones-20261116/`. Las reglas y límites de
producción se explican en `RAG_COBERTURA_GENERAL.md` y
`RECUPERACION_GENERAL_CONTEXTO.md`.
