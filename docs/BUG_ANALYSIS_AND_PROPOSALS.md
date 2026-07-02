# מסמך ניתוח באגים והצעות לתיקון

מסמך זה מרכז את הניתוח הטכני של הבאגים שדווחו ב-PR "שינויים בעורך קוד ועוד", כולל הצבעה על הקוד הקיים (Current Code) והצעה לתיקון (Proposed Fix).

> **הערה:** מסמך זה נכתב בהתאם להנחיות ב-`.cursorrules` ובבקשת ה-PR. הקוד המוצע הוא רעיוני וטרם יושם בפועל.

---

## 1. שמירת מיקום במעבר בין עורכים
**הבעיה:** במעבר בין עורך פשוט למתקדם, הסמן חוזר לתחילת הקובץ.

### הקוד הנוכחי (`webapp/static/js/editor-manager.js`)
הפונקציה שמחליפה עורך מאתחלת את העורך החדש עם הטקסט בלבד, ללא העברת מיקום.

```javascript
// Current Implementation (lines 262-282 approx)
toggleBtn.addEventListener('click', async () => {
  const prev = this.currentEditor;
  // ...
  if (this.currentEditor === 'codemirror') {
    // מעביר רק value
    await this.initCodeMirror(container, { language: lang, value: this.textarea.value, theme: 'dark' });
  } else {
    // מעביר רק value
    this.initSimpleEditor(container, { value: this.cmInstance ? this.cmInstance.state.doc.toString() : this.textarea.value });
  }
  // ...
});
```

### ההצעה המתוקנת
יש להוסיף מתודות `getCursor()` ו-`setCursor()` ולהעביר את המיקום באתחול.

```javascript
// Proposed Implementation
toggleBtn.addEventListener('click', async () => {
  const cursor = this.getCursorPosition(); // { line, ch } או offset
  // ...
  if (this.currentEditor === 'codemirror') {
    await this.initCodeMirror(container, { ..., cursor });
  } else {
    this.initSimpleEditor(container, { ..., cursor });
  }
});

// בתוך initCodeMirror / initSimpleEditor:
// אם התקבל cursor, השתמש ב-cmInstance.dispatch({ selection: ... }) או textarea.setSelectionRange(...)
```

---

## 2. באג בכפתור "הדבק" (עורך מתקדם)
**הבעיה:** כפתור "הדבק" דורס את כל תוכן הקובץ.

### הקוד הנוכחי (`webapp/static/js/editor-manager.js`)
הפונקציה `handleClipboardPaste` קוראת ל-`setEditorContent` שמחליפה הכל.

```javascript
// Current Implementation (lines 439 + 373)
this.setEditorContent(text);

// setEditorContent:
view.dispatch({
  changes: { from: 0, to: view.state.doc.length, insert: value }, // דורס הכל
  selection: { anchor: value.length }
});
```

### ההצעה המתוקנת
שימוש בפונקציה ייעודית `insertAtCursor` או שינוי `setEditorContent` לתמיכה בהוספה.

```javascript
// Proposed Implementation
insertContent(text) {
  if (this.cmInstance) {
    const view = this.cmInstance;
    view.dispatch(view.state.replaceSelection(text)); // הדבקה במיקום הסמן
  } else if (this.textarea) {
    this.textarea.setRangeText(text, this.textarea.selectionStart, this.textarea.selectionEnd, 'end');
  }
}
```

---

## 3. חסר כפתור העלאת תמונה
**הבעיה:** חסר כפתור 🖼️ במסך "עריכת קובץ" (קיים רק ב"יצירה").

### הקוד הנוכחי (`webapp/templates/edit_file.html`)
הקוד מכיל רק שדות טקסט (שם, שפה, תיאור) ללא הבלוק של `image-upload-trigger` שקיים ב-`upload.html`.

```html
<!-- Current edit_file.html structure -->
<div>
  <label>שם קובץ</label>
  <input type="text" name="file_name" ...>
</div>
```

### ההצעה המתוקנת
העתקת הלוגיקה וה-HTML מ-`upload.html` ל-`edit_file.html` (או יצירת Partial משותף).

