# Procedencia y autenticidad sin pendientes duplicados

## Cambio local

Continuación de `DISPONIBILIDAD_AUTENTICIDAD_ENTREGA.md` y
`VIGENCIA_COPIAS_CERTIFICADAS.md`, comprobada el 17 de noviembre de 2026.

Cuando ya hay un cotejo concreto de autenticidad o procedencia del archivo, el
estado `review_status` del catálogo no debe generar otra tarea equivalente.
El cotejo concreto permanece abierto, con su afirmación, motivo, citas y controles
humanos. No se declara autenticidad, certificación ni entrega por agrupar tareas.

También se corrige el problema inverso: dos comprobaciones materiales de
procedencia de un mismo documento antes podían compartir identificador y perder
una de sus descripciones. Ahora mantienen identidades distintas según la pregunta,
afirmación, explicación, fundamento y pasajes. Una aprobación de un cotejo anterior
no se aplica automáticamente a una discrepancia distinta.

## Condiciones y trazabilidad

- El genérico debe proceder del catálogo (`catalog_check=review_status`), ser de
  evidencia y tener fundamento `metadata_only`. La IA no puede emitir ese marcador
  mediante su esquema de salida.
- Debe existir un cotejo concreto de autenticidad, origen o trazabilidad **del
  archivo**. Solo autenticar la firma o el sello, aclarar una competencia, comparar
  un título o preparar una certificación futura no lo sustituye.
- Se exige la misma pregunta y la misma identidad documental: fuente, documento,
  versión, hash completo y revisión de extracción. Una revisión de extracción
  ausente se conserva como tal y no equivale a otra revisión numerada. Identidad
  insuficiente o distinta conserva los pendientes por separado.
- `gap_decisions` conserva el genérico original y los identificadores de los
  cotejos que lo cubren mediante `covered_by_specific_check`. No se crea una
  verificación ni se marca el material como resuelto.
- Redacción reutiliza esa relación para evitar reintroducir el mismo genérico.
  Después de una revisión humana, solo se reutiliza una relación ya auditada y la
  resolución del mismo cotejo, pregunta y versión. Un control resuelto sin esa
  relación previa no sirve para quitar un genérico nuevo.
- Los metadatos resumidos de candidatos ya no borran el hash del respaldo al
  normalizar pendientes. Los candidatos conservan además su hash y revisión de
  extracción para las comprobaciones posteriores.

Los controles de vigencia, aplicación, transcripción, diferencias de firma,
competencia, certificación y entrega conservan sus propios alcances. Esta mejora
no añade llamadas de IA ni reglas para un número, título o expediente particular.

## Código

- `src/pqrs_claro/source_assessment.py`: marca exclusivamente el genérico local y
  conserva la identidad de los candidatos.
- `src/pqrs_claro/evidence_contract.py`: identifica materiales, concilia el
  genérico, conserva auditoría y aplica la misma política en Redacción.
- `src/pqrs_claro/source_sufficiency.py`: instrucción común para lector, Redacción
  y revisión; política 7.
- Se invalidan las cachés afectadas: análisis 26, lector 6, Redacción 22/23 y
  revisión 17/18. No se modifican expedientes guardados ni se activa el piloto
  independiente de procedimientos.

## Validación

Las pruebas usan bibliotecas temporales y documentos ficticios nuevos. La
comparación real está acotada a cuatro llamadas por variante, sin repetir hasta
obtener un resultado favorable. La referencia es una copia del código local
inmediatamente anterior a este ajuste; **no es el `master` remoto**, que aún no
contiene las correcciones locales de los turnos anteriores.

Artefactos reproducibles locales: `output/qa/provenance-dedup-20261116/`.
El nombre de la carpeta conserva la fecha de inicio del ensayo.

Las 65 pruebas específicas nuevas cubren tres originales ficticios de categorías
institucional y nacional, varios tipos de cotejo, datos incompletos, cambio de
versión/hash/extracción, preguntas diferentes y revisión humana registrada. Una
regresión histórica detectada durante la integración se corrigió: el aviso local
de que un oficio es borrador conserva la obligación compartida de localizar su
versión expedida, sin duplicar un pedido simple de ese mismo documento.
Otra guarda conserva el marcador local en la auditoría aunque el modelo proponga
antes una fila genérica equivalente; así Redacción no puede reintroducirla por
haber perdido el origen de la decisión. La suite final de contrato, procedencia,
revisión humana y antecedentes históricos pasa **143 pruebas**.

