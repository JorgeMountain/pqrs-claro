# Archivo histórico de peticiones y respuestas

Una respuesta anterior puede aportar lo que la institución ya informó sobre un asunto. Su utilidad depende de que corresponda a la persona, periodo, pregunta y documentos pertinentes. El sistema conserva esa respuesta y sus anexos como fuentes distintas, con referencias al original. Una petición anterior conserva lo que alguien solicitó o afirmó; por sí sola no acredita que se le hubiera respondido.

## Consultar y organizar

En **Biblioteca de fuentes → Archivo histórico** se puede filtrar por carpeta de procedencia, radicado, oficio y nombre. Cada archivo conserva sus alias, sus posibles relaciones con otros documentos y observaciones sobre borradores o diferencias de identificación. Los duplicados exactos comparten una fuente; archivos con bytes distintos permanecen separados aunque tengan nombres o números parecidos.

La incorporación conserva todos los originales. La extracción puede estar lista, ser parcial, estar pendiente de OCR o no estar disponible para el formato. El texto parcial conserva su advertencia. Un archivo sin texto sigue disponible como original y no se presenta como consultado por la búsqueda.

## Utilizar antecedentes en un expediente

Después de confirmar las solicitudes, en **Antecedentes para consultar** se selecciona la colección y se guarda la vinculación. Esto habilita su búsqueda para ese expediente. Desvincularla excluye sus documentos de búsquedas posteriores y marca desactualizados los resultados que dependían de ella. El catálogo histórico permanece disponible aunque no esté vinculado.

LangGraph recupera fragmentos y evalúa su pertinencia. La búsqueda combina coincidencias generales con pasajes de contestaciones históricas localizados mediante expresiones explícitas de inicio de respuesta. Esto ayuda a distinguir la contestación de las preguntas reproducidas en un oficio; sigue siendo necesario revisar lo que cada fragmento permite afirmar.

Las respuestas previas aportan antecedentes atribuidos. También pueden representar el documento solicitado cuando se pide precisamente copia de ese oficio o respuesta y existen indicios de identidad en el archivo. Esta localización es preliminar: no certifica autenticidad, integridad, expedición ni entrega. Los anexos pueden aportar evidencia histórica o el archivo solicitado cuando corresponde. Una referencia de estilo conserva su uso separado.

Un correo de remisión puede respaldar la localización de ese correo cuando es lo pedido. Su lista de adjuntos no sustituye los archivos adjuntos ni demuestra que fueron recibidos o leídos. Del mismo modo, un oficio que menciona un acta no reemplaza el acta.

El periodo consultado se conserva. Si una nueva petición pregunta por hechos de 2015, los antecedentes y registros que se deben contrastar corresponden a 2015. La fecha reciente de la petición no obliga por sí sola a obtener registros actuales ni a repetir una comprobación ya documentada. Sí permanece pendiente revisar que el antecedente sea aplicable al asunto, persona y periodo concretos.

La revisión registrada puede documentar quién comprobó una fuente y cómo lo hizo. Una declaración general de que algunas respuestas ya habían sido verificadas se conserva a nivel de colección y no marca indiscriminadamente todos sus archivos como aprobados. La pertinencia para la solicitud nueva se evalúa por separado.

## Persistencia y recuperación

- `data/library/`: original de cada fuente, con SHA-256.
- `data/biblioteca.sqlite`: fuentes, extracciones, colecciones, vínculos con expedientes, relaciones documentales y revisiones.
- `data/imports/<colección>/`: inventario de procedencias, resultado de importación y comprobaciones.
- `data/backups/`: copia coherente de SQLite previa a la importación.

Estos datos quedan fuera de Git. La importación no mueve ni altera los archivos aportados. Los ZIP se leen sin ejecutar su contenido ni extraer rutas arbitrarias. Los contenedores se conservan, incluso cuando no existe un lector para expandirlos.

`scripts/import_history.py` incorpora un inventario local con clasificación revisable. El importador comprueba los SHA antes de guardar, conserva nuevas procedencias de archivos repetidos y puede reintentarse. No llama a OpenAI para indexar el lote. La búsqueda con evaluación, cuando se solicita desde la aplicación, utiliza la configuración de OpenAI autorizada.

La lectura nativa no sustituye el OCR, una revisión institucional ni la comprobación de entrega de documentos. El respaldo de SQLite previo a importar tampoco sustituye una política de respaldo externo para originales y bases de datos.

## Validar el uso de antecedentes

La validación documental usa una referencia preparada antes de ejecutar el modelo: solicitudes con citas de origen, fuentes esenciales esperadas, límites y afirmaciones que no deben hacerse. Cuando una solicitud se toma de su reproducción en una respuesta anterior, se identifica esa procedencia y se conserva la cita correspondiente; no se presenta como lectura de la petición original.

`scripts/validate_history.py` prepara una copia SQLite aislada en `output/validation-f4/`, conserva las referencias y ejecuta el grafo de fuentes de la aplicación. Los originales compartidos se consultan por lectura y se comprueban por SHA; los expedientes de prueba quedan separados de los expedientes de trabajo. Cada intento conserva sus llamadas, resultados, comprobaciones y configuración identificada por hashes del código.

El procedimiento y los comandos se describen en [FASE4.md](FASE4.md#validación-documental-reproducible). Encontrar una fuente esencial y conservar una cita exacta son comprobaciones técnicas. La pertinencia del pasaje, su alcance y la revisión institucional requieren valoración adicional. Los resultados efectivamente obtenidos y sus límites se registran en [VALIDACION.md](VALIDACION.md).
