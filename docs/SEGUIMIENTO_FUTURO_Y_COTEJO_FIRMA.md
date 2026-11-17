# Seguimiento futuro y cotejo de firma

Una respuesta puede describir correctamente una decisión aún no publicada y no
registrar el seguimiento que el solicitante pidió. También puede mezclar el cotejo
de una firma ya existente con preparar una copia futura, volviendo no bloqueante
un control material de autenticidad. Se corrigen ambas rutas sin añadir otra etapa
de IA ni cambiar la búsqueda de fuentes.

## Seguimiento solicitado

`requested_followup.py` deriva una actuación no bloqueante de la misma cobertura
validada que usa el lector. Exige una petición explícita, el vínculo del inciso con
su cobertura, un anuncio todavía pendiente tanto en el claim como en la cita
literal, y una fuente actual, legible y autorizada. Conserva los IDs del inciso,
pasaje, archivo y versión. Una fecha futura aislada o explicar un procedimiento
no crea una tarea; tampoco se exige un documento que todavía no debe existir.

Se reutiliza el seguimiento ya registrado mediante vínculos exactos. Un control
resuelto conserva su resolución y no reaparece como supervisión genérica. No se
fusionan controles por semejanza textual ni por compartir archivo. Las variantes
de lenguaje que no reconoce esta guarda conservadora siguen en el lector y la
revisión normales: la regla no pretende sustituir la comprensión semántica.

## Firma existente y entrega futura

`evidence_contract.py` reconoce un cotejo material expresamente propuesto sobre
una firma existente, con un defecto o validación sin resolver. Lo conserva como
comprobación de evidencia. Cuando la misma descripción añade preparar o entregar
la copia solicitada, separa esa parte: la entrega permanece como actuación futura
no bloqueante. La descripción original y el fragmento separado quedan en los
datos de auditoría; no se afirma que se haya cotejado, certificado o entregado nada.

Una preparación futura expresamente declarada no se reclasifica como evidencia
por mencionar una condición de procedencia. Se conserva el control de procedencia
por separado. La entrega genérica inferida solo se evita cuando los vínculos
exactos de requisitos, gaps y actuaciones actuales ya representan la entrega.
Si el lector marcó el contenido como respondido y no vinculó el gap, se admite
únicamente el caso inequívoco de un requisito de entrega singular, una cobertura
documental literal y una actuación con esos mismos pasajes y versiones. No se
reescribe la suficiencia ni se interpreta `supported` como entrega realizada.
Una referencia distinta, una lista parcialmente representada o una versión vieja
no permite omitirla; los registros ya guardados y sus cierres no se borran.

La mera solicitud de copia, un nombre de firmante o la firma de una respuesta
futura no crean un cotejo material. Procedencia, competencia y vigencia conservan
su propósito y sus reglas de aplicabilidad. Una resolución humana se reutiliza
solo bajo los controles existentes de alcance, versión y permiso.

## Integración y compatibilidad

El registro único alimenta planificación, redacción y normalización de pendientes.
Lector, redactor y revisor comparten instrucciones para separar objetos de las
tareas, reutilizar controles y mantener completa la respuesta. Se invalidan los
resultados anteriores mediante versiones: análisis de fuentes 29, política del
lector 9, suficiencia 9, borrador 30/31 y revisión 25/26. Estas versiones incluyen
el ajuste posterior de alcance temporal. El piloto independiente de
procedimientos continúa desactivado. No se migran ni recalculan expedientes reales.

La evaluación detectó además falsas alertas locales de atribución e identidad.
`draft_claim_checks.py` reconoce reportes y previsiones documentales explícitas;
una mera mención del documento sigue sin bastar. `answer_coverage.py` puede
comprobar el artículo definido inmediatamente anterior al rango seleccionado por
el revisor si, y solo si, forma el nombre completo exacto del detalle citado.
No reescribe borradores ni rangos y no acepta autoridades parecidas o citas ajenas.

## Evaluación

Se usan tres expedientes ficticios nuevos, seis solicitudes y seis documentos de
apoyo: observatorio, museo y vivero. La rúbrica se guarda separada antes de llamar
a la API. Incluye dos seguimientos, firma manuscrita borrosa, validación de firma
digital pendiente, una consulta informativa y una copia simple sin esas exigencias.

La base de esta evaluación es el candidato anterior al presente ajuste, congelado
en `output/qa/trace-generalization-20261117/candidate`; no se presenta como una
comparación nueva contra master. Se compara primero el lector y después se ejecuta
Redacción del candidato reutilizando sus fuentes, sin repetir las búsquedas. La
evaluación no incluye extracción automática inicial de solicitudes ni OCR.

Los resultados y límites se registran en el informe de resultados correspondiente.
Las pruebas de software y una cita válida no sustituyen la revisión semántica de
las respuestas, de las actuaciones ni de los pendientes.

Pruebas locales del contrato:

```powershell
scripts/dev-python.ps1 -m pytest -q tests/test_requested_followup.py tests/test_followup_contract.py tests/test_signature_delivery_separation.py tests/test_evidence_contract.py tests/test_source_uncertainties.py tests/test_verification_reuse_service.py
```

El runner `scripts/check_request_trace_generalization.py` acepta
`--fixture-prefix followup_signature --source-only` para el lector y
`--draft-from-run <run-fuentes>` para reutilizar una lectura ya guardada. Las
llamadas reales requieren `--run-api`; `--max-calls` impone el límite explícito.
Cada variante utiliza otra carpeta y comprueba que el código importado coincide
con la copia congelada. No se sobrescriben resultados de ejecuciones previas.

`scripts/check_reader_contract_replay.py` reproduce respuestas capturadas por la
ruta normal del lector, con la red bloqueada y otro directorio de datos. Comprueba
igualdad de instrucciones, input y modelo; así se puede validar una corrección del
contrato local sin pagar otra lectura ni atribuirle una mejora del modelo.
