# Propuesta de recorrido: de siete etapas visibles a tres

Fecha: 10 de septiembre de 2026. Estado: maqueta interactiva aislada, pendiente de integración.

## Resultado revisable

Abrir http://127.0.0.1:8772/. Archivos: `output/ux-peticiones-20260910/`.
La maqueta utiliza un snapshot de las tres solicitudes, seis párrafos aprobados y pasajes citados de la validación `natural-demo-complete-20260910`. Copia solamente los originales utilizados y los archivos finales de esa demo. No consulta IA, escribe bases de datos ni registra aprobaciones institucionales. Las ediciones viven en memoria del navegador y desaparecen al recargar.

1. **Entender la petición.** Conservar la identificación actual, su edición y confirmación cuando se integre. La maqueta parte de una identificación ya confirmada y permite cotejar los numerales con la petición original.
2. **Preparar las respuestas.** Una acción coordina búsqueda, evaluación de alcance, redacción y revisión automática. Cada tarjeta reúne texto propuesto, fuentes, pendientes y edición. La biblioteca es secundaria. El detalle técnico no se convierte en una etapa de navegación obligatoria.
3. **Revisar el oficio.** Leer el documento completo, volver a una respuesta cuando haga falta, revisar y aprobar con identidad y alcance explícitos; exportar exactamente esa versión aprobada.

## Contrato para integrar con LangGraph

- Mantener los servicios y controles existentes. La simplificación de navegación no elimina las comprobaciones ni cambia los criterios de suficiencia.
- Crear un coordinador del recorrido que observe los resultados persistidos y continúe desde el primer resultado ausente o invalidado. Reutilizar las versiones y fingerprints existentes; no repetir ejecuciones completas ante cambios de pantalla.
- Exponer progreso por pregunta y reintento de la pregunta afectada. Evitar peticiones duplicadas por doble clic; conservar avance tras recargar o cerrar el equipo.
- En una misma tarjeta, respaldo encontrado puede coexistir con confirmación pendiente, archivo faltante o un fallo parcial de análisis. Cada pendiente debe señalar el alcance y una acción concreta.
- Los pasajes se abren en un panel con documento/versión, ubicación y original. Evitar confundir secciones de DOCX con páginas de PDF.
- Editar texto, soportes o aportes invalida la evaluación y aprobación aplicables. La interfaz debe comunicarlo en esa respuesta, sin descartar los resultados de las demás.
- Resolver un pendiente registra explicación, actor, documentos y alcance por pregunta mediante los servicios reales. El historial y las comprobaciones reutilizables siguen disponibles bajo demanda.
- La aprobación final debe corresponder al snapshot vigente de cada respuesta. El oficio y sus descargas deben corresponder a ese mismo contenido, verificados por el servicio de exportación.
- Un fallo de análisis no se trata como ausencia del documento. Documento faltante requiere búsqueda suficientemente acotada al documento solicitado.

## Qué permite probar la maqueta

- Navegar los tres momentos; reproducir visualmente la preparación con datos guardados.
- Leer respuestas, abrir pasajes y originales, buscar entre las fuentes utilizadas.
- Editar una respuesta y observar la invalidación de su revisión; restaurar el texto validado.
- Simular respaldo con confirmación pendiente, fallo de análisis con reintento local y falta de un documento concreto.
- Leer el oficio con ediciones temporales y probar la confirmación de revisión. Esta confirmación no se registra en el sistema.
- Descargar el Word/PDF de la validación anterior, identificados expresamente como archivos que no incorporan las ediciones de la maqueta. La vista HTML ilustra el armado propuesto; no se presenta como reproducción literal de esos archivos.

La carga de nuevos archivos y la evaluación real de ediciones todavía no están conectadas. El escenario de documento faltante explica dónde se aportaría el documento y mantiene el pendiente abierto.

## Orden siguiente de implementación

1. Consolidar navegación y tarjetas de respuesta usando las APIs actuales, inicialmente contra la copia aislada.
2. Incorporar coordinación y reanudación del procesamiento con progreso por pregunta, cancelación y reintentos sin duplicados.
3. Integrar resolución de pendientes y edición con invalidación y trazabilidad existentes.
4. Unificar la revisión final y las descargas de la versión realmente aprobada.
5. Validar el recorrido completo en copia aislada: demo, pendiente real, error de lectura, edición, reapertura y oficio. Después actualizar el servidor principal.

## Verificación de esta maqueta

Revisión en el navegador: navegación, panel de fuentes y originales, coexistencia de respaldo y pendiente, resolución simulada con motivo, edición reflejada en el oficio y aprobación deshabilitada, restauración, búsqueda sin coincidencias, documento faltante y reintento conservando las tres tarjetas.
Anchos revisados: 320, 768, 1024 y 1440 px, sin desbordamiento horizontal del documento. La biblioteca y el reinicio permanecen accesibles en móvil. Consola sin avisos ni errores durante las pruebas observadas.

