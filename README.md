
# Dynamic Jury Network (DJN)

## Overview

Dynamic Jury Network (DJN) is a multi‑agent reasoning framework that improves decision quality by orchestrating multiple large language models (LLMs) as a structured **jury system**.

Instead of relying on a single model response, DJN gathers reasoning from multiple models, analyzes agreement between them, and synthesizes a final decision using a moderator model.

The system is implemented as a **Django web application** with an internal execution engine that handles orchestration, schema validation, logging, and statistical tracking of model performance.

DJN aims to provide:
- More reliable AI outputs
- Reduced hallucinations
- Transparent reasoning
- Consensus‑driven recommendations

---

# Core Idea

Typical AI systems depend on a **single model output**, which may suffer from:

- hallucinations
- reasoning errors
- overconfidence
- limited perspective

DJN addresses this by introducing a **jury‑based reasoning system**.

Instead of one answer, the system:

1. Selects multiple models dynamically
2. Assigns them reasoning roles
3. Collects structured responses
4. Measures agreement between them
5. Produces a final moderated recommendation

This design is inspired by **deliberative decision systems**, similar to expert panels or jury deliberation.

---

# System Architecture

DJN consists of three major layers.

User Interface (Django)
        |
        v
DJN Execution Engine
        |
        v
Model Pool + Database + Logs


### Components

| Component | Description |
|-----------|-------------|
| Web Layer | Handles user queries and renders results |
| DJN Engine | Executes the jury reasoning protocol |
| LLM Pool | Collection of candidate models available for juror selection |
| Database | Stores runs, rounds, juror responses, and statistics |
| Logging | Stores full execution traces for analysis |

---

# Dynamic Juror Selection

A key feature of DJN is **dynamic juror selection**.

Rather than using a fixed set of models, the system selects jurors based on:

##### 1. Query Category

The **query category** represents the **type of user question** (e.g., coding, career, planning, factual, opinion, general).
It helps the system **select appropriate juror models and reasoning strategies** for that specific problem type. 

---

##### 2. Historical Model Performance

This refers to **past performance statistics of each model**, such as accuracy, agreement with majority decisions, and user feedback.
These metrics help the system **select better-performing models as jurors in future runs**.

---

##### 3. Response Latency

**Response latency** is the **time taken by a model to generate a response**, usually measured in milliseconds.
It is used to evaluate **efficiency and responsiveness of models during deliberation rounds**. 

---

##### 4. Statistical Acceptance Rate

The **statistical acceptance rate** measures **how often a model’s responses are accepted or positively rated by users**.
It is calculated using user feedback and used to **rank models for future jury selection**. 

Models are stored in a **model pool** and selected at runtime using a scoring strategy.

This enables the system to adaptively choose the most suitable models for each task.

---

# Query Processing Pipeline

Each user query follows a structured execution pipeline.

## 1. Query Intake

The system records:

- original user query
- optional constraints
- session identifier

This information initializes a new DJN run.

---

## 2. Query Classification

A moderator model categorizes the query into one of several categories:

- coding
- career
- planning
- factual
- opinion
- general

If necessary, the system may generate clarifying questions.

---

## 3. Assumption Generation

If the query lacks important details, the system generates explicit assumptions and constructs a normalized query.

This ensures that jurors reason over a well‑defined problem statement.

---

## 4. Jury Selection

Jurors are dynamically selected from the model pool.

Each juror is assigned a specific reasoning role:

| Role | Purpose |
|-----|--------|
| PROPOSER | Suggests the main solution |
| CRITIC | Identifies weaknesses |
| REFINER | Improves and restructures ideas |
| RISK | Highlights risks and limitations |

This role structure encourages diverse reasoning perspectives.

---

# Multi‑Round Reasoning

DJN performs reasoning in multiple rounds.

The system currently supports **up to three rounds**, though most queries finish in two.

## Round 1

Each juror produces structured output containing:

- verdict label
- short summary (TLDR)
- reasoning points

Outputs are validated using strict schemas to ensure consistent structure.

Agreement metrics are then computed.

---

## Agreement Evaluation

The system measures consensus using:

- majority verdict
- agreement score
- TLDR similarity
- disagreement rate

