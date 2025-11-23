# 🎯 מדריך מימוש: Smooth Scrolling (גלילה חלקה)

## 📋 סקירה כללית

מדריך זה מתאר כיצד להוסיף תכונת גלילה חלקה ונעימה לעיניים ב-WebApp של CodeBot. התכונה תשפר את חווית המשתמש בעת ניווט במסמכים ארוכים, עריכת קוד ושימוש בתפריטי ניווט.

## 🎯 יעדי התכונה

1. **גלילה חלקה ונעימה**: אנימציות עדינות במקום קפיצות חדות
2. **תמיכה רחבה**: עכבר, trackpad, מקלדת ופקודות ניווט
3. **ביצועים מיטביים**: שימוש ב-GPU acceleration ומניעת jank
4. **התאמה אישית**: מהירות ו-easing functions ניתנים להגדרה
5. **נגישות מלאה**: תמיכה במשתמשי מקלדת ו-screen readers

---

## 🌟 תכונות מתוכננות

### תמיכה בסיסית
- ✅ גלגלת עכבר עם אנימציה חלקה
- ✅ Trackpad gestures (two-finger scroll)
- ✅ Page Up/Down עם אנימציה
- ✅ Home/End עם אנימציה
- ✅ גלילה לאלמנט ספציפי (anchor links)

### תכונות מתקדמות
- ✅ Smooth scroll ב-"Jump to Line" בעורך
- ✅ Momentum scrolling (המשך גלילה אינרציאלי)
- ✅ Overscroll bounce (iOS-style)
- ✅ גלילה חכמה ב-TOC (Table of Contents)
- ✅ תמיכה ב-RTL (מימין לשמאל)

### התאמה אישית
- ✅ בחירת מהירות גלילה (איטי/רגיל/מהיר)
- ✅ Easing functions (linear/ease-in-out/cubic-bezier)
- ✅ טוגל הפעלה/כיבוי לכל התכונה
- ✅ העדפות נפרדות למקלדת ועכבר

---

## 🏗️ ארכיטקטורה

### מבנה הקומפוננטות

```
webapp/
├── static/
│   ├── js/
│   │   ├── smooth-scroll.js       # ליבת המערכת
│   │   ├── scroll-manager.js      # מנהל גלילה מרכזי
│   │   ├── scroll-animations.js   # אנימציות ו-easing
│   │   └── scroll-preferences.js  # ניהול העדפות
│   └── css/
│       └── smooth-scroll.css      # עיצוב ואנימציות CSS
├── templates/
│   └── base.html                  # הוספת הסקריפטים
└── docs/webapp/
    └── smooth-scrolling.rst       # תיעוד למשתמש
```

---

## 📦 מימוש

### 1. יצירת מנהל הגלילה הבסיסי

**קובץ: `webapp/static/js/smooth-scroll.js`**