No se modificaron en este trabajo los módulos de producción ni los expedientes. Esta verificación no equivale a validar la futura integración con los servicios reales.

## Ajuste solicitado: documento original y origen de cada solicitud

La primera etapa incorpora la página original y el botón **Ver de dónde salió** en cada solicitud. Al seleccionarlo, la tarjeta queda marcada y el visor se desplaza al pasaje, resaltando sus líneas directamente sobre la imagen del PDF. El texto de origen también queda disponible debajo, con regreso a la tarjeta y opción de quitar el resaltado. En escritorio amplio, preguntas y original aparecen juntos; en pantallas pequeñas el visor aparece después de las tarjetas y se enfoca al consultar el origen.

`prepare_original.py` renderiza el PDF sin modificarlo y obtiene las coordenadas buscando literalmente los fragmentos ya confirmados. Comprueba que el texto de cada conjunto de rectángulos coincide con la cita completa; falla si no puede localizarla con exactitud. Las tres solicitudes tienen respectivamente 3, 3 y 4 rectángulos. No se alteró el PDF fuente (hash conservado).

Comprobado en navegador: selección de los tres numerales, movimiento al pasaje, texto de origen, regreso del foco a la tarjeta, eliminación de marcas y continuidad hacia las respuestas. Revisada la adaptación a 320, 768 y 1440 px sin desbordamiento horizontal. La integración posterior debe conservar esta vinculación con las páginas y referencias vigentes de cada expediente real.

## Ajuste solicitado: encabezado conservado, barra plegable y tarjetas compactas

Se conserva el encabezado institucional completo: logo, divisor, nombre, subtítulo y estado de demostración a la derecha. El control del menú queda debajo del encabezado, en el borde superior derecho de la barra lateral. Es una barra plegable integrada a la distribución, no un diálogo que cubra el encabezado. Cuando se pliega, queda una franja estrecha con el mismo botón; al abrirla reaparecen la petición, biblioteca y reinicio. Escape permite plegarla desde sus controles.

En escritorio, abrir o plegar redistribuye el contenido sin mover ni cambiar el tamaño del encabezado. El documento va a la derecha de las solicitudes cuando el área de trabajo dispone de más de 720 px; el ajuste usa el ancho disponible del contenido, no solamente el de la ventana. En móvil, el panel se despliega por debajo del encabezado y se cierra al elegir una acción.

Las tarjetas de solicitudes usan títulos de 16 px, cuerpo de 14 px, interlineado 1,5, margen interior de 16–18 px y separación de 12 px. Se conservan el texto completo y el acceso al origen. La vista de respuestas conserva su presentación previa.

Verificado en navegador a 320, 768, 1024 y 1440 px: sin desbordamiento horizontal, documento a la derecha cuando hay espacio suficiente, encabezado con idéntica altura y posición del logo al plegar, acceso al menú y tres rectángulos de resaltado para el numeral 2.

## Ajuste de jerarquía: las solicitudes como contenido principal

La identificación usa aproximadamente 60 % del ancho para solicitudes y 40 % para el original. Se redujeron el encabezado de sección, los espacios interiores de las tarjetas y los controles del visor. Los títulos de las solicitudes conservan 16 px y el cuerpo 14 px; el contenido no se recorta. El visor limita su altura a 440 px o 50 vh y mantiene el desplazamiento, apertura del PDF y resaltado. En una ventana de 1440 px con menú plegado, las tarjetas miden aproximadamente 132, 132 y 173 px de alto. Comprobados los cuatro rectángulos del numeral 3, consola sin errores y ausencia de desbordamiento a 320, 768 y 1024 px.


## Separador ajustable entre solicitudes y documento

Se incorpora un separador vertical con asa central para arrastrar y repartir el ancho. Flechas izquierda/derecha ajustan dos puntos porcentuales, Home/End llevan a los límites y doble clic o Enter restauran 60/40. La preferencia se conserva en almacenamiento local del navegador; no escribe expedientes ni llama a la IA. Al cambiar de solicitud se conserva el ancho, incluido el resaltado del pasaje.

El reparto se limita a 30–70 % y protege aproximadamente 280 px por panel cuando el espacio lo permite. En la distribución vertical de pantallas pequeñas, el control desaparece. Verificación en navegador: arrastre real de 58 a 47 %, persistencia tras seleccionar otra solicitud y recargar, doble clic a 60 %, límites de ambos paneles a 1024 px, control oculto sin desbordamiento a 320 px y consola sin errores.

## Confirmación de aplicabilidad con un clic

