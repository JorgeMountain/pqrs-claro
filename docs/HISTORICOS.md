# Archivo histórico de peticiones y respuestas

Una respuesta anterior puede aportar lo que la institución ya informó sobre un asunto. Su utilidad depende de que corresponda a la persona, periodo, pregunta y documentos pertinentes. El sistema conserva esa respuesta y sus anexos como fuentes distintas, con referencias al original. Una petición anterior conserva lo que alguien solicitó o afirmó; por sí sola no acredita que se le hubiera respondido.

## Consultar y organizar

En **Biblioteca de fuentes → Archivo histórico** se puede filtrar por carpeta de procedencia, radicado, oficio y nombre. Cada archivo conserva sus alias, sus posibles relaciones con otros documentos y observaciones sobre borradores o diferencias de identificación. Los duplicados exactos comparten una fuente; archivos con bytes distintos permanecen separados aunque tengan nombres o números parecidos.

La incorporación conserva todos los originales. La extracción puede estar lista, ser parcial, estar pendiente de OCR o no estar disponible para el formato. El texto parcial conserva su advertencia. Un archivo sin texto sigue disponible como original y no se presenta como consultado por la búsqueda.

## Utilizar antecedentes en un expediente

Después de confirmar las solicitudes, en **Antecedentes para consultar** se selecciona la colección y se guarda la vinculación. Esto habilita su búsqueda para ese expediente. Desvincularla excluye sus documentos de búsquedas posteriores y marca desactualizados los resultados que dependían de ella. El catálogo histórico permanece disponible aunque no esté vinculado.

LangGraph recupera fragmentos y evalúa su pertinencia. Las respuestas previas aportan antecedentes atribuidos; los anexos aportan evidencia histórica o el documento solicitado cuando corresponde. Una referencia de estilo sigue siendo una categoría separada. Una mención de un anexo no reemplaza el archivo ni prueba que fue entregado.

La revisión registrada puede documentar quién comprobó una fuente y cómo lo hizo. Una declaración general de que algunas respuestas ya habían sido verificadas se conserva a nivel de colección y no marca indiscriminadamente todos sus archivos como aprobados. La pertinencia para la solicitud nueva se evalúa por separado.

## Persistencia y recuperación

- `data/library/`: original de cada fuente, con SHA-256.
- `data/biblioteca.sqlite`: fuentes, extracciones, colecciones, vínculos con expedientes, relaciones documentales y revisiones.
- `data/imports/<colección>/`: inventario de procedencias, resultado de importación y comprobaciones.
- `data/backups/`: copia coherente de SQLite previa a la importación.

Estos datos quedan fuera de Git. La importación no mueve ni altera los archivos aportados. Los ZIP se leen sin ejecutar su contenido ni extraer rutas arbitrarias. Los contenedores se conservan, incluso cuando no existe un lector para expandirlos.

`scripts/import_history.py` incorpora un inventario local con clasificación revisable. El importador comprueba los SHA antes de guardar, conserva nuevas procedencias de archivos repetidos y puede reintentarse. No llama a OpenAI para indexar el lote. La búsqueda con evaluación, cuando se solicita desde la aplicación, utiliza la configuración de OpenAI autorizada.

La lectura nativa no sustituye el OCR, una revisión institucional ni la comprobación de entrega de documentos. El respaldo de SQLite previo a importar tampoco sustituye una política de respaldo externo para originales y bases de datos.