```javascript
class SmoothScrollManager {
  constructor(options = {}) {
    this.config = {
      duration: 400,
      easing: 'ease-in-out',
      offset: 0,
      enabled: true,
      wheelSensitivity: 1,
      keyboardSensitivity: 1.5,
      ...options
    };
    
    this.isScrolling = false;
    this.rafId = null;
    this.startTime = null;
    this.startPos = 0;
    this.targetPos = 0;
    
    // קאש של אלמנטים לביצועים טובים
    this.scrollContainers = new WeakMap();
    
    // אתחול משתנים לניהול listeners
    this.boundHandlers = null;
    this.listenersAttached = false;
    
    // טען העדפות משמורות
    this.loadPreferences();
    
    // אתחול מאזינים
    this.init();
  }
  
  init() {
    if (!this.config.enabled) return;
    
    // מנע כפילויות - הסר listeners קיימים לפני הוספה
    if (this.listenersAttached) {
      this.removeListeners();
    }
    
    // שמור references ל-bound functions כדי שנוכל להסיר אותן
    if (!this.boundHandlers) {
      this.boundHandlers = {
        wheel: this.throttle(this.onWheel.bind(this), 16),
        keydown: this.onKeyDown.bind(this),
        anchorClick: null
      };
    }
    
    // מאזין לגלגלת עכבר
    document.addEventListener('wheel', this.boundHandlers.wheel, { passive: false });
    
    // מאזין למקלדת
    document.addEventListener('keydown', this.boundHandlers.keydown);
    
    // מאזינים לקישורים פנימיים
    this.attachAnchorListeners();
    
    // תמיכה ב-touch devices
    this.attachTouchListeners();
    
    // סמן שהמאזינים מחוברים
    this.listenersAttached = true;
  }
  
  onWheel(event) {
    if (!this.config.enabled) return;
    
    // מנע גלילה רגילה
    event.preventDefault();
    
    // חשב כיוון וכמות גלילה
    const delta = this.normalizeWheelDelta(event);
    const distance = delta * this.config.wheelSensitivity;
    
    // בצע גלילה חלקה
    this.smoothScrollBy(distance);
  }
  
  onKeyDown(event) {
    if (!this.config.enabled) return;
    
    const scrollKeys = {
      'PageUp': -window.innerHeight * 0.9,
      'PageDown': window.innerHeight * 0.9,
      'Home': -document.documentElement.scrollHeight,
      'End': document.documentElement.scrollHeight,
      'ArrowUp': -100,
      'ArrowDown': 100,
      ' ': event.shiftKey ? -window.innerHeight * 0.9 : window.innerHeight * 0.9
    };
    
    const distance = scrollKeys[event.key];
    if (distance !== undefined) {
      event.preventDefault();
      this.smoothScrollBy(distance * this.config.keyboardSensitivity);
    }
  }
  
  smoothScrollBy(distance) {
    const currentPos = window.pageYOffset;
    const targetPos = Math.max(0, Math.min(
      currentPos + distance,
      document.documentElement.scrollHeight - window.innerHeight
    ));
    
    this.animateScroll(currentPos, targetPos);
  }
  
  smoothScrollTo(target, options = {}) {
    const element = typeof target === 'string' 
      ? document.querySelector(target) 
      : target;
      
    if (!element) return;
    
    const rect = element.getBoundingClientRect();
    const absoluteTop = window.pageYOffset + rect.top;
    const targetPos = absoluteTop - (options.offset || this.config.offset);
    
    this.animateScroll(window.pageYOffset, targetPos, options);
  }
  
  animateScroll(from, to, options = {}) {
    // בטל אנימציה קיימת
    if (this.rafId) {
      cancelAnimationFrame(this.rafId);
    }
    
    this.startPos = from;
    this.targetPos = to;
    this.startTime = performance.now();
    this.isScrolling = true;
    
    const duration = options.duration || this.config.duration;
    const easing = this.getEasingFunction(options.easing || this.config.easing);
    
    const animate = (currentTime) => {
      const elapsed = currentTime - this.startTime;
      const progress = Math.min(elapsed / duration, 1);
      const easedProgress = easing(progress);
      
      const currentPos = this.startPos + (this.targetPos - this.startPos) * easedProgress;
      window.scrollTo(0, currentPos);
      
      if (progress < 1) {
        this.rafId = requestAnimationFrame(animate);
      } else {
        this.isScrolling = false;
        this.rafId = null;
        
        // Callback לאחר סיום
        if (options.callback) {
          options.callback();
        }
      }
    };
    
    this.rafId = requestAnimationFrame(animate);
  }
  
  // Easing functions
  getEasingFunction(name) {
    const easingFunctions = {
      'linear': t => t,
      'ease-in': t => t * t,
      'ease-out': t => t * (2 - t),
      'ease-in-out': t => t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t,
      'cubic-bezier': t => this.cubicBezier(0.42, 0, 0.58, 1, t),
      'elastic': t => t === 0 || t === 1 ? t : 
        -Math.pow(2, 10 * (t - 1)) * Math.sin((t - 1.1) * 5 * Math.PI)
    };
    
    return easingFunctions[name] || easingFunctions['ease-in-out'];
  }
  
  // נורמליזציה של delta בין דפדפנים שונים
  normalizeWheelDelta(event) {
    let delta = 0;
    
    if (event.deltaMode === 0) {
      // Pixel mode
      delta = event.deltaY;
    } else if (event.deltaMode === 1) {
      // Line mode
      delta = event.deltaY * 40;
    } else if (event.deltaMode === 2) {
      // Page mode
      delta = event.deltaY * window.innerHeight;
    }
    
    // נרמול לטווח סביר
    return Math.sign(delta) * Math.min(Math.abs(delta), 200);
  }
  
  // ניהול מאזינים לקישורי עוגן
  attachAnchorListeners() {
    // שמור את ה-handler לצורך הסרה מאוחר יותר
    this.boundHandlers.anchorClick = (e) => {
      const anchor = e.target.closest('a[href^="#"]');
      if (!anchor) return;
      
      e.preventDefault();
      const targetId = anchor.getAttribute('href').slice(1);
      if (targetId) {
        const target = document.getElementById(targetId);
        if (target) {
          this.smoothScrollTo(target);
        }
      }
    };
    
    // השתמש ב-delegation לביצועים טובים יותר
    document.addEventListener('click', this.boundHandlers.anchorClick);
  }
  
  // תמיכה במכשירי מגע
  attachTouchListeners() {
    // TODO: implement touch support בעתיד
    // כרגע נשען על תמיכת הדפדפן הנייטיבית
  }
  
  // Utility functions
  throttle(func, wait) {
    let timeout;
    let previous = 0;
    
    return function(...args) {
      const now = Date.now();
      const remaining = wait - (now - previous);
      
      if (remaining <= 0) {
        if (timeout) {
          clearTimeout(timeout);
          timeout = null;
        }
        previous = now;
        func.apply(this, args);
      } else if (!timeout) {
        timeout = setTimeout(() => {
          previous = Date.now();
          timeout = null;
          func.apply(this, args);
        }, remaining);
      }
    };
  }
  
  // שמירת וטעינת העדפות
  async savePreferences() {
    const prefs = {
      smoothScroll: {
        enabled: this.config.enabled,
        duration: this.config.duration,
        easing: this.config.easing,
        wheelSensitivity: this.config.wheelSensitivity,
        keyboardSensitivity: this.config.keyboardSensitivity
      }
    };
    
    // שמירה ל-localStorage
    localStorage.setItem('smoothScrollPrefs', JSON.stringify(prefs.smoothScroll));
    
    // שמירה לשרת (תאימות לאחור)
    try {
      const body = JSON.stringify(prefs);
      const headers = { 'Content-Type': 'application/json' };
      
      await Promise.allSettled([
        fetch('/api/ui_prefs', { method: 'POST', headers, body }),
        fetch('/api/user/preferences', { method: 'POST', headers, body })
      ]);
    } catch (error) {
      console.warn('Failed to save smooth scroll preferences:', error);
    }
  }
  
  loadPreferences() {
    // נסה לטעון מ-localStorage
    const saved = localStorage.getItem('smoothScrollPrefs');
    if (saved) {
      try {
        const prefs = JSON.parse(saved);
        Object.assign(this.config, prefs);
      } catch (error) {
        console.warn('Failed to load smooth scroll preferences:', error);
      }
    }
  }
  
  // הסרת כל המאזינים
  removeListeners() {
    if (!this.listenersAttached) return;
    
    // הסר מאזינים בסיסיים
    if (this.boundHandlers) {
      if (this.boundHandlers.wheel) {
        document.removeEventListener('wheel', this.boundHandlers.wheel);
      }
      if (this.boundHandlers.keydown) {
        document.removeEventListener('keydown', this.boundHandlers.keydown);
      }
      if (this.boundHandlers.anchorClick) {
        document.removeEventListener('click', this.boundHandlers.anchorClick);
      }
    }
    
    this.listenersAttached = false;
  }
  
  // API ציבורי
  enable() {
    if (this.config.enabled) return; // כבר מופעל
    
    this.config.enabled = true;
    this.init();
    this.savePreferences();
  }
  
  disable() {
    if (!this.config.enabled) return; // כבר מכובה
    
    this.config.enabled = false;
    
    // בטל אנימציות פעילות
    if (this.rafId) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
      this.isScrolling = false;
    }
    
    // הסר מאזינים
    this.removeListeners();
    
    this.savePreferences();
  }
  
  updateConfig(newConfig) {
    Object.assign(this.config, newConfig);
    this.savePreferences();
  }
}

// אתחול גלובלי
window.smoothScroll = new SmoothScrollManager();
```