La maqueta reemplaza el formulario obligatorio del escenario de confirmación por «Ver respaldo», «Confirmar que aplica» y «No aplica». El alcance mostrado es la aplicación del antecedente de 2019-2 a la solicitud 2; no certifica hechos nuevos, autenticidad, entrega ni aprobación del oficio.

La confirmación registra automáticamente un evento de prueba con actor explícitamente simulado, fecha/hora, solicitud original, alcance, respuesta y documentos/versiones/pasajes. Se puede consultar el historial y reabrir la decisión. El historial permanece durante la sesión y se pierde al recargar o reiniciar la maqueta; no se escribe ninguna base de datos. La conexión con las comprobaciones del sistema real todavía está pendiente y deberá usar la identidad efectiva del revisor y versiones vigentes del expediente.

«No aplica» pide un motivo breve (selección). Contradicción u otra diferencia requiere una explicación concreta. El rechazo conserva la revisión abierta y evita mostrar el antecedente rechazado como respaldo aplicable. No equivale a marcar una comprobación como innecesaria: se rechaza la aplicación de ese antecedente a la pregunta. Reabrir conserva el historial. Editar la respuesta sigue invalidando su revisión.

La confirmación rápida solo se ofrece para el escenario de aplicabilidad con su pasaje disponible. No se ofrece para documento faltante, error de análisis o edición pendiente. Verificado en navegador: confirmación sin formulario, registro automático, aprobación final separada, reapertura, rechazo que mantiene el pendiente y la aprobación bloqueada, motivo obligatorio en excepciones y ausencia de botón rápido en faltantes/errores.

## Carga de fuentes conectada (10 de septiembre de 2026)

La vista ofrece «Agregar evidencia» en cada respuesta y «Agregar fuente» en la biblioteca. Ambos formularios usan `POST /api/evidence`: guardan originales y procedencia en la biblioteca real, registran un recibo con expediente/versión/solicitud y lanzan la búsqueda existente de LangGraph. PDF, DOCX, TXT, PNG y JPG; límite de 20 MB. La biblioteca muestra documentos reales, con filtro de texto.

El duplicado exacto se reutiliza dentro del mismo alcance y tipo; no se convierte un documento privado en compartido. Cada carga conserva su procedencia en el recibo. La opción de nueva versión conserva el archivo anterior. Los antecedentes manuales tienen colección explícita vinculada al expediente; no se les inventa estado de emisión ni verificación. Un documento compartido de una colección no se incorpora a otros expedientes sin vincularla.

Los errores de lectura se conservan con el original y no entran como pasajes utilizables. Los formatos no admitidos y archivos que superan el límite se rechazan antes de crear la fuente. Si la búsqueda no puede iniciarse, el archivo queda guardado y se ofrece reintentar sin cargar otra copia. Los resultados y pendientes se consultan por pregunta; se distingue archivo leído de archivo seleccionado como respaldo. La búsqueda actual evalúa las solicitudes del expediente completo.

La carga y la búsqueda son reales; las respuestas y aprobaciones de esta vista todavía son las de la demostración. No se implementó aquí la reescritura automática ni la aprobación del oficio. Añadir fuentes no sobrescribe textos. Los cambios de catálogo impiden confirmar como vigente la propuesta inicial; un duplicado sin cambios no la invalida por el solo hecho de volver a cargarlo.

Validación: 54 pruebas locales aprobadas en carga, biblioteca, búsqueda, originales y lectura de imágenes. Navegador: cargas desde tarjeta y biblioteca, deduplicación real, persistencia tras recarga, formulario obligatorio y foco de regreso al cerrar con Escape. Sin desbordamiento a 320/768/1024/1440 ni errores de consola. Búsqueda real con IA: tres solicitudes completadas sin error técnico; P1/P2 con respaldo y P3 con respaldo más cinco comprobaciones pendientes. Se comprobó igualdad de identificación y filas de revisión respecto a la copia anterior: ningún texto fue sobrescrito. Estos resultados no equivalen a una nueva aprobación del oficio.

La copia usada es `output/qa/evidence-upload-20260910/data`; las evidencias de prueba se conservan junto a ella. El servidor conectado se abre en `http://127.0.0.1:8774/`. La vista anterior de 8772 incluye un enlace. Arranque desde la raíz del proyecto:

```powershell
.\scripts\dev-python.ps1 scripts/serve-evidence-demo.py --data-dir output/qa/evidence-upload-20260910/data --case 4eb81e7815d447b1af953343b761db6c --port 8774
```

El lanzador exige una carpeta QA explícita. Los endpoints y el componente `static/evidence-upload.js` están en el código de la aplicación; el montaje del recorrido sigue usando los archivos visuales y el snapshot local de `output/ux-peticiones-20260910`.
