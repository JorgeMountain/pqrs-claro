# Validación visual de la fase 2

`phase2-queue.js` utiliza la bandeja real con respuestas GET ficticias. Bloquea las escrituras y no consulta proveedores de IA.

Copiar temporalmente `index.html` de recorrido a `__qa-phase2.html`, sustituir su script principal por `__qa-phase2.js` y copiar la fixture con ese nombre. Abrirla en el servidor local.

1. Elegir Todas: la primera tarjeta muestra Analizando y la segunda Consultar.
2. Pulsar Terminar trabajo simulado: debe aparecer Continuar automáticamente y detenerse el contador de lecturas.
3. Recargar y simular un fallo: la lista se conserva, aparece el error y se recupera automáticamente sin cambiar de pestaña.
4. Salir de la bandeja: el contador ya no aumenta.

Se comprobó también el controlador `createLive` usando la fixture de fase 1 con `record.management={owner_id:'gestor-1',started_at:'2026-09-28T12:00:00Z',state:'closed',revision:3}`: tipos deshabilitados, ninguna acción de confirmar/preparar, aviso para reabrir y acceso al documento.

Cerrar las pestañas y retirar únicamente los archivos temporales al finalizar. La evidencia visual local está en `output/qa/audit-20260927/phase2-queue.png`.
