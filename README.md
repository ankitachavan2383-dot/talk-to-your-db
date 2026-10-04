# sql-chat-agent

**Ask any database a question in plain English. Get back validated SQL, the
result, and a natural-language explanation — safely.**

This is an agentic text-to-SQL system: it doesn't just translate a question
into a query once and hope for the best. It grounds itself in your real
schema, enforces hard safety guardrails before anything touches your
database, retries and self-corrects when a query fails, and connects to
databases you register yourself rather than being hardcoded to one dataset.

```
"How many male and female patients are recorded with depression?"
        ↓
   Schema Agent → SQL Generator → SQL Validator → SQL Executor
        ↓                                              ↓
   (self-corrects on failure) ←——————————————————— error?
        ↓
"187 male and 243 female patients are recorded with a depression diagnosis."
```

---

## Why this exists

Most "ask your database a question" demos are a single LLM call wrapped in a
try/except. That's fragile and unsafe the moment it meets a real schema or a
real user. This project treats each of those failure points as a first-class
concern:

| Problem | How it's handled |
|---|---|
| LLM doesn't know your schema | Schema introspection grounds every prompt in real table/column names |
| LLM output isn't reliably parseable | Forced structured output via function/tool calling |
| LLM-generated SQL could be destructive | Deterministic, code-level guardrails — not another LLM call |
| First SQL attempt sometimes fails | Bounded self-correction loop feeds the exact DB error back to the model |
| Running against one hardcoded DB isn't realistic | Users register their own databases; credentials are encrypted at rest |
| Running forever on one connection isn't safe | Read-only roles enforced, query timeouts, row caps, retry limits |

---

## Architecture

```
┌───────────────┐        ┌──────────────────────────────────────────────┐
│  Streamlit     │  HTTP  │                FastAPI Backend                │
│  Frontend      │───────▶│                                                │
└───────────────┘        │  ┌──────────────┐   ┌──────────────────────┐  │
                          │  │ Schema Agent  │──▶│ SQL Generator (LLM)   │  │
                          │  └──────────────┘   └───────────┬──────────┘  │
                          │                                  │             │
                          │                       ┌──────────▼──────────┐ │
                          │                       │   SQL Validator      │ │
                          │                       │   (guardrails)        │ │
                          │                       └──────────┬──────────┘ │
                          │                                  │             │
                          │   ┌──────────────┐    ┌──────────▼──────────┐ │
                          │   │ Self-Correct  │◀──▶│   SQL Executor       │ │
                          │   │ Loop (LLM)    │    │   (read-only conn)    │ │
                          │   └──────────────┘    └──────────┬──────────┘ │
                          │                                  │             │
                          │                       ┌──────────▼──────────┐ │
                          │                       │  Answer Generator     │ │
                          │                       │  (LLM, rows → text)   │ │
                          │                       └───────────────────────┘ │
                          └────────────────────────┬───────────────────────┘
                                                     │
                     ┌───────────────────────────────┼──────────────────────────┐
                     │                                │                           │
          ┌──────────▼─────────┐        ┌─────────────▼──────────┐   ┌──────────▼────────┐
          │ Metadata DB          │        │ Target DB(s)             │   │ LLM Provider        │
          │ (PostgreSQL)          │        │ (whatever the user        │   │ (Groq,               │
          │ — registered DB       │        │  connects — read-only     │   │  OpenAI-compatible)  │
          │   connections          │        │  role enforced)           │   │                      │
          │ — Fernet-encrypted     │        └───────────────────────────┘   └─────────────────────┘
          │   credentials           │
          └────────────────────────┘
```

### Key components

- **Metadata DB (PostgreSQL)** — stores which databases a user has registered
  to query, with connection credentials encrypted at rest (Fernet symmetric
  encryption, key supplied via `APP_SECRET_KEY`). This is separate from any
  database being *queried* — it's the app's own bookkeeping store.
- **Schema Agent** — introspects the target database's actual schema at query
  time so the LLM is grounded in reality instead of guessing table/column
  names.
- **SQL Generator** — calls the LLM (Groq, via an OpenAI-compatible API) with
  forced structured output (function/tool calling), so the response is
  always parseable JSON, never free-form prose.
- **SQL Validator** — deterministic, code-level guardrails: SELECT-only,
  single statement, no comment-based injection, enforced row limits. This is
  the actual security boundary, not the prompt.
- **SQL Executor** — runs the validated query against the target database
  over a connection using a **read-only role** (`REQUIRE_READONLY_ROLE`),
  with a hard timeout (`SQL_TIMEOUT_S`) and row cap (`SQL_MAX_ROWS`).
- **Self-Correction Loop** — on execution failure, the exact database error
  is fed back to the LLM for a bounded number of retries (`SQL_MAX_RETRIES`)
  before giving up and surfacing a clear error.
- **Answer Generator** — turns the result rows into a natural-language
  answer for a non-technical user.

---

## Tech stack

- **Backend**: FastAPI (Python)
- **LLM**: Groq (OpenAI-compatible API, function/tool calling for structured output)
- **Metadata DB**: PostgreSQL (via SQLAlchemy / psycopg)
- **Secrets**: Fernet symmetric encryption for stored DB credentials
- **Frontend**: Streamlit
- **Auth**: Bearer token on the API

---

## Setup

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/sql-chat-agent.git
cd sql-chat-agent
cp .env.example .env
```

Fill in `.env`:

```dotenv
GROQ_API_KEY=your-groq-key
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=openai/gpt-oss-120b

METADATA_DB_URL=postgresql+psycopg://app:app@localhost:5432/appmeta

# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
APP_SECRET_KEY=

API_TOKEN=

SQL_TIMEOUT_S=15
SQL_DEFAULT_LIMIT=1000
SQL_MAX_ROWS=10000
SQL_MAX_RETRIES=2
REQUIRE_READONLY_ROLE=true
SEND_SAMPLE_VALUES_TO_LLM=false
```

### 2. Start the metadata database

```bash
docker run --name appmeta -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app \
  -e POSTGRES_DB=appmeta -p 5432:5432 -d postgres:16
```

### 3. Install dependencies and run the backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 4. Run the frontend

```bash
cd frontend
pip install -r requirements.txt
streamlit run streamlit_app.py
```

### 5. Register a database and ask a question

Connect a target database through the UI (or API), then ask questions like:

- "How many records are there by category?"
- "What's the trend over the last 6 months?"
- "Show me the top 10 by value."

---

## Security notes

This app executes LLM-generated SQL against real databases. Treat it
accordingly:

- Always connect target databases using a **read-only** role at the database
  level — `REQUIRE_READONLY_ROLE` is an application-level check, not a
  substitute for actual database permissions.
- Keep `SEND_SAMPLE_VALUES_TO_LLM=false` unless you've confirmed the data
  going to your LLM provider is appropriate to share externally.
- Set a real `API_TOKEN` before deploying anywhere reachable from the public
  internet.
- Rotate `APP_SECRET_KEY` only with a migration plan — rotating it without
  re-encrypting stored credentials will make existing saved connections
  unreadable.

---

## Roadmap / possible extensions

- Row-level / column-level access control per user
- Query result caching for repeated questions
- Multi-agent planning for multi-step analytical questions
- CI pipeline running guardrail unit tests on every push
- Support for additional LLM providers behind the same structured-output interface

---

## License

MIT (or your choice — update this section before publishing).