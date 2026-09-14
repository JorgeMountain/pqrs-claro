# Preparación automática en 8772

El recorrido conserva su diseño. En el espacio de trabajo, **Cargar petición** guarda un PDF y comienza la identificación; **Mis expedientes** abre casos existentes. Se pueden revisar las tarjetas, consultar el original con resaltado y corregir título o descripción antes de confirmar.

**Confirmar solicitudes** confirma la versión revisada e inicia en el servidor la búsqueda de fuentes, la redacción y el guardado para revisión. No hace falta un segundo clic en «Preparar las respuestas». Se consultan las fuentes elegibles del expediente: sus soportes, normas compartidas y colecciones vinculadas. «Fuentes de consulta» permite ajustar esas colecciones; no otorga acceso automático a antecedentes privados de otros casos.

Las tarjetas muestran los resultados reales guardados y sus pasajes. Volver a abrir el caso o recargar únicamente consulta el avance. La etapa se conserva en la URL. Un doble envío de la confirmación reutiliza el mismo trabajo. El servicio continúa si se cierra la pestaña mientras el servidor permanece activo.

Si se interrumpe el servidor, el trabajo queda marcado como interrumpido y ofrece continuar, sin consumir IA automáticamente al abrir la página. Los errores conservan la identificación confirmada. Una nueva fuente obliga a actualizar el respaldo; las redacciones ya guardadas para revisión se conservan y las evaluaciones o aprobaciones afectadas se invalidan mediante el servicio de revisión existente.

## Implementación

- `preparation.py` coordina los servicios existentes, que ejecutan los grafos de fuentes y borradores. Persiste el estado en la tabla `preparations` de `data/expedientes.sqlite`.
- `POST /api/cases/{id}/confirm-and-prepare` recibe la versión revisada. La ruta anterior `/confirm` mantiene su comportamiento y no inicia trabajos adicionales.
- `GET /api/cases/{id}/preparation` es solo lectura; `POST` con versión permite continuar o actualizar explícitamente.
- El navegador muestra progreso sin sostener el trabajo. 8772 utiliza el backend de 8770; no crea otra base de expedientes.

## Validación y alcance

Las pruebas de integración cubren confirmación repetida, ausencia de aprobación automática, lecturas sin regeneración, recuperación tras falta de fuentes, conservación de redacción humana, interrupción y compatibilidad de la confirmación anterior. Se ejecutan con servicios, persistencia y grafos reales y proveedores de IA dobles.

En navegador, sobre datos ficticios aislados, se cargó un PDF, corrigió una solicitud, confirmó e inició la preparación sin otro botón, consultaron fuentes y recuperaron respuestas al recargar. Esto valida la orquestación y la interfaz; no constituye una nueva evaluación de calidad con OpenAI ni modifica expedientes reales.

La demo original sigue separada y conserva sus acciones de ejemplo. Para expedientes reales, el recorrido permite preparar, editar, comprobar y aprobar respuestas, y generar el oficio en la tercera etapa. Los servicios existentes se reutilizan; no se aprueban documentos automáticamente.

## Edición real desde las tarjetas

«Editar respuesta» abre el panel con los párrafos guardados. Permite modificar texto, agregar o quitar párrafos y registrar el nombre de quien edita. Se utiliza la ruta existente de revisión con control de versión. Las citas y la función de cada párrafo conservado permanecen asociadas; los párrafos nuevos no reciben soportes inventados. Los pendientes no se resuelven al guardar texto.

Guardar actualiza la tarjeta y persiste la revisión; una modificación invalida evaluación y aprobación anteriores. Cancelar no escribe. Cerrar el panel conserva temporalmente el texto local mientras siga abierta la página. Una colisión de versiones mantiene el texto local y ofrece cargar explícitamente la versión guardada, sin sobrescribirla. El nombre registrado es atribución declarada, no autenticación.

Se verificaron guardado, recarga, cancelación, párrafos y conflicto entre dos pestañas en un caso ficticio aislado. Pasaron seis pruebas del servicio de revisión sobre invalidación, concurrencia y conservación de cambios con fuentes desactualizadas. No se ejecutó IA ni se modificaron respuestas de expedientes reales para esta comprobación.

