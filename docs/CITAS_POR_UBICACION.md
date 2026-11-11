# Citas por ubicación y reintento de errores

El evaluador de fuentes recibe cada fragmento con sus `numbered_lines`, pares
`[número, texto]` numerados desde 1 dentro del fragmento. Devuelve `chunk_id`,
`line_start` y `line_end`. Python obtiene la cita y su ubicación a partir de las
líneas originales, incluidos los espacios, Unicode y saltos de línea.

Cada candidato conserva su alias y sus roles permitidos. Cuando varios pasajes
de la misma fuente, versión y ámbito comparten metadatos, `shared_fields`
envía esos campos una sola vez e identifica los candidatos a los que aplican.
Los campos que varían y las líneas de cada cita se envían con su candidato.
El lector recibe la pregunta y su contexto. Las consultas auxiliares utilizadas
por el buscador se omiten únicamente si ese contexto permite reconstruirlas
exactamente. La reparación usa el mismo conjunto de candidatos.

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

El selector de pasajes tiene su propia versión (`passage_selection_version=1`).
El servicio registra también el modelo y la versión de la política del lector.
Cuando cambia el catálogo, vuelve a buscar en el ámbito autorizado. Puede
reutilizar la lectura terminada de la ejecución anterior de ese expediente si
coinciden la política, la solicitud con su contexto y la lista completa de
fragmentos en el mismo orden, incluidos su texto, versión, ubicación y metadatos.
Entonces aplica la auditoría del catálogo y las verificaciones humanas vigentes.
Actualizar el análisis de forma explícita vuelve a invocar al lector.

La validación se realiza con fuentes ficticias y dobles de IA en SQLite aislado.
Implementar o reiniciar el servicio no vuelve a ejecutar un expediente real:
el reintento se inicia con la acción de la interfaz.
