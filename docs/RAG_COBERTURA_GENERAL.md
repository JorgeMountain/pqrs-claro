# Contexto, cobertura y pendientes del RAG

Esta corrección actúa en el recorrido común de búsqueda, lectura, redacción y
revisión. No contiene identificadores de expedientes, fuentes de la prueba ni
respuestas esperadas. Mantiene cinco preguntas simultáneas, Fast configurable,
E5 residente, permisos por expediente y un máximo de 24 candidatos por lectura.

## Contexto original

La pregunta atómica recibe extractos literales del escrito original, con página,
líneas y límites de extracción. El contexto delimita nivel, población, periodo y
propósito; no acredita hechos ni sustituye fuentes institucionales. La pregunta
actual tiene prioridad sobre las otras preguntas del documento.

Los originales de hasta 12.000 caracteres se conservan completos; los más largos
usan una selección acotada y declaran sus omisiones. Véase
`CONTEXTO_ORIGINAL_PQRS.md`. Una omisión de extracción/contexto nunca acredita que
un documento no exista. La firma de resultados incluye las páginas originales y
la versión del contexto, incluso si la identificación no cambió.

## Recuperación

La selección de `master` se conserva como base. Una ampliación de hasta cuatro
fragmentos puede sustituir resultados léxicos/contextuales de la parte final;
protege los respaldos semánticos, de cuerpo, identidad, tema y respuesta contigua.
Cuando la semántica quedó excluida, permite recuperar candidatos de ese canal.
Los reglamentos generales no se descartan exclusivamente porque su título no
enumere cada procedimiento que contienen. Los lugares restantes de la ampliación
permiten leer continuaciones del mismo documento y versión, con citas separadas.
La consulta semántica sigue siendo la pregunta atómica. Los títulos normativos
literalmente mencionados en el escrito permiten abrir una búsqueda acotada dentro
del documento; el nombre en la pregunta tiene prioridad sobre el de una hermana.
Si no hay un nombre completo, el tipo documental y los calificadores explícitos
del ámbito compartido pueden localizar candidatos. Las preguntas hermanas no se
usan para construir esa pista. Una lista que continúa literalmente en la página
siguiente tiene prioridad sobre vecinos genéricos, dentro del mismo presupuesto.
Los detalles y límites se describen en `RECUPERACION_GENERAL_CONTEXTO.md`.

La recuperación sigue siendo una selección: encontrar 24 fragmentos no prueba
exhaustividad. Cada fragmento conserva identidad, versión, hash, página y líneas.
La continuación no autoriza otra colección ni una versión retirada. La cita exacta
debe respaldar la afirmación, no basta pertenecer al documento correcto.

## Comprobación de incisos

`request_requirements.py` divide coordinaciones explícitas de la pregunta en
incisos literales. No inventa subpreguntas ni convierte una lista de documentos
requeridos al aspirante en una orden de entregar esos documentos al solicitante.

El lector debe comprobar cada identificador una vez y enlazarlo con afirmaciones
respaldadas o un pendiente concreto. Se rechazan identificadores omitidos,
duplicados, índices inexistentes y cobertura completa contradictoria con los
incisos. Un aviso de catálogo por sí solo no sustituye la brecha de un inciso.
El intento de lectura admite una reparación acotada; si el contrato sigue fallando,
el resultado es un error de análisis, no un documento faltante inventado.

`sufficiency.evaluated_gaps` conserva la lista original que indexan los checks;
los pendientes de trabajo pueden normalizarse, agruparse o recibir controles
adicionales. Así no se interpretan los índices contra una lista posterior distinta.

Redacción y la revisión del texto editado vuelven a comprobar cada inciso contra
los párrafos y pendientes actuales. Un inciso omitido impide una comprobación
satisfactoria. El grafo final conserva esa defensa aunque un proveedor devuelva
`passed`. La aprobación sigue siendo humana y exige una evaluación vigente.
Un control ya cerrado o declarado no aplicable no sustituye la contestación del
inciso: debe existir una respuesta o una brecha específica todavía abierta. Las
actuaciones posteriores de entrega se conservan aparte.