## Decisiones por pendiente

Las tarjetas muestran los pendientes abiertos, las actuaciones posteriores y las decisiones registradas. «Confirmar con respaldo» permite seleccionar un pasaje o un aporte atribuido, explicar su aplicación y registrar el responsable. «No aplica este pendiente» registra un motivo sobre ese punto; no elimina un antecedente ni acredita automáticamente suficiencia de la respuesta. «Reabrir» conserva la decisión anterior en el historial.

«Aportar información comprobada» utiliza el registro de hechos de la revisión: texto, fundamento, fecha y autor declarado. Un pendiente documental requiere fuente documental, no solo un aporte personal. «Agregar evidencia» utiliza la carga y actualización de búsqueda existentes. Las actuaciones de ejecución posterior se muestran separadas del respaldo.

Se conservan los párrafos y pendientes de otras preguntas; una decisión invalida la evaluación/aprobación de la versión anterior. Si las fuentes cambiaron, se permite seguir editando texto o reabrir, pero una nueva decisión sobre respaldo requiere actualizar la preparación. Las decisiones quedan en el expediente y su historial; esta conexión no las publica como comprobaciones reutilizables en otros expedientes.

Registrar una decisión conserva el texto que ya exista. Si la solicitud todavía no tiene borrador, resolver sus puntos necesarios inicia su primera redacción automáticamente, como se describe a continuación. Para respuestas existentes, la actualización propuesta por IA permite revisar el cambio antes de aplicarlo.

## Revisión previa y redacción en paralelo

### Confirmaciones documentales y fallos de cita

Los pendientes de estado documental muestran «Es la versión expedida» y «Es un documento de trabajo». El panel identifica el archivo y su versión, permite abrir el original y pide el nombre de quien confirma. El servidor fija la explicación y el vínculo al archivo; no exige otro adjunto ni una explicación libre. «No lo sé / Volver» no registra una decisión. Un archivo identificado como borrador no puede declararse expedido mediante este atajo: debe incorporarse la versión correspondiente.

La procedencia puede confirmarse con «Ya revisé este archivo», con el mismo registro de atribución. Estas decisiones pertenecen a la revisión del expediente; no cambian silenciosamente el catálogo global ni se trasladan a archivos distintos por compartir número de oficio. No certifican todos los hechos o anexos ni aprueban el oficio final. Si ya había texto, se conserva y queda pendiente de revisión.

La IA tiene un reintento para corregir la cita de una comprobación declarada por un antecedente. Si esa declaración opcional sigue sin poder vincularse literalmente, se omite y aparece un detalle del análisis, conservando los pasajes válidos y las brechas de contenido. Los errores de lectura reales continúan siendo errores: no se pueden cerrar con «Confirmar» o «No aplica». «Reintentar análisis» inicia una nueva evaluación explícita, sin reutilizar el resultado fallido.

Una brecha de contenido no vuelve a exigir el estado documental de afirmaciones ya cubiertas como contenido atribuido. Las fuentes sin cobertura y los usos que exigen autenticidad, expedición o entrega conservan sus controles. Los pasajes explícitos fijan el archivo de una comprobación; el número de oficio por sí solo no fusiona las versiones.

Al terminar la búsqueda se crean los puntos de revisión antes de redactar. Cada solicitud sin borrador avanza cuando sus pendientes necesarios están resueltos; las actuaciones posteriores que no bloquean no impiden redactar. Las solicitudes listas se procesan con hasta tres trabajadores simultáneos, cada uno con su recorrido LangGraph de planificación, redacción y comprobación.

Las decisiones incorporan su nota, atribución y pasajes disponibles al contexto de IA. Una decisión de no aplicabilidad no acredita por sí misma un hecho. En esta revisión previa, confirmar un pendiente requiere un pasaje disponible; un pendiente documental requiere soporte documental. Las decisiones no equivalen a aprobar la respuesta final.

