# Oficio editable en el recorrido 8772

El paso 3 abre el oficio ensamblado antes de aprobarlo. Permite editar destinatario,
asunto, introducción, saludo, respuestas y cierre directamente en la hoja. Los
numerales y las preguntas originales conservan su relación con la identificación.
Los datos de fecha, radicado y anexos se despliegan sobre el documento.

Guardar conserva metadatos y respuestas en una transacción SQLite con control de
revisiones. Un conflicto en una respuesta impide guardar parcialmente el oficio.
Cancelar recupera la versión del servidor. La edición local se conserva al navegar
entre etapas y avisa antes de cerrar la pestaña con cambios sin guardar.

Las respuestas modificadas pierden su evaluación/aprobación anterior. Guardar
inicia las comprobaciones pendientes; las respuestas que ya pasaron conservan sus
comprobaciones. Generar Word/PDF es la aprobación explícita del conjunto guardado:
el servicio sigue exigiendo evaluaciones vigentes, fuentes íntegras y metadatos
completos. Un pendiente no desaparece por editar o generar el documento.

El responsable se declara una vez por sesión del navegador y se reutiliza en
ediciones, confirmaciones, aportes y aplicación de propuestas. Puede cambiarse.
Esto no incorpora autenticación institucional ni sustituye el nombre y cargo de
quien suscribe el oficio.

La vista de edición usa la misma secuencia de contenido que el exportador. La
paginación exacta se consulta en las imágenes del PDF generado. Word y PDF mantienen
el membrete activo y no imprimen las citas internas. Los anexos seleccionados
tienen descarga conjunta en el paquete ZIP.

El editor incluye una barra compacta con deshacer/rehacer (hasta 80 cambios locales,
reiniciados al guardar o cancelar), guardar, buscar/reemplazar texto editable,
añadir/quitar párrafos y contador de palabras/caracteres. Las preguntas originales
no se modifican mediante el buscador. Los párrafos nuevos conservan la sección y
referencias del párrafo de origen y pasan por la comprobación al guardar; no se
puede quitar la última respuesta concreta de un numeral. Los bloques de contexto
compartidos se editan en texto, pero no admiten inserción/eliminación desde la barra.

La vista permite zoom del 50 al 200 %, ajuste al ancho, desplazamiento independiente
y pantalla completa dentro de la aplicación (Escape para salir). El zoom no cambia
el tamaño de letra del archivo exportado. Ctrl/⌘ + S guarda; Ctrl/⌘ + F abre la
búsqueda; Ctrl/⌘ + Z y Ctrl/⌘ + Y deshacen/rehacen mientras se edita el documento.
El formato tipográfico del Word y PDF continúa definido por el membrete institucional.

Compatibilidad: un mapa satisfactorio del motor 14 puede seguir vigente con el 15
solo si coinciden todas las entradas actuales, incluidas fuentes, modelo,
comprobaciones y colecciones. Mapas con errores de análisis no usan esta excepción.
No se cambian sus resultados ni sus huellas guardadas.
