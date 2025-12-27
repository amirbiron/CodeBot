## 🎨 דיאגרמות ארכיטקטורה

### 1. זרימת פקודה בסיסית - Command Flow
```mermaid
graph LR
    A[User Command] --> B{Permission Check}
    B -->|Authorized| C[Validate Args]
    B -->|Denied| D[Error Response]
    C --> E[Metrics Collection]
    E --> F[Execute Command]
    F --> G[Format Response]
    G --> H[Send to User]
    F --> I[Log Metrics]
    I --> J{Alert Check}
    J -->|Threshold Exceeded| K[Trigger Alert]
    J -->|Normal| L[Store Metrics]
```

### 2. ארכיטקטורת המערכת הכללית - System Architecture
```mermaid
graph TB
    subgraph "Telegram Interface"
        U[User] --> TB[Telegram Bot]
    end
    
    subgraph "Command Processing Layer"
        TB --> CR[Command Router]
        CR --> PH[Permission Handler]
        PH --> CH[Command Handlers]
    end
    
    subgraph "Core Services"
        CH --> MC[Metrics Collector]
        CH --> GH[GitHub API Handler]
        CH --> CD[Code Analyzer]
        MC --> MS[Metrics Storage]
        MC --> MA[Metrics Analyzer]
    end
    
    subgraph "Storage Layer"
        MS --> PG[(PostgreSQL)]
        MS --> RD[(Redis Cache)]
        CD --> FS[File System]
    end
    
    subgraph "Monitoring & Alerts"
        MA --> AM[Alert Manager]
        AM --> NS[Notification Service]
        MA --> PE[Prometheus Exporter]
        PE --> GD[Grafana Dashboards]
    end
    
    NS -->|Alert| TB
```

### 3. זרימת איסוף מטריקות - Metrics Collection Flow
```mermaid
sequenceDiagram
    participant App as Application
    participant RC as Request Context
    participant MC as Metrics Collector
    participant BQ as Batch Queue
    participant BW as Batch Writer
    participant DB as PostgreSQL
    participant PM as Prometheus

    App->>RC: Start Request
    RC->>RC: Generate Request ID
    RC->>MC: Track Request Start
    MC->>PM: Increment Counter
    
    App->>App: Execute Operation
    
    alt Success
        App->>MC: Track Success
        MC->>PM: Update Metrics
    else Error
        App->>MC: Track Error
        MC->>PM: Increment Error Counter
    end
    
    MC->>BQ: Queue Metric
    BQ->>BW: Batch (100 items or 5s)
    BW->>DB: Bulk Insert
    DB-->>BW: Acknowledge
```

### 4. מערכת התראות חכמות - Smart Alert System
```mermaid
graph TD
    subgraph "Detection Layer"
        M1[Error Rate Monitor]
        M2[Latency Monitor]
        M3[Rate Limit Monitor]
        M4[System Health Monitor]
    end
    
    subgraph "Analysis Layer"
        M1 --> AE[Alert Engine]
        M2 --> AE
        M3 --> AE
        M4 --> AE
        AE --> TA{Threshold Analysis}
    end
    
    subgraph "Decision Layer"
        TA -->|Critical| C[Create Alert]
        TA -->|Warning| W[Create Warning]
        TA -->|Normal| N[No Action]
        C --> ES[Enrich with Suggestions]
        W --> ES
        ES --> GL[Add Grafana Links]
        GL --> RP[Add Runbook]
    end
    
    subgraph "Delivery Layer"
        RP --> TN[Telegram Notification]
        RP --> DB[(Store Alert)]
        RP --> WH[Webhook]
        TN --> U[User]
    end
```