Guardar una decisión programa la continuación en el servidor, incluso si se cierra la pestaña. Si cambia una decisión durante la generación o antes de incorporar el resultado, el borrador anterior no se adopta. Los textos existentes y las ediciones humanas se conservan. Durante una búsqueda incompleta se pueden consultar los puntos detectados; las decisiones se habilitan al terminar la búsqueda.

Validación: ocho regresiones específicas cubren concurrencia máxima de tres, avance independiente, contexto humano, reapertura durante y después de generar, errores de fuentes aislados, respaldo documental y límite de candidatos. El recorrido de confirmación y redacción automática se comprobó en navegador con un motor simulado y un expediente aislado. Esto verifica la integración, no una nueva comparación de calidad con IA real.


## Propuestas de actualización con IA

«Actualizar con IA» abre una comparación para la respuesta seleccionada. «Generar propuesta con IA» utiliza el texto guardado, sus fuentes, aportes y decisiones; un grafo de LangGraph propone el ajuste y después comprueba sus soportes. Las observaciones se muestran junto al texto. No se exige aceptarlo: «Mantener mi texto y descartar propuesta» conserva la respuesta.

«Aplicar propuesta» registra quién aplica el cambio, guarda una nueva revisión y conserva aportes y decisiones. No aprueba la respuesta. Si cambia el texto, una decisión o las fuentes durante la generación o antes de aplicar, la propuesta anterior no puede sobrescribir la nueva versión.

Las propuestas y su estado se guardan en `response_proposals`, en `data/revisiones.sqlite`. Cerrar y volver consulta el resultado sin iniciar otra llamada de IA. Tras interrumpirse el servidor se puede solicitar otro intento explícitamente. La identidad del responsable es declarada, no autenticada.

La validación incluyó 11 pruebas de integración, comparación/descarte/aplicación y recarga en navegador sobre un expediente ficticio. Una prueba adicional real con OpenAI generó una propuesta con referencias válidas y detectó límites del soporte ficticio: la inclusión de un anexo no acreditaba que fuese el acta solicitada. Esto valida la conexión con el proveedor, no la suficiencia documental de un caso real. No se modificaron respuestas de expedientes reales.


## Revisión final y archivos en el recorrido

«Revisar el oficio» muestra la redacción guardada y las observaciones por solicitud. «Comprobar respuesta» invoca la revisión existente; abrir o recargar solo consulta el estado. «Revisar y aprobar» presenta el texto completo y requiere nombre y confirmación explícita. El servidor verifica la revisión y la huella evaluadas; una comprobación de una propuesta no sustituye la evaluación de la versión guardada.

Después de aprobar todas las respuestas se habilita el formulario del oficio. Se reutilizan `office.js` y los servicios de generación mediante `/shared/` y el proxy de 8772. El membrete activo, los campos confirmados y los anexos seleccionados se conservan. Los nombres de quien aprueba, prepara y suscribe se registran por separado. No se incorporan firmas ni se envía el documento.

El usuario prepara la vista previa, genera Word/PDF y descarga los archivos o el paquete con anexos. El exportador no llama a IA ni agrega referencias técnicas al texto final. Las ediciones locales deben guardarse o descartarse antes de aprobar, generar o descargar. Una edición guardada invalida la aprobación y la vigencia de los archivos anteriores; el servidor comprueba esa vigencia también al descargar.

Validación: 54 pruebas aprobadas entre el servicio de oficios, salida limpia, biblioteca y proxy. Prueba de navegador aislada con evaluación simulada, aprobación explícita y conversión real mediante Microsoft Word COM: DOCX/PDF de una página, dos párrafos conservados, vista de PDF y descarga. Esta prueba comprueba integración y fidelidad, no suficiencia académica de los textos ficticios. Evidencias en `output/qa/final-office-20260911`.


## Página de inicio y carga

La entrada de 8772 muestra «Prepara respuestas con respaldo», una zona central para seleccionar o arrastrar el PDF y accesos a «Mis expedientes» y «Ver demostración». «Cargar petición» en el menú izquierdo vuelve a esta página; no abre una ventana modal. Las etapas aparecen al abrir un expediente o la demostración. La selección permite revisar nombre y tamaño, retirar el archivo y confirmar «Cargar y analizar». El servicio de identificación y los límites del servidor se conservan.
