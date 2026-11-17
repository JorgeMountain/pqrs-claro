# Unidades de respuesta en la revisión del texto guardado

Fecha: 16 de noviembre de 2026. Pruebas aisladas, sin llamadas a la API en esta
validación y sin modificar expedientes vivos.

## Problema y contrato

La cobertura por inciso no demuestra que el texto conserve cada condición,
excepción, paso o fundamento pertinente de un respaldo. La revisión recibe ahora
`coverage_units` del plan del borrador y debe comprobar sus unidades obligatorias
contra los párrafos **actualmente guardados**. El mismo control se ejecuta en el
grafo antes de ofrecer o registrar una aprobación, aunque el proveedor devuelva
`passed`.

Las unidades conservan el inciso, su alcance, motivo y citas literales verificadas.
Los `unit_checks` enlazan la unidad con los párrafos o con una brecha específica
abierta. Un control cerrado o `metadata_only` no sustituye contenido omitido. El
contexto opcional no crea una obligación narrativa ni un pendiente nuevo. Una
exclusión `out_of_scope` necesita una explicación semántica pertinente; Python
valida su estructura, no certifica que esa interpretación sea correcta.

La revisión no reescribe el texto. Si una unidad obligatoria falta, informa
`answer_unit_omitted`. Sólo los errores estructurales del checklist permiten el
único reintento ya existente: mismo texto, mismas fuentes, errores y evaluación
anterior. Una omisión semántica no provoca un reintento para hacerla desaparecer.

## Edición, cambios de fuentes y permisos

- El guardado humano mantiene el inventario y retira la evaluación/aprobación
  anterior; después se vuelve a comprobar el contenido realmente guardado.
- El hash de entrada, la pausa de aprobación y su fotografía inmutable incluyen
  el inventario y sus comprobaciones. La política de revisión pasa a versión 9.
- Al cambiar las fuentes, un inventario existente queda invalidado (`None`); no
  se mantienen sus citas como actuales ni se borra el texto humano.
- Si no hay un plan nuevo al sincronizar, la próxima comprobación reconstruye
  **sólo el plan**, con los soportes autorizados actuales. Guarda las unidades
  antes de evaluar el texto. Esta recuperación añade una llamada de planificación
  en ese caso; la revisión normal de un inventario vigente no necesita esa llamada.
- Antes de guardar el resultado se cotejan revisión, intento, huella y fuentes.
  Si el usuario editó o la fuente cambió durante la planificación, se descarta su
  resultado. Un fallo conserva el texto y los pendientes para reintentar.
- Las resoluciones humanas conservan su atribución y alcance. Los estados
  históricos de búsqueda no las reabren; tampoco se resuelve un control por haber
  generado unidades nuevas.
- Al retirar acceso se ocultan tanto los soportes como los datos derivados del
  inventario, incluidos los expuestos por el historial.
- Los proveedores de prueba o antiguos que nunca tuvieron inventario mantienen
  compatibilidad. Si ya existía y quedó invalidado, un proveedor incapaz de
  reconstruirlo bloquea explícitamente la comprobación; no lo convierte en lista
  vacía ni permite aprobar.

Los controles legítimos de vigencia/procedencia, conflicto, transcripción y
entrega posterior permanecen separados del contenido. Completar el inventario
no los cierra ni permite afirmar que una copia ya fue entregada.

## Validación

`tests/test_review_answer_coverage.py`: **26 pruebas aprobadas**. Incluyen citas
no literales/fuera del inventario, aliases, checklist ausente u omitido, reintento
estructural, contexto opcional, hash y fotografía aprobada, edición después de
aprobar, invalidación y recuperación del plan, controles legítimos, resoluciones
históricas, concurrencia de edición/cambio de fuente y revocación en historial.

También pasaron 126 pruebas previas de motor/grafo/servicio/checklist y una tanda
de 51 pruebas de unidades, suficiencia, contexto de citas y carga de Redacción.
Estas tandas se solapan: sus cantidades no deben sumarse. Ruff no encontró
incidencias en los archivos modificados. Pytest conserva una advertencia de
deprecación de `starlette.testclient`/`anyio`, ajena a esta modificación.

Estas pruebas usan dobles explícitos del proveedor: demuestran persistencia,
contratos y bloqueos, no la capacidad semántica del modelo. La eficacia para
detectar omisiones nuevas, falsos pendientes y el coste/tiempo de las unidades
debe evaluarse por separado con preguntas y documentos nuevos. Tampoco corrige
por sí sola evidencia que el recuperador no haya seleccionado.
