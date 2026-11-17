# Resultados de alcance temporal y contenido solicitado

Se probaron seis preguntas nuevas de tres dominios ficticios: conservación textil,
residencias de intercambio y filmoteca. La identificación estaba fijada y cotejada
contra los escritos; esta prueba no evalúa identificación por IA ni OCR. Los
criterios y documentos se sellaron antes de observar resultados y no se cambiaron.

## Ejecuciones y resultados conservados

| Ejecución | Alcance real | Rúbrica original | Checkers | Llamadas API |
|---|---|---|---|---:|
| `runs/candidate` | Fuentes y Redacción de seis preguntas | 22/24 completos; dos parciales | 4/6 `passed` | 31 |
| `runs/contract-final` | Replay de las siete respuestas del lector, sin nueva inferencia | Conserva cobertura y citas; corrige controles locales | No vuelve a redactar | 0 |
| `runs/fil-final` | Solo las dos preguntas de FIL, con fuentes preparadas | 7/8; combinado con TEX/RES anteriores: 23/24 | 2/2 de FIL `passed`; combinado: 5/6 | 6 |
| `runs/fil-identifiers` | Ensayo adicional de identificadores, solo las dos preguntas de FIL | 7/8; combinado sigue en 23/24 | 2/2 de FIL `passed` | 10 |
| `runs/contract-verified` | Replay final de las siete respuestas del lector, seis preguntas | Conserva respaldos, cobertura y todos los controles de `contract-final` | No vuelve a redactar ni revisar con IA | 0 |

Total de este corpus: **47 llamadas reales: 31 + 6 + 10**. Los replays y las
auditorías hicieron cero llamadas. El replay omite las 24 llamadas antiguas de
Redacción y reutiliza únicamente las siete respuestas del lector. No se ejecutó
una comparación completa adicional contra master. Tampoco se atribuye una nueva
ejecución a TEX y RES: sus cuatro respuestas proceden de la primera tanda.

## Qué quedó comprobado

- El resultado futuro conserva su carácter pendiente, su condición y las fechas,
  horas y lugares preguntados. La recepción ya documentada permanece en pasado.
- La lista común, las dos alternativas, los días calendario y las condiciones
  particulares de la reserva están completos. No se acumulan alternativas.
- El calendario informativo no crea seguimiento. La copia simple conserva una
  sola entrega no bloqueante, sin introducir autenticación.
- La prueba detectó una transformación local incorrecta: una entrega certificada
  propuesta correctamente como actuación futura se convertía en cotejo genérico
  bloqueante. La corrección conserva una entrega certificada específica y separada
  del cotejo material legítimo de autenticidad. FIL pasa de tres controles a dos.
- Se conservan seis respaldos y diez referencias válidas en el conjunto combinado.
  Las citas literales, versiones, hashes, permisos y los controles que llegan a
  Redacción se mantienen. Las dos repeticiones de FIL usan exactamente el mismo
  ID y resultados de fuentes; no se modificó el historial original.

El estado `partial` de FIL conserva un cotejo legítimo de autenticidad abierto;
puede coexistir con checkers `passed`. No significa que se haya perdido la cita ni
que la copia ya esté certificada o entregada.

## Límite de la rúbrica y decisión sobre el experimento

La rúbrica exigía incluir AR-66 al explicar que Q-518 conduce al Acta 581 y a AR-88,
en vez de al Acta 518 solicitada. AR-66 permanece en la fuente, pero no aparece en
la respuesta de ninguna repetición. Se conserva por tanto **23/24**, sin elevar la
puntuación retrospectivamente.

Una revisión independiente y ciega del alcance distinguió un dato pertinente de
uno indispensable: la relación Acta 518 → Acta 581 mediante Q-518 ya explica la
discrepancia y el cotejo necesario. La pregunta no exige enumerar todos los códigos
de las cintas. Este criterio sobredemandaba un literal contextual; su ausencia no
justifica forzar otra frase, abrir otro pendiente ni añadir una ronda de IA.

