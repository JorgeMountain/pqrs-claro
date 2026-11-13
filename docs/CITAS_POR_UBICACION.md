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

### Al desvincular una colección

Cada consulta del mapa de fuentes comprueba los permisos actuales del expediente,
incluidos los sondeos de una búsqueda en curso. Al retirar una colección utilizada
como ámbito de una búsqueda anterior, el mapa deja de entregar sus resultados
antes de la siguiente búsqueda. Se oculta el análisis anterior completo porque sus
resúmenes, citas y pendientes pueden combinar varias fuentes. El expediente
conserva los originales y el registro de la búsqueda para auditoría.

Al guardar el cambio, la pantalla cierra el detalle de la fuente retirada y
descarta las respuestas pendientes que correspondían al permiso anterior. Las
pestañas del mismo origen reciben el aviso para actualizar su vista del
expediente. Este aviso solo identifica el expediente. En la prueba con las
dos interfaces abiertas, retirar el permiso desde cualquiera de ellas quitó la
cita de ambas sin iniciar otra búsqueda.

Una ventana visible en otro perfil también consulta los vínculos de su
expediente al recuperar el foco y cada cinco segundos. En Redacción, este
sondeo también permite detectar correcciones de las fuentes. En cada interfaz
se verificó en Chrome que una retirada por API hiciera desaparecer la cita y
su pendiente, incluso sin recibir el aviso entre pestañas.

Al actualizar las fuentes, el lector vuelve a evaluar los documentos autorizados.
El mapa puede volver a mostrar los respaldos que siguen vigentes e indicar qué
dato quedó pendiente al perder su fuente.

La revisión conserva en el historial el texto humano de cada versión. Antes de
sincronizar, el expediente oculta los párrafos que citaban la colección retirada.
Después de sincronizar, el editor permite guardar la respuesta con los pasajes
autorizados. Las lecturas del historial también respetan los permisos actuales.

La validación se realiza con fuentes ficticias y dobles de IA en SQLite aislado.
Implementar o reiniciar el servicio no vuelve a ejecutar un expediente real:
el reintento se inicia con la acción de la interfaz.

### Al retomar una petición en Redacción

Al elegir **Ver fuentes**, Redacción recuerda en ese navegador el expediente,
su versión y la petición seleccionada. Al volver desde la bandeja o abrir un
enlace a esa petición, comprueba que sigue vigente y carga primero su cita,
el enlace al original y sus pendientes. Las demás respuestas se cargan a
continuación. Para confirmar la revisión conjunta, el gestor debe esperar
a que estén guardadas todas las respuestas actuales.

La primera apertura sigue el flujo habitual. Si la selección guardada caducó
o la petición desapareció, se abre la vista general. Si el gestor cambia de
petición durante la carga, la pantalla descarta la respuesta que llegue para
la selección anterior.

### Al corregir una fuente con Redacción abierta

El gestor puede mantener abierta la petición que está revisando. Cuando
Redacción detecta una corrección registrada en la biblioteca entre las fuentes
que el expediente puede consultar, muestra un aviso y retira los pasajes,
enlaces al original y pendientes anteriores. La detección aprovecha el sondeo
cada cinco segundos de la pestaña visible. Una pestaña que estaba en segundo
plano comprueba el estado al volver a ella. Una fuente exclusiva de otro
expediente queda fuera de esa comprobación.

Desde el aviso, el gestor puede pulsar **Recalcular preparación**. También
puede iniciar el recálculo otro cliente. Cuando termina y la revisión está
vigente, la misma pantalla muestra juntos los pasajes, enlaces al original y
pendientes actualizados de la petición seleccionada. Ante un fallo temporal
al leer la revisión, la pantalla mantiene ocultos los resultados anteriores
y vuelve a consultar. El gestor sigue siendo quien revisa y confirma las
respuestas.

### Pruebas con expedientes ficticios

En Chrome se compararon ocho reaperturas por tamaño con la versión
`77aef1c`. La cita y el pendiente de la petición elegida aparecieron antes
en 22 de 24 pares. El ahorro mediano por par fue de 143, 137 y 332 ms en
expedientes de 2, 10 y 25 peticiones. En un control donde ambas versiones
recordaban la selección, priorizar el detalle aportó 50, 29 y 245 ms,
respectivamente. Estas medidas llegan hasta la aparición de ambos elementos
en pantalla. La descarga completa terminó algo después en ese control.

En la prueba de corrección, dos pestañas retiraron la cita y el pendiente
anteriores entre 0,72 y 3,65 s después de guardar la fuente. Al pulsar
**Recalcular preparación**, ambas mostraron la nueva versión entre 2,39 y
4,92 s. Se comprobó el contenido del original enlazado, el recálculo desde
otro cliente y la retirada de un permiso. El ensayo usó una biblioteca
temporal y un lector simulado. Los tiempos son locales.

Con Playwright y Google Chrome instalados, se puede repetir la comprobación
desde la raíz del repositorio. Abre la segunda petición de un expediente
ficticio, la retoma, registra una nueva versión de la fuente y comprueba en
la misma pestaña el aviso, la cita, el enlace al original y el nuevo pendiente.

```powershell
.\scripts\test.ps1 tests/check_redaction_browser.py
```
