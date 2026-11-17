# Vigencia y cotejos documentales: copia, firma y trazabilidad

Corrección local del 17 de noviembre de 2026. Continúa el hallazgo documentado en
`PROCEDENCIA_Y_AUTENTICIDAD_SIN_DUPLICADOS.md`; no modifica sus resultados históricos.

## Problema y comportamiento corregido

Pedir copia de una norma, identificar a quien firmó y reconstruir el ingreso del
archivo no equivale a preguntar si esa norma está vigente o resulta aplicable.
El código confundía dos señales: el verbo «verifique» activaba una actuación
genérica, y «la firma corresponde a esa persona» activaba una interpretación de
efectos jurídicos por la palabra «corresponde».

Ahora se interpreta ese propósito documental únicamente al decidir si corresponde
el cotejo **genérico de vigencia del catálogo**. La pregunta original, su intención
global, citas y controles concretos permanecen intactos. No se autentica una firma,
resuelve una discrepancia, certifica ni entrega un documento por retirar ese aviso.

La regla funciona por alcance lingüístico y documental, sin números de resolución,
nombres propios ni expedientes incorporados al código.

## Guardas

- La excepción sigue limitada a `validity` con `basis=metadata_only`, una copia
  identificada y usos documentales (`document_delivery`/`attributed_content`).
- Preguntar por vigencia, derogación, aplicación, efectos jurídicos, derechos o
  una decisión para el caso conserva el control, incluso en un periodo histórico.
- No se confunde identidad con competencia para firmar. Las formulaciones
  ambiguas sobre a quién corresponde firmar y el fundamento normativo conservan
  el comportamiento prudente anterior.
- Los objetos de una verificación se evalúan antes de dividir las comas: «verifique
  la firma, la competencia del firmante» no se reduce a revisar solo la firma.
- Se respeta el contexto común o de la petición superior y se excluyen las otras
  preguntas independientes. El contexto incompleto no permite dar por descartada
  una consulta jurídica.
- Un cotejo material de vigencia, una contradicción, una transcripción dudosa y
  las comprobaciones de firma, autenticidad y procedencia continúan pendientes.
  Los usos como regla (`rule`) mantienen sus controles correspondientes.
- Las decisiones se conservan en `gap_decisions` como `non_blocking_metadata`.
  No se agregan llamadas de IA por búsqueda.

## Archivos y cachés

`src/pqrs_claro/source_sufficiency.py` incorpora la interpretación local de cotejos
documentales y la instrucción compartida por el lector, Redacción y revisión.
No se cambia `classify_request_intent` ni se reescribe la solicitud guardada.

Versiones: política 8, análisis 27, lector 7, Redacción 24/25 y revisión 19/20.
Las cachés nuevas distinguen esta política. No se han recalculado expedientes
reales ni modificado comprobaciones humanas ya guardadas.

## Pruebas offline

`tests/test_copy_authentication_legal_scope.py` usa tres documentos ficticios nuevos
en bibliotecas temporales. Sus 36 casos incluyen consultas documentales, jurídicas,
contexto heredado, ambigüedad de competencia, puntuación, discrepancias materiales,
transcripción, certificación y entrega. La referencia anterior falla en 12 de ellos
y aprueba 24. La política final, junto con las regresiones de copia certificada y
alcance jurídico relacionadas, pasa **157 pruebas**.

```powershell
.\scripts\dev-python.ps1 -m pytest tests/test_copy_authentication_legal_scope.py tests/test_certified_copy_validity.py tests/test_application_scope_regressions.py tests/test_source_application_scope.py -q
```

La suite ampliada de fuentes, Redacción, revisión y reutilización de comprobaciones
pasa **892 pruebas con el código final**; se registra en `affected-final-tests.txt`
dentro de la carpeta del ensayo. Ruff y `git diff --check` pasan. Los conteos de
suites se solapan; no deben sumarse. No se ejecutó la suite completa de Word/PDF
ni otros módulos ajenos a este cambio.

## Cuatro peticiones nuevas con el lector real

Se crearon dos PDF fuente distintos: un acuerdo sobre préstamo de telescopios y
una resolución sobre salas de ensayo. Cuatro peticiones nuevas y su rúbrica se
congelaron antes del ensayo. Toda la información es ficticia y el almacenamiento
está aislado de los expedientes reales.

Se hicieron **cuatro llamadas** al lector candidato. Para comparar la política
anterior y la nueva se reprocesaron exactamente esas cuatro respuestas, más las
dos respuestas anteriores que mostraban el problema, sin nuevas llamadas.
La referencia es el código local anterior a este cambio, no el `master` remoto.

| Consulta | Pendientes antes → después | Resultado del cotejo de vigencia |
|---|---:|---|
| A: copia, firma y registro de ingreso | 4 → 3 | Solo se retira el aviso genérico innecesario |
| B: copia auténtica, firma y archivo | 3 → 3 | Ya no tenía ese aviso innecesario |
| C: además pregunta por vigencia y derogación | 5 → 5 | Se conservan los controles jurídicos |
| D: además pregunta por aplicación y permiso personal | 4 → 4 | Se conserva la aplicación al caso |
| PROC-C anterior, primera respuesta | 3 → 2 | Se retira únicamente vigencia genérica |
| PROC-C anterior, segunda respuesta | 3 → 2 | Se retira únicamente vigencia genérica |

**6/6 comparaciones controladas** conservan exactamente respaldos, citas, cobertura,
brechas evaluadas, controles retenidos y acciones futuras. No aparece ningún
pendiente adicional; desaparecen solo tres avisos `validity + metadata_only`.
Tras las últimas guardas de puntuación y competencia, otro replay sin API confirmó
que los seis resultados completos del código final coinciden con el candidato
probado, incluida su auditoría.

Las cuatro lecturas nuevas recuperan el respaldo correcto y producen **4/4 citas
válidas**: literalidad, documento, versión, hash y permiso comprobados. El lector
no presenta firma o autenticidad como acreditadas. En D utiliza los 17 años y la
ausencia de autorización aportados en la petición, sin pedirlos de nuevo, y mantiene
condicionada la conclusión a la aplicabilidad de la norma.

Con el índice y E5 preparados, las citas quedaron persistidas en 15,971; 8,859;
19,721 y 25,162 segundos. No se hizo una medición pagada de latencia de referencia
y **no se afirma una aceleración**. Uso total: 32.623 tokens de entrada y 12.743 de
salida, cuatro llamadas, sin reintentos adicionales.

Artefactos locales: `output/qa/copy-auth-legal-scope-20261117/`, incluidos PDF,
rúbrica, snapshots, `reader-candidate.json`, `reader-review.md`,
`replay-comparison.json`, `policy-final-tests.txt` y `affected-final-tests.txt`.

## Alcance real

Al finalizar el ensayo del 17 de noviembre de 2026, el cambio estaba implementado
en el código local, sin commit, push ni despliegue. El estado de integración
posterior se documenta en
[INTEGRACION_CORRECCIONES_RAG_20261117.md](INTEGRACION_CORRECCIONES_RAG_20261117.md).
La comparación comprueba búsqueda, lectura y cita persistida; no es una aprobación
humana ni una prueba de expedición y entrega final. Otros controles genéricos de
identidad/procedencia observados en A y C son iguales antes y después y no se
eliminan mediante una regla de vigencia. El ensayo no garantiza ausencia universal
de redundancias ni interpretación perfecta de cualquier frase nueva.