La suite afectada de fuentes, suficiencia, reutilización de verificaciones,
Redacción y revisión pasa **803 pruebas**. Se ejecutó antes de la última guarda
del marcador, verificada después en las 143 anteriores y en el replay final de
las ocho respuestas. Los conteos se solapan; no deben sumarse. Ruff y
`git diff --check` pasan. No se ejecutó la suite completa de Word ni otros módulos
ajenos al cambio.

```powershell
.\scripts\dev-python.ps1 -m pytest tests/test_provenance_deduplication.py tests/test_provenance_dedup_verification.py tests/test_evidence_contract.py tests/test_historical_analysis.py -q
```

### Cuatro PQRS nuevas con el lector real

Dos PDF fuente nuevos (Circular 318/2025 sobre costura y Resolución 762/2023 sobre
huerto comunitario), cuatro PDF de peticiones, índice preparado y rúbrica congelada
fuera del payload. Las referencias de estos ensayos no aparecen en la política.

| Petición | Cita validada antes | Cita validada después | Pendientes de evidencia antes → después |
|---|---:|---:|---:|
| A: copia certificada de circular | 11,957 s | 9,369 s | 1 → 1 |
| B: copia auténtica de resolución | 12,349 s | 11,779 s | 1 → 1 |
| C: copia, firma y registro de ingreso | 15,724 s | 18,016 s | 3 → 3 |
| D: copia, vigencia y derogación | 20,133 s | 16,743 s | 3 → 3 |

Ambas variantes conservan **4/4 respaldos correctos y 4/4 citas válidas**, incluidos
texto literal, documento, versión, hash y permiso. Las lecturas independientes
generan textos y acciones diferentes; sus ocho pendientes por variante no son una
medición aislada del filtro. Ninguna salida afirma que certificación, firma,
trazabilidad, vigencia o entrega se hayan comprobado sin evidencia.

Para aislar la corrección se reprocesaron las **ocho respuestas capturadas** bajo
ambas políticas, sin otra llamada a la API:

- En la respuesta candidata de C, el código anterior genera cuatro pendientes;
  el nuevo conserva tres. Solo se retira la procedencia genérica, cubierta por el
  cotejo específico de ingreso del archivo. Firma, ingreso y vigencia permanecen.
- En otras respuestas, el conteo no baja porque el código anterior ya ocultaba
  el genérico al darle la misma identidad que al material. Ahora hay una relación
  de cobertura explícita y auditada, sin fundir dos controles materiales distintos.
- Los respaldos, la cobertura del lector y sus brechas evaluadas son idénticos en
  **8/8 replays**. Todos los controles materiales y acciones se conservan, salvo
  los identificadores que ahora incorporan su alcance concreto. No aparece ningún
  pendiente adicional. Se registran cinco relaciones de cobertura.

**Hallazgo pendiente:** C todavía recibe un cotejo genérico de vigencia aunque
pregunta por copia, firma y trazabilidad, no por efectos jurídicos. Ocurre antes y
después, y no se elimina mediante esta conciliación de procedencia. La pregunta D
sí pide vigencia y derogación, por lo que sus controles correspondientes deben
seguir abiertos. No confundir ambos casos ni presentar el ensayo como ausencia
total de pendientes innecesarios.

**Actualización del 17 de noviembre:** este hallazgo se corrigió posteriormente en
`VIGENCIA_Y_COTEJOS_DOCUMENTALES.md`, con cuatro peticiones nuevas y reprocesamiento
de las dos respuestas de C. Se conservan aquí los resultados del ensayo original.

Tiempo total de las cuatro corridas: 60,55 → 56,21 s. Una muestra por pregunta no
demuestra una mejora de velocidad. Fueron **8 llamadas**, 62.896 tokens de entrada
y 20.919 de salida (83.815 en total); el cambio no añade llamadas por consulta.

Los detalles exactos están en `reader-comparison.json`, `replay-comparison.json`,
los snapshots de código, las respuestas originales y sus validaciones dentro de
la carpeta del ensayo. `reader-final-review.md` recoge la revisión semántica;
`affected-final-tests.txt` conserva la ejecución de las 803 pruebas. El replay
posterior comprueba el código final sin repetir las llamadas pagadas.

## Alcance

Al finalizar el ensayo del 17 de noviembre de 2026, este cambio estaba implementado
en el código local, sin commit, push ni despliegue. El estado de integración
posterior se documenta en
[INTEGRACION_CORRECCIONES_RAG_20261117.md](INTEGRACION_CORRECCIONES_RAG_20261117.md).
Las pruebas de la IA comprueban búsqueda, interpretación del lector y
cita validada; no certifican aprobación humana, oficio final ni entrega efectiva.
El reconocimiento conservador de lenguaje nuevo puede conservar redundancias
ambiguas; no se usa similitud aproximada para borrar controles materiales.
