# Vigencia y copias certificadas

Cambio local validado el 16 de noviembre de 2026. Continúa la separación de
[disponibilidad, autenticidad y entrega](DISPONIBILIDAD_AUTENTICIDAD_ENTREGA.md).
La referencia es el código local anterior, con sus modificaciones acumuladas;
no se presenta como comparación contra el commit de master.

## Comportamiento

| Solicitud | Autenticidad/certificación | Vigencia de la norma |
|---|---|---|
| Copia certificada identificada | Conserva el cotejo pendiente | El estado desconocido del catálogo no crea por sí solo otro cotejo. |
| Copia certificada y confirmar si está vigente o derogada | Conserva el cotejo pendiente | Conserva el control de vigencia y la incertidumbre específica. |
| Copia certificada y explicar si aplica a una persona/caso | Conserva el cotejo pendiente | Conserva vigencia y aplicabilidad. |
| Aplicación en un periodo histórico | Conserva los controles pertinentes | Conserva el cotejo del régimen para ese periodo. |

Ofrecer una copia, certificarla, determinar sus efectos jurídicos y entregarla
son actuaciones distintas. Este cambio no certifica archivos ni cierra ninguna
comprobación humana. Una contradicción o brecha concreta de vigencia se conserva
aunque la solicitud incluya también una copia.

## Implementación

`source_sufficiency.py` añade `copy_without_legal_application`, independiente de
`copy_without_current_application`. El segundo conserva la política anterior de
autenticidad/procedencia; el nuevo se utiliza exclusivamente para `validity`.

La exención requiere una norma identificada como copia disponible, usos limitados
a copia o contenido atribuido y ausencia de una consulta de efectos jurídicos en
la pregunta, sus ancestros y el contexto común del escrito. No hereda solicitudes
de preguntas hermanas. El contexto truncado conserva la protección. La exención
anterior no puede anular un resultado negativo del control nuevo.

Se reconocen consultas de vigencia, derogación, aplicación, entrada en vigor,
efectos, suspensión y periodos históricos, respetando negaciones y contrastes.
Las etiquetas de la IA no pueden borrar una pregunta jurídica explícita.

La eliminación se limita a `validity` con `basis=metadata_only`, mediante
`classify_proposed_gaps`, conservando la propuesta y el motivo en `gap_decisions`.
No se alteran `content_gap`, contradicciones, autenticidad, identidad, OCR,
versiones, permisos ni entrega. Un `application=unresolved` puede referirse a
autenticidad: su incertidumbre material permanece, sin convertirla automáticamente
en una duda de vigencia normativa. Usar la fuente como `rule` mantiene sus controles.

La guía compartida informa de esta distinción al lector, planificador, redactor y
comprobadores. No hay agentes ni llamadas adicionales en el flujo del producto.

Versiones actuales: fuentes **25**, lector **5**, suficiencia **6**; borrador
**20**/revisión **15** en modo habitual y **21/16** con el auditor experimental.
Se invalidan cálculos antiguos para recalcular con la política nueva, sin
sobrescribir texto humano ni resolver pendientes existentes. El auditor
experimental sigue desactivado; no se recalcularon expedientes vivos.

## Pruebas locales

`tests/test_certified_copy_validity.py`: **71 pruebas** con tres normas ficticias
nuevas sobre juegos de mesa, vivero y archivo de mapas. Se conservan los archivos
en bibliotecas temporales y se fija la selección del lector para comparar entradas
idénticas, sin API.

Cubren copias certificadas, autenticidad con estados `supported/unresolved`,
vigencia/aplicación explícitas, derogación, vigor, suspensión, efectos, periodo
histórico, negaciones, contexto común/padre/hermano, contexto incompleto y brechas
materiales. El conjunto inicial de 50 casos reprodujo 18 fallos en la referencia;
se añadieron regresiones de lenguaje y alcance antes del cierre.

- Suite final de política y regresiones relacionadas: **247 pruebas aprobadas**.
- Suite de integración afectada de fuentes, Redacción y revisión: **646 aprobadas**.
  Esta ejecución precede a los dos últimos ajustes de alcance, comprobados en la
  suite final de 247 y en los replays. Los conteos tienen solapamiento; no sumarlos.
