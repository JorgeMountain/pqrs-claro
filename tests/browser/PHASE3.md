# Prueba de fase 3

`phase3-intake.js` usa `createLive` de producción con dos peticiones ficticias y fetch simulado. Bloquea endpoints inesperados y no utiliza proveedores de IA.

Como en fase 1, copiar temporalmente el index de recorrido a `__qa-phase3.html`, cambiar el script principal por `__qa-phase3.js` y copiar la fixture con ese nombre. Abrirla en el servidor local.

1. Simular fallo parcial y activar Reintentar pendientes: el aviso debe mostrar modo `incremental`.
2. Abrir Ver detalle y decisión general y activar Reanalizar todo con IA: el aviso debe mostrar modo `full`.
3. Simular análisis parcial: una petición queda clasificándose y otra conserva su resultado. No debe poder confirmarse mientras está ejecutándose.
4. Terminar simulación: vuelven los resultados y la confirmación permanece desmarcada.

Se verificó el recorrido con teclado (Enter) y se revisó la consola sin errores. Cerrar la pestaña y retirar ambos archivos temporales al terminar. No conectar la fixture a expedientes reales.
