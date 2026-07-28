# דיאגרמות קשרים בין קבצי ה-Observability

## דיאגרמה 1: סקירה כללית - זרימת נתונים ותלויות עיקריות

```mermaid
flowchart TB
    subgraph Config["📁 קבצי קונפיגורציה"]
        alerts_yml["config/alerts.yml<br/>הגדרות חלון וקולדאון"]
        error_sig_yml["config/error_signatures.yml<br/>חתימות שגיאות"]
        runbooks_yml["config/observability_runbooks.yml<br/>Playbooks & Quick Fix"]
    end

    subgraph Monitoring["📊 שכבת ניטור"]
        alerts_storage["monitoring/alerts_storage.py<br/>אחסון MongoDB"]
        error_signatures["monitoring/error_signatures.py<br/>סיווג שגיאות"]
        metrics_storage["monitoring/metrics_storage.py<br/>מטריקות בקשות"]
        log_analyzer["monitoring/log_analyzer.py<br/>אגרגטור לוגים"]
    end

    subgraph Alerting["🚨 שכבת התראות"]
        internal_alerts["internal_alerts.py<br/>התראות פנימיות"]
        alert_manager["alert_manager.py<br/>ספים אדפטיביים"]
        alert_forwarder["alert_forwarder.py<br/>Slack/Telegram"]
    end

    subgraph Observability["👁️ שכבת Observability"]
        observability["observability.py<br/>לוגים + Sentry"]
        obs_instrumentation["observability_instrumentation.py<br/>Tracing ידני"]
        obs_otel["observability_otel.py<br/>OpenTelemetry"]
    end

    subgraph Core["⚙️ ליבה"]
        config_py["config.py<br/>BotConfig"]
        metrics_py["metrics.py<br/>Prometheus + EWMA"]
        rules_api["webapp/rules_api.py<br/>Visual Rules API"]
    end

    %% קונפיג → מודולים
    error_sig_yml -->|"טעינת patterns"| error_signatures
    alerts_yml -->|"הגדרות grouping"| log_analyzer
    runbooks_yml -->|"quick fix rules"| alert_forwarder

    %% שכבת ניטור
    error_signatures -->|"סיווג"| log_analyzer
    log_analyzer -->|"התראות מקובצות"| internal_alerts
    metrics_storage -.->|"dual-write"| metrics_py

    %% שכבת התראות
    internal_alerts -->|"critical"| alert_manager
    internal_alerts -->|"forward"| alert_forwarder
    alert_manager -->|"dispatch"| alert_forwarder
    alert_manager -->|"record"| alerts_storage

    %% Observability
    observability -->|"emit_event"| internal_alerts
    observability -->|"signatures"| error_signatures
    metrics_py -->|"note_request"| alert_manager
    metrics_py -->|"anomaly"| internal_alerts

    %% Core
    config_py -.->|"SENTRY_DSN"| observability
    config_py -.->|"DB settings"| alerts_storage
```

---

## דיאגרמה 2: זרימת בקשה (Request Flow) ומדידת ביצועים

```mermaid
flowchart LR
    subgraph Request["📥 בקשה נכנסת"]
        http_req["HTTP Request"]
    end

    subgraph Metrics["📈 מדידה"]
        record_outcome["metrics.py<br/>record_request_outcome()"]
        ewma["EWMA latency"]
        prom["Prometheus counters"]
    end

    subgraph Storage["💾 אחסון"]
        metrics_storage["monitoring/metrics_storage.py<br/>enqueue_request_metric()"]
        mongo_metrics[("MongoDB<br/>service_metrics")]
    end

    subgraph Alerting["🚨 התראות"]
        alert_manager["alert_manager.py<br/>note_request()<br/>check_and_emit_alerts()"]
        thresholds["Adaptive Thresholds<br/>mean + 3σ"]
    end

    subgraph Emit["📤 פליטה"]
        internal_alerts["internal_alerts.py"]
        telegram["Telegram"]
        grafana["Grafana Annotations"]
    end

    http_req --> record_outcome
    record_outcome --> ewma
    record_outcome --> prom
    record_outcome -->|"dual-write"| metrics_storage
    metrics_storage --> mongo_metrics
    
    record_outcome --> alert_manager
    alert_manager --> thresholds
    thresholds -->|"breach"| internal_alerts
    internal_alerts --> telegram
    internal_alerts --> grafana
```

