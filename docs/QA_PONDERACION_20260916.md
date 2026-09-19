# Recuperación de ponderaciones — 16 de septiembre de 2026

El caso PDF de tres solicitudes falló después del reinicio: la página 4 de la
guía quedó tercera en el ranking de contenido, que reservaba solo dos pasajes.
El límite compartido por documento también bloqueaba candidatos semánticos.
Se enviaron las páginas 5, 31 y 37, sin el pasaje con las ponderaciones.

Se reservan ahora hasta cuatro pasajes de contenido por documento de tema
coincidente, y se permite llegar a seis con el canal semántico. Se conserva
el límite global de 24, el filtrado de permisos y versiones, las citas originales
y la evaluación de suficiencia. La versión 18 invalida búsquedas incompletas
anteriores; no cierra sus pendientes automáticamente.

Validación: 79 pruebas de recuperación, contexto, alcance y reintentos pasaron.
Dos regresiones cubren una respuesta detrás de dos referencias al portal y
la recuperación semántica después de reservar contenido del mismo documento.
En una copia aislada del caso real, la IA recibió la página 4 y devolvió
`references_found`, `support_found`, sin pendientes. La comprobación anterior
de fechas sigue recuperando el pasaje de la página 44.

No se ejecutó búsqueda ni se registraron decisiones en el expediente vivo.
Al activar el servicio, el usuario debe actualizar las fuentes para reemplazar
el análisis guardado. Esto valida el caso observado, no garantiza toda pregunta.
