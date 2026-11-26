# Architecture, Workflow and ER Diagrams

Diagrams use Mermaid. They render in VS Code (extension "Markdown Preview Mermaid Support"), GitHub, or https://mermaid.live.

## 1. System architecture

```mermaid
flowchart LR
  subgraph Browser
    UI[Bootstrap 5 pages] --- JS[main.js + Socket.IO client]
  end
  subgraph Server["Flask server (local PC)"]
    R[Routes + RBAC + CSRF]
    SIO[Flask-SocketIO rooms: user_id / admins]
    COORD{{Agent Coordinator}}
    IA[Intake Agent]
    MA[Matching Agent]
    VA[Verification Agent]
    NA[Notification Agent]
    IMG[image_matching.py - OpenCV]
    ML[scikit-learn TF-IDF + cosine]
    DB[(SQLite)]
    FS[[uploads/ folder]]
  end
  UI -->|HTTP forms| R
  JS <-->|WebSocket / polling| SIO
  R --> COORD
  COORD --> IA & MA & VA & NA
  MA --> ML & IMG
  IMG --> FS
  R --> DB
  IA & MA & VA & NA --> DB
  NA --> SIO
```

## 2. Agent workflow: new report

```mermaid
sequenceDiagram
  participant U as User
  participant F as Flask route
  participant C as Coordinator
  participant I as Intake Agent
  participant M as Matching Agent
  participant N as Notification Agent
  participant B as Browsers (Socket.IO)
  U->>F: submit lost/found form + photo
  F->>F: validate + save image (secure upload)
  F->>C: process_new_report(kind, user, form, image)
  C->>I: raw form
  I-->>C: validated structured data (or errors)
  C->>C: save report in SQLite
  C->>M: find_matches(kind, item_id)
  M->>M: TF-IDF/cosine + metadata + OpenCV image score
  M-->>C: ranked matches (stored in matches table)
  C->>N: notify_matches(matches)
  N->>B: new_notification to BOTH users' rooms
  C->>B: stats_update + new_report to everyone (aggregate only)
```

## 3. Agent workflow: claim and return

```mermaid
sequenceDiagram
  participant O as Owner
  participant C as Coordinator
  participant V as Verification Agent
  participant N as Notification Agent
  participant A as Admin
  O->>C: submit_claim(match, answers)
  C->>V: check ownership of lost item, build Q/A, advisory score
  V-->>C: claim saved as PENDING, match = claim_pending
  C->>N: tell finder, claimant, admins
  A->>C: approve / reject (only admins)
  C->>V: apply_decision
  V-->>C: approved => items + match = returned, other matches closed
  C->>N: tell both users, contacts released, dashboard stats pushed
```

## 4. Database ER diagram

```mermaid
erDiagram
  users ||--o| admin : "has role"
  users ||--o{ lost_items : reports
  users ||--o{ found_items : reports
  users ||--o{ notifications : receives
  users ||--o{ claims : submits
  lost_items ||--o{ matches : "matched in"
  found_items ||--o{ matches : "matched in"
  matches ||--o{ claims : "claimed through"
  matches ||--o{ notifications : "triggers"
  users { int id PK
    text name
    text email UK
    text password_hash
    text phone
    text role }
  admin { int id PK
    int user_id FK }
  lost_items { int id PK
    int user_id FK
    text item_name
    text category
    text description
    text lost_date
    text location
    text color
    text brand
    text image_path
    text contact
    text search_text
    text status }
  found_items { int id PK
    int user_id FK
    text item_name
    text category
    text description
    text found_date
    text location
    text color
    text brand
    text image_path
    text contact
    text secret_details
    text search_text
    text status }
  matches { int id PK
    int lost_id FK
    int found_id FK
    real text_score
    real meta_score
    real image_score
    real combined_score
    text status }
  claims { int id PK
    int match_id FK
    int claimant_id FK
    text answers
    real verification_score
    text status
    text admin_note }
  notifications { int id PK
    int user_id FK
    int match_id FK
    text message
    int is_read }
  agent_logs { int id PK
    text agent
    text action
    text detail }
```

## 5. How agents communicate

Agents are Python modules with plain functions. They never import or call each other. The coordinator is the only
component that knows the order of work:

| Step | Coordinator calls | Data in | Data out |
|---|---|---|---|
| 1 | `intake_agent.process` | raw form dict | `{ok, errors, data}` |
| 2 | `database_models.insert_item` | `data` | `item_id` |
| 3 | `matching_agent.find_matches` | kind, `item_id` | list of stored matches with scores |
| 4 | `notification_agent.notify_matches` | matches | notification rows + live events |
| 5 | `notification_agent.broadcast_*` | item / stats | live dashboard update |
| claim | `verification_agent.submit_claim` | match id, answers | pending claim + advisory score |
| decision | `verification_agent.apply_decision` | claim id, admin choice | items returned or match reopened |

Each step writes a row to `agent_logs`, so the hand-overs can be demonstrated live in **Admin > Overview**.
One deliberate change from the original list order: the Intake Agent validates **before** the report is saved,
so invalid data never reaches the database.