---

## דיאגרמה 3: מערכת סיווג שגיאות (Error Classification)

```mermaid
flowchart TB
    subgraph Config["📁 קונפיגורציה"]
        error_yml["config/error_signatures.yml"]
    end

    subgraph Signatures["🔍 סיווג"]
        error_sig_class["monitoring/error_signatures.py<br/>ErrorSignatures class"]
        sig_rule["SignatureRule<br/>id, category, pattern, severity, policy"]
        sig_match["SignatureMatch<br/>תוצאת סיווג"]
    end

    subgraph Consumers["📋 צרכנים"]
        observability["observability.py<br/>classify_error()"]
        log_analyzer["monitoring/log_analyzer.py<br/>LogEventAggregator"]
        alerts_storage["monitoring/alerts_storage.py<br/>compute_error_signature()"]
    end

    subgraph Output["📤 תוצרים"]
        sentry_tags["Sentry Tags<br/>error_category, error_signature"]
        alert_meta["Alert Metadata<br/>category, signature, policy"]
        fingerprint["Fingerprint<br/>de-duplication"]
    end

    error_yml -->|"load"| error_sig_class
    error_sig_class --> sig_rule
    error_sig_class -->|"match(line)"| sig_match

    sig_match --> observability
    sig_match --> log_analyzer
    alerts_storage -->|"hash-based"| fingerprint

    observability --> sentry_tags
    log_analyzer --> alert_meta
    log_analyzer --> fingerprint
```

---

## דיאגרמה 4: זרימת התראות (Alert Flow)

```mermaid
flowchart TB
    subgraph Sources["🎯 מקורות התראות"]
        metrics_anomaly["metrics.py<br/>_maybe_trigger_anomaly()"]
        alert_mgr_breach["alert_manager.py<br/>check_and_emit_alerts()"]
        log_agg["monitoring/log_analyzer.py<br/>LogEventAggregator"]
        external["Sentry Webhook<br/>External Sources"]
    end

    subgraph InternalAlerts["📨 internal_alerts.py"]
        emit_internal["emit_internal_alert()"]
        buffer["In-memory Buffer<br/>deque(maxlen=200)"]
        rules_eval["Rules Evaluation<br/>services/rules_evaluator.py"]
    end

    subgraph Routing["🔀 ניתוב"]
        severity_check{"severity?"}
        critical_path["alert_manager.py<br/>forward_critical_alert()"]
        normal_path["alert_forwarder.py<br/>forward_alerts()"]
    end

    subgraph Sinks["📤 סינקים"]
        telegram["Telegram<br/>ALERT_TELEGRAM_*"]
        slack["Slack<br/>SLACK_WEBHOOK_URL"]
        grafana["Grafana Annotations<br/>GRAFANA_URL"]
        mongo_alerts[("MongoDB<br/>alerts_log")]
    end

    subgraph Silences["🔇 השתקות"]
        silence_check["monitoring/silences.py<br/>is_silenced()"]
    end

    metrics_anomaly --> emit_internal
    alert_mgr_breach --> emit_internal
    log_agg --> emit_internal
    external --> emit_internal

    emit_internal --> buffer
    emit_internal --> rules_eval
    rules_eval -->|"silenced?"| silence_check
    
    emit_internal --> severity_check
    severity_check -->|"critical"| critical_path
    severity_check -->|"other"| normal_path

    critical_path --> silence_check
    silence_check -->|"not silenced"| telegram
    silence_check -->|"not silenced"| grafana
    critical_path --> mongo_alerts

    normal_path --> silence_check
    normal_path --> slack
    normal_path --> telegram
    normal_path --> mongo_alerts
```

---

## דיאגרמה 5: אחסון התראות ב-MongoDB

