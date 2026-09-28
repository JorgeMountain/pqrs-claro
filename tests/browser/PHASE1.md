# Prueba de borradores de fase 1

Fixture `phase1-drafts.js`: usa el controlador real `createLive` y el HTML de la aplicación, con datos ficticios y `fetch` simulado. Bloquea cualquier endpoint no previsto. No conectar esta fixture a casos reales.

Para ejecutarla, crear temporalmente `static/recorrido/__qa-phase1.html` a partir de `index.html`, reemplazando el script de app por `__qa-phase1.js`; copiar `phase1-drafts.js` con ese nombre en la misma carpeta. Abrir `/__qa-phase1.html` en el servidor local.

Recorrido comprobado: cambiar tipo a Documentos → guardar sin confirmar → bandeja ficticia → reabrir → descartar segunda petición → deshacer. El tipo corregido permanece. Limpiar el borrador ficticio con el botón de QA; volver a editar/guardar y recargar para verificar recuperación. El servidor ficticio se reinicia al recargar, por lo que esta segunda prueba se hace sin descartes pendientes.

Al terminar usar Limpiar borrador de prueba, cerrar la pestaña y retirar únicamente los dos archivos temporales. Mantener los archivos de tests como fixture reproducible.