---

### 2. שילוב עם CodeMirror

**הרחבה לקובץ: `webapp/static/js/codemirror-setup.js`**

```javascript
// הוספת תמיכה ב-smooth scrolling ל-CodeMirror
function setupCodeMirrorSmoothScroll(view) {
  if (!window.smoothScroll || !window.smoothScroll.config.enabled) {
    return [];
  }
  
  // Extension של CodeMirror לגלילה חלקה
  const smoothScrollExtension = EditorView.domEventHandlers({
    wheel(event, view) {
      if (!window.smoothScroll.config.enabled) return false;
      
      event.preventDefault();
      const delta = window.smoothScroll.normalizeWheelDelta(event);
      const scrollTop = view.scrollDOM.scrollTop;
      const targetScroll = scrollTop + delta;
      
      // אנימציית גלילה בתוך העורך
      animateEditorScroll(view.scrollDOM, targetScroll);
      return true;
    }
  });
  
  // Jump to line עם אנימציה
  const jumpToLineSmooth = (view, lineNumber) => {
    const line = view.state.doc.line(lineNumber);
    const pos = line.from;
    const coords = view.coordsAtPos(pos);
    
    if (coords) {
      const targetScroll = coords.top - view.scrollDOM.offsetTop - 100;
      animateEditorScroll(view.scrollDOM, targetScroll);
      
      // הדגש את השורה לאחר הגלילה
      setTimeout(() => {
        view.dispatch({
          selection: { anchor: pos, head: pos },
          effects: EditorView.scrollIntoView(pos, {
            y: 'center'
          })
        });
      }, window.smoothScroll.config.duration);
    }
  };
  
  // פונקציית עזר לאנימציה
  function animateEditorScroll(element, target) {
    const start = element.scrollTop;
    const distance = target - start;
    const duration = window.smoothScroll.config.duration;
    const easing = window.smoothScroll.getEasingFunction(
      window.smoothScroll.config.easing
    );
    
    let startTime = null;
    
    function animate(currentTime) {
      if (!startTime) startTime = currentTime;
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const easedProgress = easing(progress);
      
      element.scrollTop = start + distance * easedProgress;
      
      if (progress < 1) {
        requestAnimationFrame(animate);
      }
    }
    
    requestAnimationFrame(animate);
  }
  
  // חשוף API גלובלי
  window.CodeMirrorSmoothScroll = {
    jumpToLine: jumpToLineSmooth
  };
  
  return [smoothScrollExtension];
}
```

---

### 3. שילוב עם TOC וניווט

**הרחבה לקובץ: `webapp/templates/md_preview.html`**

```javascript
// שיפור גלילה ב-TOC
function enhanceTOCScrolling() {
  const tocItems = document.querySelectorAll('#mdTocNav a');
  
  tocItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const targetId = item.getAttribute('href').slice(1);
      const targetElement = document.getElementById(targetId);
      
      if (targetElement && window.smoothScroll) {
        // גלילה חלקה עם offset להתחשב ב-sticky header
        window.smoothScroll.smoothScrollTo(targetElement, {
          offset: 80,
          duration: 500,
          easing: 'ease-in-out',
          callback: () => {
            // עדכון active state
            updateActiveTOCItem(item);
            // Focus לנגישות
            targetElement.focus({ preventScroll: true });
          }
        });
      }
    });
  });
}

// גלילה חכמה - מזהה אם המשתמש קורא ומאטה את הגלילה
function setupSmartScrolling() {
  let isReading = false;
  let readingTimer = null;
  
  document.addEventListener('wheel', (e) => {
    // אם גוללים לאט, כנראה קוראים
    if (Math.abs(e.deltaY) < 50) {
      isReading = true;
      clearTimeout(readingTimer);
      readingTimer = setTimeout(() => {
        isReading = false;
      }, 3000);
    }
    
    // התאם מהירות גלילה למצב קריאה
    if (window.smoothScroll && isReading) {
      window.smoothScroll.updateConfig({
        wheelSensitivity: 0.5,
        duration: 600
      });
    } else if (window.smoothScroll) {
      window.smoothScroll.updateConfig({
        wheelSensitivity: 1,
        duration: 400
      });
    }
  });
}
```

---

### 4. UI להגדרות משתמש

**הוספה לקובץ: `webapp/templates/base.html`**