```mermaid
flowchart LR
    subgraph Input["📥 קלט"]
        record_alert["record_alert()<br/>alert_id, name, severity, summary"]
        details["details dict<br/>endpoint, alert_type, duration"]
    end

    subgraph Processing["⚙️ עיבוד"]
        sanitize["_sanitize_details()<br/>redact sensitive"]
        enrich["enrich_alert_with_signature()<br/>error_signature_hash, is_new_error"]
        build_key["_build_key()<br/>de-duplication key"]
    end

    subgraph Storage["💾 אחסון"]
        alerts_log[("MongoDB: alerts_log<br/>TTL: 30 days")]
        alert_catalog[("MongoDB: alert_types_catalog<br/>Registry")]
        error_sig_coll[("MongoDB: error_signatures<br/>Fingerprints")]
    end

    subgraph Query["🔍 שאילתות"]
        fetch_alerts["fetch_alerts()"]
        aggregate_summary["aggregate_alert_summary()"]
        aggregate_timeseries["aggregate_alert_timeseries()"]
        fetch_by_type["fetch_alerts_by_type()"]
    end

    Input --> sanitize
    sanitize --> enrich
    enrich --> build_key
    build_key -->|"upsert"| alerts_log
    build_key -->|"catalog"| alert_catalog
    enrich -->|"signature check"| error_sig_coll

    alerts_log --> fetch_alerts
    alerts_log --> aggregate_summary
    alerts_log --> aggregate_timeseries
    alert_catalog --> fetch_by_type
```

---

## דיאגרמה 6: אגרגטור לוגים (Log Analyzer)

```mermaid
flowchart TB
    subgraph Config["📁 קונפיגורציה"]
        alerts_yml["config/alerts.yml<br/>window, min_count, cooldown"]
        error_yml["config/error_signatures.yml<br/>patterns, categories"]
    end

    subgraph Input["📥 קלט"]
        log_line["Log Line<br/>warning/error/critical"]
        structlog["structlog processor<br/>_mirror_to_log_aggregator()"]
    end

    subgraph Aggregator["🔄 LogEventAggregator"]
        noise_filter["is_noise()?<br/>allowlist check"]
        classify["signatures.match()<br/>category, signature"]
        fingerprint["_fingerprint()<br/>canonicalize + hash"]
        group["_Group<br/>category, count, samples"]
    end

    subgraph Emit["📤 פליטה"]
        emit_check{"count >= min_count<br/>OR immediate?"}
        emit_alert["internal_alerts.py<br/>emit_internal_alert()"]
        cooldown["Cooldown Check"]
    end

    Config --> Aggregator
    structlog --> log_line
    log_line --> noise_filter
    noise_filter -->|"not noise"| classify
    classify --> fingerprint
    fingerprint --> group
    
    group --> emit_check
    emit_check -->|"yes"| cooldown
    cooldown -->|"passed"| emit_alert
```

---

## דיאגרמה 7: מערכת Observability מלאה

```mermaid
flowchart TB
    subgraph Logging["📝 לוגים"]
        structlog_cfg["setup_structlog_logging()"]
        emit_event["emit_event()"]
        redact["_redact_sensitive()"]
        otel_ids["_add_otel_ids()<br/>trace_id, span_id"]
    end

    subgraph Tracing["🔍 Tracing"]
        otel_setup["observability_otel.py<br/>setup_telemetry()"]
        traced["@traced decorator<br/>observability_instrumentation.py"]
        span["start_span()"]
    end

    subgraph Correlation["🔗 Correlation"]
        request_id["generate_request_id()"]
        bind_ctx["bind_request_id()<br/>bind_command()<br/>bind_user_context()"]
        headers["prepare_outgoing_headers()"]
    end

    subgraph Integration["🔌 אינטגרציות"]
        sentry["Sentry<br/>init_sentry()"]
        prometheus["Prometheus<br/>metrics.py"]
        mongo_alerts["MongoDB<br/>alerts_storage.py"]
    end

    structlog_cfg --> emit_event
    emit_event --> redact
    emit_event --> otel_ids
    
    otel_setup --> traced
    otel_setup --> span
    
    bind_ctx --> request_id
    bind_ctx --> headers
    otel_ids --> headers

    emit_event -->|"error/critical"| sentry
    emit_event -->|"classification"| mongo_alerts
    traced --> prometheus
```

