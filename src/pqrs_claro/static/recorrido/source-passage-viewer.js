import {esc} from './views.js';

export function sourcePassageViewer(caseId, support, answerTexts = []) {
  const query = new URLSearchParams({case_id: caseId});
  const number = Number(support.page);
  const hasPage = Number.isInteger(number) && number > 0;
  const pageAnchor = support.location_kind !== 'section' && hasPage ? '#page=' + number : '';
  const original = caseId && support.source_id ? '<a class="source-passage-original" target="_blank" rel="noopener" href="/api/sources/' +
    encodeURIComponent(support.source_id) + '/original?' + query + pageAnchor + '">Abrir documento original ↗</a>' : '';
  if (!original || !hasPage) {
    return '<div class="source-passage-quote"><p>La cita guardada no tiene una ubicación disponible.</p><blockquote>' +
      esc(support.quote) + '</blockquote>' + original + '</div>';
  }
  return '<source-passage-viewer data-case="' + esc(caseId) + '" data-source="' + esc(support.source_id) +
    '" data-page="' + esc(support.page) + '" data-version="' + esc(support.version) +
    '" data-answer="' + esc(JSON.stringify(answerTexts)) +
    '" data-from="' + esc(support.line_start) + '" data-to="' + esc(support.line_end) + '">' +
    '<div data-passage-body aria-busy="true"><p role="status">Abriendo el respaldo…</p></div>' +
    '<details class="source-passage-quote"><summary>Leer cita textual</summary><blockquote>' +
    esc(support.quote) + '</blockquote></details>' + original + '</source-passage-viewer>';
}

// Whitespace may differ between the PDF text layer and the stored extraction.
// A repeated or partial-word match cannot identify a unique place on the page.
function uniqueRange(text, quote) {
  const needle = quote.trim().replace(/\s+/gu, ' ');
  if (!needle) return null;
  const normalized = text.replace(/\s+/gu, ' ');
  let range = null;
  const letter = /[\p{L}\p{N}]/u;
  for (let start = normalized.indexOf(needle); start >= 0; start = normalized.indexOf(needle, start + 1)) {
    const end = start + needle.length;
    if ((start && letter.test(normalized[start - 1]) && letter.test(normalized[start])) ||
        (end < normalized.length && letter.test(normalized[end - 1]) && letter.test(normalized[end]))) continue;
    if (range) return null;
    range = [start, end];
  }
  if (!range) return null;
  const original = [...range];
  let removed = 0;
  for (const space of text.matchAll(/\s{2,}/gu)) {
    const index = space.index - removed;
    if (index >= range[1]) break;
    const extra = space[0].length - 1;
    removed += extra;
    if (index < range[0]) original[0] += extra;
    original[1] += extra;
  }
  return original;
}

const functionWords = new Set('a al ante bajo con contra cada de del desde donde durante el ella ellas ello ellos en entre era eran es esa ese eso esta este estos fue ha han hasta la las le les lo los más muy o para pero por que quien se según ser son su sus sea sobre tras tu un una unas uno unos y ya'.split(' '));
const negative = new Set(['no', 'ni', 'nunca', 'tampoco', 'sin', 'excepto', 'salvo']);
const tokens = text => text.toLocaleLowerCase('es').match(/\d+(?:[-.,/]\d+)*(?:\s*%)?|[\p{L}\p{M}]+/gu)?.map(t => t.replace(/\s/g, '')) || [];
const numbered = t => /^\d/.test(t);

