# Omisiones y regresiones: continuación general del RAG

Fecha: 16 de noviembre de 2026. Implementación local conservada: **candidate-v2**.
Al finalizar ese ensayo no se había hecho commit, push, despliegue ni modificación
de expedientes vivos. El estado de integración posterior se documenta en
[INTEGRACION_CORRECCIONES_RAG_20261117.md](INTEGRACION_CORRECCIONES_RAG_20261117.md).
La comparación parte del árbol de trabajo aceptado de la ronda anterior
(`accepted-v3.2`), **no de un master limpio**. Los ensayos y el código de cada
candidato permanecen separados e inmutables en
`output/qa/rag-omisiones-general-20261116/`.

## Cambio general conservado

El plan identifica unidades de contenido pertinentes en los pasajes completos:
condiciones, alternativas, excepciones, fundamentos y pasos. Python materializa
sus citas literales y valida alcance, versión y permiso. La escritura y la
revisión comprueban las unidades frente al texto actual. No se añaden nombres de
expedientes, artículos ni respuestas de evaluación a las reglas de producción.

Las unidades de contenido se separan de controles de catálogo y de actuaciones
futuras. Esta separación corrige el primer piloto, que intentaba convertir
recordatorios de autenticidad o entrega en citas y bloqueaba algunos planes.
Una copia puede prepararse sin afirmar autenticidad ni entrega; una pregunta
mixta sigue exigiendo respaldo para el contenido explicado. Un pendiente
específico abierto no se sustituye por una alerta genérica de vigencia.

El inventario acompaña el guardado y las comprobaciones de Redacción. Una fuente
corregida invalida el inventario; la siguiente comprobación lo reconstruye con
los soportes actuales sin reescribir el texto humano. La revocación oculta las
citas derivadas, incluido el historial. Los resultados concurrentes obsoletos
se descartan antes de guardarse. Véanse
[UNIDADES_RESPUESTA_RAG.md](UNIDADES_RESPUESTA_RAG.md) y
[QA_UNIDADES_REVISION_20261116.md](QA_UNIDADES_REVISION_20261116.md).

## Comparación con las 40 solicitudes anteriores

Se reutilizó exactamente la misma selección y resultado del lector. Por tanto,
esta comparación mide conservación del contenido durante plan/redacción/check,
no una mejora del recuperador. La rúbrica original permaneció sin cambios y no
se envió a la IA. Se auditaron los textos, no sólo su estado `passed`.

| Criterio | Referencia anterior | Variante conservada |
| --- | ---: | ---: |
| Núcleo de la respuesta contestado | 37/40 | 37/40 |
| Rúbrica ampliada completa | 28/40 | 31/40 |
| Borradores generados | 40/40 | 40/40 |
| Respuestas antes completas que retroceden | — | 0 |

Las tres mejoras completas corresponden a equivalencias de escalas, integración
de informes y ramas de firmas, y fundamento de un umbral basado en un estudio con
sus autores. Son consecuencias de reglas generales de conservación del contenido.
Otra respuesta ahora hace visible una remisión normativa y conserva la brecha
específica para consultar su contenido; no se cuenta como si ese artículo ya se
hubiera leído. Se verificaron **54 apariciones de soportes y 133 citas literales
de unidades**. Los controles heredados del lector permanecen conservados.

La rúbrica ampliada incluye detalles adicionales de la fuente que algunas
preguntas no solicitan directamente. No se convierten automáticamente en nuevas
obligaciones ni pendientes. El conteo estricto se mantiene para comparabilidad;
no demuestra nueve documentos faltantes.

Evidencia consolidada: `accepted-consolidated.json`, con hashes y auditorías
independientes `audit-pilot-v2-01`, `audit-pilot-v2-02-04-05-08` y
`audit-pilot-v2-03-06-07`.

## Documentos y preguntas nuevos

