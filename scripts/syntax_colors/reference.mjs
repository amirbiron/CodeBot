// מה VS Code, highlight.js ו-CodeMirror עושים עם אותו קוד — הקלט של tests/fixtures/syntax_colors_vscode_reference.json.
//
// לא מריצים את הקובץ הזה ישירות: generate_reference.py שולח לו ב-stdin את הדוגמאות ואת ה-tokenColors של הערכות,
// וכותב את התשובה. ההסבר המלא, וגם למה יש לו תלויות משלו, ב-README.md שבתיקייה.
//
// לכל שפה הקוד מחולק למקטעים: רצף תווים שבו ארבעה דברים קבועים —
//   scopes   — שרשרת ה-scopes ש-VS Code נותן (vscode-textmate + הדקדוק של VS Code)
//   hljs     — המחלקות של highlight.js, מהעוטף החיצוני פנימה (כל עוטף: רשימת המחלקות שלו)
//   cmClass  — המחלקות ש-classHighlighter של CodeMirror נותן (מחרוזת, כמו ב-DOM)
//   cmTags   — ה-tags של CodeMirror: לכל tag, השמות מ-TAG_NAME_MAP שבשרשרת שלו, מהמדויק לכללי
// ולכל ערכה: הצבע והגופן ש-VS Code נותן לכל שרשרת scopes שמופיעה (null: צבע ברירת המחדל של העורך).

import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..', '..');
const DEPS = process.env.SYNTAX_COLORS_DEPS || path.join(HERE, 'node_modules');

const requireDeps = createRequire(path.join(DEPS, 'noop.js'));
const requireRepo = createRequire(path.join(REPO, 'package.json'));

const vsctm = requireDeps('vscode-textmate');
const oniguruma = requireDeps('vscode-oniguruma');
// highlight.js ו-CodeMirror — מה-node_modules של הריפו, אותן גרסאות שהבאנדלים נבנו מהן
const hljs = requireRepo('highlight.js/lib/common');

const { tags, highlightTree, classHighlighter } = await import(
  path.join(REPO, 'node_modules/@lezer/highlight/dist/index.js')
);
const { pythonLanguage } = await import(path.join(REPO, 'node_modules/@codemirror/lang-python/dist/index.js'));
const { javascriptLanguage } = await import(path.join(REPO, 'node_modules/@codemirror/lang-javascript/dist/index.js'));

// צבע שאין בשום ערכה: מסמן "ברירת המחדל של העורך", כמו ש-VS Code מכניס את editor.foreground לפני הערכה
const DEFAULT_SENTINEL = '#010203';

const LANGUAGES = {
  python: { scope: 'source.python', grammar: 'python.json', hljs: 'python', cm: pythonLanguage },
  javascript: { scope: 'source.js', grammar: 'javascript.json', hljs: 'javascript', cm: javascriptLanguage },
};

// --- שמות ה-tags ש-syntax_colors משתמש בהם: המפתחות של TAG_NAME_MAP בבאנדל של CodeMirror ---
function tagNameMapKeys() {
  const src = fs.readFileSync(path.join(REPO, 'webapp/static_build/codemirror.bundle.entry.mjs'), 'utf8');
  const block = src.slice(src.indexOf('const TAG_NAME_MAP = {'), src.indexOf('};', src.indexOf('const TAG_NAME_MAP = {')));
  return [...block.matchAll(/^\s*(?:'([^']+)'|([A-Za-z0-9]+)):\s*tags\./gm)].map((m) => m[1] || m[2]);
}

function tagFromName(name) {
  const m = name.match(/^([A-Za-z0-9]+)\((.*)\)$/);
  if (m) return tags[m[1]](tagFromName(m[2]));
  if (!tags[name]) throw new Error(`unknown tag ${name}`);
  return tags[name];
}

function packageVersion(dir, name) {
  return JSON.parse(fs.readFileSync(path.join(dir, name, 'package.json'), 'utf8')).version;
}

function decodeEntities(s) {
  return s
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&');
}

function hljsPerChar(code, language) {
  const html = hljs.highlight(code, { language, ignoreIllegals: true }).value;
  const out = [];
  const stack = [];
  const re = /<span class="([^"]*)">|<\/span>|([^<]+)/g;
  let m;
  while ((m = re.exec(html))) {
    if (m[1] !== undefined) stack.push(m[1].split(/\s+/).filter(Boolean));
    else if (m[0] === '</span>') stack.pop();
    else for (const ch of decodeEntities(m[2])) out.push(stack.map((c) => c.slice()));
  }
  return out;
}

function cmPerChar(code, language, namedTags) {
  const tree = language.parser.parse(code);
  const classes = new Array(code.length).fill('');
  const tagChains = new Array(code.length).fill(null).map(() => []);
  highlightTree(tree, classHighlighter, (from, to, cls) => {
    for (let i = from; i < to; i++) classes[i] = cls;
  });
  // highlighter שמחזיר את ה-tags עצמם, כדי לדעת מה HighlightStyle יראה
  const tagSpy = {
    style(tokenTags) {
      return JSON.stringify(
        tokenTags.map((t) => t.set.flatMap((sub) => namedTags.filter(([, tag]) => tag === sub).map(([name]) => name)))
      );
    },
  };
  highlightTree(tree, tagSpy, (from, to, json) => {
    const chains = JSON.parse(json);
    for (let i = from; i < to; i++) tagChains[i] = chains;
  });
  return { classes, tagChains };
}