```html
<!-- Modal הגדרות גלילה -->
<div id="scrollSettingsModal" class="modal" style="display: none;">
  <div class="modal-content">
    <h3>⚙️ הגדרות גלילה חלקה</h3>
    
    <!-- Toggle הפעלה -->
    <div class="setting-row">
      <label for="smoothScrollEnabled">
        <input type="checkbox" id="smoothScrollEnabled" checked>
        הפעל גלילה חלקה
      </label>
    </div>
    
    <!-- מהירות גלילה -->
    <div class="setting-row">
      <label for="scrollSpeed">מהירות גלילה:</label>
      <select id="scrollSpeed">
        <option value="200">מהיר מאוד</option>
        <option value="400" selected>רגיל</option>
        <option value="600">איטי</option>
        <option value="800">איטי מאוד</option>
      </select>
    </div>
    
    <!-- סוג אנימציה -->
    <div class="setting-row">
      <label for="scrollEasing">סגנון אנימציה:</label>
      <select id="scrollEasing">
        <option value="linear">ליניארי</option>
        <option value="ease-in">התחלה איטית</option>
        <option value="ease-out">סיום איטי</option>
        <option value="ease-in-out" selected>חלק</option>
        <option value="elastic">אלסטי</option>
      </select>
    </div>
    
    <!-- רגישות עכבר -->
    <div class="setting-row">
      <label for="wheelSensitivity">רגישות גלגלת:</label>
      <input type="range" id="wheelSensitivity" 
             min="0.1" max="3" step="0.1" value="1">
      <span id="wheelSensitivityValue">1.0</span>
    </div>
    
    <!-- רגישות מקלדת -->
    <div class="setting-row">
      <label for="keyboardSensitivity">רגישות מקלדת:</label>
      <input type="range" id="keyboardSensitivity" 
             min="0.5" max="3" step="0.1" value="1.5">
      <span id="keyboardSensitivityValue">1.5</span>
    </div>
    
    <!-- תצוגה מקדימה -->
    <div class="setting-row">
      <button onclick="testSmoothScroll()">🎯 בדוק גלילה</button>
    </div>
    
    <!-- כפתורי פעולה -->
    <div class="modal-actions">
      <button onclick="saveSmoothScrollSettings()">💾 שמור</button>
      <button onclick="resetSmoothScrollSettings()">🔄 איפוס</button>
      <button onclick="closeScrollSettings()">❌ סגור</button>
    </div>
  </div>
</div>

<script>
// פונקציות ניהול הגדרות
function openScrollSettings() {
  const modal = document.getElementById('scrollSettingsModal');
  const config = window.smoothScroll.config;
  
  // טען הגדרות נוכחיות
  document.getElementById('smoothScrollEnabled').checked = config.enabled;
  document.getElementById('scrollSpeed').value = config.duration;
  document.getElementById('scrollEasing').value = config.easing;
  document.getElementById('wheelSensitivity').value = config.wheelSensitivity;
  document.getElementById('keyboardSensitivity').value = config.keyboardSensitivity;
  
  // עדכן תצוגת ערכים
  document.getElementById('wheelSensitivityValue').textContent = 
    config.wheelSensitivity.toFixed(1);
  document.getElementById('keyboardSensitivityValue').textContent = 
    config.keyboardSensitivity.toFixed(1);
  
  modal.style.display = 'block';
}

function saveSmoothScrollSettings() {
  const config = {
    enabled: document.getElementById('smoothScrollEnabled').checked,
    duration: parseInt(document.getElementById('scrollSpeed').value),
    easing: document.getElementById('scrollEasing').value,
    wheelSensitivity: parseFloat(document.getElementById('wheelSensitivity').value),
    keyboardSensitivity: parseFloat(document.getElementById('keyboardSensitivity').value)
  };
  
  window.smoothScroll.updateConfig(config);
  
  // הפעל/כבה לפי הצורך
  if (config.enabled) {
    window.smoothScroll.enable();
  } else {
    window.smoothScroll.disable();
  }
  
  closeScrollSettings();
  showNotification('הגדרות גלילה נשמרו בהצלחה!', 'success');
}

function testSmoothScroll() {
  // יצירת אלמנט זמני לגלילה אליו
  const testTarget = document.createElement('div');
  testTarget.id = 'smooth-scroll-test-target';
  testTarget.style.position = 'absolute';
  testTarget.style.top = Math.floor(document.body.scrollHeight / 2) + 'px';
  testTarget.style.width = '1px';
  testTarget.style.height = '1px';
  testTarget.style.visibility = 'hidden';
  document.body.appendChild(testTarget);
  
  // גלול לאלמנט הזמני
  window.smoothScroll.smoothScrollTo(testTarget, {
    callback: () => {
      // הסר את האלמנט הזמני
      testTarget.remove();
      
      // חזור למעלה אחרי השהייה
      setTimeout(() => {
        window.smoothScroll.smoothScrollTo('body');
      }, 500);
    }
  });
}

function resetSmoothScrollSettings() {
  const defaultConfig = {
    enabled: true,
    duration: 400,
    easing: 'ease-in-out',
    wheelSensitivity: 1,
    keyboardSensitivity: 1.5
  };
  
  window.smoothScroll.updateConfig(defaultConfig);
  openScrollSettings(); // רענן את הטופס
}

function closeScrollSettings() {
  document.getElementById('scrollSettingsModal').style.display = 'none';
}

// מאזינים לשינויים בזמן אמת
document.getElementById('wheelSensitivity').addEventListener('input', (e) => {
  document.getElementById('wheelSensitivityValue').textContent = 
    parseFloat(e.target.value).toFixed(1);
});

document.getElementById('keyboardSensitivity').addEventListener('input', (e) => {
  document.getElementById('keyboardSensitivityValue').textContent = 
    parseFloat(e.target.value).toFixed(1);
});
</script>
```

---

### 5. סגנונות CSS

**קובץ: `webapp/static/css/smooth-scroll.css`**

