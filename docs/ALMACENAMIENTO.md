# Dónde guardar la información

## Decisión para PQRS Claro

Mantener **Drive institucional como futuro repositorio de documentos del equipo**, preferiblemente una unidad compartida si está disponible en la institución. La fase 4 construye primero una biblioteca local para comprobar la carga, las versiones y la búsqueda con documentos controlados.

Drive resuelve una necesidad humana: organizar, compartir y conservar documentos. PQRS Claro necesita además su propio catálogo de fuentes, texto extraído, referencias y resultados por solicitud. Una carpeta por sí sola no aporta ese control.

| Opción | Cuándo la elegiría | Decisión para el proyecto |
|---|---|---|
| Biblioteca local | Desarrollo y piloto en este equipo, con un conjunto revisado | Es la opción implementada en la fase 4 |
| Drive institucional, unidad compartida | El equipo ya trabaja en Google Workspace | Primera opción para una futura conexión |
| SharePoint | La institución ya administra los documentos del equipo en Microsoft 365 | Alternativa preferible en ese entorno; evitar una segunda biblioteca paralela |
| Almacenamiento de objetos, como Amazon S3 | Aplicación alojada y con varios usuarios que justifique operación e infraestructura propias | Evaluar en una etapa posterior de operación |

Los archivos de una unidad compartida de Google pertenecen al equipo y permanecen cuando una persona sale de él. Esa propiedad hace que sea más adecuada que depender de una carpeta personal para el archivo institucional. Su disponibilidad concreta depende de la cuenta y de la configuración del administrador. [Documentación de Google](https://support.google.com/a/users/answer/7212025?hl=es).

SharePoint permite gestionar versiones y restaurar versiones anteriores de documentos. Si la institución ya usa ese entorno, aprovecharlo evita duplicar el lugar de trabajo del equipo. [Documentación de Microsoft](https://learn.microsoft.com/en-us/sharepoint/version-overview).

Amazon S3 permite conservar distintas versiones de un objeto. Encaja como almacenamiento de una aplicación alojada, pero requiere definir accesos, operación y costos; no reemplaza por sí solo una biblioteca de trabajo para las personas. [Documentación de AWS](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html).

## Qué se conserva ahora

La biblioteca local guarda el archivo original de cada versión y su huella SHA-256. El catálogo SQLite relaciona el documento con su categoría, procedencia, ámbito, revisión y estado de vigencia. El texto extraído y sus ubicaciones permiten recuperar fragmentos y volver al original.

Un resultado de búsqueda conserva las versiones concretas que utilizó y la solicitud que evaluó. Al cambiar una fuente o la información de la solicitud, puede quedar pendiente de actualizar. Eso permite explicar con qué documentos se produjo un resultado anterior.

El archivo del documento y el índice tienen funciones distintas:

| Capa | Contiene | Cómo se recuperaría |
|---|---|---|
| Originales | Archivos PDF, DOCX o TXT de cada versión | Desde la copia de respaldo del archivo o, en el futuro, del repositorio conectado |
| Catálogo y expediente | Identificadores, procedencia, revisiones, decisiones y resultados | Desde un respaldo coherente de la base de datos y sus archivos |
| Índice de búsqueda | Texto y términos derivados de los originales | Se puede reconstruir a partir de los documentos y el catálogo |
| Checkpoints | Punto de ejecución de LangGraph | Ayudan a continuar; no sustituyen los documentos ni el historial |

La configuración `PQRS_CLARO_DATA_DIR` indica el directorio local de datos. **La base SQLite en uso debe permanecer fuera de carpetas sincronizadas con Drive o OneDrive.** Una sincronización de archivos no coordina las escrituras de la base ni sustituye un respaldo consistente. Para trasladar el piloto se debe detener la aplicación y copiar juntos los datos y originales; antes de un uso institucional habrá que implementar y comprobar respaldo y restauración.

## Cómo conectaríamos Drive después

1. Seleccionar una biblioteca institucional y definir qué documentos puede leer la aplicación.
2. Registrar el identificador remoto, versión y procedencia de cada archivo incorporado.
3. Descargar las versiones autorizadas, extraer su texto e incorporarlas al catálogo propio.
4. Detectar cambios y marcar los resultados afectados para actualizar.
5. Mostrar el enlace institucional y la versión concreta utilizada, además del original conservado por la aplicación.

La conexión necesita credenciales y permisos del repositorio elegido. Esta entrega **no incorpora conectores de nube, cargas externas ni respaldo automático**. El OCR y la evaluación de pertinencia sí pueden transmitir a OpenAI el contenido necesario, con la configuración ya autorizada. Guardar documentos localmente no significa que todo su procesamiento sea local.
