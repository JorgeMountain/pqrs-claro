# Prueba de navegación de revisión — fase 4

`phase4-review.js` usa el controlador real createLive con 30 peticiones ficticias, dos con observaciones, un gestor ficticio y API simulada. Ninguna llamada llega a IA ni a un expediente real. Se utiliza el identificador del gestor seleccionado solo para asociarlo al nombre ficticio de prueba; no se modifica la selección del usuario.

Crear temporalmente `static/recorrido/__qa-phase4.html` copiando index.html y sustituyendo el script principal por `__qa-phase4.js`. Copiar la fixture con ese nombre en la misma carpeta y abrirla en el servidor local.

1. Con Enter, activar Siguiente con observaciones: foco en la petición 3 y apertura de sus detalles; repetir para llegar a la 17.
2. Elegir la petición 30 en el índice: foco en su encabezado.
3. Cambiar su tipo, guardar desde la barra y activar Ir a confirmar. El formulario conserva el cambio, el gestor es editable y la casilla no se marca automáticamente.
4. Cambiar la ruta general: la ruta visible debe actualizarse como propuesta pendiente de confirmación.
5. Probar 390×844 y 1366×900: sin desbordamiento horizontal, barra disponible y encabezados enfocados visibles. Revisar consola.

Al terminar, usar Limpiar borrador de prueba, restaurar el tamaño del navegador, cerrar la pestaña y retirar solamente los dos archivos temporales. La fixture rechaza cualquier API no contemplada.
