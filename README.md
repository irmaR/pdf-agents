---
title: Chargeback Dispute Bot
emoji: 📄
colorFrom: blue
colorTo: indigo
sdk: streamlit
sdk_version: 1.58.0
app_file: app.py
pinned: false
license: mit
---

# Chargeback Dispute Bot

Agentic pipeline that processes retailer deduction PDFs and auto-drafts dispute letters — or routes to human review when edge cases are detected.

## How it works

```
PDF  →  parse  →  DB lookup  →  edge-case check  →  draft email  →  auto_drafted
                                      ↓ (flag)
                               human_review queue
```

| Step | What happens | Technology |
|------|-------------|------------|
| 1. PDF ingestion | Extract PO number, deduction code, amount, reason text | PyMuPDF (regex) + HuggingFace zero-shot classifier (`facebook/bart-large-mnli`) cross-check |
| 2. DB lookup | Match PO against shipment records | SQLite (`chargebacks.db`, seeded at runtime) |
| 3. Edge case check | Gate auto-send on rules: missing BOL, amount > $500, unknown code, classifier mismatch | Deterministic rule engine |
| 4. Email draft | Generate a professional dispute letter citing BOL and delivery evidence | HuggingFace Inference API — `Qwen/Qwen2.5-7B-Instruct` (falls back to a template if no token) |

## Project structure

```
chargeback_bot/
├── main.py              # pipeline orchestrator
└── tools.py             # parse_pdf, query_shipment, check_edge_cases, draft_dispute_email

flag_human/
└── db.py                # SQLite init + seed data + lookup

tests/
└── evals/
    ├── test_pipeline.py     # pytest golden-case eval harness
    └── generate_sample.py   # creates sample remittance PDFs

sample.pdf               # sample remittance (PO-8821, code SS, $240)
requirements.txt         # unpinned deps
requirements.lock        # pinned lockfile
setup.sh                 # one-shot team setup script
```

## Quickstart

### 1. Clone and enter the project

```bash
git clone git@github.com:irmaR/pdf-agents.git
cd pdf-agents
```

### 2. Set up the environment

```bash
bash setup.sh
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.lock
```

### 3. Add your HuggingFace token

```bash
echo "HF_TOKEN=your_token_here" > .env
```

Get a free token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).  
The token is optional — without it the pipeline uses a structured template for the email instead of the LLM.

### 4. Generate a sample PDF and run the pipeline

```bash
python tests/evals/generate_sample.py   # creates sample.pdf
python -m chargeback_bot.main
```

### 5. Run the eval harness

```bash
pytest tests/evals/ -v
```

## Edge cases that trigger human review

| Rule | Flag |
|------|------|
| PO not found in DB | `PO <x> not found in shipment database` |
| BOL number missing | `Missing BOL number` |
| Deduction amount > $500 | `Dispute amount $x exceeds $500 auto-approve limit` |
| Unknown deduction code | `Unknown deduction code '<x>'` |
| Classifier disagrees with stated code (>60% confidence) | `Classification mismatch: ...` |

## Deduction codes

| Code | Meaning |
|------|---------|
| `SS` | Short shipment |
| `LD` | Late delivery |
| `LB` | Labeling violation |
| `PD` | Price discrepancy |
| `DA` | Damaged goods |
