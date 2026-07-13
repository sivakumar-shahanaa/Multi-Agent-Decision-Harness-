# Company Brain – Decision Harness

A multi-agent AI decision orchestration system that enables multiple specialized LLM agents to independently evaluate a problem, detect disagreements, and generate a structured final verdict through an orchestrator. The system is fully instrumented with Weights & Biases Weave for observability and supports human-in-the-loop decision making through adjustable agent weights and contextual overrides.

Built during the **Multi-Agent Orchestration Build Day Hackathon (May 2026).**

---

## Overview

Decision Harness simulates an AI organization rather than a single assistant.

Given a question, five specialized agents independently analyze the problem from different perspectives. Their responses are passed to an orchestrator, which:

- Aggregates all agent outputs
- Detects areas of agreement and conflict
- Applies configurable weighted scoring
- Incorporates optional human feedback
- Produces a structured final decision with supporting reasoning

The entire execution pipeline is traced using **Weights & Biases Weave**, making every model invocation and orchestration step transparent and debuggable.

---

## Features

- Five independent specialist LLM agents
- Central orchestration agent for structured decision synthesis
- Configurable agent weighting system
- Human-in-the-loop override support
- Full Weave instrumentation and tracing
- Automated evaluation with custom scoring metrics
- FastAPI backend for serving orchestration requests
- React frontend for interactive decision making

---

## Architecture

```
                User Question
                      │
        ┌─────────────┼─────────────┐
        │             │             │
   Agent 1       Agent 2       Agent 3
        │             │             │
        └─────────────┼─────────────┘
              Agent 4     Agent 5
                     │
                     ▼
            Decision Orchestrator
                     │
       Weighted Aggregation + Override
                     │
                     ▼
            Structured Final Verdict
                     │
                     ▼
          Weave Trace & Evaluations
```

---

## Tech Stack

**Backend**
- Python 3.11+
- FastAPI
- OpenAI / Anthropic APIs

**Observability**
- Weights & Biases Weave

**Frontend**
- React

---

## Project Structure

```
.
├── main.py                 # FastAPI server
├── agents.py               # Specialist agent implementations
├── orchestrator.py         # Decision orchestration logic
├── evaluation.py           # Weave scorers and evaluation
├── demo_v2.jsx             # React frontend
├── requirements.txt
└── README.md
```

---

## Workflow

1. User submits a decision question.
2. Five specialist agents independently generate structured analyses.
3. Responses are collected by the orchestrator.
4. Agent outputs are weighted according to configurable importance.
5. Optional human override/context is incorporated.
6. The orchestrator produces a final verdict with reasoning.
7. Every execution is logged and evaluated using Weave.

---

## Evaluation

The project includes custom Weave evaluation metrics such as:

- **Confidence Score** – Measures normalized confidence from agent outputs.
- **Verdict Strength** – Scores final verdict quality based on decision strength.

These metrics allow different orchestration strategies and weight configurations to be compared directly in the Weave dashboard.

---

## Running the Project

### Install dependencies

```bash
pip install -r requirements.txt
```

### Start the FastAPI server

```bash
uvicorn main:app --reload
```

The backend will run locally at:

```
http://localhost:8000
```

---

## API

### POST `/run`

Example request:

```json
{
  "question": "Should this project win the Most Sophisticated Harness prize?",
  "weights": {
    "agent1": 1.0,
    "agent2": 0.8,
    "agent3": 1.2,
    "agent4": 1.0,
    "agent5": 0.9
  },
  "override": "Prioritize implementation quality over presentation."
}
```

Example response:

```json
{
  "agents": [...],
  "orchestrator": {
    "verdict": "STRONG",
    "score": 9.3,
    "reasoning": "...",
    "summary": "..."
  }
}
```

---

## Weave Instrumentation

All agent executions and orchestration steps are wrapped with `@weave.op()` to provide:

- Complete execution traces
- LLM call inspection
- Evaluation dashboards
- Agent comparison
- Performance analysis

---

## Future Improvements

- Persistent storage for decision history
- Authentication and user management
- Additional specialist agents
- Dynamic agent selection
- Streaming responses
- Multi-round agent debate
- Real-time collaborative decision sessions

---

## Acknowledgements

Built during the **Company Brain – Multi-Agent Orchestration Build Day Hackathon (May 2026)** using:

- FastAPI
- React
- OpenAI / Anthropic
- Weights & Biases Weave
