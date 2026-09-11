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