```css
/* הגדרות בסיס לגלילה חלקה */
html {
  /* Enable smooth scrolling as fallback */
  scroll-behavior: smooth;
}

/* Disable browser smooth scroll when JS is active */
html.js-smooth-scroll {
  scroll-behavior: auto;
}

/* אנימציות לאלמנטים בזמן גלילה */
.scroll-animated {
  transition: transform 0.3s ease-out;
}

/* אינדיקטור גלילה */
.scroll-progress {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #4CAF50, #2196F3);
  transform-origin: left;
  transform: scaleX(0);
  transition: transform 0.1s ease-out;
  z-index: 9999;
}

/* Modal הגדרות */
#scrollSettingsModal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
  animation: fadeIn 0.3s ease-out;
}

#scrollSettingsModal .modal-content {
  background: white;
  border-radius: 12px;
  padding: 24px;
  max-width: 500px;
  width: 90%;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  animation: slideUp 0.3s ease-out;
}

.dark-mode #scrollSettingsModal .modal-content {
  background: #1e1e1e;
  color: #e0e0e0;
}

.setting-row {
  margin: 16px 0;
  display: flex;
  align-items: center;
  gap: 12px;
}

.setting-row label {
  flex: 1;
  font-weight: 500;
}

.setting-row select,
.setting-row input[type="range"] {
  flex: 1;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid #ddd;
}

.dark-mode .setting-row select,
.dark-mode .setting-row input[type="range"] {
  background: #2a2a2a;
  border-color: #444;
  color: #e0e0e0;
}

/* סגנון לסליידרים */
input[type="range"] {
  -webkit-appearance: none;
  height: 6px;
  background: #ddd;
  border-radius: 3px;
  outline: none;
}

input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  background: #2196F3;
  border-radius: 50%;
  cursor: pointer;
  transition: background 0.3s;
}

input[type="range"]::-webkit-slider-thumb:hover {
  background: #1976D2;
  transform: scale(1.1);
}

/* כפתורים */
.modal-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
  justify-content: flex-end;
}

.modal-actions button {
  padding: 10px 20px;
  border-radius: 6px;
  border: none;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s;
}

.modal-actions button:first-child {
  background: #4CAF50;
  color: white;
}

.modal-actions button:first-child:hover {
  background: #45a049;
}

/* אנימציות */
@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes slideUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

/* Momentum scrolling for touch devices */
.smooth-scroll-container {
  -webkit-overflow-scrolling: touch;
  overflow-scrolling: touch;
}

/* Performance optimization */
.will-change-scroll {
  will-change: scroll-position;
}

/* Overscroll behavior */
body {
  overscroll-behavior-y: contain;
}

/* מחוון מיקום בגלילה */
.scroll-indicator {
  position: fixed;
  right: 20px;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 100px;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 2px;
  z-index: 100;
  transition: opacity 0.3s;
  opacity: 0;
}

body.is-scrolling .scroll-indicator {
  opacity: 1;
}

.scroll-indicator-thumb {
  position: absolute;
  width: 100%;
  background: #2196F3;
  border-radius: 2px;
  transition: height 0.3s, top 0.1s;
}

/* Smooth scroll for keyboard navigation */
:focus {
  outline: 2px solid #2196F3;
  outline-offset: 2px;
}

/* Skip link for accessibility */
.skip-to-content {
  position: absolute;
  top: -40px;
  left: 0;
  background: #000;
  color: white;
  padding: 8px;
  text-decoration: none;
  z-index: 100;
  border-radius: 0 0 4px 0;
}

.skip-to-content:focus {
  top: 0;
}

/* תמיכה ב-RTL */
[dir="rtl"] .scroll-indicator {
  right: auto;
  left: 20px;
}

[dir="rtl"] .scroll-progress {
  transform-origin: right;
}

/* Reduced motion support */
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
  
  .scroll-progress,
  .scroll-animated {
    transition: none !important;
  }
}

/* High contrast mode */
@media (prefers-contrast: high) {
  .scroll-indicator {
    background: black;
    border: 1px solid white;
  }
  
  .scroll-indicator-thumb {
    background: white;
  }
  
  .scroll-progress {
    background: black;
    border-bottom: 2px solid white;
  }
}
```

---

## 🔧 אופטימיזציות וביצועים

### 1. GPU Acceleration
```css
.smooth-scroll-element {
  transform: translateZ(0);
  will-change: transform;
  backface-visibility: hidden;
}
```

### 2. Debouncing & Throttling
```javascript
// Throttle scroll events to 60fps
const throttledScroll = throttle(handleScroll, 16);

// Debounce resize events
const debouncedResize = debounce(handleResize, 250);
```

### 3. Passive Event Listeners
```javascript
// שיפור ביצועים ב-touch devices
document.addEventListener('touchmove', handleTouch, { passive: true });
```

### 4. Virtual Scrolling לרשימות ארוכות
```javascript
// מימוש virtual scrolling לרשימות עם אלפי פריטים
class VirtualScroller {
  constructor(container, items, itemHeight) {
    this.container = container;
    this.items = items;
    this.itemHeight = itemHeight;
    this.visibleRange = { start: 0, end: 50 };
    // ...
  }
}
```

---

## 📱 אופטימיזציות ספציפיות לאנדרואיד

### בעיות נפוצות באנדרואיד שהתכונה פותרת

1. **Jittery Scrolling** - גלילה מקוטעת ולא חלקה
2. **Overscroll Issues** - בעיות עם bounce ו-rubber band effects  
3. **Touch Lag** - השהייה בתגובה למגע
4. **Momentum Problems** - בעיות באינרציה של הגלילה
5. **WebView Performance** - ביצועים גרועים בתוך אפליקציות

### פתרונות ממוקדים לאנדרואיד

