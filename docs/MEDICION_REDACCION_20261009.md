# Redacción: prueba real y ajuste del 9 de octubre de 2026

Se usó la API autorizada, el modelo configurado `gpt-6-luna` y el ejemplo existente
de diez solicitudes sobre admisiones. Los borradores se generaron en copias de las
bases de datos bajo `output/performance-20261009/draft-real/`. No se modificaron las
respuestas del expediente original ni se enviaron comunicaciones.

## Resultados

| Prueba | Tiempo total | Llamadas a la API | Resultado automático |
| --- | ---: | ---: | --- |
| Motor aislado: tres solicitudes simultáneas | 32,7 s | 11 | 3 comprobadas; una necesitó ajuste |
| Servicio completo, diez solicitudes, concurrencia 3 | 59,7 s | 30 | 10 comprobadas |
| Servicio completo, concurrencia 5 | 49,2 s | 32 | 9 comprobadas; una observación persistente |
| Concurrencia 5 y regla de enlaces corregida | 39,1 s | 30 | 10 comprobadas |

La comparación final representa aproximadamente un 34 % menos de tiempo para este
ejemplo. No es una garantía de latencia: las ejecuciones fueron consecutivas, el
proveedor reutilizó parte de la entrada en caché y el contenido generado varía.
No hubo reintentos HTTP ni errores del proveedor en estas cuatro pruebas.

El historial de ese expediente registra una ejecución anterior de 17 min 44 s,
del 8 de octubre. No tenía instrumentación por etapa y no permite atribuir toda
la diferencia a un cambio particular. La preparación léxica de la fase 2 optimiza
la búsqueda; no acelera directamente la generación del modelo.

## Hallazgos y cambios

La aplicación ya redactaba tres solicitudes simultáneamente. Cada una mantiene
la secuencia planificar → redactar → comprobar y, cuando corresponde, un ajuste
acotado y una nueva comprobación. El tiempo de API medido por etapa fue del orden
de segundos; las validaciones locales repetidas añadieron entre 2 y 6 segundos
por solicitud en estas pruebas. Esos tiempos paralelos no deben sumarse como
tiempo total del expediente.

La regla de estilo prohibía todas las URL, incluso cuando la petición preguntaba
cuál era el recurso web. Se observó una contradicción real: el primer control pidió
retirar el enlace y el segundo pidió incluirlo. Eso produjo dos llamadas adicionales
y dejó una observación pendiente. Se aclaró la regla común: una dirección que sea
parte de la respuesta puede incluirse si figura literalmente en el pasaje citado;
no se permiten enlaces inventados ni se exige bibliografía técnica.

Las instrucciones del motor ahora tienen una huella incluida en la clave del grafo.
Un reintento tras cambiar instrucciones no reutiliza pasos incompatibles. Los
borradores terminados y las ediciones humanas se conservan: no se regeneran por
reiniciar el sistema ni por este cambio de instrucciones.

La concurrencia admite de 1 a 6 solicitudes. Se conserva 3 como valor predeterminado
y se configura 5 en este piloto mediante `PQRS_CLARO_DRAFT_CONCURRENCY=5` en
`.env.local`. También admite una variable de entorno, que tiene prioridad. Requiere
reiniciar el servidor. `/api/config` expone el límite activo sin revelar credenciales.
Si una cuenta presenta límites de tasa, puede bajarse a 3; aumentar simultaneidad
no reduce por sí mismo el número de llamadas ni su consumo.

## Consumo y evidencia

Las cuatro pruebas hicieron **103 llamadas**, con **1.472.181 tokens de entrada**
reportados y **24.181 de salida**, incluidos los de razonamiento. Una parte de la
entrada fue reportada como caché por el proveedor. No se expresa una cifra monetaria
porque el proyecto no tiene tarifas configuradas; estos datos no son una factura.

Cada carpeta de prueba conserva `report.json`, los eventos de rendimiento y los
borradores aislados. La primera prueba guarda además las salidas por solicitud;
las pruebas completas guardan SQLite y sus checkpoints. Son artefactos locales
ignorados por Git y contienen información del caso: no deben publicarse como logs.

La batería de regresión cubre concurrencia acotada, preservación de comprobaciones,
reanudación de pasos, cambio de instrucciones, conservación de borradores terminados,
referencias exactas, fuentes cambiadas y aislamiento entre expedientes. La revisión
automática no sustituye la aprobación humana ni demuestra calidad para otros casos.

Validación final: 118 pruebas aprobadas y Ruff sin errores. Se reinició el servidor
sin trabajos activos; `/api/config` confirmó `gpt-6-luna` y concurrencia 5 en el
puerto 8772. Las huellas de las 31 tablas de datos de trabajo coincidieron antes y
después: los ensayos no modificaron el expediente ni sus respuestas guardadas.
