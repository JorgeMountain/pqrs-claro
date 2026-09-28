# Mejoras derivadas de la auditoría de PQRS

Inicio: 27 de septiembre de 2026. Primera entrega: fase 1.
Referencia: `output/qa/audit-20260927/AUDITORIA.md`.

Estado al 28 de septiembre de 2026: fases 1, 2 y 3 implementadas localmente. Fase 4 pendiente. Antes de iniciar la fase 2 se creó y subió a origin/master el commit 0bb6c0a (bandeja de gestores y fase 1), por solicitud del usuario. La fase 2 está en el commit 611ce39, subido a origin/master. La fase 3 permanece local, pendiente de commit y push. Servidor unificado: puerto 8772.

## Fase 1 — Conservar el trabajo del gestor — IMPLEMENTADA

- Guardado automático del borrador de revisión inicial en este navegador y botón **Guardar borrador**. No requiere completar el responsable, las notas ni la confirmación. No llama a la IA.
- Recuperación de tipos, rutas, notas, comunicaciones y responsable al salir y volver a abrir el expediente o al recargar la página.
- Al descartar y deshacer, las correcciones se conservan por identificador de petición. El borrador conserva también las peticiones retiradas para poder recuperarlas.
- La recuperación no marca la revisión como aprobada: la confirmación humana continúa siendo explícita.
- Si cambia el contenido o la generación del análisis, se conserva la copia anterior para consultarla o descargarla, sin aplicarla silenciosamente a la nueva revisión. Conviene descargarla antes de iniciar un nuevo borrador que la sustituya.
- Si otra pestaña actualizó el borrador, se evita sobrescribirlo y se permite descargar el trabajo de la pestaña actual.
- La bandeja conserva búsqueda, filtros, pestaña, orden y página durante la navegación en la aplicación. Al abrir desde una tarjeta y regresar, recupera el desplazamiento. Estos filtros no se guardan entre recargas completas.

### Alcance del guardado

Es un borrador **local de este navegador y este origen (host/puerto)**. No está sincronizado entre computadores, navegadores o gestores. Borrar los datos del sitio elimina esta copia. Las decisiones confirmadas conservan su guardado habitual en el servidor. La descarga JSON es una copia de recuperación consultable; aún no hay importador de borradores.

### Evidencia

- `node --test tests/*.mjs`: 39 comprobaciones aprobadas (24 previas y 15 nuevas).
- Nuevas regresiones: persistencia del controlador real `createLive`, estado de bandeja, descarte/deshacer, cambio de generación/contenido, aislamiento por expediente, fallo de almacenamiento, conflicto entre pestañas y escape del contenido.
- Navegador real con `createLive` y módulos de producción, APIs simuladas y datos ficticios: corregir Información a Documentos, guardar sin confirmar, salir/reabrir, descartar otra petición, deshacer y recargar. Corrección conservada; casilla de confirmación desmarcada.
- Evidencias: `output/qa/audit-20260927/phase1-tests.txt` y `phase1-draft.png`.
- No se enviaron solicitudes a proveedores de IA ni se modificaron expedientes reales durante la validación.

## Fase 2 — Estados fiables, fechas y concurrencia — IMPLEMENTADA

1. La bandeja consulta cada dos segundos mientras existen trabajos activos. Al finalizar actualiza las tarjetas y deja de consultar; al salir no realiza más solicitudes. Un error conserva la lista y se reintenta con espera creciente hasta 30 segundos. No repinta mientras está abierto un diálogo; conserva filtros y foco de botones.
2. Gmail usa la fecha original del correo convertida a Bogotá (UTC−05:00). Una fecha manual explícita tiene prioridad. Se corrigen defaults antiguos sin cambios de metadatos; se conservan las fechas que pudieron haber sido editadas manualmente. No se altera la fecha de incorporación ni se recalculan plazos.
3. Papelera, restauración y borrado definitivo validan la revisión de gestión dentro de la transacción, además de las versiones anteriores. Una pestaña desactualizada recibe 409 antes de modificar el expediente. Clientes antiguos sin este campo solo funcionan si la gestión sigue en revisión cero.
4. Última actividad incluye revisión inicial, preparación, fuentes, borradores, revisión de respuestas y oficios. La consulta lee proyecciones de fechas; no ejecuta modelos.
5. Finalizar requiere que no haya trabajos en curso. Las admisiones de análisis, preparación, redacción, comprobación, propuestas y generación de oficio rechazan expedientes cerrados. La revisión inicial tampoco se confirma sobre un caso cerrado. La tarjeta muestra **Consultar**; para continuar trabajando, el responsable debe cambiar el estado a **En gestión** desde **Detalles y gestión**, dejando el motivo. El cierre es manual y no acredita envío.
6. La búsqueda antigua de fuentes aplica la misma revisión inicial obligatoria. La antigua API de demostración rechaza el flujo gestionado antes de crear expedientes; la demostración visual estática sigue disponible.

