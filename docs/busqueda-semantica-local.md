# Búsqueda por significado en el equipo local

El canal semántico de `source_semantic.py` compara el significado de una pregunta
con fragmentos originales de fuentes ya autorizadas para ese expediente. Lo
complementan los canales de texto, identificadores y entidades del recuperador.
Una puntuación semántica sirve para ordenar candidatos; no certifica que un hecho
sea verdadero, que un documento sea auténtico ni que aplique al nuevo caso.

Se utiliza `intfloat/multilingual-e5-small`, con 384 dimensiones, prefijos
`query:` / `passage:`, media de tokens y normalización. La inferencia ONNX se hace
en CPU. Tanto el modelo como los vectores permanecen en el equipo: la instalación
descarga archivos públicos del modelo y nunca envía documentos o consultas.

## Instalación y ejecución

Después de instalar las dependencias del proyecto, el modelo se descarga de forma
explícita, una sola vez:

```powershell
.\scripts\dev-python.ps1 -m pqrs_claro.source_semantic --download
```

No hay descargas al importar el módulo ni al buscar. La versión de los archivos
está fijada por revisión de Hugging Face, y la huella SHA-256 del ONNX se comprueba
antes de cargarlo. El archivo ONNX ocupa aproximadamente 118 MB; el resto de
archivos incluye el tokenizador. No se requiere GPU ni una API key nueva.

La aplicación usa `data/semantic` junto a su directorio de datos. Para preparar
un corpus congelado sin alterar expedientes:

```powershell
.\scripts\dev-python.ps1 -m pqrs_claro.source_semantic `
  --chunks output/audit-peticion-maquinas/chunks.json
```

`SemanticIndex.prepare(chunks)` completa la caché antes de recorrer los numerales.
`rank(query, eligible, limit=60)` devuelve copias de los fragmentos elegibles con
su puntuación. Una instancia reutiliza el modelo y los vectores entre consultas.
La aplicación limita normalmente la inferencia a cuatro hilos de CPU y lotes de
ocho textos. La preparación explícita permite ajustar `--threads 8` en equipos
que dispongan de suficientes núcleos. Preparar decenas de miles de fragmentos por
primera vez puede tomar varios minutos; ese coste no se repite por pregunta.

## Persistencia y límites

Con E5 instalado, el trabajador de la biblioteca detecta fuentes recuperables
al arrancar y al cambiar el catálogo. Prepara en segundo plano documentos
nuevos, nuevas versiones y correcciones de OCR antes de que llegue una pregunta.
Una colección histórica entra en este proceso cuando está vinculada a un
expediente autorizado. El servicio vuelve a comprobar el ámbito y la vigencia
al buscar.

La cola se conserva en disco. El equipo dedica CPU local a la indexación mientras
la aplicación está abierta. La primera búsqueda puede encontrar una preparación
en curso, especialmente después de incorporar una colección grande. En ese caso
usa el índice léxico y los vectores ya disponibles, e informa la cobertura
semántica pendiente. El avance del trabajador se consulta en
`GET /api/library/semantic-preparation`.

- `data/semantic/models` contiene el modelo público.
- `data/semantic/embeddings.sqlite` contiene vectores y huellas, en una base
  independiente de los expedientes. La clave incorpora modelo, revisión,
  configuración y SHA-256 del título más texto original.
- La indexación guarda cada lote. Un reinicio reutiliza lo terminado; un cambio
  de contenido calcula únicamente los vectores nuevos. Cambiar una revisión
  humana no modifica el significado del texto original.
- Los lotes agrupan textos de longitud similar para reducir el relleno del
  tokenizador, conservando el contenido. E5 admite hasta 512 tokens por vector;
  el fragmento que recibe el evaluador conserva su cita completa.
- La caché puede contener otros expedientes, pero la matriz de puntuación se
  construye exclusivamente a partir de `eligible`. El índice nunca incorpora
  por su cuenta una colección o un documento no autorizado.
- Si falta el modelo o falla el canal, se expone `warning` y continúa la búsqueda
  por los demás canales. El canal no inventa candidatos para disimular el fallo.

## Reutilización de matrices y selección exacta

Las matrices de puntuación se reutilizan entre preguntas de una misma ejecución.
La clave conserva el orden de las huellas del título y texto de los fragmentos
elegibles. Los identificadores, versiones, citas y metadatos se toman siempre de
la consulta actual: compartir un vector no incorpora un documento fuera de ámbito.

`PQRS_CLARO_SEMANTIC_MATRIX_CACHE_MB` configura el presupuesto estimado de esta
caché en MiB. Acepta enteros de 0 a 1024, con 512 como valor predeterminado. Se puede
definir en `.env.local` o en el entorno del proceso; el entorno tiene prioridad.
La aplicación lee la opción al arrancar. En código, `SemanticIndex` admite el
equivalente en bytes mediante `matrix_cache_bytes`.

Se conservan como máximo cuatro matrices dentro del presupuesto, contando sus
valores numéricos y una estimación del costo de sus claves. Se expulsan matrices
antes de reservar su reemplazo. El valor 0 desactiva la reutilización; una matriz
que excede el presupuesto se calcula temporalmente sin conservarse. Este límite
no cubre toda la RAM: el modelo, vectores, textos, matrices temporales y demás
componentes necesitan memoria adicional. El servicio procesa un expediente a la
vez y comparte la instancia semántica entre sus solicitudes.

La selección obtiene el umbral de los mejores candidatos sin ordenar todo el
corpus. Los empates en ese umbral se resuelven por `chunk_id`, conservando el orden
de entrada si también coincide el identificador. Se usan las puntuaciones sin
redondear y el mismo producto matricial; no es una búsqueda aproximada. El cambio
no modifica el modelo, los embeddings ni la política de evidencia, ni fuerza a
reprocesar los resultados guardados.

El avance de implementación y sus mediciones se registran en
[OPTIMIZACION_RAG.md](OPTIMIZACION_RAG.md).

## Comprobaciones

```powershell
.\scripts\dev-python.ps1 -m pytest tests/test_source_semantic.py -q
```

Las pruebas cubren persistencia, cambios de contenido y modelo, aislamiento de
otros expedientes, reanudación tras interrupción y errores. Una prueba adicional,
ejecutada cuando está instalado el modelo, recupera una paráfrasis en español
sin términos discriminantes compartidos. Esta prueba nunca descarga el modelo.

Referencias técnicas: [ejemplo oficial de FastEmbed para E5-small](https://github.com/qdrant/fastembed#-dense-text-embeddings),
[informe de los autores de Multilingual E5](https://arxiv.org/abs/2402.05672),
[revisión del modelo utilizada](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3).
