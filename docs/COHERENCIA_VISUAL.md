# Coherencia del recorrido del gestor

Revisión y ajustes locales del 16 de noviembre de 2026 sobre las cuatro etapas
del recorrido. El objetivo es que las mismas acciones ocupen posiciones
predecibles y que se distinga la etapa abierta del avance ya completado.

## Comportamiento acordado

- Los pies de etapa comparten `stage-actions.css`: guardar o volver a la
  izquierda; continuar, aprobar o generar a la derecha. Hasta 760 píxeles
  se apilan en ese mismo orden. El orden visual coincide con el del teclado.
- Preanálisis coloca las acciones después de las verificaciones y del visor.
  Identificación coloca sus acciones después de la revisión conjunta y las
  opciones de responsable. Las condiciones para habilitar el avance se conservan.
- Redacción mantiene el guardado antes de volver a la bandeja, incluidos los
  cambios de paneles cerrados con la X. Véase
  [guardado y revisión de citas](CITAS_POR_UBICACION.md).
- Borrador conserva sus acciones diferenciadas de guardar, descartar,
  aprobar/generar y finalizar. Una acción oculta permanece oculta.
- Los indicadores del recorrido usan verde claro para Preanálisis, verde
  oscuro para Identificación, azul para Redacción y morado para Borrador.
  Las rayas del avance pendiente se conservan.
- Una etapa completada conserva el visto bueno. Si es la pantalla abierta,
  además mantiene `aria-current="step"`, un aro y el título subrayado.
- Los paneles de corregir y descartar una petición dicen «CONTEXTO DE LA
  PETICIÓN». Las acciones secundarias Cancelar/Volver preceden a Guardar/Confirmar.
  Descartar una petición se distingue con rojo y conserva su confirmación.
- Corregir una petición tiene un botón Cancelar explícito, además de la X.
  Cancelar no guarda. El formulario mantiene su acción de guardado original.

Los colores del recorrido identifican etapas; los avisos de revisión, los
errores y los resultados conservan su significado independiente. Este ajuste
no modifica el lector del RAG, los permisos, las confirmaciones requeridas
ni la generación de documentos.

## Navegación y lectura

Las fuentes de Redacción incluyen «Volver a la petición N» al principio y al
final del panel. El retorno abre y enfoca la petición correspondiente por su
identificador, conserva la selección y no vuelve a buscar ni redactar. Sigue
disponible cuando una corrección o retirada de permiso ha ocultado los respaldos.

Las cuatro etapas ofrecen «Ir a revisión y acciones». Lleva el foco a la
confirmación de esa etapa, o a sus acciones cuando no hay confirmación disponible.
Al usarlo no se confirma, guarda ni avanza. Desde el final de las fuentes hay
otro acceso a la revisión conjunta. Los atajos forman parte de la página y no
superponen una barra sobre el texto. Redacción conserva el foco de la petición,
del encabezado de fuentes o de la revisión conjunta durante sus actualizaciones.

`workflow-accessibility.css` lleva a 13 px los metadatos de citas y los textos
de apoyo revisados; los indicadores de etapa y estado tienen un mínimo de 12 px.
«Por revisar» comparte morado y blanco entre bandeja, Identificación y Redacción.
Al editar Identificación, la etiqueta pasa inmediatamente a «Por revisar»;
volver a marcar la casilla no equivale a guardar esa revisión.

Los campos editables usan el borde `--color-control-line: #75839b`, con contraste
calculado de 3,83:1 sobre blanco (antes 1,91:1). Se conserva el tratamiento de
campos deshabilitados, de solo lectura y errores explícitos. Estos estilos no
se aplican a las imágenes del PDF ni al contenido impreso del oficio.

## Comprobaciones

Se revisaron en Chrome seis estados del recorrido en 320, 390, 768, 1024 y
1440 píxeles: Preanálisis, Identificación pendiente y completada, Redacción
con pendiente y preparada, y Borrador. Las 30 combinaciones conservan el
orden de acciones, permiten enfocar los botones habilitados y no presentan
desbordamiento horizontal ni errores de JavaScript.

En Identificación se comprobó que Cancelar no envíe cambios, que Guardar
conserve la corrección y sus referencias después de recargar, y que una ruta
alternativa mantenga deshabilitado el avance a Redacción. La regresión de
guardado de Redacción pasó sus cuatro casos en Chrome.

La prueba de navegación comprueba que las cuatro etapas puedan conservar
simultáneamente el estado completado y una única selección actual.

```powershell
node --test tests/test_expediente_workspace.mjs tests/test_response_save.mjs
.\scripts\test.ps1 tests/check_redaction_save_browser.py
.\scripts\test.ps1 tests/check_redaction_navigation_browser.py tests/check_redaction_browser.py
```

La revisión visual usa expedientes, fuentes y motores ficticios con
almacenamiento temporal. No es una evaluación de calidad de respuestas de IA.
Las capturas y el informe de esta sesión están en
`output/playwright/coherencia-20261116/`, fuera del control de versiones.

La segunda comprobación revisa las cuatro etapas en los mismos cinco anchos,
los tamaños y bordes calculados, la navegación con teclado y el foco visible.
El retorno móvil deja un margen de 76 px para la barra superior; en escritorio
conserva 12 px. Se ensayó además un viewport efectivo de 720 × 480 con DPR 2,
como emulación de ampliación; no es una prueba del zoom nativo del navegador.
Estos resultados y capturas están en `output/playwright/navegacion-legibilidad-20261116/`.

La prueba de navegación cambia entre tres peticiones, pliega y reabre su
respuesta, conserva la selección después de recargar y comprueba el foco tras
el sondeo. Compara la revisión persistida y los contadores de los motores:
volver a una respuesta o ir a la revisión no guarda ni ejecuta la IA. También
retira una autorización desde otro cliente: cita, pendiente y enlace desaparecen
sin recargar, y volver a la petición no los restaura.

Validación al terminar este bloque: 234 pruebas JavaScript, siete pruebas de
Chrome (navegación y revocación, corrección abierta y guardado), Ruff y
`git diff --check` aprobados. Borrador conserva un único atajo tras actualizarse;
el expediente cerrado puede usar el acceso a sus acciones de consulta.

## Seguimiento de la auditoría visual

- [x] Guardar las ediciones al salir de Redacción y conservarlas al reabrir.
- [x] Unificar la posición y el orden de las acciones principales de etapa.
- [x] Alinear los colores de etapa y señalar la etapa actual completada.
- [x] Corregir contexto y orden de acciones en los paneles revisados.
- [x] Facilitar el retorno desde una fuente a la respuesta seleccionada en móvil.
- [x] Revisar tamaños mínimos de citas, estados y controles secundarios.
- [x] Unificar las variantes visuales de los estados «Por revisar» entre pantallas.
- [x] Revisar contraste de bordes de campos editables y acceso a acciones en páginas largas.
