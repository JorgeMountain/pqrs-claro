# Mis expedientes

La vista `/?view=cases` reúne los expedientes en una lista con búsqueda por asunto,
nombre de archivo y número de caso. Incluye filtros de estado y entrada PDF/Gmail,
orden por fecha o asunto y páginas de diez resultados. Se abre desde el inicio
o desde «Mis expedientes» en el menú. En pantallas estrechas las filas se adaptan
a una disposición vertical.

«Solicitudes confirmadas» describe la identificación; no afirma que las respuestas
estén aprobadas. «En proceso» incorpora los trabajos activos de identificación,
fuentes, preparación, redacción, revisión, propuestas y generación de oficios.
«Actualizar» vuelve a consultar los estados.

## Eliminar y restaurar

El icono de papelera abre una confirmación con el asunto, archivo y número de
solicitudes del expediente. «Cancelar» no cambia nada. «Eliminar expediente» lo
mueve a la pestaña Papelera, donde se puede restaurar o eliminar definitivamente.

Se conservan originales, correos, fuentes, respuestas, aprobaciones y exportaciones.
Las fuentes compartidas de la biblioteca no se eliminan. Un expediente en la
papelera no puede abrirse, modificarse ni volver a importarse desde Gmail hasta
que se restaure o se elimine definitivamente. Los demás expedientes siguen disponibles.

### Eliminar definitivamente y repetir una prueba

En **Mis expedientes → Papelera**, pulsa **Eliminar definitivamente** en el
expediente elegido y confirma en el diálogo. Después abre Gmail, actualiza la
bandeja y vuelve a importar el mismo correo como una petición nueva. También
puedes volver a subir el PDF desde Nueva petición.

La eliminación definitiva borra el expediente, sus revisiones, análisis,
checkpoints, comprobaciones exclusivas, borradores, aprobaciones, editor guardado,
soportes exclusivos y archivos generados. No se puede restaurar desde la aplicación.
Conserva las fuentes compartidas y las comprobaciones que ya fueron aplicadas
explícitamente a otros expedientes, para no romper sus respaldos.

El correo original en Gmail y su copia local de recepción permanecen disponibles;
se libera el vínculo de todos los mensajes asociados al expediente. Cada nueva
importación recibe una identidad distinta y comienza sin análisis ni respuestas
anteriores. Los clics repetidos siguen creando un solo expediente.

Si un archivo está abierto o la limpieza se interrumpe, el expediente permanece
en la papelera y no puede restaurarse parcialmente. Cierra el archivo y pulsa
**Eliminar definitivamente** otra vez. El correo se libera solo cuando termina
la limpieza. No se elimina automáticamente ningún expediente al activar esta función.

No se permite eliminar/restaurar durante un trabajo activo del expediente. La
acción comprueba la versión de contenido y una revisión independiente del estado
de papelera; las operaciones concurrentes o una lista desactualizada reciben 409.
Si ocurre, pulsa «Actualizar» antes de intentarlo de nuevo.

## Persistencia y comprobación

`case_lifecycle` y `case_lifecycle_events`, en `expedientes.sqlite`, conservan el
estado y las fechas de eliminación/restauración. Se crean al iniciar sin reescribir
el contenido de los expedientes existentes. El cambio de papelera no incrementa
la versión de contenido, por lo que restaurar conserva las aprobaciones vigentes.

La API utiliza `GET /api/cases?deleted=true`, `DELETE /api/cases/{id}` y
`POST /api/cases/{id}/restore` y `DELETE /api/cases/{id}/permanent`.
Las mutaciones requieren `version`,
`lifecycle_revision` y `confirmed: true`, con la protección local de origen habitual.

Las pruebas `test_case_lifecycle.py` comprueban confirmación, origen, concurrencia,
trabajos activos, persistencia y restauración con originales, aprobaciones y
exportaciones intactas. `test_gmail.py` comprueba que reimportar no reactive un
expediente eliminado. La batería de ciclo de vida, Gmail y preparación pasó 56
pruebas; la batería inicial con aplicación y modo unificado pasó 52.

En Edge se probaron búsqueda, filtros, paginación, cancelación, eliminación y
restauración usando únicamente 14 expedientes ficticios en una carpeta temporal.
Se verificaron 320, 768, 1024 y 1440 px, sin desbordamiento horizontal ni errores
HTTP/JavaScript. Evidencia local excluida de Git: `output/qa/case-browser-20260919/`.

La interfaz está activa en 8772. Antes de reiniciar se comprobó que no hubiera
trabajos en curso y se respaldó la base de expedientes. Tras el reinicio se
compararon los 47 cuerpos de expediente: ninguno cambió y la papelera seguía
vacía. La verificación de navegador sobre datos reales fue de solo lectura;
también comprobó cancelar con Escape y devolver el foco al botón de origen.

El borrado definitivo se valida en `test_case_purge.py`: aislamiento frente a otros
expedientes, preservación de biblioteca y correo, eliminación de archivos y
checkpoints, concurrencia, versiones, origen, bloqueo durante trabajo activo,
recuperación de limpieza incompleta y reimportación idempotente desde PDF adjunto
o cuerpo del correo. La prueba real de navegador utiliza expedientes ficticios;
sus evidencias se guardan en `output/qa/case-purge-20260919/`.