- Ruff y `git diff --check` aprobados. No se repitió la suite general de Word/PDF
  y otros módulos ajenos a este cambio.

```powershell
.\scripts\dev-python.ps1 -m pytest tests/test_certified_copy_validity.py tests/test_document_availability_dimensions.py tests/test_source_sufficiency.py tests/test_source_application_scope.py tests/test_application_scope_regressions.py tests/test_normative_attribution.py -q
```

## Comparación con el lector real

Cuatro PQRS nuevas, dos PDF fuente ficticios, datos aislados, índice preparado y
rúbrica congelada fuera del payload. Cuatro llamadas por variante; ocho en total,
sin repetir hasta obtener resultados favorables.

| Caso | Vigencia antes → después | Todos los pendientes antes → después |
|---|---:|---:|
| Copia certificada de circular | 1 → 0 | 2 → 2 |
| Copia certificada de resolución | 1 → 0 | 2 → 1 |
| Copia certificada y vigencia/derogación | 1 → 1 | 3 → 3 |
| Copia certificada y aplicación a persona de 17 años | 1 → 1 | 3 → 3 |

Resultado: vigencias innecesarias **2 → 0**, vigencias pertinentes **2 → 2**.
Autenticidad y entrega futura permanecen en los cuatro casos. Se conservan los
mismos cuatro respaldos y **4/4 citas válidas** en ambas variantes: texto literal,
identidad, versión, hash y permiso. El caso de aplicación conserva el mínimo de
18 años y no lo convierte en una decisión definitiva para la persona de 17 años.

El total real baja **10 → 9**, no 10 → 8: en el primer caso el modelo expresó la
autenticidad de otra manera y dejó además un control genérico de procedencia.
La metadata explícita de corpus ficticio influyó en esa valoración. No se oculta
la redundancia ni se atribuye ese cambio semántico al filtro.

Para aislar el cambio, se reprodujeron las ocho respuestas guardadas con el código
final y la misma auditoría de catálogo, sin nuevas llamadas:

- **4/4 respuestas de referencia:** solo desaparecen las dos vigencias genéricas
  (**10 → 8**). Todos los demás controles, resoluciones, acciones y respaldos son
  exactamente iguales; no se añade ningún pendiente.
- **4/4 respuestas candidatas:** controles, acciones y respaldos idénticos a los
  resultados guardados. Los ajustes finales no cambian esos cuatro casos.

Tiempo total del lector: **60,59 → 62,23 s**. Una ejecución por variante no permite
afirmar aceleración ni regresión de rendimiento. Uso: **8 llamadas**, 62.158 tokens
de entrada y 21.711 de salida (**83.869** en total). Este ensayo no incluye nueva
Redacción con API, aprobación humana, oficio ni entrega efectiva.

Artefactos locales: `output/qa/certified-copy-validity-20261116/`, incluidos los
PDF, rúbrica, snapshots, `reader-audit.md`, `reader-comparison.json`,
`replay-final-baseline.json`, `replay-final-candidate.json`, `affected-tests.txt`
y `policy-final-tests.txt`. Los hashes de fuentes y código se conservaron.

## Límites

Continuación: `PROCEDENCIA_Y_AUTENTICIDAD_SIN_DUPLICADOS.md` documenta el ajuste
posterior de procedencia y autenticidad, probado con otras cuatro PQRS ficticias.
Ese ensayo también identifica una vigencia genérica residual en una pregunta que
combina copia, firma y trazabilidad; los resultados históricos anteriores no se
modifican ni se generalizan como garantía para todas las preguntas mixtas.
La corrección posterior de esa combinación de copia, firma y trazabilidad está en
`VIGENCIA_Y_COTEJOS_DOCUMENTALES.md`, con nuevas pruebas y comparación controlada.

La interpretación de frases nuevas y la formulación de pendientes aún dependen
parcialmente de la IA. No se garantiza ausencia universal de redundancias. La
conciliación de constancias ausentes mencionada en el ensayo anterior no se ha
modificado aquí. Al finalizar el ensayo del 16 de noviembre de 2026, el cambio
permanecía en los archivos locales, sin commit, push ni despliegue. El estado de
integración posterior se documenta en
[INTEGRACION_CORRECCIONES_RAG_20261117.md](INTEGRACION_CORRECCIONES_RAG_20261117.md).