---

## דיאגרמה 8: תלויות בין מודולים (Module Dependencies)

```mermaid
graph TB
    subgraph Level1["שכבה 1: קונפיגורציה"]
        config["config.py"]
        alerts_yml["alerts.yml"]
        error_sig_yml["error_signatures.yml"]
        runbooks_yml["runbooks.yml"]
    end

    subgraph Level2["שכבה 2: ליבת Observability"]
        observability["observability.py"]
        obs_otel["observability_otel.py"]
        obs_instr["observability_instrumentation.py"]
    end

    subgraph Level3["שכבה 3: מדידה ואחסון"]
        metrics["metrics.py"]
        error_signatures["error_signatures.py"]
        alerts_storage["alerts_storage.py"]
        metrics_storage["metrics_storage.py"]
    end

    subgraph Level4["שכבה 4: התראות"]
        alert_manager["alert_manager.py"]
        internal_alerts["internal_alerts.py"]
        log_analyzer["log_analyzer.py"]
    end

    subgraph Level5["שכבה 5: העברה"]
        alert_forwarder["alert_forwarder.py"]
        rules_api["rules_api.py"]
    end

    %% Level 1 dependencies
    config -.-> observability
    config -.-> alerts_storage
    
    %% Level 2 dependencies
    observability --> error_signatures
    observability --> log_analyzer
    
    %% Level 3 dependencies
    error_sig_yml --> error_signatures
    metrics --> metrics_storage
    metrics --> alert_manager
    metrics --> internal_alerts
    
    %% Level 4 dependencies
    alerts_yml --> log_analyzer
    error_signatures --> log_analyzer
    log_analyzer --> internal_alerts
    alert_manager --> alerts_storage
    alert_manager --> internal_alerts
    
    %% Level 5 dependencies
    internal_alerts --> alert_forwarder
    internal_alerts --> alert_manager
    alert_forwarder --> runbooks_yml
    alert_manager --> alert_forwarder
```

---

## טבלת סיכום: קבצים ותפקידיהם

| קובץ | תפקיד עיקרי | תלויות עיקריות | צורך ב- |
|------|-------------|----------------|---------|
| `config/alerts.yml` | הגדרות window/cooldown | - | `log_analyzer.py` |
| `config/error_signatures.yml` | חתימות שגיאות | - | `error_signatures.py` |
| `config/observability_runbooks.yml` | Playbooks & Quick Fix | - | `alert_forwarder.py`, dashboard |
| `monitoring/alerts_storage.py` | אחסון התראות MongoDB | pymongo | `alert_manager.py`, dashboard |
| `monitoring/error_signatures.py` | סיווג שגיאות | yaml/json | `observability.py`, `log_analyzer.py` |
| `monitoring/metrics_storage.py` | אחסון מטריקות | pymongo | `metrics.py` |
| `monitoring/log_analyzer.py` | אגרגציית לוגים | `error_signatures.py` | `observability.py` |
| `internal_alerts.py` | התראות פנימיות | - | `metrics.py`, `alert_manager.py` |
| `alert_forwarder.py` | Slack/Telegram | requests | `internal_alerts.py` |
| `alert_manager.py` | ספים אדפטיביים | - | `metrics.py` |
| `config.py` | קונפיגורציה ראשית | pydantic | רוב המודולים |
| `metrics.py` | Prometheus + EWMA | prometheus_client | webapp, bot |
| `observability.py` | לוגים + Sentry | structlog, sentry_sdk | כל המודולים |
| `observability_instrumentation.py` | Tracing ידני | opentelemetry | handlers |
| `observability_otel.py` | OpenTelemetry setup | opentelemetry | webapp |
| `webapp/rules_api.py` | Visual Rules API | Flask | webapp |