async function main() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const wasm = fs.readFileSync(path.join(path.dirname(requireDeps.resolve('vscode-oniguruma')), 'onig.wasm')).buffer;
  await oniguruma.loadWASM(wasm);
  const onigLib = Promise.resolve({
    createOnigScanner: (p) => new oniguruma.OnigScanner(p),
    createOnigString: (s) => new oniguruma.OnigString(s),
  });
  const grammarsDir = path.join(DEPS, 'tm-grammars', 'grammars');
  const grammarFiles = Object.fromEntries(Object.values(LANGUAGES).map((l) => [l.scope, l.grammar]));
  const registry = new vsctm.Registry({
    onigLib,
    loadGrammar: async (scope) =>
      grammarFiles[scope]
        ? vsctm.parseRawGrammar(fs.readFileSync(path.join(grammarsDir, grammarFiles[scope]), 'utf8'), grammarFiles[scope])
        : null,
  });

  const namedTags = tagNameMapKeys().map((name) => [name, tagFromName(name)]);
  const languages = {};
  for (const [langId, lang] of Object.entries(LANGUAGES)) {
    const code = input.samples[langId];
    const grammar = await registry.loadGrammar(lang.scope);
    const perChar = new Array(code.length).fill(null);
    let ruleStack = vsctm.INITIAL;
    let offset = 0;
    for (const line of code.split('\n')) {
      const r = grammar.tokenizeLine(line, ruleStack);
      for (const t of r.tokens) {
        for (let c = t.startIndex; c < Math.min(t.endIndex, line.length); c++) perChar[offset + c] = t.scopes;
      }
      ruleStack = r.ruleStack;
      offset += line.length + 1;
    }
    const hl = hljsPerChar(code, lang.hljs);
    if (hl.length !== code.length) throw new Error(`highlight.js text differs from the sample (${langId})`);
    const cm = cmPerChar(code, lang.cm, namedTags);

    const segments = [];
    for (let i = 0; i < code.length; i++) {
      const ch = code[i];
      const scopes = perChar[i] || [lang.scope];
      const key = JSON.stringify([scopes, hl[i], cm.classes[i], cm.tagChains[i]]);
      const last = segments[segments.length - 1];
      if (last && last.key === key && ch !== '\n') last.text += ch;
      else segments.push({ key, text: ch, scopes, hljs: hl[i], cmClass: cm.classes[i], cmTags: cm.tagChains[i] });
    }
    languages[langId] = segments.map(({ key, ...rest }) => rest);
  }

  const themes = {};
  for (const [themeId, tokenColors] of Object.entries(input.themes)) {
    registry.setTheme({ name: themeId, settings: [{ settings: { foreground: DEFAULT_SENTINEL } }, ...tokenColors] });
    const colorMap = registry.getColorMap();
    // ההכרעה של VS Code לכל שרשרת: tokenizeLine2 על השורות האמיתיות, אחרי setTheme. ה-API הציבורי לא מכריע שרשרת
    // שרירותית, ולכן כל טוקן מקבל את המטא-דאטה של המקטע הבינארי שהוא מתחיל בו.
    const styles = {};
    for (const [langId, lang] of Object.entries(LANGUAGES)) {
      const code = input.samples[langId];
      const grammar = await registry.loadGrammar(lang.scope);
      let ruleStack = vsctm.INITIAL;
      for (const line of code.split('\n')) {
        const r1 = grammar.tokenizeLine(line, ruleStack);
        const r2 = grammar.tokenizeLine2(line, ruleStack);
        const bin = r2.tokens;
        for (const t of r1.tokens) {
          let meta = bin[1];
          for (let k = 0; k < bin.length; k += 2) if (bin[k] <= t.startIndex) meta = bin[k + 1];
          const fg = colorMap[(meta >>> 15) & 0x1ff];
          const fontStyle = (meta >>> 11) & 0xf;
          styles[JSON.stringify(t.scopes)] = {
            fg: fg.toUpperCase() === DEFAULT_SENTINEL.toUpperCase() ? null : fg.toLowerCase(),
            fontStyle,
          };
        }
        ruleStack = r1.ruleStack;
      }
    }
    themes[themeId] = styles;
  }

  process.stdout.write(
    JSON.stringify({
      versions: {
        'vscode-textmate': packageVersion(DEPS, 'vscode-textmate'),
        'vscode-oniguruma': packageVersion(DEPS, 'vscode-oniguruma'),
        'tm-grammars': packageVersion(DEPS, 'tm-grammars'),
        'highlight.js': packageVersion(path.join(REPO, 'node_modules'), 'highlight.js'),
        '@lezer/highlight': packageVersion(path.join(REPO, 'node_modules'), '@lezer/highlight'),
        '@codemirror/lang-python': packageVersion(path.join(REPO, 'node_modules'), '@codemirror/lang-python'),
        '@codemirror/lang-javascript': packageVersion(path.join(REPO, 'node_modules'), '@codemirror/lang-javascript'),
      },
      languages,
      themes,
    })
  );
}

await main();