### 5. זיהוי כפילויות קוד - Duplicate Detection Pipeline
```mermaid
graph LR
    subgraph "Input"
        CF[Code Files]
    end
    
    subgraph "Phase 1: Exact Matching"
        CF --> NM[Normalize Code]
        NM --> HG[Generate Hash]
        HG --> EM[Exact Match Map]
    end
    
    subgraph "Phase 2: Fuzzy Matching"
        CF --> TK[Tokenize]
        TK --> MH[MinHash]
        MH --> FM[Find Similar >85%]
    end
    
    subgraph "Phase 3: AST Analysis"
        CF --> AP[AST Parser]
        AP --> ST[Structure Tree]
        ST --> SC[Structure Compare]
    end
    
    subgraph "Results"
        EM --> MR[Merge Results]
        FM --> MR
        SC --> MR
        MR --> RS[Refactor Suggestions]
        RS --> RE[Report]
    end
```

### 6. Triage Investigation Flow
```mermaid
graph TD
    subgraph "Input"
        RID[Request ID]
    end
    
    subgraph "Data Collection"
        RID --> DG{Data Gathering}
        DG --> M[Metrics]
        DG --> L[Logs]
        DG --> T[Traces]
        DG --> RR[Related Requests]
    end
    
    subgraph "Analysis"
        M --> TL[Build Timeline]
        L --> TL
        T --> TL
        RR --> TL
        TL --> RC[Root Cause Analysis]
        RC --> SG[Generate Suggestions]
    end
    
    subgraph "Output"
        SG --> FR[Format Report]
        FR --> HTML[HTML Report]
        FR --> MSG[Telegram Message]
        HTML --> U[User]
        MSG --> U
    end
```

### 7. Database Schema Relationships
```mermaid
erDiagram
    METRICS ||--o{ ALERTS : triggers
    METRICS {
        string request_id PK
        datetime timestamp
        string metric_type
        string operation
        string status
        float value
        json metadata
        string user_id FK
        string error_code
    }
    
    ALERTS ||--o{ ALERT_ACTIONS : has
    ALERTS {
        string alert_id PK
        datetime timestamp
        string severity
        string alert_type
        string title
        text description
        array affected_services
        json metrics_snapshot
        datetime resolved_at
    }
    
    ALERT_ACTIONS {
        int id PK
        string alert_id FK
        string action_type
        text suggestion
        string runbook_url
    }
    
    CODE_DUPLICATES ||--|| FILES : references
    CODE_DUPLICATES {
        string duplicate_id PK
        datetime detection_time
        string file1
        int file1_start_line
        int file1_end_line
        string file2
        int file2_start_line
        int file2_end_line
        float similarity_score
        string detection_method
    }
    
    METRICS_AGGREGATES ||--|| METRICS : summarizes
    METRICS_AGGREGATES {
        int id PK
        datetime period_start
        datetime period_end
        string operation
        int total_requests
        int success_count
        int error_count
        float avg_latency_ms
        float p95_latency_ms
    }
```

### 8. Command Handler Architecture
```mermaid
graph TB
    subgraph "Bot Interface"
        U[User Input] --> DP[Dispatcher]
    end
    
    subgraph "Command Handlers"
        DP --> SH[/status Handler]
        DP --> EH[/errors Handler]
        DP --> LH[/latency Handler]
        DP --> RH[/rate_limit Handler]
        DP --> TH[/triage Handler]
        DP --> DH[/dashboard Handler]
    end
    
    subgraph "Services Layer"
        SH --> HS[Health Service]
        EH --> MS[Metrics Service]
        LH --> MS
        RH --> GS[GitHub Service]
        TH --> IS[Investigation Service]
        DH --> AS[Aggregation Service]
    end
    
    subgraph "Data Layer"
        HS --> DB[(Database)]
        MS --> DB
        MS --> RC[(Redis)]
        GS --> GA[GitHub API]
        IS --> DB
        IS --> ES[Elastic/Logs]
        AS --> DB
    end
```

### 9. Performance Optimization Flow
```mermaid
graph LR
    subgraph "Incoming Requests"
        R1[Request 1]
        R2[Request 2]
        R3[Request 3]
    end
    
    subgraph "Caching Layer"
        R1 --> CK{Cache Check}
        R2 --> CK
        R3 --> CK
        CK -->|Hit| CR[Return Cached]
        CK -->|Miss| QL[Query Load]
    end
    
    subgraph "Batching"
        QL --> BQ[Batch Queue]
        BQ --> BT{Batch Trigger}
        BT -->|Size=100| BP[Process Batch]
        BT -->|Time=5s| BP
    end
    
    subgraph "Processing"
        BP --> PP[Parallel Processing]
        PP --> DB[(Database)]
        DB --> UC[Update Cache]
        UC --> RR[Return Results]
    end
```

