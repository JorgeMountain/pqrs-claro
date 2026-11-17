# Disponibilidad, autenticidad y entrega de copias

## Alcance

Cambio general en el código local, evaluado el 16 de noviembre de 2026. No depende
de identificadores de expedientes, números de normas ni nombres del corpus QA.
La referencia de comparación es el estado local inmediatamente anterior, que ya
contenía otros cambios sin fusionar; **no es una comparación contra master**.

Una copia identificada y disponible no necesita convertirse en una copia
certificada para poder preparar su entrega. La certificación solicitada, un
defecto concreto o la prueba de una entrega pasada conservan sus comprobaciones.
La aprobación humana y la entrega efectiva siguen siendo actuaciones diferentes.

## Implementación

- `source_documents.available_copy_matches` reutiliza la comprobación de identidad
  del original: encabezado, número/año cuando corresponden, identidad de catálogo,
  versión, hash y ausencia de reemplazo. Recibe candidatos del snapshot autorizado
  de biblioteca, que comprueba los bytes y los permisos. Una mención, un título
  coincidente o un fragmento sin identidad suficiente permanecen como candidatos.
- `sufficiency.document_states` conserva tres dimensiones por fuente:
  disponibilidad (`identified_copy`/`candidate_only`), autenticidad
  (`not_inferred_from_availability`, con exigencia explícita separada) y entrega
  futura (`pending`). Ninguna dimensión crea una verificación humana ni registra
  una entrega que no ha ocurrido.
- `metadata_check_required` convierte en observaciones únicamente los controles
  genéricos de procedencia/versión expedida marcados `metadata_only`, cuando la
  copia está identificada, los usos son copia/contenido atribuido y no se exige
  autenticidad, aplicación actual o una actuación adicional. La propuesta original
  y el motivo se conservan en `gap_decisions`; no se modifica el catálogo.
- Se conservan las brechas `content_gap`, contradicciones, transcripción, extracción,
  anexos faltantes, identidad ambigua y exigencias de firma o certificación. Las
  exigencias globales del escrito y sus padres se consideran; las preguntas
  hermanas no se convierten en requisitos propios. Las negaciones explícitas no
  añaden obligaciones. «Envíeme hoy una copia» no prueba que se pida vigencia actual.
- Lector, planificador, redactor y comprobadores reciben la misma explicación de
  los estados, dentro de las llamadas existentes. La tarea de entrega permanece
  abierta y no bloquea la preparación del contenido. Una recepción histórica
  consultada necesita evidencia independiente.

Versiones de este primer ensayo: fuentes 24, lector 4, suficiencia 5; borrador 18/revisión 13 en modo
habitual y borrador 19/revisión 14 en el piloto previo. Se invalidan resultados
derivados antiguos sin sobrescribir texto humano ni cerrar pendientes. No se
activó el auditor experimental de procedimientos como parte de este cambio.

## Pruebas locales

`tests/test_document_availability_dimensions.py` contiene 69 casos con tres
documentos nuevos conservados en bibliotecas temporales: instrumentos musicales,
archivo y observatorio. Las selecciones del lector se simulan para comparar la
misma entrada, pero los archivos, sus versiones, hashes y permisos son reales.

En las tres copias comunes: controles genéricos bloqueantes **4 → 0**, respaldos
**3 → 3** y tareas de entrega abiertas **3 → 3**. Se mantienen cotejos de copia
certificada/auténtica/autenticada/firmada/suscrita, constancia de expedición, sello
de autenticación, contradicción de firma, anexo ausente, OCR y recepción pasada.
La frase «no requiero certificación, solo la versión firmada» conserva la exigencia
positiva de firma; no se extiende la negación a la alternativa pedida.
La alteración de bytes y la revocación de permisos siguen impidiendo reutilizar
la fuente. Se prueban también negaciones, alcance global y fragmentos vecinos.

Se ajustaron expectativas antiguas que exigían procedencia genérica para una
copia común. Los casos que sí piden aplicación actual o actuaciones adicionales
continúan exigiendo sus controles, aunque el modelo los etiquete como atribución.

```powershell
.\scripts\dev-python.ps1 -m pytest tests/test_document_availability_dimensions.py tests/test_document_copy_anaphora.py tests/test_source_sufficiency.py tests/test_source_application_scope.py tests/test_application_scope_regressions.py -q
```

## Comparación con lector real

Seis PQRS nuevas y tres PDF completamente ficticios, con biblioteca aislada,
índice preparado, fuentes idénticas y rúbrica separada del payload. Una ejecución
por variante, seis llamadas en cada una; no se repitieron casos hasta aprobar.