#### 1. Touch Event Optimization
```javascript
class AndroidScrollOptimizer {
  constructor() {
    this.isAndroid = /Android/i.test(navigator.userAgent);
    this.touchStartY = 0;
    this.touchVelocity = 0;
    this.lastTouchTime = 0;
    this.momentumID = null;
    
    if (this.isAndroid) {
      this.initAndroidOptimizations();
    }
  }
  
  initAndroidOptimizations() {
    // הפעל hardware acceleration
    document.body.style.transform = 'translateZ(0)';
    
    // מאזינים אופטימליים ל-touch
    const touchOptions = {
      passive: true,
      capture: false
    };
    
    document.addEventListener('touchstart', this.onTouchStart.bind(this), touchOptions);
    document.addEventListener('touchmove', this.onTouchMove.bind(this), touchOptions);
    document.addEventListener('touchend', this.onTouchEnd.bind(this), touchOptions);
    
    // הפעל smooth scrolling נייטיבי כ-fallback
    this.enableNativeSmoothing();
  }
  
  onTouchStart(e) {
    this.touchStartY = e.touches[0].clientY;
    this.lastTouchTime = performance.now();
    this.touchVelocity = 0;
    
    // בטל momentum קיים
    if (this.momentumID) {
      cancelAnimationFrame(this.momentumID);
    }
  }
  
  onTouchMove(e) {
    const currentY = e.touches[0].clientY;
    const currentTime = performance.now();
    const timeDelta = currentTime - this.lastTouchTime;
    const distance = currentY - this.touchStartY;
    
    // חשב מהירות
    this.touchVelocity = distance / timeDelta;
    
    // עדכן ערכים
    this.touchStartY = currentY;
    this.lastTouchTime = currentTime;
    
    // אופטימיזציה: דילוג על עדכונים מיותרים
    if (Math.abs(this.touchVelocity) < 0.01) return;
    
    // גלילה חלקה בזמן אמת
    this.performSmoothScroll(distance);
  }
  
  onTouchEnd(e) {
    // הפעל momentum scrolling משופר
    if (Math.abs(this.touchVelocity) > 0.5) {
      this.startMomentumScroll(this.touchVelocity);
    }
  }
  
  startMomentumScroll(initialVelocity) {
    let velocity = initialVelocity * 30; // המרה ל-pixels
    const friction = 0.95; // חיכוך
    const threshold = 0.5; // סף עצירה
    
    const animate = () => {
      velocity *= friction;
      
      if (Math.abs(velocity) > threshold) {
        window.scrollBy({
          top: -velocity,
          behavior: 'instant' // כבר מונפש ידנית
        });
        
        this.momentumID = requestAnimationFrame(animate);
      }
    };
    
    this.momentumID = requestAnimationFrame(animate);
  }
  
  performSmoothScroll(distance) {
    // שימוש ב-transform במקום scroll לביצועים טובים יותר
    const scrollContainer = document.querySelector('.scroll-content');
    if (scrollContainer) {
      const currentTransform = scrollContainer.style.transform;
      const currentY = this.extractTranslateY(currentTransform);
      const newY = currentY + distance;
      
      scrollContainer.style.transform = `translateY(${newY}px)`;
      scrollContainer.style.transition = 'transform 0.1s ease-out';
    } else {
      // fallback לגלילה רגילה
      window.scrollBy(0, -distance);
    }
  }
  
  enableNativeSmoothing() {
    // הפעל CSS optimizations
    const style = document.createElement('style');
    style.textContent = `
      /* Android-specific optimizations */
      .android-optimized {
        -webkit-overflow-scrolling: touch;
        overflow-scrolling: touch;
        scroll-behavior: smooth;
        -webkit-transform: translateZ(0);
        transform: translateZ(0);
        -webkit-backface-visibility: hidden;
        backface-visibility: hidden;
        -webkit-perspective: 1000;
        perspective: 1000;
        will-change: scroll-position;
      }
      
      /* מניעת overscroll bounce באנדרואיד */
      .android-no-bounce {
        overscroll-behavior-y: contain;
        overscroll-behavior-x: none;
      }
      
      /* שיפור ביצועים לאלמנטים כבדים */
      .android-optimized img,
      .android-optimized video,
      .android-optimized iframe {
        transform: translateZ(0);
        will-change: transform;
      }
      
      /* Optimize font rendering */
      .android-optimized {
        text-rendering: optimizeSpeed;
        -webkit-font-smoothing: antialiased;
      }
    `;
    document.head.appendChild(style);
    
    // החל את המחלקות על הגוף
    document.body.classList.add('android-optimized', 'android-no-bounce');
  }
  
  // כלי עזר
  extractTranslateY(transform) {
    if (!transform || transform === 'none') return 0;
    const match = transform.match(/translateY\(([-\d.]+)px\)/);
    return match ? parseFloat(match[1]) : 0;
  }
}
```

#### 2. Chrome for Android Specific
```javascript
// זיהוי Chrome באנדרואיד
const isChromeAndroid = /Chrome\/[\d.]+.*Mobile/i.test(navigator.userAgent);

if (isChromeAndroid) {
  // הפעל Passive Event Listeners
  window.addEventListener('scroll', handleScroll, { passive: true });
  
  // השתמש ב-Intersection Observer לביצועים טובים
  const scrollObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
        }
      });
    },
    {
      rootMargin: '50px',
      threshold: 0.01
    }
  );
  
  // הוסף lazy loading לתמונות
  document.querySelectorAll('img[data-src]').forEach(img => {
    scrollObserver.observe(img);
  });
}
```

#### 3. Samsung Internet Browser
```javascript
// זיהוי Samsung Internet
const isSamsungBrowser = /SamsungBrowser/i.test(navigator.userAgent);

if (isSamsungBrowser) {
  // Samsung Internet דורש optimizations שונות
  const samsungOptimizer = {
    init() {
      // השבת smooth scrolling נייטיבי (בעייתי ב-Samsung)
      document.documentElement.style.scrollBehavior = 'auto';
      
      // השתמש ב-custom implementation
      this.setupCustomScroll();
    },
    
    setupCustomScroll() {
      let scrolling = false;
      let scrollTimeout;
      
      window.addEventListener('scroll', () => {
        if (!scrolling) {
          document.body.classList.add('is-scrolling');
        }
        
        scrolling = true;
        clearTimeout(scrollTimeout);
        
        scrollTimeout = setTimeout(() => {
          scrolling = false;
          document.body.classList.remove('is-scrolling');
        }, 150);
      });
    }
  };
  
  samsungOptimizer.init();
}
```

#### 4. WebView בתוך אפליקציות
```javascript
// זיהוי WebView
const isWebView = () => {
  const standalone = window.navigator.standalone;
  const userAgent = window.navigator.userAgent.toLowerCase();
  const safari = /safari/.test(userAgent);
  const ios = /iphone|ipod|ipad/.test(userAgent);
  const android = /android/.test(userAgent);
  
  // iOS WebView
  if (ios) {
    if (!standalone && !safari) return true;
  }
  
  // Android WebView
  if (android) {
    // בדוק אם יש wv בגרסה
    if (userAgent.includes('wv')) return true;
    // בדוק אם אין Chrome/Firefox
    if (!userAgent.includes('chrome') && !userAgent.includes('firefox')) return true;
  }
  
  return false;
};

if (isWebView()) {
  // אופטימיזציות ל-WebView
  const webViewOptimizer = {
    init() {
      // הגבל את כמות ה-DOM nodes הנראים
      this.enableVirtualScrolling();
      
      // השתמש ב-RAF לכל האנימציות
      this.optimizeAnimations();
      
      // מזער reflows ו-repaints
      this.batchDOMUpdates();
    },
    
    enableVirtualScrolling() {
      // מימוש virtual scrolling לרשימות ארוכות
      const listContainer = document.querySelector('.long-list');
      if (listContainer) {
        const virtualScroller = new VirtualScroller(listContainer, {
          itemHeight: 80,
          buffer: 5,
          renderItem: (item) => {
            const element = document.createElement('div');
            element.className = 'list-item';
            element.textContent = item.text;
            return element;
          }
        });
        virtualScroller.init();
      }
    },
    
    optimizeAnimations() {
      // השתמש ב-RAF לכל האנימציות
      const originalAnimate = Element.prototype.animate;
      Element.prototype.animate = function(...args) {
        return new Promise(resolve => {
          requestAnimationFrame(() => {
            const animation = originalAnimate.apply(this, args);
            animation.onfinish = resolve;
          });
        });
      };
    },
    
    batchDOMUpdates() {
      // קבץ עדכוני DOM
      const pendingUpdates = [];
      let rafId = null;
      
      window.batchUpdate = (updateFn) => {
        pendingUpdates.push(updateFn);
        
        if (!rafId) {
          rafId = requestAnimationFrame(() => {
            const fragment = document.createDocumentFragment();
            pendingUpdates.forEach(fn => fn(fragment));
            document.body.appendChild(fragment);
            
            pendingUpdates.length = 0;
            rafId = null;
          });
        }
      };
    }
  };
  
  webViewOptimizer.init();
}
```

