# Recuperar contexto y contenido

Esta mejora conecta cada pregunta con su contexto y recupera contenido que antes
quedaba fuera de la búsqueda. Mantiene LangGraph, los originales y la revisión humana.

## El recorrido

1. **Entender a qué se refiere la pregunta.** La pregunta conserva su identificación
   original. Se adjuntan sus padres, la lista de subpreguntas y los numerales a los
   que remite expresamente. «CUARTO» se resuelve por su etiqueta, no suponiendo que
   su identificador interno es P4. Una sección anterior puede aportar contexto
   orientativo para «las preguntas formuladas», sin inventar una relación de padre.
2. **Leer las fuentes.** El texto nativo conserva sus páginas o secciones. En Windows,
   las nuevas fuentes PDF pueden usar OCR local. La reextracción de históricos se
   prepara en un plan y se aplica con respaldo, comprobación de huellas y control
   de concurrencia. OCR sigue marcado para cotejo; no convierte el documento en aprobado.
3. **Consultar solo el ámbito del expediente.** Antes de puntuar se excluyen otras
   colecciones, otros casos, fuentes reemplazadas y categorías ajenas a evidencia.
4. **Combinar búsquedas.** La consulta original conserva su propio canal. Se suman
   consultas de contexto, identificadores de documentos, entidades concretas como
   correos y embeddings multilingües locales. La fusión usa posiciones de ranking;
   no compara directamente números de BM25 con similitudes de vectores.
5. **Recuperar la contestación.** Si aparece una pregunta en un oficio anterior,
   se puntúa esa pregunta y se incorporan los párrafos contiguos de su respuesta.
   Pedir una copia se distingue de preguntar por el hecho mencionado en ese documento.
   Cada fragmento conserva su cita y coordenadas originales; no se fabrica una cita
   mezclando páginas ni se transforma la coincidencia en evidencia aprobada.
6. **Evaluar la solicitud.** Los dos nodos de LangGraph reciben la misma pregunta y
   su contexto. El evaluador debe usar ese contexto para resolver pronombres y
   referencias, sin convertir todas las preguntas relacionadas en requisitos nuevos.

## Límites deliberados

- Se conservan hasta 24 candidatos. Una respuesta contigua puede ocupar hasta ocho
  fragmentos y 6.500 caracteres; los documentos muy largos siguen requiriendo lectura
  directa. El evaluador mantiene su límite de ocho soportes seleccionados.
- La referencia del mismo escrito aporta contexto sobre lo solicitado; no acredita
  hechos institucionales. Las señales de ranking tampoco prueban autenticidad.
- Una referencia ambigua o truncada se identifica como tal. No se completa con datos inventados.
- Las páginas ilegibles, manuscritas o exclusivamente gráficas pueden seguir sin
  texto suficiente. Sus originales permanecen disponibles y la excepción se documenta.
- Los contadores de lectura de las colecciones se calculan con su contenido vigente,
  para que una reextracción no deje visibles las cifras de la importación inicial.

## Persistencia y ejecución

El índice semántico usa un modelo público descargado explícitamente y se ejecuta
localmente. Los documentos no se envían a un servicio de embeddings. Los vectores
se reutilizan por huella del texto y versión del modelo; una fuente modificada solo
requiere preparar sus fragmentos nuevos. La preparación guarda avance por lotes.
La página muestra el avance de preparación y después las solicitudes procesadas.

Si ese canal falla, la búsqueda textual continúa con una advertencia. Instalar el
modelo cambia la huella de la búsqueda. Un reintento después de un fallo temporal
del canal semántico descarta su checkpoint de recuperación anterior, conservando
las ejecuciones ya registradas. Los errores de evaluación mantienen su reanudación habitual.

La versión 8 de análisis y la revisión de extracción invalidan resultados anteriores.
Actualizar fuentes no reabre la identificación ni aprueba o publica una respuesta.

## Rendimiento de temas y fechas

La búsqueda de temas utiliza las posiciones del índice léxico para preseleccionar
fragmentos, y después aplica las mismas reglas de coincidencia, puntuación y orden.
La búsqueda de fechas también preselecciona candidatos, conservando palabras cortadas
y variantes Unicode. Cuando el índice puede omitir una variante, se mantiene el recorrido
completo. El filtro de permisos y colecciones se aplica antes de estas operaciones.

Esta optimización está integrada desde el 19 de octubre de 2026. No cambia el evaluador
Luna, las citas ni la versión de selección; no invalida ni reprocesa resultados guardados.
Se utiliza automáticamente cuando se ejecuta una nueva búsqueda con el código actualizado.

En la comparación local del 16 de octubre, 17 solicitudes de dos casos pasaron de
718,92 a 148,91 segundos de recuperación, con 408 resultados de candidatos idénticos
en contenido, orden y metadatos. Es una reducción observada del 79,29 % en esa muestra;
excluye carga inicial, validación de PDF, evaluación con Luna y redacción. Los resultados
se conservan en `../experiments/retrieval-speed-20261016/INFORME.md`.

## Comprobación

Las pruebas sintéticas cubren contexto, alcance, citas inmutables, coincidencias por
correo, respuestas contiguas, intención de entrega, caché, recuperación tras fallos
y conservación de resultados anteriores. Hay una prueba opcional con el modelo real
que recupera una paráfrasis y bloquea conexiones de red durante la inferencia.
`test_topic_prefilter.py` y `test_date_prefilter.py` comprueban además que la
preselección conserve coincidencias, citas, orden, alcance y cambios de texto.

`scripts/check_retrieval_benchmark.py` compara una referencia independiente con el
buscador real. Recibe explícitamente caso, fuentes, alcance y referencia; no escribe
en expedientes ni llama a un LLM. Falla si pierde un pasaje que antes recuperaba.
Los datos reales y sus resultados se conservan localmente en `output/qa/`, fuera de Git.
Una proporción de citas recuperadas en esa muestra no equivale a precisión global
ni al porcentaje de solicitudes completamente respondibles.

Esta entrega corresponde al primer bloque de corrección. La reutilización estructurada
de comprobaciones y la separación de los cuatro estados requieren su siguiente bloque.

Detalles operativos: [OCR local](OCR_LOCAL.md) y
[búsqueda semántica local](busqueda-semantica-local.md).
