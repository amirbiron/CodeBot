// This entry imports libraries and exposes them on window for md_preview.html
import MarkdownIt from 'markdown-it';
import { full as markdownItEmoji } from 'markdown-it-emoji';
import markdownItTaskLists from 'markdown-it-task-lists';
import markdownItAnchor from 'markdown-it-anchor';
import markdownItFootnote from 'markdown-it-footnote';
import markdownItTocDoneRight from 'markdown-it-toc-done-right';
import markdownItContainer from 'markdown-it-container';
import markdownItAdmonition from 'markdown-it-admonition';
import hljs from 'highlight.js/lib/common';
// KaTeX: load JS and CSS; CSS will be bundled separately
import renderMathInElement from 'katex/contrib/auto-render';
// Mermaid
import mermaid from 'mermaid';

// Expose on window to keep template logic intact
if (typeof window !== 'undefined') {
  window.markdownit = (opts) => new MarkdownIt(opts);
  window.markdownitEmoji = markdownItEmoji;
  window.markdownitTaskLists = markdownItTaskLists;
  window.markdownitAnchor = markdownItAnchor;
  window.markdownitFootnote = markdownItFootnote;
  window.markdownitTocDoneRight = markdownItTocDoneRight;
  window.markdownitContainer = markdownItContainer;
  window.markdownitAdmonition = markdownItAdmonition;
  window.hljs = hljs;
  window.renderMathInElement = renderMathInElement;
  window.mermaid = mermaid;
}
