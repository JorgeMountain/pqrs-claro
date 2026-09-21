# Revisión de respaldos

La acción **Confirmar con respaldo** presenta pasajes para leer, con página,
líneas y enlace al documento original. Muestra hasta tres coincidencias próximas
al punto pendiente; el resto queda en **Ver otras fuentes**, con búsqueda por
nombre o contenido. No selecciona ni confirma un pasaje automáticamente.

Para una comprobación de transcripción o procedencia, prioriza el pasaje señalado
en el pendiente. Para fechas, muestra un extracto literal próximo a la fecha y
permite desplegar el pasaje completo. El orden ayuda a revisar; no certifica que
la fuente pruebe el hecho. El guardado conserva el identificador del pasaje
completo y exige la decisión explícita y su explicación.

## Calendarios

La versión 19 del análisis reserva candidatos según la relación entre la fecha
y el evento próximo en el texto. Evita que menciones de reglamentos antiguos o
inscripciones desplacen un calendario por repetir más palabras en toda la página.
Conserva las citas originales, los filtros de acceso y el límite de candidatos.

Los análisis anteriores incompletos deben actualizarse: cambiar el código no
reescribe resultados ya guardados. Los análisis anteriores satisfactorios
conservan la compatibilidad únicamente si coinciden todas sus demás entradas.

## Validación

Se añadieron regresiones con calendario, referencias normativas e inscripciones
competidoras, y preguntas formuladas con «cuándo». Pasaron 72 pruebas focalizadas.
La prueba con IA de una copia aislada de la solicitud de fechas recuperó la guía,
página 3, con respaldo encontrado y cero pendientes.

En Edge se comprobó el selector a 320, 768, 1024 y 1440 px, la búsqueda secundaria,
los enlaces al PDF, la selección obligatoria y el envío del identificador elegido
mediante transporte simulado, sin guardar confirmaciones reales. Evidencias
locales: `output/qa/calendar-supports-20260919/`.