| Caso | Pendientes antes | Después | Resultado |
|---|---:|---:|---|
| Copia común de circular | 1 | 0 | Conserva copia y entrega futura. |
| Copia común de resolución | 1 | 0 | Conserva copia y entrega futura. |
| Copia certificada | 3 | 3 | Conserva el cotejo de autenticidad solicitado. |
| Consulta de materiales, sin copia | 0 | 0 | Conserva los cinco materiales y no añade entrega. |
| Constancia de recepción pasada | 1 | 1 | No acredita recepción sin la constancia. |
| Copia común de acta | 1 | 0 | Conserva copia y entrega futura. |

Los cinco soportes y sus cinco citas son exactamente los mismos: identificadores,
texto literal, versión, hash y permisos cotejados. Los tres bloqueos genéricos
innecesarios desaparecen. Los dos requisitos materiales legítimos probados
(certificación y recepción pasada) permanecen. No se asume que los cuatro
pendientes restantes sean cuatro requisitos distintos: hay redundancias previas.

Tiempo total del lector para los seis casos: **47,10 → 40,82 s**. Es una sola
ejecución; no demuestra una aceleración general ni mide la respuesta final aprobada.
La comparación consumió 12 llamadas, 96.210 tokens de entrada y 14.428 de salida.
No se añadieron nuevas llamadas a la arquitectura del producto.

Artefactos locales reproducibles en `output/qa/document-copy-states-20261116/`:
`fixture-content.json`, `rubric-not-sent.json`, snapshots de código, originales,
resultados, observaciones SDK, `reader-comparison.json` y `reader-audit.md`.

## Redacción con los hallazgos guardados

Se ejecutaron los métodos normales `OpenAIDraftEngine.plan/write/check` para la
copia común y la certificada, sin repetir la búsqueda, añadir reparaciones ni
activar el auditor experimental. Seis llamadas adicionales, cero errores.

- Copia común: `needs_review`, contenido comprobado `passed`, una cita válida y
  únicamente la entrega futura abierta. No reaparece el cotejo genérico eliminado.
- Copia certificada: `needs_evidence`, contenido comprobado `passed`, los tres
  controles heredados y la entrega futura conservados. No afirma certificación
  ni añade pendientes. Que el contenido pase no cierra sus controles abiertos.

Planificación/redacción/comprobación tardaron 13,23 s y 34,44 s, respectivamente.
No hay comparación anterior de estos dos tiempos. El probe consumió 74.240 tokens
de entrada y 4.178 de salida. Total del ensayo: **18 llamadas, 189.056 tokens**.
Los estados siguen requiriendo revisión humana; no hubo aprobación ni entrega.

Las seis respuestas guardadas se reprodujeron después con el código local final,
sin API, conservando exactamente soportes, comprobaciones, pendientes, acciones y
estados: **6/6** (`replay-current.json`). Esto incluye el ajuste posterior que
acota la negación antes de una alternativa afirmativa. Las pruebas locales de esa
negación no necesitaron repetir las llamadas reales.

La suite específica final de disponibilidad, anáforas y aplicabilidad pasó
**214 pruebas**. Otra ejecución final de lectura, recuperación, contratos de
Redacción/revisión y regresiones afectadas pasó **301 pruebas**. Además, una
comprobación previa de integración de fuentes, Redacción y revisión pasó 450
pruebas (con solapamiento; no sumar los conteos). Ruff y `git diff --check`
aprobaron los archivos de este cambio.

La suite general se interrumpió aproximadamente al 50% por su duración; no se
declara aprobada. Mostró una expectativa antigua de `test_normative_attribution`
que exigía procedencia genérica para una copia común. Se actualizó esa expectativa
al comportamiento solicitado, manteniendo el control de vigencia cuando sí se
pide una copia vigente; el archivo pasó en la ejecución final de 301 pruebas.
Los logs parciales y finales se conservan en `regression.txt` y `affected-final.txt`.

## Límites observados

- El aviso genérico de vigencia en copias certificadas observado en este ensayo
  se corrigió posteriormente. La comparación y los controles conservados están
  en [Vigencia y copias certificadas](VIGENCIA_COPIAS_CERTIFICADAS.md).
- En la referencia, la conciliación de una constancia ausente que mencionaba una
  resolución localizada describió mal el objeto del pendiente. El candidato
  conservó una descripción correcta propuesta por el modelo, pero esa variación
  no demuestra que se haya corregido aquel reconciliador.
- Las decisiones semánticas y la comprensión de formulaciones nuevas aún pueden
  fallar. Los resultados prueban este conjunto y las regresiones, no ausencia
  universal de errores. No se elimina un pendiente concreto para mejorar un conteo.
- La validación se realiza en copias aisladas; los expedientes vivos no se
  recalculan ni se marcan aprobados por este ensayo.