Cuando el modelo devuelve un checklist estructuralmente inválido, Redacción y la
revisión del texto editado permiten una sola repetición de la comprobación con el
mismo texto y las mismas fuentes. Se conserva el diagnóstico; si sigue inválido,
se bloquea. Una omisión semántica por sí sola no activa esa repetición. Si coexiste
con un error estructural, debe seguir figurando como omisión después de repararlo.

## Pendiente de contenido y control documental

Se conserva la diferencia entre falta de contenido, identidad ambigua,
transcripción, contradicción, procedencia, vigencia, aplicabilidad y entrega.
Una descripción atribuida del contenido de un documento histórico no equivale a
aplicar una norma al caso actual. Las reservas de catálogo pueden ser no bloqueantes
solo cuando no afectan lo preguntado; las contradicciones, lectura insuficiente e
identidad no confirmada permanecen abiertas.

Una norma identificada, íntegra y autorizada puede usarse como `document` si se
pide su copia. En una pregunta mixta, el mismo soporte puede respaldar
`document_delivery`, `attributed_content` y `rule`, sin repetir el fragmento.
Nunca adquiere por eso capacidad de probar hechos, estado oficial del expediente,
autenticidad o entrega realizada. Preparar la entrega sigue como actuación aparte.
Pedir una copia histórica no exige por sí solo que esa norma continúe vigente:
la vigencia se mantiene cuando se pretende aplicar la regla o se pide actualidad.
Los controles de procedencia, identidad e integridad de la copia siguen separados.

Un archivo localizado por título pero con identidad insuficiente genera cotejo;
no se exige otra copia por el mero nombre genérico de su archivo. Localizado no
significa completo, pertinente, auténtico ni enviado.

## Compatibilidad y uso

Versiones del modo habitual: contexto 2, análisis de fuentes 23, lector 3,
suficiencia 4, redacción 16 y revisión 11. El piloto de referentes, desactivado por
defecto, utiliza redacción 17 y revisión 12. El inventario de detalles y los
pendientes de aplicabilidad se describen en
[INVENTARIO_AUTORIDADES_Y_PENDIENTES.md](INVENTARIO_AUTORIDADES_Y_PENDIENTES.md).
Un resultado previo no se etiqueta como comprobado bajo la nueva
política. Hay que actualizar fuentes, generar o sincronizar el borrador y volver
a comprobarlo. El texto humano se conserva; ninguna migración aprueba respuestas.

Los ensayos usan copias independientes y expedientes ficticios. No recategorizan
la biblioteca viva, no retiran permisos reales, no envían respuestas y no marcan
como revisadas las fuentes reales. Los tiempos de lectura sobre candidatos
capturados excluyen el catálogo, el índice, el navegador y la revisión humana;
no deben compararse como aceleración con tiempos completos del servicio.

## Límites

La segmentación es estructural y la suficiencia semántica sigue dependiendo de la
IA y de la revisión humana. No garantiza detectar todo inciso implícito ni recuperar
todo artículo en documentos futuros. Los checks hacen observables las omisiones
detectadas y bloquean su aprobación, pero no convierten una evaluación del modelo
en una prueba de exhaustividad. Deben conservarse pruebas con documentos nuevos,
ámbitos distractores, listas incompletas, fuentes corregidas y permisos retirados.

La continuación añade un inventario de unidades con citas literales entre el
plan, la redacción y la revisión del texto guardado. El contrato y sus límites
están en [UNIDADES_RESPUESTA_RAG.md](UNIDADES_RESPUESTA_RAG.md); la comparación
con documentos nuevos y los candidatos descartados se documenta en
[RESULTADOS_OMISIONES_GENERALES_20261116.md](RESULTADOS_OMISIONES_GENERALES_20261116.md).

El piloto de referentes contrasta los efectos de actuaciones distintas. No se
activó por defecto porque la validación completa aún produjo omisiones y
pendientes incorrectos. Incluye la redacción generada y el texto editado que se
vuelve a comprobar. Su contrato,
coste y límites están en
[CLARIDAD_PROCEDIMIENTOS_RAG.md](CLARIDAD_PROCEDIMIENTOS_RAG.md).
