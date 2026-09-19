# Recuperación de fechas explícitas

La pregunta sobre las fechas de presentación de la convocatoria 2027-1 recibió
fragmentos de las páginas 47 y 5 de la guía. Esos pasajes mencionaban jornadas y
restricciones, pero no las fechas. La página 44 sí contiene la respuesta.

La búsqueda ahora reserva hasta dos candidatos que contienen fechas explícitas
y términos del evento cerca de esas fechas. Se conservan texto y ubicación
originales, permisos, versiones, límites de candidatos y prioridad de referencias
documentales explícitas. La presencia de una fecha no equivale a respaldo:
la evaluación de pertinencia permanece a cargo del evaluador.

## Validación

- 82 pruebas de recuperación, alcance, contexto, reintentos, servicio y borrador
  pasaron. Incluyen fechas escritas y numéricas, ruido documental, límites,
  duplicados y exclusión de fuentes privadas, ajenas o sustituidas.
- Se copiaron las bases a `output/qa/exam-dates-20260916` y se usó la misma
  solicitud y las mismas tres fuentes habilitadas del expediente de prueba.
- La evaluación real con IA recuperó la página 44, seleccionó las líneas 19–23
  y produjo `references_found`, `support_found`, sin pendientes.
- Se incrementó la versión del análisis a 17 para evitar reutilizar resultados
  incompletos anteriores. Se mantiene la compatibilidad de resultados antiguos
  satisfactorios cuando todas sus entradas coinciden.

## Activación

La validación se realizó en una copia aislada; no reemplaza resultados ni
revisiones del expediente activo. El proceso local anterior seguía en ejecución
durante la comprobación. Para activar el cambio hace falta reiniciar el servicio
y actualizar la búsqueda desde «Reintentar o actualizar fuentes».

El reinicio está pendiente de confirmación tras un rechazo del control automático
a la detención del proceso. No se presenta la prueba aislada como activación.