If agreement exceeds a threshold, the process proceeds directly to final judgment.

Otherwise, another round begins.

---

## Round 2

In the second round, jurors receive a summary of:

- common ground
- disagreements
- open questions

Jurors refine their reasoning based on these insights.

This step simulates deliberation within a jury.

---

# Final Judgment

A moderator model analyzes all juror responses and generates the final recommendation.

The output includes:

- final recommendation
- reasoning summary
- confidence level
- major disagreements

Confidence levels are categorized as:

- HIGH
- MEDIUM
- LOW

---

# Database Design

The system stores structured execution data using Django models.

| Model | Purpose |
|------|--------|
| DJNRun | Represents a single user query session |
| DJNRound | Stores information about each reasoning round |
| JurorResponse | Stores responses from individual jurors |
| LLMPool | Database of available LLM models |
| ModelRollingStat | Tracks long‑term model performance |

This design allows the system to track model reliability over time.

---

# Performance Tracking

DJN maintains rolling statistics for each model.

Tracked metrics include:

- user acceptance rate
- majority win rate
- disagreement rate
- schema validity rate
- average latency

These statistics influence future juror selection.

---

# Logging System

Each run is logged as a JSON record.

Logs are stored in:

logs/djn_runs.jsonl

Each record contains:

- timestamp
- query
- juror outputs
- final decision
- execution metadata

These logs allow debugging and analysis of the reasoning process.

---

# Project Structure
```text
Dynamic-Jury-Network/
├── .env.example
├── .gitignore
├── credentials.json        # Create this from your Google Cloud Console
├── manage.py
├── requirements.txt
│
├── djn_db/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── db_writer.py
│   ├── models.py
│   ├── selector.py
│   ├── stats.py
│   ├── management/
│   │   ├── __init__.py
│   │   └── commands/
│   │       ├── __init__.py
│   │       └── seed_llmpool.py
│   └── migrations/
│       ├── __init__.py
│       └── 0001_initial.py
│
├── djn_engine/
│   ├── __init__.py
│   ├── json_enforce.py
│   ├── llms.py
│   ├── logger.py
│   ├── pool.py
│   ├── run.py
│   └── schemas.py
│
├── djn_site/
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── docs/
│   ├── architecture/
│   │   ├── activityDiagram.png
│   │   ├── sequenceDiagram.png
│   │   ├── sysArchitecture.png
│   │   └── usecaseDiagram.png
│   └── screenshots/
│       ├── About_Page_Dark_BG.png
│       ├── Final-Response-Google-Docs.png
│       ├── History_Page_Dark_BG.png
│       ├── Home_Page_Dark_BG.png
│       ├── Home_Page_Light_BG.png
│       └── Jury_Page_Dark_BG.png
│
├── logs/
│   └── djn_runs.jsonl
│
└── webapp/
    ├── __init__.py
    ├── admin.py
    ├── apps.py
    ├── urls.py
    ├── views.py
    ├── migrations/
    │   └── __init__.py
    ├── static/
    │   └── webapp/
    │       └── css/
    │           └── app.css
    ├── templates/
    │   └── webapp/
    │       ├── about.html
    │       ├── base.html
    │       ├── history.html
    │       ├── home.html
    │       └── jury_discussion.html
    └── templatetags/
        ├── __init__.py
        └── djn_extras.py
```
---

# Key Features

Dynamic Jury Network provides several advantages over single‑model systems.

### Multi‑Model Reasoning
Combines outputs from multiple LLMs.

### Dynamic Juror Selection
Chooses jurors based on performance statistics and query type.

### Structured Reasoning
Uses defined roles and multi‑round deliberation.

### Schema‑Validated Outputs
Ensures machine‑readable responses.

### Statistical Model Tracking
Learns which models perform best over time.

---

# Current Limitations

The current implementation is an MVP version.

Limitations include:

- limited number of reasoning rounds
- moderate execution latency due to multiple model calls
- basic juror scoring strategy
- no reinforcement learning optimization


---

# Conclusion

Dynamic Jury Network demonstrates how structured multi‑agent reasoning can improve AI decision quality.

By combining multiple models within a deliberative framework, DJN produces more robust and transparent recommendations compared to traditional single‑model systems.