### 10. Rate Limiting and Backoff Strategy
```mermaid
stateDiagram-v2
    [*] --> Normal: System Start
    
    Normal --> Warning: 80% Quota Used
    Warning --> Critical: 90% Quota Used
    Critical --> Backoff: 95% Quota Used
    
    Warning --> Normal: Quota Reset
    Critical --> Warning: Quota < 90%
    Backoff --> Critical: Manual Override
    Backoff --> Normal: Quota Reset
    
    state Normal {
        [*] --> FullSpeed
        FullSpeed: All Operations Normal
    }
    
    state Warning {
        [*] --> Reduced
        Reduced: Non-critical Ops Delayed
    }
    
    state Critical {
        [*] --> Minimal
        Minimal: Only Critical Ops
    }
    
    state Backoff {
        [*] --> Paused
        Paused: All GitHub Ops Suspended
    }
```

### 11. Real-time Dashboard Data Flow
```mermaid
graph TD
    subgraph "Data Sources"
        M[Metrics DB]
        R[Redis Cache]
        G[GitHub API]
        S[System Stats]
    end
    
    subgraph "Aggregation"
        M --> AG[Aggregator]
        R --> AG
        G --> AG
        S --> AG
        AG --> DP[Data Processor]
    end
    
    subgraph "Formatting"
        DP --> SF[Status Formatter]
        DP --> PF[Performance Formatter]
        DP --> EF[Error Formatter]
        DP --> KF[KPI Formatter]
    end
    
    subgraph "Visualization"
        SF --> DB[Dashboard Builder]
        PF --> DB
        EF --> DB
        KF --> DB
        DB --> PB[Progress Bars]
        DB --> EM[Emoji Status]
        DB --> TB[Tables]
        TB --> TM[Telegram Message]
    end
```

### 12. Error Handling and Recovery
```mermaid
graph TD
    E[Error Occurs] --> ET{Error Type}
    
    ET -->|Database| DBE[DB Error Handler]
    ET -->|API| APE[API Error Handler]
    ET -->|Timeout| TE[Timeout Handler]
    ET -->|Unknown| UE[Generic Handler]
    
    DBE --> RT1{Retry?}
    RT1 -->|Yes| RTC1[Retry with Backoff]
    RT1 -->|No| FO1[Failover to Cache]
    
    APE --> RT2{Rate Limited?}
    RT2 -->|Yes| BK[Activate Backoff]
    RT2 -->|No| RTC2[Retry Request]
    
    TE --> CX[Cancel Operation]
    CX --> NF[Notify User]
    
    UE --> LOG[Log Error]
    LOG --> ALT[Alert Admin]
    
    RTC1 --> SR{Success?}
    RTC2 --> SR
    FO1 --> SR
    BK --> SR
    
    SR -->|Yes| RES[Return Result]
    SR -->|No| ERR[Return Error]
```

### 13. CI/CD Pipeline for Monitoring Features
```mermaid
graph LR
    subgraph "Development"
        DC[Code Changes] --> PR[Pull Request]
    end
    
    subgraph "Testing"
        PR --> UT[Unit Tests]
        PR --> IT[Integration Tests]
        PR --> PT[Performance Tests]
        UT --> TG{Tests Pass?}
        IT --> TG
        PT --> TG
    end
    
    subgraph "Deployment"
        TG -->|Yes| STG[Deploy to Staging]
        TG -->|No| FIX[Fix Issues]
        STG --> ST[Staging Tests]
        ST --> MT[Monitor Metrics]
        MT --> PD{Metrics OK?}
    end
    
    subgraph "Production"
        PD -->|Yes| PRD[Deploy to Production]
        PD -->|No| RB[Rollback]
        PRD --> PM[Production Monitoring]
        PM --> AL[Alert Setup]
    end
```