### Validación de fase 2

- 15 nuevas pruebas Python con SQLite temporal, motores ficticios y sin API de IA real: recepción original/manual, defaults antiguos, pestaña obsoleta, cierre/reapertura, todos los trabajadores activos, ruta especializada, demo sin escritura parcial y última actividad.
- 45 comprobaciones JavaScript aprobadas, incluyendo actualización periódica, parada al salir, reintentos y estado de consulta de expedientes cerrados.
- Navegador real con módulos de producción y APIs simuladas: Analizando cambia a Continuar sin recargar; Finalizada muestra Consultar; recuperación tras fallo; contador detenido al salir; campos deshabilitados y confirmación ausente en expediente cerrado.
- Servidor local reiniciado solo tras comprobar que no había trabajos activos. Lectura posterior: 51 expedientes, todos con última actividad, cero en proceso. No se modificaron casos reales como prueba.
- Evidencias locales: `output/qa/audit-20260927/phase2-queue.png` y fixture reproducible `tests/browser/phase2-queue.js`. Resultado de suite completa registrado en `output/qa/audit-20260927/PHASE2_VALIDACION.md`.

Límites: el selector continúa siendo una simulación local, no autenticación. La bandeja sin trabajos no consulta permanentemente nuevas entradas externas; el botón Actualizar sigue disponible. El cierre no es aprobación institucional ni envío de comunicaciones. No se añadió migración entre las dos copias del proyecto.

## Fase 3 — Menos esperas y consumo de IA — IMPLEMENTADA

- Revisión inicial persistente por petición: una corrección de contenido, título o referencias reevalúa esa petición y las dependencias identificadas, conservando las independientes. La numeración sin efecto en referencias no consulta IA.
- Descartar/deshacer conserva el mecanismo existente de reutilización sin llamadas; guardar el borrador sigue siendo local. Ninguna reutilización confirma automáticamente la revisión humana.
- Original, metadatos generales, fuentes, colecciones, modelo o instrucciones distintos invalidan los resultados dependientes. Un informe antiguo vigente puede incorporarse a la caché al editar, sin repetir todas las peticiones.
- El reintento incremental conserva resultados válidos incluso tras un fallo. La opción explícita **Reanalizar todo con IA** descarta la reutilización para ese análisis. El cliente indica qué modo solicita; la API antigua conserva el modo completo por compatibilidad.
- La pantalla muestra peticiones por analizar y resultados conservados. El servidor registra llamadas al motor, peticiones evaluadas/reutilizadas y duración; estas llamadas no equivalen necesariamente a solicitudes HTTP del proveedor.
- Los checkpoints de fuentes dependen del contexto común y de la petición enriquecida, no de toda la identificación. Los de redacción dependen de la petición, hallazgo, modelo, versión de reglas y original; un mero cambio de versión del caso no fuerza la redacción de lo idéntico.

### Validación y alcance

536 pruebas Python de fuentes, borradores, revisión inicial y preparación aprobadas; 46 JavaScript aprobadas. Pruebas con motores ficticios: corregir P1 evalúa solo P1 y conserva P2; cambiar fuentes/modelo evalúa ambas; en fuentes y borradores no se repite P2. Se validan referencias entre peticiones, descarte/deshacer, reintento, compatibilidad e imposibilidad de confirmar una revisión antigua.

Navegador real con controlador de producción y APIs ficticias: Reintentar pendientes envía incremental; Reanalizar todo envía full; el progreso diferencia los resultados conservados. Fixture: `tests/browser/phase3-intake.js`. Evidencia local: `output/qa/audit-20260927/phase3-incremental.png`.

Límites: el documento original se sigue enviando completo cuando hace falta una evaluación, y se revisan nuevamente sus comprobaciones generales en esa llamada. No se promete un porcentaje de ahorro ni una latencia del proveedor: las medidas son de pruebas locales sin IA real. Los checkpoints anteriores de fuentes/redacción pueden requerir una primera actualización con las nuevas claves. La confirmación humana y los controles de vigencia siguen obligatorios. Detalle en `docs/ANALISIS_INCREMENTAL.md`.

## Fase 4 — Revisión más intuitiva — PENDIENTE

- Mostrar la ruta general y el siguiente paso sin tener que abrir varios detalles.
- Reducir la información repetida; separar resultado, motivo y evidencia.
- Añadir índice de peticiones y acceso al siguiente punto pendiente.
- Acercar guardar/confirmar al trabajo del gestor sin ocultar avisos relevantes.
- Proponer el gestor seleccionado como responsable cuando corresponda, permitiendo corregirlo.
- Validar teclado, pantalla estrecha y expedientes largos.

Criterio de salida: completar un expediente largo con menos desplazamiento, sin perder el acceso a la evidencia ni confundir guardar borrador, confirmar y preparar.
