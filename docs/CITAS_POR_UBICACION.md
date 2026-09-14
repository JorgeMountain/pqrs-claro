# Citas por ubicación y reintento de errores

El evaluador de fuentes recibe cada fragmento como `numbered_lines` y devuelve
`chunk_id`, `line_start` y `line_end`. Esas líneas empiezan en 1 dentro del fragmento;
no son las líneas de la página del PDF. El contrato remoto no admite `quote` ni
`declaration_quote`: Python obtiene ambos textos de las líneas originales, incluidos
sus espacios, Unicode y saltos de línea.

Se rechazan identificadores desconocidos, fragmentos no seleccionados como soporte,
rangos invertidos o fuera de límites, pasajes vacíos y textos que excedan los límites.
Un único intento de reparación permite corregir la selección. La validación posterior
de ámbito, roles y usos probatorios sigue activa. Una ubicación válida no certifica
la pertinencia, autenticidad o suficiencia de una fuente.

Los resultados conservan `citation_locations` y `analysis_diagnostic`: versión del
selector, cantidad de intentos, categoría del error y referencias a rangos o alias
fallidos. El diagnóstico excluye mensajes crudos del proveedor, credenciales y cuerpos
de documentos. Los intentos anteriores permanecen en `source_runs`. Los resultados
antiguos muestran su mensaje original; no se inventan detalles que no fueron guardados.

El recorrido ofrece «Reintentar las N solicitudes con error» cuando finaliza una
búsqueda vigente con errores. Envía `retry_failed_only: true` a `/preparation`.
El servidor determina los IDs fallidos, conserva literalmente los demás resultados
y abre una ejecución nueva para los fallidos. Registra `retry_of_run_id` y
`retry_request_ids`. No combina este modo con la actualización general
`retry_analysis`. Si cambiaron las solicitudes, fuentes, colecciones, comprobaciones
o configuración relevante, rechaza el reintento selectivo y solicita actualizar.

La revisión conserva textos y decisiones al sincronizar el análisis. Como antes,
el cambio de la huella global de fuentes invalida evaluaciones y aprobaciones que
dependían de esa huella; no se trasladan aprobaciones al nuevo conjunto automáticamente.

Se mantiene la versión 15 de las entradas del análisis: este cambio modifica la forma
de seleccionar citas, no el contrato probatorio del resultado guardado. El selector
tiene su propia versión (`passage_selection_version=1`). Esto permite recuperar solo
los errores de una ejecución anterior sin volver a evaluar resultados ya validados.

La validación se realiza con fuentes ficticias y dobles de IA en SQLite aislado.
Implementar o reiniciar el servicio no vuelve a ejecutar un expediente real:
el reintento se inicia con la acción de la interfaz.
