# סכמת לוגים ואירועים (Observability)

מסמך זה מתאר את הסכמה המומלצת והאירועים הקנוניים שנעשה בהם שימוש במערכת.

## שדות חובה בכל אירוע
- schema_version: "1.0"
- event: שם אירוע בפורמט snake_case (לדוגמה: file_saved)
- severity: info | warn | error
- timestamp: ISO8601 (מוסף אוטומטית ע"י structlog)
- request_id: מזהה בקשה קצר (ContextVar)
- trace_id / span_id: מוזרק אוטומטית כאשר OpenTelemetry פעיל

## שדות מומלצים
- user_ref / user_id
- resource {type, id}
- attributes — שדות לפי אירוע
- error_code — לשגיאות בלבד, קוד יציב
- msg_he — טקסט תיאורי בעברית

## אירועים מרכזיים
- file_saved, file_read_success, file_read_unreadable
- github_upload_* (saved/direct_success/error)
- github_zipball_fetch_error, github_zip_create_error, github_zip_persist_error
- github_inline_download_error, github_multi_zip_error
- github_safe_delete_error, github_delete_file_error
- github_share_selected_links_error, github_share_single_link_error
- repo_analysis_start/repo_analysis_done/repo_analysis_error
- metrics_view_error, alerts_parse_error, alert_received
- db_* errors (לפי מקור)
- business_metric (metric=...)
- performance (operation=..., duration_ms=...)

## דגימה (Sampling)
- LOG_INFO_SAMPLE_RATE שולט בדגימת לוגי info
- Allowlist: business_metric, performance, github_sync

## פרטיות
- טשטוש שדות רגישים: token/password/secret/authorization/cookie
- אין לוג לתוכן קוד/שאילתות גולמיות — רק מטא-נתונים

