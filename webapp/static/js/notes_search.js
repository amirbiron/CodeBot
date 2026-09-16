/**
 * חיפוש בפתקים — טעינת התוצאות והדגשת המילה.
 *
 * **הדגשה משלנו, ולא ``highlightSnippet`` של החיפוש הגלובלי.** הפונקציה
 * ההיא (``global_search.js``) מקבלת ``(text, ranges)`` ואינה מחפשת בעצמה:
 * בלי ``ranges`` מהשרת היא מחזירה ``escapeHtml(text)`` ותו לא. כאן השרת
 * במכוון אינו שולח היסטים — הוא סופר תווים, מונגו נקודות-קוד, ו-JS
 * יחידות UTF-16, וערבוב היחידות האלה הוא בדיוק הבאג שהפיל את חיפוש
 * הקוד (‎#3353). ההתאמה נעשית כאן, על הטקסט שכבר בידנו.
 *
 * **ואין ``innerHTML`` באף מקום בקובץ הזה.** כל טקסט שמגיע מהשרת נכנס
 * דרך ``textContent``, וה-``<mark>`` נוצר ב-``createElement``. זה לא
 * זהירות יתרה: התוכן הוא מה שהמשתמש הקליד בפתק, כלומר בדיוק הקלט
 * ש-``bugbot-rules/xss-innerhtml`` מתאר. ``escapeHtml`` של החיפוש
 * הגלובלי גם אינה מבריחה מרכאות, ולכן העתקה ממנה הייתה גוררת את הבעיה.
 */
