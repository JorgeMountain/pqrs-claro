# Gestión de Peticiones · presentación de la demo

La interfaz usa el nombre **Gestión de Peticiones** y el logo original de la
Facultad de Ingeniería de la Universidad de Antioquia. La presentación visual
se define en `static/institutional.css`; los componentes del flujo conservan
sus estilos y comportamiento. El nombre técnico del paquete y las claves de
guardado local se mantienen para recuperar los expedientes y ediciones existentes.

## Abrir y presentar

1. Ejecutar `scripts/start.ps1` desde la carpeta del proyecto y abrir
   [la página local](http://127.0.0.1:8770/).
2. Empezar por la portada: explica comprensión, fuentes y borradores, y revisión
   hasta generar el oficio. El logo o **Nueva petición** regresan al inicio.
3. Para recorrer un ejemplo ya guardado, abrir **Mis expedientes** y elegir
   **Ejemplo ficticio · tres solicitudes**. El menú está plegado inicialmente
   en móvil y abierto en escritorio.
4. Para iniciar un ejemplo nuevo, elegir **Iniciar ejemplo de demostración**.
   Crea un expediente ficticio de tres solicitudes y ejecuta identificación
   real con IA. Requiere que el análisis esté configurado.
5. Mostrar las fuentes, los borradores y la revisión. **Generar Word y PDF**
   permanece bloqueado mientras falten las aprobaciones y comprobaciones exigidas.

La etiqueta **Demo** identifica la presentación del prototipo. No cambia datos,
no anonimiza expedientes reales ni simula aprobaciones. La biblioteca puede
contener documentación real; elegir previamente el material que se mostrará
durante una presentación.

## Validación visual del 8 de septiembre de 2026

- Navegador real sobre el servidor local: portada, fuentes, borradores,
  revisión, oficio y biblioteca.
- Portada, fuentes, oficio y biblioteca sin desbordamiento horizontal en
  320, 768, 1024 y 1440 px; revisión comprobada también en móvil.
- Navegación por teclado de los controles de inicio y cambio de etapas con
  foco visible. Los textos y etiquetas describen las acciones.
- Logo servido con dimensiones originales 437 × 131 y contenido idéntico
  al archivo extraído del membrete. Los activos servidos coinciden con el código.
- Contraste de los colores de texto principales entre 5.24:1 y 12.76:1.
- Sin errores ni avisos de consola observados en el recorrido.
- `pytest tests/test_app.py -q`: nueve pruebas HTTP aprobadas, con datos
  temporales y sustitutos explícitos de IA.

Esta revisión valida la presentación y navegación. No ejecutó nuevos análisis,
no aprobó respuestas y no generó oficios de los expedientes reales.
