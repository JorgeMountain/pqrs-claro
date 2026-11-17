# Seguimiento de omisiones y reutilización de pendientes

La búsqueda puede recuperar un respaldo correcto y perder una parte al redactar.
Además, un control puede viajar repetido en las listas de faltantes, actuaciones
y comprobaciones. Este cambio conecta información ya existente y conserva una
vista única de los controles entregados al redactor.

## Cambio general

- `request_trace.py` deriva una traza por inciso a partir de los mismos requisitos,
  unidades, detalles y comprobaciones existentes. Conserva IDs de fuentes, unidades,
  párrafos y controles; no solicita otro inventario al modelo.
- Distingue `not_evaluated`, `retrieval_gap`, `evidence_not_used`, `pending` y
  `reviewed_answer`. El último significa que la revisión vinculó una respuesta;
  no acredita por sí mismo su corrección semántica. Una brecha de recuperación
  tampoco demuestra que un documento no exista.
- Cuando una omisión detectada tiene un destino inequívoco dentro del mismo inciso,
  se conecta con la reparación acotada existente. Una coincidencia de fuente entre
  incisos no permite elegir un destino.
- Una unidad obligatoria omitida completamente, con citas válidas y sin párrafo
  señalado, puede añadirse como un párrafo nuevo. La respuesta del modelo identifica
  la unidad; Python exige sus fuentes exactas y conserva todos los párrafos previos.
  La operación queda registrada en `repair.added_unit_ids`.
- La corrección sigue limitada a un intento, seguido por una comprobación completa.
  No modifica pendientes ni resoluciones. Un fallo o una nueva omisión permanece
  visible; no inicia un ciclo de intentos hasta aprobar.

## Registro de controles

`pending_registry` conserva controles abiertos y resueltos. Prioriza los registros
de `checks`, admite las vistas antiguas y conserva controles nuevos distintos.
`normalize_pending` deriva de ahí los abiertos. Una propuesta con
`existing_check_keys` reutiliza el registro: la paráfrasis no cambia su objeto,
alcance, etapa, versión o resolución. Una referencia desconocida se rechaza.

El contexto del planificador y redactor usa `existing_pending`, eliminando las
copias redundantes de `finding.missing`, `finding.actions` y `finding.checks`.
El comprobador recibe además `draft.pending` para contrastar el resultado concreto;
esa comparación se mantiene. La suficiencia, las incertidumbres y la trazabilidad
documental siguen disponibles y no se confunden con nuevas tareas.

No hay fusión por semejanza textual ni supresión de controles por compartir archivo.
Autenticidad de una firma, competencia del firmante y preparación de la entrega
pueden ser actuaciones diferentes. La reutilización documental sigue pasando por
los controles existentes de documento, versión, permiso y alcance.

## Conservación y límites

Se validan plan, cita literal y ámbito antes de reparar. El inventario inválido o
reemplazado no suministra unidades nuevas. Las unidades opcionales de contexto no
se convierten en obligaciones. Se mantiene el límite de veinte párrafos y los
controles que impiden guardar resultados obsoletos si cambian las entradas.

La reparación corresponde a la generación del borrador, no a una edición automática
del texto humano. Las comprobaciones de revisión y aprobación humana permanecen.
Borradores usan versiones 30/31 (habitual/piloto de procedimientos); revisión 25/26.
Incluyen las correcciones posteriores de seguimiento futuro, cotejo de firma y alcance temporal;
la evaluación inicial de versiones 26/27 y 21/22 permanece en su informe histórico.
El piloto independiente de procedimientos continúa desactivado.

Este seguimiento depende de los vínculos y omisiones detectados por la revisión
existente. No descubre por sí solo un detalle que tanto el inventario como la
revisión omitan. No se cambia el recuperador, el cupo de fragmentos ni el lector Fast.

## Evaluación reproducible

`tests/fixtures/request_trace_generalization_content.json` contiene tres PQRS
ficticias, seis solicitudes y cinco documentos de apoyo. La rúbrica separada tiene
24 criterios y se sella antes de ejecutar; no se envía al modelo. Se usan ámbitos
de archivo sonoro, préstamo de instrumentos y reservas de una huerta.

`scripts/check_request_trace_generalization.py` prepara PDFs y bases aisladas; solo
con `--run-api` ejecuta el proveedor. Compara una copia de `master` f633ba4 con una
copia del candidato, registra llamadas, fuentes, respuestas, citas, tiempos e
identidad del código. La identificación inicial está fijada y cotejada literalmente;
la prueba no evalúa extracción automática de solicitudes ni OCR de imágenes.

Las pruebas de omisiones introducidas deliberadamente se informan separadas de la
tasa de errores espontáneos de la IA. Los resultados de software, el estado
`passed` y las citas válidas no sustituyen la evaluación semántica de la rúbrica.
Los tiempos de las ejecuciones solapadas son descriptivos, no una demostración
de aceleración. No se modifican expedientes de la instalación.

Comandos locales (PowerShell):

```powershell
scripts/dev-python.ps1 -m pytest -q tests/test_request_trace.py tests/test_draft_omission_trace.py tests/test_request_trace_generalization.py tests/test_evidence_contract.py
scripts/dev-python.ps1 scripts/check_request_trace_generalization.py --code-root <copia-congelada> --variant <nombre-nuevo> --run-api
```
