# Integración alternativa conservada · 8770

**Decisión vigente del usuario: continuar sobre http://127.0.0.1:8772, preservando su diseño e interacción.** La integración de 8770 no fue aceptada como sustituto. Se conserva como implementación alternativa y referencia técnica, sin borrar versiones ni datos. Las futuras conexiones de biblioteca y expedientes deben incorporarse al recorrido de 8772, sin sustituir su interfaz ni presentar estados simulados como resultados reales.

`scripts/start-recorrido.ps1` inicia o comprueba el recorrido elegido en 8772. Su interfaz está en `src/pqrs_claro/static/recorrido/` y ya incorpora la [biblioteca compartida real](BIBLIOTECA_RECORRIDO.md) y la [confirmación con preparación automática](PREPARACION_AUTOMATICA.md). Conserva los documentos y respuestas de la demostración en `output/ux-peticiones-20260910/`; no equivale a una validación nueva del expediente completo. `scripts/start.ps1` continúa sirviendo el servicio y la integración alternativa de 8770, descrita a continuación.

## Lo integrado

1. **Entender la petición:** carga e identificación reales, corrección y confirmación; tarjetas compactas, documento original a la derecha y ancho ajustable. El resaltado usa las referencias guardadas de cada solicitud. Si no se encuentra una coincidencia visual exacta, muestra el pasaje y explica la limitación.
2. **Preparar las respuestas:** consulta automática de las fuentes elegibles del expediente, generación inicial y preparación de la revisión. Las tarjetas muestran respuestas guardadas, soporte, pendientes y acceso a revisión. Los documentos históricos mantienen su alcance: sus colecciones se vinculan desde los detalles de fuentes.
3. **Revisar el oficio:** utiliza la revisión y exportación existentes. Solo se genera desde contenido aprobado; el cambio de interfaz no autoriza firmas, envíos ni hechos nuevos.

La biblioteca permite consultar documentos y versiones, conservar procedencia y lectura, y agregar fuentes. Cada respuesta permite agregar evidencia a su expediente. Una carga guarda el original y solicita la búsqueda; no equivale a verificar el contenido ni a aprobar una respuesta.

Actualizar respaldo conserva la redacción previamente editada y sincroniza fuentes y pendientes. No reescribe automáticamente el texto con IA. Los estados de respaldo de la búsqueda vigente se muestran aun cuando el texto anterior necesite revisión.

## Conservación y operación

- `/anterior` conserva la interfaz previa y su controlador. Ambas interfaces usan la misma base de datos: editar en una afecta al mismo expediente en la otra.
- La maqueta de `output/ux-peticiones-20260910/` se conserva, pero no es la aplicación principal ni contiene el estado vivo de los expedientes.
- Los datos siguen en `data/`, con SQLite y originales locales. No se importaron las modificaciones de QA al expediente vivo.
- Antes de activar la nueva ruta se copiaron las nueve bases SQLite mediante la API de respaldo a `output/qa/workspace-primary-20260910/backup/`. Los originales permanecen en su ubicación.
- La preparación encadena búsquedas y borradores desde la página. Si se cierra durante el proceso, la etapa iniciada conserva su ejecución en el servidor; al volver, el botón permite continuar. No implica ejecución autónoma de todas las etapas con la página cerrada.

## Validación y siguientes mejoras

Se comprobaron rutas principal/anterior, referencias del PDF, carga de evidencias, contratos de revisión y generación. En navegador se comprobó: respuestas guardadas, consulta de pasajes, formulario de evidencia, biblioteca real, acceso a revisión/oficio, resaltado, ajuste del divisor y ausencia de desbordamiento horizontal a 320, 768, 1024 y 1440 píxeles.

La integración no sustituye una validación completa con IA y generación DOCX/PDF de una petición nueva. Esa validación debe hacerse en una copia aislada, revisar el resultado y registrar qué requirió intervención.

Prioridades siguientes:

1. Simplificar las confirmaciones reales dentro de cada tarjeta, registrando quién confirma, qué confirma y a qué solicitud aplica. Actualmente se utilizan los formularios completos existentes.
2. Ofrecer una propuesta de reescritura selectiva tras cambios de evidencia o de aplicabilidad, con comparación antes de reemplazar la redacción guardada.
3. Pulir la revisión final y cerrar una prueba completa desde una petición nueva hasta el oficio descargado.

Drive conserva la procedencia de los documentos importados, sin sincronización automática. OnBase sigue pendiente de comprobar los mecanismos disponibles con el acceso institucional autorizado.
