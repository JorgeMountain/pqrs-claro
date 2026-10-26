# Recursos mínimos de arranque

La interfaz principal abre la bandeja real y carga `data.json` durante su inicio.
Este snapshot vacío permite iniciar una copia recién clonada, sin documentos ni
bases de datos del equipo de desarrollo. El logo se sirve desde `static/assets/`.

La demostración histórica de tres solicitudes sigue disponible si la instalación
ya tiene `output/ux-peticiones-20260910/data.json` y su carpeta `files/`.
Esos documentos locales no se distribuyen con el código. Para probar un entorno
nuevo, usa los documentos ficticios de `examples/` y un directorio de datos separado.