La extensión experimental `identifier` no mejoró la puntuación y se retiró del
código. Su estado exacto permanece en `retired-identifier-code`, además de los
snapshots y resultados del ensayo. La guía final pide que la relación sea
comprensible y conserve los datos indispensables para lo solicitado, sin convertir
códigos incidentales en obligaciones. **No hubo otra ejecución de API después de
ese matiz y de la retirada.**

Permanece la observación semántica de atribución de TEX/P1: el revisor pide atribuir
más claramente al aviso la condición inicial. El falso aviso local sobre «El aviso
prevé» se corrigió y se probó localmente; no se borró ni se sustituyó el dictamen de
la IA. Por eso el conjunto observado mantiene **5/6 checkers `passed`**, sin
proclamar aprobación integral ni una mejora comparativa de latencia.

## Validación y trazabilidad

Tras el último arreglo y el replay final: **529 pruebas focales aprobadas**, Ruff en
`src`, `tests` y cuatro scripts, y `git diff --check` sin errores. Una pasada amplia
previa aprobó 1386 pruebas. Son verificaciones de etapas y conjuntos superpuestos;
no se suman ni se presentan las 1386 como una nueva pasada del código final.

Una revisión local posterior encontró otra guarda necesaria en la deduplicación
de entregas: comparar también nombres de documentos no numerados y la modalidad
de copia, para no suprimir una entrega certificada por otra simple o dirigida a
otro archivo. Se corrigió y probó en las dos rutas de reutilización. El replay
intermedio `contract-release` detectó una regresión: la localización «disponible
en el archivo…» se confundía con el nombre del objeto, generando una entrega
genérica extra. Se separó esa cola explícita sin introducir coincidencias por
similitud. Los títulos distintos y las modalidades incompatibles siguen protegidos.

El nuevo replay `contract-verified` conserva exactamente los controles de las seis
preguntas de `contract-final`: 1, 0, 0, 1, 0 y 2 respectivamente. No cambia respaldos,
cobertura, requisitos ni citas; verifica versiones, hashes y permisos. Se reutilizan
las siete respuestas capturadas con red bloqueada, sin inferencia nueva ni cambios
al historial. Los resultados intermedios, incluida la regresión, se mantienen.
`validation-verified.json` registra las comprobaciones y los hashes del código final.
Estas pruebas locales no modifican las 47 llamadas ni equivalen a una nueva
redacción completa con la IA después del último ajuste.

Evidencia local en `output/qa/temporal-coverage-20261117/`:

- `audit-candidate.{json,md}`: los 22/24 iniciales y la causa del control extra.
- `audit-final-combined.{json,md}`: los 23/24 tras corregir la entrega, con origen
  explícito de cada respuesta.
- `runs/contract-final/{state.json,control-comparison.json}`: replay sin API,
  igualdad de modelo, instrucciones y payloads, y preservación de cobertura/citas.
- `runs/contract-verified/{state.json,control-comparison.json}` y
  `validation-verified.json`: replay del código final, controles idénticos a los
  esperados y 529 pruebas focales aprobadas; ninguna llamada o conexión de red.
- `runs/fil-final` y `runs/fil-identifiers`: fuentes, borradores, controles,
  capturas API y métricas de ambas repeticiones. La última tiene diez solicitudes
  y diez respuestas exitosas, sin mejora de cobertura respecto de las seis
  llamadas de la anterior; los pendientes son idénticos.
- Sello anterior a resultados:
  `../temporal-coverage-generalization-20261117/fixture-seal.json`.

Fixtures en `tests/fixtures/temporal_coverage_generalization_{content,rubric}.json`.
SHA-256 del contenido:
`0c47031285d8ba42c4856385f5ffb4e0079caaca0db9b0616238acabc508448a`.
SHA-256 de la rúbrica:
`1d95f3465f2837f342d9d4e4486c790bb6884db964829e029ab7e6de802bc68e`.

Durante la evaluación aislada no se modificaron expedientes productivos ni se
hizo commit, push o fusión. La integración posterior conserva la observación
de atribución pendiente y no equivale a aprobar ni recalcular expedientes reales.
