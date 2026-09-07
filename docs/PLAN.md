# Un recorrido comprensible para responder PQRS

## Objetivo del producto

Recibir una petición y sus soportes, identificar cada solicitud, localizar evidencia pertinente, preparar respuestas, resolver faltantes con el responsable y generar un oficio institucional fiel a una versión aprobada.

El proyecto anterior permanece como referencia. La nueva base tiene su propio repositorio Git, configuración, dependencias y almacenamiento. El aprendizaje se conserva; las funciones entran cuando su etapa y sus pruebas las justifican.

## Entrega 1: partes 1 a 3

| Parte | Construcción | Demostración que la cierra |
|---|---|---|
| 1. Definir el resultado | Objetivo, ejemplos ficticios y resultados esperados | Comparar lo esperado con lo observado por solicitud |
| 2. Construir la base | Contratos, grafo corto, expedientes y checkpoints | Pausar, cerrar y continuar sin perder correcciones |
| 3. Comprender la petición | PDF por página, OCR, identificación y referencias | Ver la solicitud junto al original; corregir y confirmar |

La primera entrega termina en **Identificación confirmada**. Esa confirmación significa que una persona contrastó la lista de solicitudes; no aprueba una respuesta ni completa una PQRS.

## Ejemplo que acompaña el desarrollo

`peticion_ejemplo.pdf` contiene tres solicitudes, distribuidas en dos páginas. Todo su contenido es ficticio.

| Solicitud | Qué se espera identificar ahora | Qué hará falta en etapas posteriores |
|---|---|---|
| Procedimiento y requisitos | Una solicitud con ambas condiciones, página 1 | Reglas aplicables al trámite, revisadas |
| Fecha y estado del caso | Una solicitud que pide esos dos datos, página 1 | Registro o aporte atribuido a quien los conoce |
| Copia del acta | Una solicitud documental, página 2 | El archivo; conocer su contenido no reemplaza la copia |

El documento no incluye nombre de solicitante ni acredita recepción. Estos campos no deben completarse por inferencia.

## Casos de evaluación

La referencia legible por código está en `examples/cases.json` y los PDF se regeneran con `scripts/make_examples.py`.

| Caso | Resultado esperado |
|---|---|
| Principal | 3 solicitudes con página y fecha literal correctas |
| Subapartados | 4 elementos: padre, apartados a/b y otra solicitud; conservar relación entre páginas |
| Sin fecha | 1 solicitud; nombre y fecha permanecen ausentes |
| Escaneado | 1 solicitud; OCR visible y revisión de imagen requerida |
| Sin solicitudes | Detención explicada, sin inventar una petición |
| Reservado | 2 solicitudes; se evalúa después de fijar las instrucciones |

Se valida contra la referencia humana, no solamente contra los IDs producidos por la IA. Las citas deben coincidir con las líneas extraídas; la pertinencia de esas líneas se contrasta en los ejemplos. Un caso aprobado no demuestra exactitud en cualquier documento.

## Reglas de aceptación

1. Conservar el original y su huella, sin recortarlo ni sustituirlo.
2. Mantener páginas y referencias para localizar cada solicitud, incluidos sus apartados.
3. Diferenciar extracción nativa y OCR; no presentar una transcripción incierta como verificación humana.
4. No inventar solicitudes, personas ni fechas ausentes.
5. Guardar correcciones como versiones y rechazar escrituras con versión antigua.
6. Recuperar la pausa después de reiniciar y confirmar el contenido humano guardado.
7. Mostrar errores de lectura, límites o proveedor como problemas pendientes, sin resultados simulados.
8. Permitir comprender la pantalla y operar el recorrido con teclado y en una pantalla pequeña.

## Entrega 2: parte 4

Construir una biblioteca local de fuentes PDF, DOCX y TXT con originales versionados, procedencia, revisión atribuida y vigencia explícita. Buscar fragmentos por solicitud, evaluar su pertinencia y mostrar el respaldo junto a los faltantes.

La demostración utiliza las reglas ficticias de Aula Abierta y un registro ficticio de EJEMPLO-042: P1 debe recuperar procedimiento y requisitos; P2, recepción y estado al corte del registro; P3 debe continuar pendiente porque no está el acta.

LangGraph coordina un recorrido de fuentes separado de la identificación. Los resultados conservan las solicitudes y versiones utilizadas, los avances parciales y la necesidad de actualizarse cuando cambia la biblioteca.

El alcance detallado y los criterios de aceptación están en [FASE4.md](FASE4.md). La decisión inicial sobre alojamiento es biblioteca local durante el piloto y futura conexión a Drive institucional, preferiblemente una unidad compartida. [ALMACENAMIENTO.md](ALMACENAMIENTO.md) compara las alternativas y distingue el repositorio humano del catálogo propio.

## Lo que sigue

Parte 5: plan, redacción y comprobaciones con evidencia. Parte 6: revisión humana de respuestas y faltantes. Parte 7: DOCX/PDF fieles a lo aprobado. Parte 8: evaluación ampliada, operación e integraciones concretas.

Cada nueva entrega debe mostrar qué entra, qué transforma Python, qué propone la IA, qué coordina LangGraph y qué se puede comprobar al terminar. Mantendremos un plan y un repositorio, con cambios registrados en Git.