// Keep the entire source sentence, including qualifications. Select only on a
// distinctive literal sequence also found in a paragraph citing this passage.
export function focusedSentences(quote, answerTexts) {
  if (!answerTexts?.length || typeof Intl.Segmenter !== 'function' ||
      quote.length > 20000 || quote.trim().split(/\s+/u).length < 65) return [];
  const breaker = new Intl.Segmenter('es', {granularity:'sentence'});
  const sentences = text => [...breaker.segment(text.replace(/\s+/gu, ' ').trim())].map(s => s.segment.trim());
  const answers = answerTexts.flatMap(sentences).map(tokens);
  // An isolated page number separated by blank lines is outside the running text.
  const body = quote.replace(/^[ \t]*\d+[ \t]*\r?\n(?:[ \t]*\r?\n)+/u, '');
  const parts = sentences(body);
  const padded = parts.map(part => ' ' + tokens(part).join(' ') + ' ');
  const selected = [];
  for (const [index, part] of parts.entries()) {
    if (!/[.!?]$/u.test(part)) continue;
    // In a heading such as "Prueba 2:", the numeral labels the item.
    // The heading remains visible in full when the sentence is highlighted.
    const heading = part.match(/^(\p{L}+)\s+(\d+):\s+/u);
    const words = tokens(heading ? part.slice(heading[0].length) : part);
    const keyWords = new Set(words.filter(w => !functionWords.has(w)));
    const values = words.filter(numbered);
    const limited = words.some(w => negative.has(w));
    const found = answers.some(answer => {
      if (values.some(value => !answer.includes(value))) return false;
      if (values.some(v => v.endsWith('%')) && answer.some(v => v.endsWith('%') && !values.includes(v))) return false;
      const phrase = ' ' + answer.join(' ') + ' ';
      if ((limited || answer.some(w => negative.has(w))) && answer.join(' ') !== words.join(' ')) return false;
      if (values.length && [['mínim','máxim'],['máxim','mínim']].some(([from,to]) =>
        words.some(w => w.startsWith(from)) && answer.some(w => w.startsWith(to)))) return false;
      if (heading && answer.some((w, i) => w === heading[1].toLocaleLowerCase('es') &&
          numbered(answer[i + 1] || '') && answer[i + 1] !== heading[2])) return false;
      for (let first = 0; first < words.length; first++) {
        for (let end = first + 2; end <= Math.min(first + 8, words.length); end++) {
          const run = words.slice(first, end);
          const anchors = new Set(run.filter(w => keyWords.has(w)));
          if (anchors.size < 2 || ![...anchors].some(w => !numbered(w))) continue;
          if (!run.some(numbered) && anchors.size * 2 < keyWords.size) continue;
          const literal = ' ' + run.join(' ') + ' ';
          if (phrase.includes(literal) && !padded.some((p, j) => j !== index && p.includes(literal))) return true;
        }
      }
      return false;
    });
    if (found) selected.push(part);
  }
  return selected.length < parts.length ? selected : [];
}

export function textRange(text, quote, from, to) {
  const lines = text.split('\n');
  if (from >= 1 && to >= from && to <= lines.length) {
    const offset = from === 1 ? 0 : lines.slice(0, from - 1).join('\n').length + 1;
    const found = uniqueRange(lines.slice(from - 1, to).join('\n'), quote);
    return found && found.map(index => index + offset);
  }
  return uniqueRange(text, quote);
}

export function markedWords(words, quote) {
  const range = uniqueRange(words.map(word => word[0]).join(' '), quote);
  if (!range) return [];
  let offset = 0;
  return words.filter(([text]) => {
    const start = offset;
    offset += text.length + 1;
    return start < range[1] && offset - 1 > range[0];
  });
}

function textMarkup(text, ranges) {
  let start = 0, result = '';
  for (const [from, to] of ranges) {
    result += esc(text.slice(start, from)) + '<mark>' + esc(text.slice(from, to)) + '</mark>';
    start = to;
  }
  return result + esc(text.slice(start));
}

function centerMark(canvas) {
  const mark = canvas.querySelector('mark, .source-passage-mark');
  if (mark) canvas.scrollTop += mark.getBoundingClientRect().top -
    canvas.getBoundingClientRect().top - canvas.clientHeight / 3;
}

