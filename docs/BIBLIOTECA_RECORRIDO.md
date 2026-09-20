# Biblioteca real en el recorrido de 8772

El botón **Biblioteca de fuentes** abre el panel lateral conservando las tarjetas y el documento de la petición. Permite:

- Buscar documentos compartidos por título, archivo, radicado incluido en el nombre, procedencia o nombre de colección. Esta búsqueda filtra el catálogo; no es búsqueda semántica dentro del contenido.
- Filtrar por tipo y estado de extracción, y recorrer todos los resultados con paginación.
- Consultar texto extraído por página/sección y abrir el original.
- Consultar versiones anteriores y cargar nuevas versiones de normas, respuestas y anexos históricos, conservando el original y la colección de procedencia.
- Cargar PDF, DOCX, TXT e imágenes mediante el servicio existente. Los duplicados exactos se reutilizan dentro del mismo alcance y tipo. La carga no certifica el contenido ni aprueba respuestas.

La biblioteca compartida incluye las colecciones importadas de ONMAN y Drive. No muestra soportes privados de otros expedientes ni sincroniza Drive automáticamente. La selección de las colecciones aplicables a una petición sigue siendo parte de su alcance de búsqueda; ver un documento en el catálogo no acredita que responda a una solicitud.

## Operación y conservación

Desde el 19 de septiembre de 2026, `scripts/start-recorrido.ps1` y `scripts/start.ps1` inician interfaz y API en un solo proceso (`pqrs_claro.unified_app`) en 8772, usando los mismos datos de `data/`. Si ya está activo, comprueban la instancia existente. No se inicia un backend adicional en 8770 ni se copia la biblioteca.

La interfaz está en `src/pqrs_claro/static/recorrido/`; los recursos/documentos de la demo se sirven desde `output/ux-peticiones-20260910/`. Esa versión anterior queda conservada. Se guardaron además copias de sus archivos de interfaz y de las bases relevantes en `output/qa/library-recorrido-20260910/`.

Si el servicio no está disponible, el panel muestra un error con reintento. No sustituye la biblioteca real por resultados de demostración.

## Validación y límite de esta entrega

Se probaron los contratos de carga compartida, duplicado, versiones, conservación del original, alcance privado y errores de conexión. Una norma importada conserva su colección al agregar una versión. En navegador se cargaron fuentes ficticias exclusivamente en la copia QA, se consultaron ambas versiones, se probaron filtros y se comprobó el panel a 320, 768, 1024 y 1440 píxeles. La comprobación en 8772 utilizó lecturas de los documentos reales.

El recorrido permite cargar y seleccionar expedientes reales. Al confirmar las solicitudes inicia automáticamente la búsqueda y preparación de respuestas; ver [preparación automática](PREPARACION_AUTOMATICA.md). La carga compartida sin expediente sigue guardando únicamente la fuente, sin iniciar una búsqueda ni reescribir la demo.

La demo original y sus descargas se conservan como ejemplo separado. La aprobación y exportación del oficio real aún deben conectarse al recorrido; la resolución de pendientes ya guarda decisiones reales; los servicios correspondientes y la interfaz anterior siguen disponibles.