```html
<!-- Proposed edit_file.html structure -->
<div class="filename-field">
  <div class="filename-field-header">
    <label>שם קובץ</label>
    <!-- כפתור העלאה -->
    <button type="button" id="imageUploadTrigger" class="image-upload-trigger">🖼️</button>
  </div>
  <!-- ... Preview container & Input file hidden ... -->
</div>
```
*נדרש גם להעתיק את קוד ה-JS הרלוונטי (`handleMarkdownImageFiles`, `renderMarkdownImages` וכו').*

---

## 4, 5, 6. בעיות Live Preview (קפיצות, גובה, שטח מת)
**הבעיה:** הפעלת Preview גורמת לקפיצות, הקטנת העורך, ושטח מת ב-HTML.

### הקוד הנוכחי (`webapp/static/css/split-view.css` & HTML)
ה-textarea מוגדר עם `rows="18"` מה שקובע גובה קבוע, וה-container של ה-iframe לא מוגדר למתוח את התוכן.

```css
/* Current CSS */
.split-preview-canvas {
  min-height: 160px; /* גובה מינימלי בלבד */
}
/* הטקסטאריה נשארת עם גובה הדיפולט שלה, מה שגורם לבעיות ב-Flex */
```

### ההצעה המתוקנת
שימוש ב-Flexbox מלא לכל הגובה ומתיחת רכיבי התוכן.

```css
/* Proposed CSS Fixes */
.split-panel--editor, .split-panel--preview {
  height: 100%;
  overflow: hidden; /* מניעת גלילה כפולה */
}

#editorContainer, #editorContainer textarea {
  height: 100% !important;
  box-sizing: border-box;
  resize: none; /* ביטול Resize ידני במצב Split */
}

.split-preview-content {
  display: flex;
  flex-direction: column;
}

.split-preview-canvas {
  flex: 1; /* מתיחה לגובה מלא */
  display: flex;
  flex-direction: column;
}

.split-preview-canvas iframe {
  flex: 1;
}
```

---

## 7. לוגיקת הסתרה (שפה vs סיומת)
**הבעיה:** שינוי שפה לא מסתיר את ה-Preview אם הוא לא רלוונטי.

### הקוד הנוכחי (`webapp/static/js/live-preview.js`)
הבדיקה היא "או זה או זה", כך שאם הסיומת היא `.md` (או שם הקובץ נחשב כזה), שינוי השפה ל-Python לא מכבה את ה-Preview.

```javascript
// Current Logic
isPreviewEligible() {
  // ...
  return isMarkdownLanguage(language) || isHtmlLanguage(language) || isMarkdownExtension(fileName) || ...;
}
```

### ההצעה המתוקנת
מתן קדימות לבחירת המשתמש בתיבת השפה (אם היא מפורשת).

```javascript
// Proposed Logic
isPreviewEligible() {
  const language = this.languageSelect ? this.languageSelect.value : '';
  const fileName = this.fileNameInput ? this.fileNameInput.value : '';
  
  // אם המשתמש בחר שפה ספציפית (לא 'text' ולא ריק), נסתמך עליה בלבד
  if (language && language !== 'text') {
    return isMarkdownLanguage(language) || isHtmlLanguage(language);
  }
  
  // אחרת, נבדוק לפי סיומת
  return isMarkdownExtension(fileName) || isHtmlExtension(fileName);
}
```

---

## 8. חריגת אלמנטים במובייל
**הבעיה:** שדות הטופס חורגים מהרוחב במסך צר.

### הקוד הנוכחי
השדות מוגדרים עם `width: 100%` וגם `padding`, אך ללא `box-sizing` מתאים בקונטקסט של הטופס.

```css
.form-field {
  width: 100%;
  padding: .75rem;
  /* box-sizing: border-box; חסר או לא משפיע בגלל היררכיה */
}
```

### ההצעה המתוקנת
הוספת Reset ברור ל-box-sizing.

```css
/* Proposed CSS */
.form-field, .source-url-input {
  box-sizing: border-box; /* ודא שפדינג לא מוסיף לרוחב */
  max-width: 100%;
}
```

---

## 9. באגים כלליים (Onboarding אקראי)
**הבעיה:** סיור מודרך מופיע שוב ושוב.
*הערה: לא אותר קוד ספציפי בקבצים שנסקרו, אך מוצע פתרון עקרוני.*

### ההצעה המתוקנת
לוודא בדיקה אמינה מול `localStorage` ושמירת דגל קבוע (למשל `onboarding_seen_v2`) שאינו נמחק ביציאה.

```javascript
// Proposed Generic Logic
const ONBOARDING_KEY = 'app_onboarding_completed_v1';
if (!localStorage.getItem(ONBOARDING_KEY)) {
  showTutorial();
  localStorage.setItem(ONBOARDING_KEY, 'true');
}
```

---

### סיכום
מסמך זה מהווה בסיס לביצוע התיקונים ב-PR. בשלב הבא (לאחר אישור) יש ליישם את השינויים בקבצים:
- `webapp/static/js/editor-manager.js`
- `webapp/static/js/live-preview.js`
- `webapp/templates/edit_file.html`
- `webapp/static/css/split-view.css`