(function () {
  'use strict';

  var form = document.getElementById('noteSearchForm');
  var input = document.getElementById('noteSearchInput');
  var colors = document.getElementById('noteSearchColors');
  var msg = document.getElementById('noteSearchMsg');
  var list = document.getElementById('noteSearchResults');
  if (!form || !input || !list) { return; }

  var TARGET_LABELS = {
    board: 'לוח',
    file: 'קובץ',
    repo: 'ריפו',
    unknown: 'לא ידוע'
  };

  /**
   * בריחת תווי רג'קס — **שקולה ל-``re.escape`` שבשרת**.
   *
   * שני הצדדים חייבים להסכים מה ליטרלי: השרת מצא את הפתק לפי דפוס אחד,
   * ואם הדגש כאן מפרש ``config.py`` אחרת, תוצאה שחזרה עם התאמה תוצג בלי
   * הדגשה — כלומר תיראה כמו באג בשרת.
   */
  function escapeRegex(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  /**
   * מוסיף ל-``container`` את ``text`` כשכל מופע של ``query`` עטוף
   * ב-``<mark>``. מחזיר **כמה מופעים סומנו**.
   *
   * ערך ההחזרה אינו קישוט: העמוד צריך לדעת אם באמת סומן משהו כדי להחליט
   * אם להציג "המילה מופיעה בהמשך הפתק". ספירה שהייתה מוסקת מחדש בחוץ היא
   * ספירה שיכולה לא להסכים עם מה שבאמת צויר.
   */
  function highlightInto(container, text, query) {
    var value = String(text == null ? '' : text);
    var needle = String(query == null ? '' : query);
    if (!needle) {
      container.appendChild(document.createTextNode(value));
      return 0;
    }

    var re = new RegExp(escapeRegex(needle), 'gi');
    var last = 0;
    var hits = 0;
    var m;
    while ((m = re.exec(value)) !== null) {
      if (m.index > last) {
        container.appendChild(document.createTextNode(value.slice(last, m.index)));
      }
      var mark = document.createElement('mark');
      mark.className = 'notes-search-mark';
      mark.textContent = m[0];
      container.appendChild(mark);
      last = m.index + m[0].length;
      hits += 1;
      // מחט ריקה אינה אפשרית כאן (יש ``if (!needle)`` למעלה), אבל
      // ``lastIndex`` שלא זז הוא לולאה אינסופית שמקפיאה את הלשונית —
      // ולכן החסם נשאר.
      if (m[0].length === 0) { re.lastIndex += 1; }
    }
    if (last < value.length) {
      container.appendChild(document.createTextNode(value.slice(last)));
    }
    return hits;
  }

  function setMessage(text, isError) {
    if (!msg) { return; }
    msg.textContent = String(text || '');
    msg.classList.toggle('is-error', !!isError);
    msg.hidden = !text;
  }

  function selectedColorId() {
    var pressed = colors && colors.querySelector('.notes-color-chip[aria-pressed="true"]');
    return pressed ? (pressed.getAttribute('data-color-id') || '') : '';
  }

  function renderResult(hit, query) {
    var li = document.createElement('li');
    li.className = 'notes-search-result';

    var link = document.createElement('a');
    link.className = 'notes-search-link';
    link.href = hit.url || ('/note/' + encodeURIComponent(hit.id || ''));
    // **כרטיסייה חדשה, ולא ניווט במקום.** תוצאות חיפוש הן רשימה שחוזרים
    // אליה: פותחים פתק, מסתכלים, וממשיכים לבא בתור. ניווט באותה כרטיסייה
    // מאבד את הרשימה, ו"חזור" מריץ את החיפוש מחדש.
    //
    // ``rel`` אינו קישוט: בלי ``noopener`` העמוד שנפתח מקבל
    // ``window.opener`` ויכול לנווט את עמוד החיפוש למקום אחר.
    link.target = '_blank';
    link.rel = 'noopener noreferrer';

    var swatch = document.createElement('span');
    swatch.className = 'notes-search-swatch';
    swatch.setAttribute('aria-hidden', 'true');
    // הגוון נקבע כאן ולא ב-CSS: הוא נגזר מהפתק, ו-``style`` היא הדרך
    // היחידה להעביר ערך שהשרת חישב. ``setProperty`` ולא שרשור מחרוזת.
    swatch.style.setProperty('--chip-fill', String(hit.color || ''));
    link.appendChild(swatch);

    var body = document.createElement('span');
    body.className = 'notes-search-body';

    var titleEl = document.createElement('span');
    titleEl.className = 'notes-search-title';
    var titleHits = 0;
    if (hit.title) {
      titleHits = highlightInto(titleEl, hit.title, query);
    } else {
      titleEl.classList.add('is-untitled');
      titleEl.textContent = 'פתק ללא שם';
    }
    body.appendChild(titleEl);

    var preview = document.createElement('span');
    preview.className = 'notes-search-preview';
    var previewHits = highlightInto(preview, hit.preview, query);
    if (hit.preview_truncated) {
      preview.appendChild(document.createTextNode('…'));
    }
    body.appendChild(preview);

    // **המקרה הנפוץ, לא קצה.** גוף הפתק הממוצע ארוך פי כמה מהתצוגה
    // המקדימה, ולכן פתק שנמצא בזכות מילה שיושבת אחרי 200 התווים הראשונים
    // היה מוצג בלי שום סימן למה הוא ברשימה. הספירה מגיעה ממה שבאמת סומן
    // בשני המקומות, ולא מניחוש.
    if (titleHits === 0 && previewHits === 0) {
      var hint = document.createElement('span');
      hint.className = 'notes-search-hint';
      hint.textContent = 'המילה מופיעה בהמשך הפתק';
      body.appendChild(hint);
    }

    var meta = document.createElement('span');
    meta.className = 'notes-search-meta';
    var where = TARGET_LABELS[hit.target] || TARGET_LABELS.unknown;
    var detail = hit.file_name || hit.repo_path || '';
    meta.textContent = detail ? (where + ' · ' + detail) : where;
    body.appendChild(meta);

    link.appendChild(body);
    li.appendChild(link);
    return li;
  }

  function render(data, query) {
    list.textContent = '';
    var results = (data && data.results) || [];
    if (!results.length) {
      setMessage('לא נמצאו פתקים.', false);
      return;
    }
    var frag = document.createDocumentFragment();
    for (var i = 0; i < results.length; i++) {
      frag.appendChild(renderResult(results[i], query));
    }
    list.appendChild(frag);
    setMessage(
      data.truncated
        ? ('מוצגים ' + results.length + ' פתקים ראשונים — יש עוד.')
        : ('נמצאו ' + results.length + ' פתקים.'),
      false
    );
  }

  var inFlight = null;

  function runSearch(query, colorId, updateUrl) {
    var needle = String(query || '').trim();
    if (!needle) {
      list.textContent = '';
      setMessage('', false);
      return;
    }

    var url = '/api/sticky-notes/search?q=' + encodeURIComponent(needle);
    if (colorId) { url += '&color=' + encodeURIComponent(colorId); }

    if (updateUrl) {
      try {
        var page = '/notes/search?q=' + encodeURIComponent(needle) +
          (colorId ? ('&color=' + encodeURIComponent(colorId)) : '');
        window.history.replaceState(null, '', page);
      } catch (e) { /* היסטוריה חסומה — החיפוש עצמו אינו תלוי בה */ }
    }

    setMessage('מחפש…', false);
    // בקשה חדשה מבטלת את הקודמת: בלי זה תשובה איטית של חיפוש ישן יכולה
    // לנחות אחרי החדשה ולדרוס אותה.
    var token = {};
    inFlight = token;
    fetch(url, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) {
        if (inFlight !== token) { return; }
        if (!res.body || res.body.ok !== true) {
          var err = res.body && res.body.error;
          if (err === 'invalid_color') {
            setMessage('הצבע שנבחר אינו מוכר.', true);
          } else if (err === 'empty_query') {
            setMessage('צריך להקליד משהו לחפש.', true);
          } else {
            setMessage('החיפוש נכשל. נסה שוב.', true);
          }
          list.textContent = '';
          return;
        }
        render(res.body, needle);
      })
      .catch(function () {
        if (inFlight !== token) { return; }
        list.textContent = '';
        setMessage('החיפוש נכשל. נסה שוב.', true);
      });
  }

  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    runSearch(input.value, selectedColorId(), true);
  });

  if (colors) {
    colors.addEventListener('click', function (ev) {
      var chip = ev.target && ev.target.closest && ev.target.closest('.notes-color-chip');
      if (!chip) { return; }
      var chips = colors.querySelectorAll('.notes-color-chip');
      for (var i = 0; i < chips.length; i++) {
        chips[i].setAttribute('aria-pressed', chips[i] === chip ? 'true' : 'false');
      }
      // שינוי מסנן מריץ מחדש רק כשכבר יש מה לסנן.
      if (input.value.trim()) {
        runSearch(input.value, selectedColorId(), true);
      }
    });
  }

  // טעינה מ-URL: העמוד ניתן לשיתוף ולרענון.
  (function bootFromUrl() {
    var params = new URLSearchParams(window.location.search || '');
    var q = params.get('q') || '';
    var color = params.get('color') || '';
    if (color && colors) {
      var chip = colors.querySelector('.notes-color-chip[data-color-id="' + CSS.escape(color) + '"]');
      if (chip) {
        var chips = colors.querySelectorAll('.notes-color-chip');
        for (var i = 0; i < chips.length; i++) {
          chips[i].setAttribute('aria-pressed', chips[i] === chip ? 'true' : 'false');
        }
      }
    }
    if (q) {
      input.value = q;
      runSearch(q, selectedColorId(), false);
    }
  })();
})();
