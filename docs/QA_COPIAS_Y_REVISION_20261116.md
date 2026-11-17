# Copias normativas, intención y revisión final

La corrección aplica a peticiones nuevas de cualquier expediente. No usa IDs,
nombres de personas ni números de resolución de la prueba original para decidir
roles, pendientes o cobertura.

## Comportamiento

- Preguntar qué documentos debe entregar un interesado describe un procedimiento;
  no ordena que el destinatario de la PQRS entregue esos archivos. Enumerar,
  describir, detallar y listar se conservan como consultas informativas.
- Las negaciones explícitas no crean tareas de entrega. Una petición compuesta
  mantiene la consulta y la entrega cuando ambas se piden. El documento solicitado
  se identifica dentro del mandato de entrega, sin tomar otra norma mencionada
  en la consulta previa.
- Una norma puede tener rol `document` cuando se solicita una copia de ese
  original. Se conservan los controles de ámbito y permisos, identidad documental,
  versión actual, hash, número y año indicados y encabezado literal. Cuando no hay
  número, se coteja el tema del documento. Los controles legítimos de procedencia,
  transcripción y aplicabilidad permanecen independientes.
- El encabezado puede comenzar por el tipo documental o por un membrete corto en
  mayúsculas separado por raya, barra vertical o dos puntos. Esta segunda opción
  solo se admite en las líneas iniciales de la primera página. Remisiones, adjuntos,
  referencias y menciones no se convierten en originales por esa opción.
- El inventario consulta título y nombre de archivo. Encontrar un candidato con
  nombre genérico, como `norma.txt`, no equivale a autenticarlo; impide pedir otra
  copia por una ausencia que el inventario no acredita.
- Localizar una norma no demuestra envío, entrega, hechos ni estado oficial del
  expediente. La entrega continúa como actuación futura abierta, sin bloquear por
  sí misma la preparación del contenido.

## Revisión después de guardar

La revisión final usa el texto guardado y requiere un registro por cada inciso de
`request_requirements`. Cada registro señala párrafos que responden, un pendiente
específico o una omisión. Se conserva en la evaluación, el checkpoint de aprobación
y el snapshot aprobado. Una evaluación anterior del lector no demuestra que un
texto editado siga respondiendo todos los incisos.

El grafo impide llegar a aprobación si falta el checklist o registra omisiones,
aunque un proveedor responda `passed`. El guardado de cambios invalida la evaluación
y la aprobación anteriores. `REVIEW_VERSION=8` invalida comprobaciones de la política
anterior mediante la huella; no sobrescribe el texto humano. Se mantiene la
aprobación explícita y la comprobación actual de fuentes y permisos.

## Pruebas locales reproducibles

```powershell
.\scripts\dev-python.ps1 -m pytest tests/test_normative_document_requests.py tests/test_request_intent.py tests/test_document_retrieval.py tests/test_source_analysis.py tests/test_historical_analysis.py -q
.\scripts\dev-python.ps1 -m pytest tests/test_rag_review_requirements.py tests/test_review_engine.py tests/test_review_service_api.py -q
```

Los casos sintéticos incluyen vivienda, movilidad, salud, comercio, contratación,
matrícula y trámites administrativos. Cubren número/año/autoridad distintos,
metadatos incompletos, documento reemplazado, bytes alterados, permiso retirado,
consulta y copia coordinadas, negaciones, encabezados con membrete, remisiones,
checklist ausente, omisión explícita, guardado/relectura, cambio de política,
reinicio del checkpoint y aprobación recuperable.

Estas pruebas usan archivos temporales y proveedores simulados; no realizan
llamadas API ni modifican expedientes vivos. Verifican reglas y persistencia, no
garantizan por sí solas que una IA interprete correctamente toda consulta futura.
La evaluación semántica con API y los resultados del corpus original y de
expedientes nuevos se documentan por separado.