Se redactaron y congelaron antes de la API doce preguntas de archivo patrimonial,
escuela de música, carga fluvial y sala comunitaria: **21 documentos, 29 fragmentos
y 74 puntos expresamente pedidos**. Hay listas divididas entre páginas, reglas de
ámbitos distractores, condiciones, alternativas, una contradicción de plazos,
copias y datos ya conocidos en el escrito. Las fuentes y la rúbrica se conservan
separadas; el ejecutor nunca carga la rúbrica como entrada de la IA.

| Prueba | Referencia | Variante conservada |
| --- | ---: | ---: |
| Respuestas completas | 12/12 | 12/12 |
| Puntos solicitados conservados | 74/74 | 74/74 |
| Respaldos con integridad comprobada | 23 | 24 |
| Errores de ejecución | 0 | 0 |
| Peticiones de datos ya conocidos | 0 | 0 |
| Preparación de archivos no solicitados | 0 | 0 |

La referencia ya respondía bien esas doce preguntas: este resultado demuestra
conservación, **no una ganancia de calidad sobre un resultado ya completo**.
La contradicción sigue abierta. Se mantienen los controles de procedencia,
vigencia, transcripción y entrega que correspondan. El rótulo explícito de
ficción provoca controles de identidad en algunas copias: no acredita una
identidad institucional real. La página de imagen usa transcripción de QA
determinista; prueba la propagación del control, no precisión de OCR real.

Después se añadió un quinto dominio, préstamo barrial de bicicletas, con tres
preguntas nuevas y 17 puntos: condiciones generales junto a una excepción,
efectos de procedimientos distintos y alcance positivo sin repetir exclusiones.
La variante conservada respondió **3/3 y 17/17**, con citas válidas y sin inventar
pendientes. Es una prueba semántica con dos fragmentos, no de recuperación difícil.

En total se verificaron **15 preguntas nuevas y 91 puntos**. Las doce primeras
tienen referencia anterior; las tres adicionales comparan los dos pilotos.
No deben presentarse como quince mejoras sobre master.

Evidencia: `holdout-comparison.json/.md`, `audit-candidate-v2.json/.md` y
`scope-holdout/audit-v2-v3.json/.md`.

## Latencia y consumo

En las doce preguntas, con índice preparado y servicio normal, el tiempo por
expediente hasta el borrador comprobado fue:

| Expediente | Referencia | Variante conservada |
| --- | ---: | ---: |
| Archivo | 56,97 s | 50,82 s |
| Música | 35,64 s | 39,52 s |
| Carga | 51,05 s | 54,66 s |
| Teatro | 73,92 s | 85,84 s |

La mediana pasa de 54,01 a 52,74 s, pero la media sube de 54,39 a 57,71 s.
**No se demuestra aceleración general.** Hubo 50→48 llamadas, 873.990→863.088
tokens de entrada y 48.271→58.314 de salida. No hay tarifa configurada para
convertirlos en costo monetario. Una observación por variante, caché y carga
compartida no permiten atribuir causalidad precisa a estas diferencias.

El límite configurado es cinco; al haber tres preguntas por expediente nuevo,
este ensayo ejecutó como máximo tres a la vez. La primera cita y el borrador
comprobado son tiempos distintos. Los cuarenta casos con lectura capturada
excluyen índice, catálogo, navegador y espera humana; no son latencia integral.

## Candidatos descartados y límites pendientes

El primer piloto falló al exigir citas a controles/acciones que no son contenido
literal: completó 9/12 preguntas nuevas. La variante conservada separa ambos
contratos y completó 12/12. Esos errores no se borraron del historial del ensayo.

Se probó después un ajuste adicional del inventario y del checker, `candidate-v3`.
Se **descartó**: una pregunta dejó de generar borrador por un contrato inválido,
otra perdió el fundamento que v2 había recuperado y otra dejó de registrar una
brecha específica reconocida. Tampoco corrigió la ambigüedad de procedimiento.
Sus doce preguntas nuevas sí conservaron 74/74: un buen resultado en un conjunto
no compensa regresiones observadas en otro. La producción local se restauró
exactamente al snapshot v2 y se verificó por hashes.

Quedan límites explícitos:

- Un texto mezcla el referente de una consecuencia después de mencionar dos
  procedimientos. La revisión independiente lo considera no listo aunque el
  checker devuelve `passed`. No se cuenta como corregido.