if (globalThis.customElements && !customElements.get('source-passage-viewer')) {
  customElements.define('source-passage-viewer', class extends HTMLElement {
    connectedCallback() {
      this.controller = new AbortController();
      this.load(this.controller.signal);
    }
    disconnectedCallback() { this.controller?.abort(); }

    async load(signal) {
      const {source, page, version} = this.dataset;
      const caseId = this.dataset.case;
      const body = this.querySelector('[data-passage-body]');
      const quoteBox = this.querySelector('details');
      const originalLink = this.querySelector('.source-passage-original');
      const quote = quoteBox.querySelector('blockquote').textContent;
      body.setAttribute('aria-busy', 'true');
      body.innerHTML = '<p role="status">Abriendo el respaldo…</p>';
      quoteBox.hidden = originalLink.hidden = true;
      const url = '/api/cases/' + encodeURIComponent(caseId) + '/source-versions/' +
        encodeURIComponent(source) + '/pages/' + encodeURIComponent(page) + '/view';
      try {
        const response = await fetch(url, {signal, cache:'no-store'});
        if (!response.ok) {
          if ([401, 403, 404, 409].includes(response.status)) {
            const error = await response.json().catch(() => ({}));
            if (signal.aborted) return;
            if (!(response.status === 404 && error.detail?.code === 'page_not_found')) {
              body.innerHTML = '<p role="status">Esta fuente ya no está disponible en el expediente.</p>';
              return;
            }
          }
          throw new Error('preview');
        }
        const meta = await response.json();
        if (signal.aborted) return;
        if (version && Number(version) !== meta.version) {
          body.innerHTML = '<p role="status">La versión disponible no coincide con la versión citada.</p>';
          return;
        }
        quoteBox.hidden = originalLink.hidden = false;
        const range = textRange(meta.text, quote, Number(this.dataset.from), Number(this.dataset.to));
        const focus = range ? focusedSentences(quote, JSON.parse(this.dataset.answer || '[]')) : [];
        const citedText = range ? meta.text.slice(...range) : '';
        const subranges = focus.map(part => uniqueRange(citedText, part));
        const focused = focus.length > 0 && subranges.every(Boolean);
        const ranges = focused ? subranges.map(([a,b]) => [range[0]+a,range[0]+b]) : range ? [range] : [];
        const pdf = meta.width > 0 && meta.height > 0;
        const isImage = /\.(?:png|jpe?g)$/iu.test(meta.filename);
        let words = pdf && range ? markedWords(meta.words, quote) : [];
        if (focused) {
          const groups = focus.map(part => markedWords(words, part));
          words = groups.every(group => group.length) ? groups.flat() : [];
        }
        const visualMarks = words.map(([, x0, y0, x1, y1]) =>
          '<span class="source-passage-mark" aria-hidden="true" style="left:' + 100*x0/meta.width +
          '%;top:' + 100*y0/meta.height + '%;width:' + 100*(x1-x0)/meta.width +
          '%;height:' + 100*(y1-y0)/meta.height + '%"></span>').join('');
        const original = originalLink.href;
        const preview = pdf ? '/api/sources/' + encodeURIComponent(source) + '/pages/' + encodeURIComponent(page) +
          '.png?' + new URLSearchParams({case_id:caseId}) : original;
        const img = pdf || isImage ? '<div class="source-passage-canvas" tabindex="0" aria-label="Página citada"><div class="source-passage-paper"><img src="' +
          esc(preview) + '" alt="' + esc(meta.filename) + (pdf ? ', página ' + esc(page) : '') + '"' +
          (pdf ? ' width="' + meta.width + '" height="' + meta.height + '"' : '') + '>' + visualMarks + '</div></div>' : '';
        const textView = '<div class="source-passage-transcript"><p>' +
          (meta.method === 'ocr' ? 'Transcripción OCR' : pdf ? 'Texto extraído de la página' : 'Texto de la sección') +
          '</p><pre class="source-passage-text" tabindex="0">' + textMarkup(meta.text, ranges) + '</pre></div>';
        body.innerHTML = (focused ? '<p class="source-passage-note">Coincidencias con la respuesta dentro de la cita.</p>' : '') +
          img + (visualMarks ? '' : textView);
        if (!range) quoteBox.open = true;
        if (pdf && !visualMarks) body.insertAdjacentHTML('beforeend',
          '<p class="source-passage-note">La ubicación exacta de la cita en la imagen está por verificar.</p>');
        const image = body.querySelector('img');
        if (image) {
          const canvas = image.closest('.source-passage-canvas');
          const loaded = () => {
            if (signal.aborted) return;
            if (image.naturalWidth) { centerMark(canvas); return; }
            canvas.replaceWith(Object.assign(document.createElement('p'), {
              textContent:'La imagen de la página no está disponible.'
            }));
            if (!body.querySelector('.source-passage-text')) body.insertAdjacentHTML('beforeend', textView);
            centerMark(body.querySelector('.source-passage-text'));
          };
          if (image.complete) loaded();
          else { image.onload = loaded; image.onerror = loaded; }
        }
        const transcript = body.querySelector('.source-passage-text');
        if (transcript) centerMark(transcript);
      } catch {
        if (signal.aborted) return;
        body.innerHTML = '<p role="status">No se pudo abrir esta página o sección. Puedes consultar la cita guardada.</p>';
        quoteBox.hidden = originalLink.hidden = false;
        quoteBox.open = true;
      } finally {
        if (!signal.aborted) body.setAttribute('aria-busy', 'false');
      }
    }
  });
}
