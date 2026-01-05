import { EditorState, Compartment } from '@codemirror/state';
import { EditorView, keymap, drawSelection, dropCursor, highlightSpecialChars, highlightActiveLine, highlightActiveLineGutter, rectangularSelection, crosshairCursor, lineNumbers } from '@codemirror/view';
import { history, defaultKeymap, historyKeymap } from '@codemirror/commands';
import { foldGutter, foldKeymap, bracketMatching, syntaxHighlighting, HighlightStyle } from '@codemirror/language';
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search';
import { autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete';
import { MergeView } from '@codemirror/merge';
import { classHighlighter, tags } from '@lezer/highlight';

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

// ==========================================
// 🎨 Dynamic HighlightStyle from syntax_colors
// ==========================================

/**
 * מיפוי שמות tags מה-JSON ל-tags objects של @lezer/highlight
 * תואם ל-VSCODE_TO_CM_TAG ב-theme_parser_service.py
 */
const TAG_NAME_MAP = {
  // Comments
  comment: tags.comment,
  lineComment: tags.lineComment,
  blockComment: tags.blockComment,
  docComment: tags.docComment,
  
  // Strings
  string: tags.string,
  'special(string)': tags.special(tags.string),
  regexp: tags.regexp,
  escape: tags.escape,
  character: tags.character,
  
  // Keywords
  keyword: tags.keyword,
  controlKeyword: tags.controlKeyword,
  moduleKeyword: tags.moduleKeyword,
  definitionKeyword: tags.definitionKeyword,
  operatorKeyword: tags.operatorKeyword,
  modifier: tags.modifier,
  unit: tags.unit,
  
  // Functions & Variables
  variableName: tags.variableName,
  'local(variableName)': tags.local(tags.variableName),
  'definition(variableName)': tags.definition(tags.variableName),
  'constant(variableName)': tags.constant(tags.variableName),
  'function(variableName)': tags.function(tags.variableName),
  'definition(function(variableName))': tags.definition(tags.function(tags.variableName)),
  'standard(function(variableName))': tags.standard(tags.function(tags.variableName)),
  'special(function(variableName))': tags.special(tags.function(tags.variableName)),
  self: tags.self,
  
  // Types & Classes
  typeName: tags.typeName,
  className: tags.className,
  namespace: tags.namespace,
  'standard(typeName)': tags.standard(tags.typeName),
  'standard(className)': tags.standard(tags.className),
  'definition(className)': tags.definition(tags.className),
  macroName: tags.macroName,
  
  // Constants & Numbers
  atom: tags.atom,
  bool: tags.bool,
  number: tags.number,
  integer: tags.integer,
  float: tags.float,
  null: tags.null,
  
  // Operators
  operator: tags.operator,
  definitionOperator: tags.definitionOperator,
  compareOperator: tags.compareOperator,
  logicOperator: tags.logicOperator,
  arithmeticOperator: tags.arithmeticOperator,
  bitwiseOperator: tags.bitwiseOperator,
  
  // Properties & Attributes
  propertyName: tags.propertyName,
  'definition(propertyName)': tags.definition(tags.propertyName),
  attributeName: tags.attributeName,
  
  // Tags (HTML/XML)
  tagName: tags.tagName,
  angleBracket: tags.angleBracket,
  
  // Punctuation
  punctuation: tags.punctuation,
  separator: tags.separator,
  bracket: tags.bracket,
  brace: tags.brace,
  paren: tags.paren,
  squareBracket: tags.squareBracket,
  
  // Markup
  heading: tags.heading,
  heading1: tags.heading1,
  heading2: tags.heading2,
  strong: tags.strong,
  emphasis: tags.emphasis,
  link: tags.link,
  quote: tags.quote,
  list: tags.list,
  monospace: tags.monospace,
  inserted: tags.inserted,
  deleted: tags.deleted,
  changed: tags.changed,
  
  // Special
  meta: tags.meta,
  processingInstruction: tags.processingInstruction,
  labelName: tags.labelName,
  content: tags.content,
  url: tags.url,
  invalid: tags.invalid,
};

/**
 * יוצר HighlightStyle דינמי מנתוני syntax_colors מה-JSON
 */
function createDynamicHighlightStyle(syntaxColors) {
  if (!syntaxColors || typeof syntaxColors !== 'object') {
    return null;
  }
  
  const specs = [];
  
  for (const [tagName, style] of Object.entries(syntaxColors)) {
    const tag = TAG_NAME_MAP[tagName];
    if (!tag) {
      // נסיון למצוא tag לפי שם פשוט (ללא modifiers)
      const simpleTag = tags[tagName];
      if (simpleTag) {
        specs.push({
          tag: simpleTag,
          ...style
        });
      }
      continue;
    }
    
    specs.push({
      tag,
      ...style
    });
  }
  
  if (specs.length === 0) {
    return null;
  }
  
  return HighlightStyle.define(specs);
}

/**
 * מחזיר את syntax_colors מה-JSON element בדף
 */
function getSyntaxColorsFromPage() {
  if (typeof document === 'undefined') return null;
  
  const el = document.getElementById('syntax-colors-data');
  if (!el) return null;
  
  try {
    return JSON.parse(el.textContent || '{}');
  } catch (e) {
    console.warn('[CM Bundle] Failed to parse syntax-colors-data:', e);
    return null;
  }
}

// שמירת ה-HighlightStyle הדינמי + hash לזיהוי שינויים
let cachedDynamicHighlighter = null;
let cachedSyntaxColorsHash = null;

/**
 * יוצר hash פשוט מה-syntax colors לזיהוי שינויים
 */
function hashSyntaxColors(syntaxColors) {
  if (!syntaxColors) return null;
  try {
    return JSON.stringify(syntaxColors);
  } catch {
    return null;
  }
}

/**
 * מאפס את ה-cache של ה-syntax highlighter (לשימוש כש-theme משתנה)
 */
function invalidateSyntaxHighlighterCache() {
  cachedDynamicHighlighter = null;
  cachedSyntaxColorsHash = null;
  console.log('[CM Bundle] Syntax highlighter cache invalidated');
}

/**
 * מחזיר את ה-syntax highlighter המתאים לערכה הנוכחית
 */
function getSyntaxHighlighter() {
  if (typeof document === 'undefined') {
    return syntaxHighlighting(classHighlighter);
  }
  
  const htmlTheme = document.documentElement.getAttribute('data-theme');
  
  // אם זו ערכה מותאמת - נסה ליצור HighlightStyle דינמי
  if (htmlTheme === 'custom') {
    const syntaxColors = getSyntaxColorsFromPage();
    const currentHash = hashSyntaxColors(syntaxColors);
    
    // בדיקה אם הנתונים השתנו מאז ה-cache האחרון
    if (cachedDynamicHighlighter !== null && currentHash === cachedSyntaxColorsHash) {
      return cachedDynamicHighlighter;
    }
    
    // נתונים חדשים או שונים - יצירת highlighter חדש
    if (syntaxColors && Object.keys(syntaxColors).length > 0) {
      const dynamicStyle = createDynamicHighlightStyle(syntaxColors);
      if (dynamicStyle) {
        cachedDynamicHighlighter = syntaxHighlighting(dynamicStyle);
        cachedSyntaxColorsHash = currentHash;
        console.log('[CM Bundle] Using dynamic HighlightStyle with', Object.keys(syntaxColors).length, 'colors');
        return cachedDynamicHighlighter;
      }
    }
    
    // fallback to classHighlighter
    cachedDynamicHighlighter = syntaxHighlighting(classHighlighter);
    cachedSyntaxColorsHash = currentHash;
    return cachedDynamicHighlighter;
  }
  
  // ערכות רגילות - classHighlighter (CSS overrides)
  return syntaxHighlighting(classHighlighter);
}

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
  // 🎨 classHighlighter כ-fallback - ערכות מותאמות משתמשות ב-dynamic HighlightStyle
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
  // 🎨 ערכה מותאמת אישית: לא טוענים oneDark כדי לתת ל-syntax_css לעבוד
  // ה-classHighlighter ב-basicSetup יוצר classes (tok-*) שה-CSS דורס
  if (typeof document !== 'undefined') {
    const htmlTheme = document.documentElement.getAttribute('data-theme');
    if (htmlTheme === 'custom') {
      return []; // Custom theme - use CSS classes only
    }
  }
  
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
  getSyntaxHighlighter,
  createDynamicHighlightStyle,
  invalidateSyntaxHighlighterCache,  // 🆕 לאיפוס cache כש-theme משתנה
  MergeView,
  syntaxHighlighting,
  HighlightStyle,
  tags
};

if (typeof window !== 'undefined') {
  console.log('[CM Bundle] Assigning CodeMirror6 to window');
  window.CodeMirror6 = api;
}

// Remove export default to prevent issues in some IIFE bundlers
// export default api;
