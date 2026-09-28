# Mejoras derivadas de la auditoría de PQRS

Inicio: 27 de septiembre de 2026. Primera entrega: fase 1.
Referencia: `output/qa/audit-20260927/AUDITORIA.md`.

Las fases siguientes son trabajo pendiente, no funciones ya implementadas. La entrega se valida en el servidor local unificado del puerto 8772. No incluye publicación, commit ni push.

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

## Fase 2 — Estados fiables, fechas y concurrencia — PENDIENTE

1. Actualizar la bandeja mientras haya trabajos activos y detener la consulta al salir; reintentar errores sin duplicar trabajos.
2. Usar la fecha original de recepción de Gmail, con conversión de zona horaria, en lugar de la fecha de importación.
3. Validar la revisión de gestión al eliminar: una pestaña antigua no debe borrar un expediente recién tomado o modificado.
4. Incluir revisión inicial, preparación y oficio en la última actividad.
5. Definir y aplicar el cierre/reapertura: una PQRS finalizada no debe iniciar trabajo de IA silenciosamente ni cerrarse mientras está procesando.
6. Corregir la ruta antigua de búsqueda de fuentes para respetar la decisión inicial y evitar que el endpoint antiguo de demo deje un expediente cuando responde con error.

Criterio de salida: pruebas con dos clientes y trabajos simulados, fechas verificadas, rechazo consistente de operaciones obsoletas y ninguna escritura parcial ante error.

## Fase 3 — Menos esperas y consumo de IA — PENDIENTE

- Reanalizar solo las peticiones cuyo contenido cambió cuando sea técnicamente válido; conservar los resultados de las demás.
- Distinguir cambios de título, contenido, selección, fuentes y configuración para invalidar únicamente lo que corresponda.
- Mostrar qué se va a actualizar y separar reintento de errores de nuevo análisis completo.
- Medir duración y número de llamadas en pruebas, comprobando que descartar, deshacer o guardar correcciones de revisión no vuelven a analizar todo.

Criterio de salida: modificar una petición no genera evaluaciones del resto; un cambio global de fuentes/modelo sí invalida los resultados que dependan de él. Confirmación humana siempre asociada a la revisión vigente.

## Fase 4 — Revisión más intuitiva — PENDIENTE

- Mostrar la ruta general y el siguiente paso sin tener que abrir varios detalles.
- Reducir la información repetida; separar resultado, motivo y evidencia.
- Añadir índice de peticiones y acceso al siguiente punto pendiente.
- Acercar guardar/confirmar al trabajo del gestor sin ocultar avisos relevantes.
- Proponer el gestor seleccionado como responsable cuando corresponda, permitiendo corregirlo.
- Validar teclado, pantalla estrecha y expedientes largos.

Criterio de salida: completar un expediente largo con menos desplazamiento, sin perder el acceso a la evidencia ni confundir guardar borrador, confirmar y preparar.
