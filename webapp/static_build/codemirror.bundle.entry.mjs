import { EditorState, Compartment } from '@codemirror/state';
import { EditorView, keymap, drawSelection, dropCursor, highlightSpecialChars, highlightActiveLine, highlightActiveLineGutter, rectangularSelection, crosshairCursor } from '@codemirror/view';
import { history, defaultKeymap, historyKeymap } from '@codemirror/commands';
import { foldGutter, foldKeymap } from '@codemirror/fold';
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search';
import { closeBrackets, closeBracketsKeymap } from '@codemirror/closebrackets';
import { bracketMatching } from '@codemirror/matchbrackets';
import { autocompletion, completionKeymap } from '@codemirror/autocomplete';
import { lineNumbers } from '@codemirror/gutter';

// Languages
import { python } from '@codemirror/lang-python';
import { javascript } from '@codemirror/lang-javascript';
import { html } from '@codemirror/lang-html';
import { css } from '@codemirror/lang-css';
import { sql } from '@codemirror/lang-sql';
import { json } from '@codemirror/lang-json';
import { markdown } from '@codemirror/lang-markdown';
import { xml } from '@codemirror/lang-xml';

// Theme
import { oneDark } from '@codemirror/theme-one-dark';

const basicSetup = [
  lineNumbers(),
  highlightActiveLineGutter(),
  highlightSpecialChars(),
  history(),
  foldGutter(),
  drawSelection(),
  dropCursor(),
  EditorState.allowMultipleSelections.of(true),
  bracketMatching(),
  closeBrackets(),
  autocompletion(),
  rectangularSelection(),
  crosshairCursor(),
  highlightActiveLine(),
  highlightSelectionMatches(),
  keymap.of([
    ...closeBracketsKeymap,
    ...defaultKeymap,
    ...searchKeymap,
    ...historyKeymap,
    ...foldKeymap,
    ...completionKeymap
  ])
];

const languageCompartment = new Compartment();
const themeCompartment = new Compartment();

function getLanguageSupport(name) {
  switch (String(name || '').toLowerCase()) {
    case 'python': return python();
    case 'javascript': return javascript();
    case 'html': return html();
    case 'css': return css();
    case 'sql': return sql();
    case 'json': return json();
    case 'markdown': return markdown();
    case 'xml': return xml();
    default: return [];
  }
}

function getTheme(name) {
  if (String(name || '').toLowerCase() === 'dark') return oneDark || [];
  return [];
}

const api = {
  EditorState,
  EditorView,
  basicSetup,
  keymap,
  Compartment,
  languageCompartment,
  themeCompartment,
  getLanguageSupport,
  getTheme
};

if (typeof window !== 'undefined') {
  window.CodeMirror6 = api;
}

export default api;