### 5. מדידת ביצועים באנדרואיד

```javascript
class AndroidPerformanceMonitor {
  constructor() {
    this.metrics = {
      fps: [],
      scrollLatency: [],
      jank: 0,
      smoothness: 100
    };
    
    if (this.isAndroid()) {
      this.startMonitoring();
    }
  }
  
  isAndroid() {
    return /Android/i.test(navigator.userAgent);
  }
  
  startMonitoring() {
    // מדידת FPS
    let lastTime = performance.now();
    let frames = 0;
    
    const measureFPS = () => {
      frames++;
      const currentTime = performance.now();
      
      if (currentTime >= lastTime + 1000) {
        const fps = Math.round((frames * 1000) / (currentTime - lastTime));
        this.metrics.fps.push(fps);
        
        // זהה jank (FPS < 30)
        if (fps < 30) {
          this.metrics.jank++;
        }
        
        frames = 0;
        lastTime = currentTime;
        
        // חשב smoothness score
        this.calculateSmoothness();
      }
      
      requestAnimationFrame(measureFPS);
    };
    
    requestAnimationFrame(measureFPS);
    
    // מדידת scroll latency
    let scrollStart = 0;
    
    window.addEventListener('touchstart', () => {
      scrollStart = performance.now();
    });
    
    window.addEventListener('scroll', () => {
      if (scrollStart) {
        const latency = performance.now() - scrollStart;
        this.metrics.scrollLatency.push(latency);
        scrollStart = 0;
      }
    });
  }
  
  calculateSmoothness() {
    const avgFPS = this.metrics.fps.reduce((a, b) => a + b, 0) / this.metrics.fps.length;
    const avgLatency = this.metrics.scrollLatency.reduce((a, b) => a + b, 0) / this.metrics.scrollLatency.length || 0;
    
    // חישוב ציון חלקות (0-100)
    const fpsScore = Math.min((avgFPS / 60) * 100, 100);
    const latencyScore = Math.max(100 - (avgLatency / 2), 0);
    const jankPenalty = Math.min(this.metrics.jank * 5, 50);
    
    this.metrics.smoothness = Math.round(
      (fpsScore * 0.6 + latencyScore * 0.4) - jankPenalty
    );
    
    // שלח ל-analytics
    this.reportMetrics();
  }
  
  reportMetrics() {
    // שלח מטריקות לשרת
    if (this.metrics.smoothness < 70) {
      console.warn('Android scroll performance degraded:', this.metrics);
      
      // הפעל fallback mode
      if (window.smoothScroll) {
        window.smoothScroll.enableAndroidFallback();
      }
    }
  }
  
  getReport() {
    return {
      avgFPS: Math.round(this.metrics.fps.reduce((a, b) => a + b, 0) / this.metrics.fps.length),
      avgLatency: Math.round(this.metrics.scrollLatency.reduce((a, b) => a + b, 0) / this.metrics.scrollLatency.length),
      jankFrames: this.metrics.jank,
      smoothnessScore: this.metrics.smoothness,
      recommendation: this.metrics.smoothness >= 80 ? 'Good' : 
                     this.metrics.smoothness >= 60 ? 'Fair' : 'Poor'
    };
  }
}

// הפעלה אוטומטית
const androidMonitor = new AndroidPerformanceMonitor();
```

### 6. הגדרות מומלצות לאנדרואיד

```javascript
// הגדרות אופטימליות למכשירי אנדרואיד
const ANDROID_OPTIMAL_CONFIG = {
  // גלילה
  scrollDuration: 300,        // מהירה יותר מ-desktop
  scrollEasing: 'ease-out',   // סיום חלק
  wheelSensitivity: 1.2,      // רגישות גבוהה יותר
  
  // Touch
  touchThreshold: 10,         // סף תחילת גלילה (pixels)
  momentumMultiplier: 1.5,    // הגברת אינרציה
  swipeVelocity: 0.5,         // מהירות סוויייפ מינימלית
  
  // ביצועים
  useTransform: true,         // transform במקום scroll
  usePassive: true,           // passive listeners
  throttleDelay: 16,          // 60fps
  debounceDelay: 100,         // עיכוב לאירועים
  
  // Features
  enableMomentum: true,       // אינרציה
  enableOverscroll: false,    // ללא bounce
  enableRubberBand: false,    // ללא rubber band
  enableSmoothKeyboard: true, // גלילה חלקה במקלדת
};

// החלת ההגדרות
if (/Android/i.test(navigator.userAgent)) {
  window.smoothScroll?.updateConfig(ANDROID_OPTIMAL_CONFIG);
}
```

---

## 🧪 בדיקות

