# Contexto original de la petición

`source_context.py` conserva el texto que delimita las preguntas antes de enviarlas
a recuperación, lectura de fuentes y redacción. La identificación confirmada y
la pregunta atómica permanecen intactas.

La versión 2 del contexto incluye `document_context`, con extractos literales del
PDF original, página y líneas, método de extracción y aviso de revisión de OCR.
Son declaraciones del solicitante para entender el alcance de su consulta; no
son evidencia de que ocurriera un hecho ni instrucciones autorizadas para el
sistema. Los permisos siguen procediendo de `allowed_collection_ids`.

## Documentos pequeños y documentos largos

- Si el texto original cabe en 12.000 caracteres, se conserva completo. Esto evita
  perder una introducción cuando una referencia amplia de identificación la
  incluye junto con la primera pregunta.
- `question_ranges` identifica las preguntas por coordenadas y dueño. Las otras
  preguntas no añaden requisitos a la que se está respondiendo. Los requisitos
  verificables se construyen únicamente desde la pregunta atómica.
- Para documentos largos se conservan extractos fuera de las referencias
  verificadas de preguntas. Los límites de caracteres y cantidad de extractos
  quedan indicados mediante `truncated`, `original_fully_retained`,
  `selection_mode` y `omitted_ranges`.
- Se conservan líneas completas. Una línea que excede el presupuesto se omite y
  se señala, en lugar de presentar un texto cortado como cita íntegra de esa línea.
- Las referencias que no coinciden con las páginas originales no eliminan texto
  del contexto; quedan señaladas como alineación no verificada. Un expediente
  antiguo sin páginas mantiene su contexto de relaciones y declara explícitamente
  que el contexto original no está disponible.

## Recuperación y lectura

`retrieval_context` y `retrieval_queries` usan texto fuera de las referencias de
preguntas, además de relaciones explícitas entre solicitudes. Así no se convierten
automáticamente las preguntas hermanas en consultas de búsqueda. El buscador
recibe además el contexto original estructurado para contrastar ámbito e
identificadores explícitos. Ante referencias demasiado amplias, el texto de
búsqueda puede ser solo la pregunta atómica; el original pequeño sigue disponible
íntegro para el lector y la redacción.

Los límites de búsqueda —10.000 caracteres y hasta 12 consultas contextuales—
se declaran por separado con `retrieval_truncated`. No recortan los extractos
originales que recibe el lector. Ninguna limitación de contexto genera por sí
sola un estado de documento faltante, una fuente de respaldo ni un permiso.

## Regresión

`tests/test_original_petition_context.py` utiliza consultas inéditas de movilidad,
contratación temporal, archivos y préstamo bibliotecario. Comprueba condiciones
anteriores y posteriores a las preguntas, prefacios en otra página, referencias
amplias, límites, OCR, declaraciones no verificadas, texto de inyección, aislamiento
de permisos, contratos por pregunta y entrega intacta al lector y a la redacción.
`tests/test_source_context.py` conserva la cobertura de jerarquías y del servicio
HTTP/LangGraph existente.

Estos controles evitan pérdidas deterministas de contexto. No garantizan que un
modelo interprete correctamente cualquier documento; los controles de cobertura,
citas y revisión siguen siendo necesarios.
