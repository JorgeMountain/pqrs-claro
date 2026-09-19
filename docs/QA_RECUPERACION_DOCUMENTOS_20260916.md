# Recuperación del contenido de documentos — 16 de septiembre de 2026

## Problema reproducido

La consulta de admisiones, recibida por correo y dividida en tres solicitudes,
tenía cuatro pendientes de fuentes. En la primera se recuperaba la portada de
la guía, pero no las competencias y ponderaciones; en la segunda no se encontraba
la duración. La tercera, sobre la credencial, ya encontraba soporte.

El corpus autorizado de la prueba contenía 1.021 fuentes y 22.549 fragmentos.
Los antecedentes de otros temas ocupaban buena parte del presupuesto de candidatos.
El asunto de la petición estaba disponible en el contexto, pero no se utilizaba
para localizar documentos antes de buscar sus pasajes.

## Cambio

- Canal adicional `document_content`: localiza hasta tres documentos mediante
  coincidencias discriminantes en sus títulos, nombres y grupos, usando el asunto
  cuando está disponible. Busca después la pregunta atómica en el cuerpo.
- Reserva como máximo dos pasajes por documento para este canal, dentro del límite
  global de 24 candidatos. Conserva la prioridad de referencias documentales explícitas.
- Normaliza variantes plurales y amplía términos generales de consulta, como
  tiempo/duración, solo para buscar. Las citas devueltas conservan texto y ubicación.
- El alcance autorizado, las versiones sustituidas y las fuentes privadas siguen
  filtrándose antes de buscar. No se incluyen respuestas ni identificadores de
  admisiones codificados en el algoritmo.
- Análisis versión 16: evita reutilizar checkpoints de búsquedas incompletas.
  Resultados anteriores satisfactorios siguen disponibles si coinciden sus entradas.

## Comprobación con IA real

Se respaldaron las bases SQLite y la caché semántica en una carpeta de QA excluida
de Git. La evaluación se ejecutó con `gpt-5.6-luna`, con todas las fuentes autorizadas
de la prueba original. No se cambiaron decisiones ni resultados del expediente vivo.

| Solicitud | Pasaje seleccionado | Pendientes de fuentes |
| --- | --- | --- |
| Competencias y porcentajes | Guía 2027-1 V4, página 4 | 0 |
| Duración del examen | Misma guía, página 44 | 0 |
| Impresión de credencial | Misma guía, página 44 | 0 |

Las tres evaluaciones devolvieron `references_found` y `support_found`, sin errores.
No se resolvieron pendientes manualmente ni se alteraron las políticas de suficiencia.
Esta comprobación cubre recuperación y evaluación de fuentes; no equivale a una
aprobación humana del oficio ni a validar toda futura consulta contra toda biblioteca.

Se añadieron nueve regresiones de localización por asunto, búsqueda dentro del
documento, preservación de citas, límites y aislamiento de fuentes. También se
ejecutaron los controles existentes de recuperación, evaluación y revisión.

## Uso en expedientes existentes

Recargar la página y, en «Preparar las respuestas», usar «Reintentar o actualizar
fuentes» si el caso mantiene los resultados anteriores. Cambiar el código no cierra
por sí solo sus pendientes guardados. No marcar «No aplica» para ocultar una
carencia de recuperación.