- El inventario semántico puede omitir un detalle o exigir una exclusión
  redundante. Las pruebas por sí solas no garantizan exhaustividad futura.
- Algunas remisiones necesitan recuperar/seleccionar más evidencia. Nombrar el
  artículo y conservar su pendiente no equivale a responder su contenido.
- El conflicto de normas sigue requiriendo determinar aplicabilidad; no se
  elimina para aumentar el porcentaje de respuestas.
- Identificar una resolución permite preparar una copia, pero no demuestra su
  consulta efectiva, autenticidad ni entrega. La actuación sigue pendiente.
- Un control ad hoc generado en un borrador antiguo puede variar al regenerarlo.
  La conservación comprobada aquí corresponde a los controles recibidos del
  lector y a las resoluciones registradas; no se afirma igualdad de toda frase
  de advertencia que el modelo haya propuesto históricamente.

La matriz mecánica incluye citas falsas/fuera de permiso, inventario incompleto,
unidades omitidas, contexto opcional, controles cerrados frente a abiertos, una
única reparación con nueva comprobación, edición humana, cambio concurrente de
fuente y revocación. Los resultados finales de pytest y del ensayo de defectos
controlados se registran junto a los artefactos anteriores.

## Defectos controlados y conservación de datos

Una prueba separada alteró deliberadamente seis respuestas ficticias correctas:
un elemento de lista, una finalidad, una condición de excepción, una autoridad
integradora, una alternativa convertida en acumulación y un límite de estabilidad.
Otros dos casos retiraron contexto opcional. Se congelaron antes de la API los
textos, fuentes, planes y criterios; ambas variantes recibieron el mismo texto y
pendientes, sin reparar ni redactar otra respuesta.

La referencia y v2 detectaron **6/6 defectos**. Ambos aceptaron uno de los dos
controles negativos; el otro se bloqueó por una expresión temporal preexistente,
no por retirar contexto. V2 también exigió una exclusión redundante junto a una
omisión real. Por tanto, esta prueba no demuestra mayor sensibilidad ni ausencia
de falsos positivos. La mediana de la comprobación pasó de 5,52 a 9,66 s; cada
variante hizo ocho llamadas. Entrada: 144.254→154.529 tokens; salida:
5.187→8.685. Son tiempos exclusivamente del checker, no hasta la cita validada.
Evidencia: `checker-mutations/audit-accepted-v2.json/.md`.

La lectura final de las cuatro bases reales, con conexiones de sólo lectura,
comparó el contenido lógico de 25 tablas seleccionadas y no encontró cambios
respecto a la huella anterior. Esta comprobación no representa un hash de todos
los archivos ni de todas las tablas del sistema. Evidencia:
`live-comparison.json` y `live-final-comparison.json`.

## Comprobación final de código

- Suite completa sobre el código conservado: **1.996 pruebas aprobadas** en
  521,74 s, con una advertencia previa de deprecación de Starlette/AnyIO.
- Ruff sobre `src/pqrs_claro` y `tests`: sin incidencias. `git diff --check`:
  sin errores de espacios; Git avisa de normalización CRLF/LF en algunos archivos.
- Los 97 módulos de producción coinciden por SHA-256 con `candidate-v2`.
- Las tandas focalizadas se incluyen en la suite; no se suman como pruebas nuevas.
- No se ejecutó navegador en esta ronda. Los ensayos reales usan los servicios
  de fuentes y borradores en copias aisladas; los contratos de revisión/guardado
  se verifican con pruebas de servicio/API y dobles explícitos del proveedor.

La primera suite detectó una expectativa antigua que buscaba `quote` en el plan.
Se actualizó para reconstruir literalmente `numbered_lines`, incluidos CRLF,
línea vacía y salto final, manteniendo la igualdad del alcance y las citas.
La suite intermedia del candidato rechazado se interrumpió y no cuenta como
validación final. El resultado completo corresponde al código restaurado.
Evidencia: `pytest-accepted-final.log`, `accepted-consolidated.json` y
`final-verification.json`.
