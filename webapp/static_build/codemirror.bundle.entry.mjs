import { EditorState, Compartment } from '@codemirror/state';
import { EditorView, keymap, drawSelection, dropCursor, highlightSpecialChars, highlightActiveLine, highlightActiveLineGutter, rectangularSelection, crosshairCursor, lineNumbers } from '@codemirror/view';
import { history, defaultKeymap, historyKeymap } from '@codemirror/commands';
import { foldGutter, foldKeymap, bracketMatching, syntaxHighlighting } from '@codemirror/language';
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search';
import { autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete';
import { MergeView } from '@codemirror/merge';
import { classHighlighter } from '@lezer/highlight';

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
  // 🎨 classHighlighter מוסיף classes קבועים (tok-*) לאלמנטי קוד,
  // מאפשר לערכות נושא מותאמות לדרוס צבעי syntax highlighting
  syntaxHighlighting(classHighlighter),
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
  const themeName = String(name || '').toLowerCase();
  if (themeName === 'dark' || themeName === 'dim') {
    return oneDark || [];
  }
  if (typeof document !== 'undefined') {
    const htmlTheme = document.documentElement.getAttribute('data-theme');
    if (htmlTheme === 'dark' || htmlTheme === 'dim') {
      return oneDark || [];
    }
  }
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
  getTheme,
  MergeView
};

if (typeof window !== 'undefined') {
  console.log('[CM Bundle] Assigning CodeMirror6 to window');
  window.CodeMirror6 = api;
}

// Remove export default to prevent issues in some IIFE bundlers
// export default api;
