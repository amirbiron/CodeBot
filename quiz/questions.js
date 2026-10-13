export const categories = {
  architecture: { name: '🏗️ ארכיטקטורה', emoji: '🏗️' },
  database: { name: '💾 בסיס נתונים', emoji: '💾' },
  security: { name: '🔒 אבטחה', emoji: '🔒' },
  testing: { name: '🧪 בדיקות ו-CI', emoji: '🧪' },
  integrations: { name: '🔗 אינטגרציות', emoji: '🔗' },
  performance: { name: '⚡ ביצועים', emoji: '⚡' },
  observability: { name: '📊 ניטור ו-Metrics', emoji: '📊' },
  configuration: { name: '⚙️ הגדרות', emoji: '⚙️' },
  resilience: { name: '🛡️ עמידות', emoji: '🛡️' },
  alerts: { name: '🚨 התראות', emoji: '🚨' },
  handlers: { name: '🔄 Handlers ו-State', emoji: '🔄' },
  docs: { name: '📝 תיעוד ו-Conventions', emoji: '📝' }
};

export const questions = [

  // ===== ארכיטקטורה =====

  {
    id: 'arch_1',
    category: 'architecture',
    type: 'multiple',
    question: 'כמה שכבות עיקריות יש בארכיטקטורת Clean Architecture של CodeBot?',
    options: ['3', '4', '6', '8'],
    correct: 2,
    explanation: 'הארכיטקטורה כוללת 6 שכבות: Telegram Interface → Command Processing → Core Services → Storage → Monitoring & Alerts'
  },
  {
    id: 'arch_2',
    category: 'architecture',
    type: 'multiple',
    question: 'מהו ה-Flow העיקרי של הבוט?',
    options: [
      'Services → Database → Handlers',
      'Handlers → Services → Database (MongoDB)',
      'Database → Services → Handlers',
      'Telegram → Database → Services'
    ],
    correct: 1,
    explanation: 'הזרימה המרכזית היא Handlers → Services → Database (MongoDB)'
  },
  {
    id: 'arch_3',
    category: 'architecture',
    type: 'boolean',
    question: 'ה-DocumentHandler מקבל את התלויות שלו דרך Dependency Injection.',
    correct: true,
    explanation: 'DocumentHandler מקבל בהזרקה: notify_admins, log_user_activity, emit_event, errors_total, encodings_to_try'
  },
  {
    id: 'arch_4',
    category: 'architecture',
    type: 'multiple',
    question: 'כיצד משותף ה-HTTP session בין הקומפוננטות?',
    options: [
      'כל קומפוננטה יוצרת session משלה',
      'דרך Singleton global',
      'דרך http_async.get_session() עם aiohttp.ClientSession משותף',
      'דרך Redis cache'
    ],
    correct: 2,
    explanation: 'ה-HTTP session משותף דרך http_async.get_session() שמחזיר aiohttp.ClientSession משותף'
  },
  {
    id: 'arch_5',
    category: 'architecture',
    type: 'multiple',
    question: 'אילו אחסונים (Storage backends) משמשים את המערכת?',
    options: [
      'MySQL, Memcached, S3',
      'MongoDB, Redis Cache, File System',
      'PostgreSQL, Redis, File System',
      'SQLite, Redis, Cloud Storage'
    ],
    correct: 1,
    explanation: 'המערכת משתמשת ב-MongoDB כבסיס נתונים ראשי, Redis Cache לקאשינג, ו-File System לאחסון קבצים'
  },

  // ===== בסיס נתונים =====

  {
    id: 'db_1',
    category: 'database',
    type: 'multiple',
    question: 'אילו שדות מאוינדקסים עם Text Search ב-code_snippets?',
    options: [
      'user_id, created_at',
      'file_name, code, note',
      'tags, is_deleted',
      'programming_language, version'
    ],
    correct: 1,
    explanation: 'השדות file_name, code ו-note מאוינדקסים עם text search index כדי לאפשר חיפוש חופשי'
  },
  {
    id: 'db_2',
    category: 'database',
    type: 'multiple',
    question: 'מהו ה-Compound Index העיקרי ב-code_snippets?',
    options: [
      '(file_name, programming_language)',
      '(user_id, created_at)',
      '(tags, is_deleted)',
      '(code, note)'
    ],
    correct: 1,
    explanation: 'ה-Compound Index העיקרי הוא (user_id, created_at) שמאפשר שליפה מהירה של קבצי המשתמש לפי זמן'
  },
  {
    id: 'db_3',
    category: 'database',
    type: 'boolean',
    question: 'ה-collection של sessions משתמש ב-TTL index על שדה expires_at.',
    correct: true,
    explanation: 'ה-sessions collection משתמש ב-TTL index על expires_at כדי למחוק sessions שפג תוקפם אוטומטית'
  },
  {
    id: 'db_4',
    category: 'database',
    type: 'multiple',
    question: 'כיצד מחוברים bookmarks ל-code_snippets?',
    options: [
      'דרך user_id בלבד',
      'דרך bookmark_name',
      'דרך file_id שמפנה ל-code_snippets',
      'דרך tags משותפים'
    ],
    correct: 2,
    explanation: 'bookmarks מחוברים ל-code_snippets דרך שדה file_id שמפנה לרשומה ב-code_snippets'
  },
  {
    id: 'db_5',
    category: 'database',
    type: 'multiple',
    question: 'מהו ערך ברירת המחדל של MONGODB_MAX_POOL_SIZE?',
    options: ['10', '25', '50', '100'],
    correct: 2,
    explanation: 'ברירת המחדל של MONGODB_MAX_POOL_SIZE היא 50 חיבורים'
  },

  // ===== אבטחה =====

  {
    id: 'sec_1',
    category: 'security',
    type: 'multiple',
    question: 'מהו הגבול של callback data בטלגרם?',
    options: ['32 bytes', '64 bytes', '128 bytes', '256 bytes'],
    correct: 1,
    explanation: 'Telegram מגביל callback data ל-64 bytes. לנתונים ארוכים יותר משתמשים ב-token shortcuts'
  },
  {
    id: 'sec_2',
    category: 'security',
    type: 'boolean',
    question: 'Code Execution Playground זמין לכל המשתמשים.',
    correct: false,
    explanation: 'Code Execution Playground (/tools/code) זמין רק למשתמשי Premium/Admin'
  },
  {
    id: 'sec_3',
    category: 'security',
    type: 'multiple',
    question: 'באיזה אחוז שימוש מופיעה אזהרת rate limit רכה?',
    options: ['50%', '70%', '80%', '90%'],
    correct: 2,
    explanation: 'אזהרה רכה (soft warning) מופיעה כשהמשתמש מגיע ל-80% מהמכסה שלו'
  },
  {
    id: 'sec_4',
    category: 'security',
    type: 'multiple',
    question: 'איזה מנגנון משמש להצפנת טוקנים?',
    options: ['AES-256', 'RSA', 'Fernet', 'bcrypt'],
    correct: 2,
    explanation: 'הצפנת טוקנים מתבצעת באמצעות Fernet (מספריית cryptography של Python)'
  },
  {
    id: 'sec_5',
    category: 'security',
    type: 'boolean',
    question: 'מותר לרשום (log) מידע אישי מזהה (PII) של משתמשים.',
    correct: false,
    explanation: 'אסור לרשום PII. יש לבצע השחרה (redaction) לערכים רגישים בלוגים ולהשתמש ב-ENV/Secret Manager לסודות'
  },

  // ===== בדיקות ו-CI =====

  {
    id: 'test_1',
    category: 'testing',
    type: 'multiple',
    question: 'אילו CI checks נדרשים לפני merge?',
    options: [
      'Lint, Build, Deploy',
      'Code Quality & Security, Unit Tests (3.11), Unit Tests (3.12)',
      'Unit Tests, Integration Tests, E2E Tests',
      'Prettier, ESLint, TypeCheck'
    ],
    correct: 1,
    explanation: 'שלושת הבדיקות הנדרשות: "🔍 Code Quality & Security", "Unit Tests (3.11)", "Unit Tests (3.12)"'
  },
  {
    id: 'test_2',
    category: 'testing',
    type: 'multiple',
    question: 'היכן ממוקם קובץ ה-stubs של Telegram לבדיקות?',
    options: [
      'tests/mocks/telegram.py',
      'tests/_telegram_stubs.py',
      'tests/fixtures/telegram_mock.py',
      'conftest.py'
    ],
    correct: 1,
    explanation: 'ה-stubs ממוקמים ב-tests/_telegram_stubs.py ונטענים אוטומטית דרך conftest.py'
  },
  {
    id: 'test_3',
    category: 'testing',
    type: 'boolean',
    question: 'בטסטים מותר לכתוב קבצים לתיקיית root של הפרויקט.',
    correct: false,
    explanation: 'כל ה-IO בטסטים חייב להשתמש ב-tmp_path (pytest fixture). אסור לכתוב או למחוק בתיקיות קוד מקור'
  },
  {
    id: 'test_4',
    category: 'testing',
    type: 'multiple',
    question: 'אילו markers קיימים לבדיקות ביצועים?',
    options: [
      '@pytest.mark.slow ו-@pytest.mark.fast',
      '@pytest.mark.performance ו-@pytest.mark.heavy',
      '@pytest.mark.benchmark ו-@pytest.mark.stress',
      '@pytest.mark.perf ו-@pytest.mark.load'
    ],
    correct: 1,
    explanation: 'שני ה-markers לבדיקות ביצועים הם @pytest.mark.performance ו-@pytest.mark.heavy'
  },
  {
    id: 'test_5',
    category: 'testing',
    type: 'multiple',
    question: 'אילו משתני סביבה נדרשים להרצת בדיקות?',
    options: [
      'TEST_MODE=1, DB_URL=test',
      'DISABLE_ACTIVITY_REPORTER=1, DISABLE_DB=1, BOT_TOKEN=x',
      'ENV=test, DEBUG=true',
      'PYTEST=true, MOCK_ALL=1'
    ],
    correct: 1,
    explanation: 'הטסטים דורשים DISABLE_ACTIVITY_REPORTER=1, DISABLE_DB=1 ו-BOT_TOKEN=x (ערך דמה)'
  },

  // ===== אינטגרציות =====

  {
    id: 'integ_1',
    category: 'integrations',
    type: 'multiple',
    question: 'אילו GitHub scopes נדרשים ליצירת Pull Request?',
    options: [
      'read, write',
      'repo, workflow',
      'admin, push',
      'pull_request, actions'
    ],
    correct: 1,
    explanation: 'ליצירת PR נדרשים scopes: repo ו-workflow'
  },
  {
    id: 'integ_2',
    category: 'integrations',
    type: 'multiple',
    question: 'מה מגבלת ה-rate limit של GitHub API עם אימות?',
    options: [
      '1000 בקשות לשעה',
      '3000 בקשות לשעה',
      '5000 בקשות לשעה',
      '10000 בקשות לשעה'
    ],
    correct: 2,
    explanation: 'GitHub מאפשר 5000 בקשות לשעה עם אימות, ורק 60 בקשות לשעה ללא אימות'
  },
  {
    id: 'integ_3',
    category: 'integrations',
    type: 'boolean',
    question: 'CodeBot תומך באינטגרציה עם GitLab ו-Bitbucket.',
    correct: false,
    explanation: 'רק GitHub נתמך. GitLab ו-Bitbucket אינם נתמכים'
  },
  {
    id: 'integ_4',
    category: 'integrations',
    type: 'multiple',
    question: 'מהו ה-secondary rate limit של GitHub?',
    options: [
      '10 בקשות לדקה',
      '1 בקשה לשנייה',
      '100 בקשות לדקה',
      '5 בקשות לשנייה'
    ],
    correct: 1,
    explanation: 'ה-secondary rate limit של GitHub הוא 1 בקשה לשנייה'
  },

  // ===== ביצועים =====

  {
    id: 'perf_1',
    category: 'performance',
    type: 'multiple',
    question: 'מהי הבעיה שנפתרה ב-Sticky Notes לגבי ביצועים?',
    options: [
      'שאילתות SQL איטיות',
      '_ensure_indexes() רץ בכל בקשה ונעל את _db_lock',
      'חוסר cache',
      'חיבורי Redis מרובים'
    ],
    correct: 1,
    explanation: 'הבעיה הייתה ש-_ensure_indexes() רץ בכל בקשה וננעל על _db_lock, מה שיצר צוואר בקבוק'
  },
  {
    id: 'perf_2',
    category: 'performance',
    type: 'multiple',
    question: 'מה ערך ה-timeout של Gunicorn שפותר את בעיית Sticky Notes?',
    options: ['30 שניות', '60 שניות', '120 שניות', '180 שניות'],
    correct: 3,
    explanation: 'הפתרון המוכח הוא Gunicorn timeout של 180 שניות'
  },
  {
    id: 'perf_3',
    category: 'performance',
    type: 'boolean',
    question: 'לפי חוק ה-Smart Projection, מותר למשוך את שדות code ו-content בשאילתות רשימה.',
    correct: false,
    explanation: 'לעולם אין למשוך את שדות code, content או raw_data בשאילתות שמחזירות רשימה. יש להשתמש ב-HEAVY_FIELDS_EXCLUDE_PROJECTION'
  },
  {
    id: 'perf_4',
    category: 'performance',
    type: 'multiple',
    question: 'מה הזמן המקסימלי שדף WebApp צריך להחזיר HTML ראשוני?',
    options: ['50ms', '100ms', '200ms', '500ms'],
    correct: 2,
    explanation: 'דפים כבדים ב-WebApp צריכים להחזיר HTML ראשוני מהר (< 200ms) ולהשתמש ב-Skeleton Loaders'
  },
  {
    id: 'perf_5',
    category: 'performance',
    type: 'multiple',
    question: 'מה יש להימנע ממנו בשאילתות MongoDB לפי הנחיות הביצועים?',
    options: ['INDEX SCAN', 'COLLSCAN', 'PROJECTION', 'AGGREGATE'],
    correct: 1,
    explanation: 'יש להימנע מ-COLLSCAN (סריקה מלאה של ה-collection) ולוודא שימוש ב-compound indexes'
  },

  // ===== ניטור ו-Metrics =====

  {
    id: 'obs_1',
    category: 'observability',
    type: 'multiple',
    question: 'מהו ה-endpoint של Prometheus metrics?',
    options: ['/health', '/status', '/metrics', '/prometheus'],
    correct: 2,
    explanation: 'ה-endpoint לחשיפת metrics הוא /metrics'
  },
  {
    id: 'obs_2',
    category: 'observability',
    type: 'multiple',
    question: 'מהי מדיניות ה-Fail-Open ב-Observability?',
    options: [
      'המערכת נכשלת אם אין tracing',
      'המערכת ממשיכה לפעול גם ללא tracing/metrics',
      'המערכת עוברת למצב debug',
      'המערכת שולחת alert על כשל'
    ],
    correct: 1,
    explanation: 'Fail-Open אומר שהמערכת ממשיכה לעבוד תקין גם אם tracing או metrics לא זמינים'
  },
  {
    id: 'obs_3',
    category: 'observability',
    type: 'multiple',
    question: 'מהו ה-URL של ממשק Jaeger?',
    options: [
      'http://localhost:9090',
      'http://localhost:3000',
      'http://localhost:16686',
      'http://localhost:8080'
    ],
    correct: 2,
    explanation: 'ממשק Jaeger זמין ב-http://localhost:16686'
  },
  {
    id: 'obs_4',
    category: 'observability',
    type: 'boolean',
    question: 'structlog משמש ל-structured logging במערכת.',
    correct: true,
    explanation: 'המערכת משתמשת ב-structlog ללוגים מובנים עם שדות כמו schema_version, event, severity, timestamp, request_id, trace_id'
  },
  {
    id: 'obs_5',
    category: 'observability',
    type: 'multiple',
    question: 'אילו ערכים אפשריים לתווית cache_hit ב-metrics?',
    options: [
      'true, false',
      'yes, no',
      'hit, miss, unknown',
      '1, 0'
    ],
    correct: 2,
    explanation: 'תווית cache_hit יכולה להיות: hit, miss, או unknown'
  },

  // ===== הגדרות =====

  {
    id: 'config_1',
    category: 'configuration',
    type: 'multiple',
    question: 'מהו סדר העדיפויות של מקורות ההגדרות (מהגבוה לנמוך)?',
    options: [
      '.env → .env.local → environment variables',
      'environment variables → .env.local → .env',
      '.env.local → .env → environment variables',
      '.env.local → environment variables → .env'
    ],
    correct: 1,
    explanation: 'סדר העדיפויות (מהגבוה לנמוך): environment variables (הגבוה ביותר) → .env.local → .env. משתני סביבה תמיד גוברים'
  },
  {
    id: 'config_2',
    category: 'configuration',
    type: 'multiple',
    question: 'אילו משתני סביבה חובה להפעלת הבוט?',
    options: [
      'BOT_TOKEN, REDIS_URL',
      'BOT_TOKEN, MONGODB_URL',
      'MONGODB_URL, GITHUB_TOKEN',
      'BOT_TOKEN, SECRET_KEY'
    ],
    correct: 1,
    explanation: 'שני משתני הסביבה ההכרחיים הם BOT_TOKEN ו-MONGODB_URL'
  },
  {
    id: 'config_3',
    category: 'configuration',
    type: 'multiple',
    question: 'מה ערך ברירת המחדל של TELEGRAM_READ_TIMEOUT_SECS?',
    options: ['10', '20', '30', '60'],
    correct: 2,
    explanation: 'ברירת המחדל של TELEGRAM_READ_TIMEOUT_SECS היא 30 שניות'
  },
  {
    id: 'config_4',
    category: 'configuration',
    type: 'boolean',
    question: 'MONGODB_URL חייב להתחיל ב-mongodb:// או mongodb+srv://.',
    correct: true,
    explanation: 'וולידציית ההגדרות דורשת ש-MONGODB_URL יתחיל ב-mongodb:// או mongodb+srv://'
  },

  // ===== עמידות =====

  {
    id: 'res_1',
    category: 'resilience',
    type: 'multiple',
    question: 'מהו מספר ניסיונות ה-retry ברירת המחדל ב-resilience layer?',
    options: ['1', '2', '3', '5'],
    correct: 2,
    explanation: 'HTTP_RESILIENCE_MAX_ATTEMPTS ברירת המחדל הוא 3 ניסיונות'
  },
  {
    id: 'res_2',
    category: 'resilience',
    type: 'multiple',
    question: 'לאחר כמה כשלונות נפתח ה-Circuit Breaker?',
    options: ['3', '5', '7', '10'],
    correct: 1,
    explanation: 'CIRCUIT_BREAKER_FAILURE_THRESHOLD ברירת המחדל הוא 5 כשלונות'
  },
  {
    id: 'res_3',
    category: 'resilience',
    type: 'multiple',
    question: 'מה זמן ההמתנה לפני שה-Circuit Breaker עובר ל-half-open?',
    options: ['10 שניות', '20 שניות', '30 שניות', '60 שניות'],
    correct: 2,
    explanation: 'CIRCUIT_BREAKER_RECOVERY_SECONDS ברירת המחדל הוא 30 שניות'
  },
  {
    id: 'res_4',
    category: 'resilience',
    type: 'boolean',
    question: 'כשה-Redis לא זמין, המערכת קורסת לחלוטין.',
    correct: false,
    explanation: 'כש-Redis לא זמין, המערכת ממשיכה לפעול ללא cache (fallback to no cache)'
  },
  {
    id: 'res_5',
    category: 'resilience',
    type: 'multiple',
    question: 'מהו ה-backoff base ברירת המחדל?',
    options: ['0.1 שניות', '0.25 שניות', '0.5 שניות', '1 שנייה'],
    correct: 1,
    explanation: 'HTTP_RESILIENCE_BACKOFF_BASE ברירת המחדל הוא 0.25 שניות, עם backoff מקסימלי של 8 שניות'
  },

  // ===== התראות =====

  {
    id: 'alert_1',
    category: 'alerts',
    type: 'multiple',
    question: 'מהו ערך ברירת המחדל של ALERT_COOLDOWN_SEC?',
    options: ['60', '120', '300', '600'],
    correct: 2,
    explanation: 'ALERT_COOLDOWN_SEC ברירת המחדל הוא 300 שניות (5 דקות)'
  },
  {
    id: 'alert_2',
    category: 'alerts',
    type: 'multiple',
    question: 'מהו ה-Startup Grace Period של האפליקציה לפני בדיקת התראות ביצועים?',
    options: ['5 דקות', '10 דקות', '20 דקות', '30 דקות'],
    correct: 2,
    explanation: 'ALERT_STARTUP_GRACE_PERIOD_SECONDS ברירת המחדל הוא 1200 שניות (20 דקות) כדי למנוע false positives אחרי deploy/cold start'
  },
  {
    id: 'alert_3',
    category: 'alerts',
    type: 'multiple',
    question: 'מהו סף אזהרת שטח דיסק נמוך?',
    options: ['50MB', '100MB', '200MB', '500MB'],
    correct: 2,
    explanation: 'התראת disk_low_space מופעלת כשנותרו פחות מ-200MB, עם rate-limit של 10 דקות'
  },
  {
    id: 'alert_4',
    category: 'alerts',
    type: 'boolean',
    question: 'ב-Visual Rule Engine, רק מנהלים (Admins) יכולים ליצור כללי התראות.',
    correct: true,
    explanation: 'Visual Rule Engine הוא Admin-only feature (מוגבל ל-ADMIN_USER_IDS)'
  },
  {
    id: 'alert_5',
    category: 'alerts',
    type: 'multiple',
    question: 'אילו פעולות (actions) תומך ה-Visual Rule Engine?',
    options: [
      'log, email, sms, page',
      'suppress, send_alert, create_github_issue, webhook',
      'block, allow, redirect, notify',
      'alert, silence, escalate, resolve'
    ],
    correct: 1,
    explanation: 'הפעולות הנתמכות: suppress, send_alert, create_github_issue, webhook'
  },

  // ===== Handlers ו-State =====

  {
    id: 'handler_1',
    category: 'handlers',
    type: 'multiple',
    question: 'מהם שלבי ה-Save Flow בבוט?',
    options: [
      'GET_CODE → saved',
      'GET_CODE → GET_FILENAME → GET_NOTE → saved',
      'GET_FILENAME → GET_CODE → saved',
      'UPLOAD → PROCESS → SAVE'
    ],
    correct: 1,
    explanation: 'ה-Save Flow עובר: GET_CODE → GET_FILENAME → GET_NOTE → saved'
  },
  {
    id: 'handler_2',
    category: 'handlers',
    type: 'multiple',
    question: 'מה קורה כשמשתמש לוחץ על כפתור ❌ (Cancel)?',
    options: [
      'ההודעה נמחקת',
      'המשתמש חוזר לתפריט הראשי',
      'ה-context.user_data מתנקה (cleanup)',
      'הבוט מתאתחל מחדש'
    ],
    correct: 2,
    explanation: 'לחיצה על Cancel מנקה את context.user_data ומסיימת את ה-conversation'
  },
  {
    id: 'handler_3',
    category: 'handlers',
    type: 'multiple',
    question: 'אילו states יש בתהליך GitHub Upload?',
    options: [
      'UPLOAD → DONE',
      'FILE_UPLOAD → REPO_SELECT → FOLDER_SELECT',
      'SELECT_REPO → PUSH → VERIFY',
      'CONNECT → AUTH → UPLOAD'
    ],
    correct: 1,
    explanation: 'ה-GitHub Upload Flow עובר: FILE_UPLOAD → REPO_SELECT → FOLDER_SELECT'
  },
  {
    id: 'handler_4',
    category: 'handlers',
    type: 'boolean',
    question: 'תפריט הגיבוי (Backup Menu) משתמש ב-ConversationHandler עם states.',
    correct: false,
    explanation: 'תפריט הגיבוי (Backup Menu) פועל רק עם CallbackQuery בלי states'
  },

  // ===== תיעוד ו-Conventions =====

  {
    id: 'docs_1',
    category: 'docs',
    type: 'multiple',
    question: 'מה הדגל שגורם לבניית Sphinx להיכשל על אזהרות?',
    options: ['-E', '--strict', '-W', '--fail-on-warning'],
    correct: 2,
    explanation: 'הדגל -W (בשילוב --keep-going) גורם ל-Sphinx לדווח על אזהרות כשגיאות'
  },
  {
    id: 'docs_2',
    category: 'docs',
    type: 'multiple',
    question: 'איזו דירקטיבה מונעת כפילויות באינדקס של Sphinx?',
    options: [':no-duplicate:', ':noindex:', ':skip-index:', ':unique:'],
    correct: 1,
    explanation: ':noindex: משמש בעמודי סקירה חופפים כמו api, database, handlers, services, configuration'
  },
  {
    id: 'docs_3',
    category: 'docs',
    type: 'multiple',
    question: 'אילו Conventional Commit types מוכרים בפרויקט?',
    options: [
      'add, remove, change, update',
      'feat, fix, chore, docs, refactor, test, build, perf',
      'new, fix, update, delete',
      'feature, bugfix, hotfix, release'
    ],
    correct: 1,
    explanation: 'הסוגים המוכרים: feat, fix, chore, docs, refactor, test, build, perf'
  },
  {
    id: 'docs_4',
    category: 'docs',
    type: 'boolean',
    question: 'מותר להריץ Prettier על קבצי Jinja templates.',
    correct: false,
    explanation: 'אסור להריץ Prettier על קבצי Jinja כי הוא שובר בלוקים של {% ... %} ו-{{ ... }}. תיקיית webapp/templates/ צריכה להיות ב-.prettierignore'
  },
  {
    id: 'docs_5',
    category: 'docs',
    type: 'multiple',
    question: 'אילו Pre-commit hooks כלולים בפרויקט?',
    options: [
      'ESLint, Prettier, TypeScript',
      'Black, isort, Flake8, MyPy, Bandit',
      'Pylint, autopep8, pyflakes',
      'Ruff, Black, MyPy'
    ],
    correct: 1,
    explanation: 'ה-pre-commit hooks כוללים: Black (formatting), isort (imports), Flake8 (linting), MyPy (types), Bandit (security)'
  },

  // ===== שאלות נוספות מעורבות =====

  {
    id: 'misc_1',
    category: 'configuration',
    type: 'multiple',
    question: 'מהי גרסת Python המינימלית הנדרשת?',
    options: ['3.7+', '3.8+', '3.9+', '3.10+'],
    correct: 2,
    explanation: 'דרישת המערכת המינימלית היא Python 3.9+'
  },
  {
    id: 'misc_2',
    category: 'integrations',
    type: 'multiple',
    question: 'מהו מגבלת גודל הקובץ בטלגרם?',
    options: ['10MB', '20MB', '50MB', '100MB'],
    correct: 2,
    explanation: 'מגבלת גודל הקובץ בטלגרם היא 50MB. מעבר לכך מוצע לינק ישיר כ-fallback'
  },
  {
    id: 'misc_3',
    category: 'observability',
    type: 'multiple',
    question: 'מהו ה-SLO לזמן תגובת חיפוש (P95)?',
    options: ['≤500ms', '≤1s', '≤1.5s', '≤3s'],
    correct: 2,
    explanation: 'ה-SLO לדוגמה קובע P95 search ≤1.5s, עם 99.9% uptime ושיעור שגיאות ≤1%'
  },
  {
    id: 'misc_4',
    category: 'alerts',
    type: 'multiple',
    question: 'מהם שני מצבי ההתראות של Sentry?',
    options: [
      'Push ו-Pull',
      'Polling ו-Webhook',
      'Active ו-Passive',
      'Sync ו-Async'
    ],
    correct: 1,
    explanation: 'Sentry תומך בשני מצבים: Polling (הבוט שואל מדי זמן) ו-Webhook (שירות ווב מקבל POST)'
  },
  {
    id: 'misc_5',
    category: 'handlers',
    type: 'multiple',
    question: 'באיזה פילטר משתמשים לקבלת הודעות טקסט (לא פקודות)?',
    options: [
      'filters.TEXT',
      'filters.ALL',
      'filters.TEXT & ~filters.COMMAND',
      'filters.MESSAGE'
    ],
    correct: 2,
    explanation: 'הפילטר filters.TEXT & ~filters.COMMAND מקבל הודעות טקסט שאינן פקודות (/)'
  }
];
