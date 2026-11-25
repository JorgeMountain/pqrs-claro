import test from 'node:test';
import assert from 'node:assert/strict';
import {textRange, markedWords, focusedSentences, sourcePassageViewer} from '../src/pqrs_claro/static/recorrido/source-passage-viewer.js';

test('la selección mantiene el texto literal y los offsets originales tras normalizar espacios', () => {
  const text = 'Preámbulo.\n\n  Cada\t prueba\n   vale el 50%.';
  const quote = 'Cada prueba vale el 50%.';
  const range = textRange(text, quote, 3, 4);
  assert.equal(text.slice(...range), 'Cada\t prueba\n   vale el 50%.');
  const words = ['Preámbulo.', 'Cada', 'prueba', 'vale', 'el', '50%.'].map(word => [word, 1, 2, 3, 4]);
  assert.deepEqual(markedWords(words, quote), words.slice(1));
});

test('la línea archivada puede identificar una copia que la geometría no distingue', () => {
  const text = 'Cupo disponible.\nCupo disponible.';
  assert.deepEqual(textRange(text, 'Cupo disponible.', 2, 2), [17, 33]);
  assert.equal(textRange(text, 'Cupo disponible.'), null);
  const words = text.split(/\s+/).map(word => [word, 1, 2, 3, 4]);
  assert.deepEqual(markedWords(words, 'Cupo disponible.'), []);
  assert.equal(textRange('A A A', 'A A'), null);
  assert.equal(textRange('Cupos disponibles.', 'Cupo'), null);
  assert.equal(textRange('Respuesta literal.', 'Respuesta modificada.'), null);
});

test('una referencia previa sin ubicación conserva la cita y evita abrir otra página', () => {
  const html = sourcePassageViewer('case', {quote:'<cita>', source_id:'version-1'});
  assert.match(html, /&lt;cita&gt;/);
  assert.match(html, /\/api\/sources\/version-1\/original\?case_id=case/);
  assert.doesNotMatch(html, /<source-passage-viewer|#page=/);
});

const context = 'El proceso de admisión para aspirantes nuevos a programas de pregrado será clasificatorio, en orden descendente de acuerdo con los puntajes obtenidos. ' +
  'La selección de los aspirantes se efectúa así: los cupos ofrecidos en cada programa son asignados inicialmente a los aspirantes que lo seleccionan como primera opción. ' +
  'El aspirante admitido a la primera opción no puede hacer uso de la segunda y viceversa.';

test('una cita de página completa centra las tres oraciones pertinentes a los porcentajes', () => {
  const quote = '  4\n\n\n Competencia lectora.\n Prueba 2:\n Competencia en Razonamiento lógico.\n' +
    'Cada aspirante debe presentar ambas pruebas; cada una tiene un valor del 50%.\n' + context;
  const answer = 'Las competencias evaluadas eran Competencia lectora y Competencia en Razonamiento lógico. ' +
    'La guía para aspirantes nuevos de la convocatoria 2027-1 señala que cada una de las dos pruebas tenía un valor del 50%.';
  assert.deepEqual(focusedSentences(quote, [answer]), [
    'Competencia lectora.', 'Prueba 2: Competencia en Razonamiento lógico.',
    'Cada aspirante debe presentar ambas pruebas; cada una tiene un valor del 50%.',
  ]);
});

test('las cifras distintas, las excepciones y las coincidencias ambiguas mantienen la cita completa', () => {
  const sentence = 'La calificación de cada prueba tiene un valor del 50%.';
  const quote = sentence + ' ' + context;
  for (const answer of [
    'La calificación de cada prueba tiene un valor del 40%.',
    'La calificación de cada prueba no tiene un valor del 50%.',
    'La calificación de cada prueba tiene un valor del 50% o del 60%.',
  ]) assert.deepEqual(focusedSentences(quote, [answer]), []);
  assert.deepEqual(focusedSentences(sentence + ' ' + quote, [sentence]), []);
  assert.deepEqual(focusedSentences('La duración máxima de la prueba es de 3 horas. ' + context,
    ['La duración mínima de la prueba es de 3 horas.']), []);
  assert.deepEqual(focusedSentences('Salvo las exenciones, cada prueba tiene un valor del 50%. ' + context,
    ['Cada prueba tiene un valor del 50%.']), []);
});
