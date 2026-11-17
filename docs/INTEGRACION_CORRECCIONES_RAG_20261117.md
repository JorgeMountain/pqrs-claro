# Integración de correcciones generales del RAG

Paquete del 17 de noviembre de 2026 para integrar las correcciones acumuladas desde
`master` en `f7f9ce06332807b52c050508f172ce6402450ba7`. Los informes fechados del
índice describen ensayos y candidatos de cada ronda; sus referencias a trabajo
local o sin commit son estados históricos, no una instrucción de despliegue.

## Comportamiento habitual incluido

- Conserva el contexto literal de la petición original, sus incisos y ámbito al
  recuperar fuentes, leerlas, redactar y revisar. Los cambios en el original
  invalidan las evaluaciones dependientes.
- Mejora la selección general dentro de los 24 candidatos, con incorporaciones
  acotadas para documentos, listas y pasajes pertinentes. No garantiza exhaustividad
  ni usa identificadores de los expedientes de evaluación como reglas.
- Mantiene unidades de respuesta, autoridades y alternativas con citas literales.
  La revisión contrasta los incisos con el texto guardado y mantiene las omisiones
  como pendientes concretos; encontrar un respaldo no equivale a contestarlo.
- Separa consulta informativa, entrega documental y actuación futura. Una norma
  identificada puede respaldar su copia sin que ello pruebe autenticidad, envío,
  integridad frente a un original externo o aplicación jurídica.
- Distingue disponibilidad, autenticidad y entrega. El catálogo no genera una
  segunda tarea genérica de procedencia cuando existe un cotejo concreto del
  mismo archivo, versión y pregunta. Controles materiales distintos mantienen su
  identidad y no heredan una aprobación ajena.
- Pedir copia, certificación, firma o trazabilidad no exige por sí solo cotejar
  vigencia. Las preguntas jurídicas, contradicciones, transcripciones y controles
  materiales permanecen. La intención ambigua conserva el comportamiento prudente.

Estos cambios son generales para nuevos análisis. No recalculan expedientes vivos
ni cierran verificaciones humanas de forma retroactiva. La aprobación final sigue
requiriendo revisión humana y los controles de fuentes y permisos.

## Piloto conservado, sin activarlo

`PQRS_PROCEDURE_SCOPE_PILOT=false` es el valor predeterminado y el de la plantilla
de configuración. La bandera controla la lectura independiente que audita
referentes ambiguos de procedimientos; **no desactiva las correcciones compartidas
del inventario, contexto, copias y pendientes** descritas arriba.

El modo `true` queda disponible para ensayos explícitos. Integrar su código y sus
pruebas no equivale a aceptar sus resultados globalmente ni activarlo en la
instalación. Sus límites están en
[CLARIDAD_PROCEDIMIENTOS_RAG.md](CLARIDAD_PROCEDIMIENTOS_RAG.md).

Versiones de caché de este paquete: suficiencia 8, análisis de fuentes 27, lector 7,
Redacción 24/25 y revisión 19/20 (habitual/piloto). La configuración de cinco
preguntas concurrentes y el lector Fast no cambia en esta integración.

## Validación del paquete

La comprobación de integración cubre todos los archivos de pruebas nuevos o
modificados y las regresiones relacionadas de fuentes, recuperación, Redacción,
revisión, permisos y verificaciones. La lista exacta de 67 archivos y sus resultados
se guarda en `output/qa/rag-integration-20261117/pytest-files.txt` y `pytest.txt`.
También se ejecutan las pruebas JavaScript existentes, Ruff sobre `src tests
scripts` y `git diff --check`.

Resultado final del paquete: **1.713 pruebas Python aprobadas** (67 archivos,
314,91 s), **234 JavaScript aprobadas**, Ruff completo y comprobación del diff
preparado aprobados. Solo apareció un aviso de deprecación de una dependencia de
pruebas; no hubo fallos. La configuración efectiva comprobada conserva piloto
`false`, cinco preguntas concurrentes y lector `fast`.

Las pruebas utilizan almacenamiento temporal y dobles locales. En esta integración
no se vuelven a pagar lecturas de la IA: se conservan los resultados de los ensayos
previos y sus comparaciones controladas. No se afirma haber repetido toda la suite
de Word/PDF ni haber desplegado o reiniciado la instalación.

Las dos últimas correcciones aportan evidencia adicional:

- [Procedencia y autenticidad](PROCEDENCIA_Y_AUTENTICIDAD_SIN_DUPLICADOS.md):
  cuatro peticiones nuevas y ocho respuestas reprocesadas conservan respaldos y
  controles materiales; se documenta la cobertura del genérico sin cerrar cotejos.
- [Vigencia y cotejos documentales](VIGENCIA_Y_COTEJOS_DOCUMENTALES.md): cuatro
  peticiones nuevas, cuatro citas válidas y seis comparaciones con respuestas
  idénticas. Desaparecen solo tres avisos genéricos innecesarios; las consultas de
  vigencia y aplicación personal mantienen sus controles.

Los informes conservan las limitaciones semánticas observadas. La integración no
es una garantía universal de que toda petición nueva quede sin omisiones o
redundancias, ni una mejora acreditada de latencia.

## Contenido que se versiona

Se guardan código, pruebas, plantilla de configuración e informes de resultados.
Las bases, documentos originales, bibliotecas, credenciales, capturas de API y
artefactos de ejecución permanecen fuera de Git mediante las exclusiones existentes.
Las pruebas reproducibles incluidas construyen sus propias fuentes ficticias.