### Unit Tests
```javascript
// tests/test_smooth_scroll.js
describe('SmoothScrollManager', () => {
  it('should initialize with default config', () => {
    const manager = new SmoothScrollManager();
    expect(manager.config.duration).toBe(400);
    expect(manager.config.enabled).toBe(true);
  });
  
  it('should calculate correct scroll position', () => {
    const manager = new SmoothScrollManager();
    const result = manager.normalizeWheelDelta({ deltaY: 100, deltaMode: 0 });
    expect(result).toBe(100);
  });
  
  it('should save preferences to localStorage', async () => {
    const manager = new SmoothScrollManager();
    manager.updateConfig({ duration: 500 });
    await manager.savePreferences();
    
    const saved = JSON.parse(localStorage.getItem('smoothScrollPrefs'));
    expect(saved.duration).toBe(500);
  });
});
```

### E2E Tests
```python
# tests/test_smooth_scroll_e2e.py
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
import time

def test_smooth_scroll_keyboard():
    """בדיקת גלילה חלקה עם מקלדת"""
    driver = webdriver.Chrome()
    driver.get("http://localhost:5000/view/test-document")
    
    # שמור מיקום התחלתי
    initial_position = driver.execute_script("return window.pageYOffset")
    
    # לחץ Page Down
    body = driver.find_element_by_tag_name("body")
    body.send_keys(Keys.PAGE_DOWN)
    
    # המתן לאנימציה
    time.sleep(0.5)
    
    # בדוק שהמיקום השתנה
    new_position = driver.execute_script("return window.pageYOffset")
    assert new_position > initial_position
    
    driver.quit()

def test_smooth_scroll_anchor_links():
    """בדיקת גלילה חלקה לעוגנים"""
    driver = webdriver.Chrome()
    driver.get("http://localhost:5000/view/test-document")
    
    # לחץ על קישור עוגן
    link = driver.find_element_by_css_selector('a[href="#section-2"]')
    link.click()
    
    # המתן לאנימציה
    time.sleep(0.5)
    
    # בדוק שהאלמנט נמצא במרכז המסך
    target = driver.find_element_by_id("section-2")
    rect = target.rect
    viewport_height = driver.execute_script("return window.innerHeight")
    scroll_pos = driver.execute_script("return window.pageYOffset")
    
    element_center = rect['y'] + rect['height'] / 2
    viewport_center = scroll_pos + viewport_height / 2
    
    # בדוק שהאלמנט קרוב למרכז (עם סטייה של 100px)
    assert abs(element_center - viewport_center) < 100
    
    driver.quit()
```

---

## 📊 מדדי ביצועים

### מדדים להצלחה
- **FPS**: שמירה על 60fps בזמן גלילה
- **Input Latency**: < 50ms מרגע הפעולה עד תחילת האנימציה
- **Jank**: < 5% מהפריימים עם jank
- **Battery**: < 5% עלייה בצריכת סוללה

### ניטור
```javascript
// מדידת ביצועים
const performanceObserver = new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) {
    if (entry.entryType === 'measure' && entry.name === 'smooth-scroll') {
      console.log(`Scroll animation took ${entry.duration}ms`);
      
      // שלח ל-analytics
      if (window.ga) {
        ga('send', 'timing', 'Smooth Scroll', 'Animation', Math.round(entry.duration));
      }
    }
  }
});

performanceObserver.observe({ entryTypes: ['measure'] });
```

---

## 🌍 נגישות

### תמיכה ב-Screen Readers
```javascript
// הודעה ל-screen readers על מיקום חדש
function announceScrollPosition() {
  const announcement = document.createElement('div');
  announcement.setAttribute('role', 'status');
  announcement.setAttribute('aria-live', 'polite');
  announcement.className = 'sr-only';
  
  const percent = Math.round((window.pageYOffset / 
    (document.documentElement.scrollHeight - window.innerHeight)) * 100);
  
  announcement.textContent = `גלילה למיקום ${percent}% בעמוד`;
  document.body.appendChild(announcement);
  
  setTimeout(() => announcement.remove(), 1000);
}
```

### Keyboard Navigation
- **Tab**: ניווט בין אלמנטים
- **Enter/Space**: הפעלת קישורים
- **Escape**: ביטול גלילה בתהליך
- **Home/End**: תחילת/סוף העמוד
- **Page Up/Down**: עמוד למעלה/למטה

---

## 🚀 הטמעה מדורגת

### שלב 1: גרסת בטא (שבוע 1)
- [ ] מימוש בסיסי של גלילה חלקה
- [ ] תמיכה בעכבר ומקלדת
- [ ] UI הגדרות בסיסי
- [ ] בדיקות עם קבוצת בטא

### שלב 2: שיפורים (שבוע 2-3)
- [ ] אינטגרציה עם CodeMirror
- [ ] תמיכה ב-touch devices
- [ ] אופטימיזציות ביצועים
- [ ] בדיקות נרחבות

### שלב 3: הפצה מלאה (שבוע 4)
- [ ] תיעוד למשתמשים
- [ ] ניטור ביצועים
- [ ] A/B testing
- [ ] הפעלה הדרגתית לכל המשתמשים

---

## 📚 משאבים נוספים

### תיעוד
- [MDN - Scroll Behavior](https://developer.mozilla.org/en-US/docs/Web/CSS/scroll-behavior)
- [Web.dev - Smooth Scrolling](https://web.dev/smooth-scrolling/)
- [CodeMirror 6 - Scroll Events](https://codemirror.net/docs/ref/#view.EditorView.scrollHandler)

### ספריות רלוונטיות
- [smooth-scrollbar](https://github.com/idiotWu/smooth-scrollbar)
- [locomotive-scroll](https://github.com/locomotivemtl/locomotive-scroll)
- [AOS (Animate On Scroll)](https://github.com/michalsnik/aos)

### כלי בדיקה
- Chrome DevTools Performance Panel
- Lighthouse (Web Vitals)
- WebPageTest

---

## 🤝 תרומה ומשוב

לתרומה למדריך או לתכונה:
1. פתח Issue ב-GitHub
2. הצע PR עם שיפורים
3. שתף משוב מחוויית השימוש

---

**עדכון אחרון:** נובמבר 2024  
**גרסה:** 1.0.0  
**מחבר:** צוות CodeBot WebApp