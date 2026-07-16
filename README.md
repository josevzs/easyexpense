# EasyExpense

Turn your Tricount export into a clean expense report — AI-categorized, PDF-ready.

## Features

- **Load data** from a Tricount `.xlsx` export or directly from the Tricount API (registry ID or share link)
- **AI auto-categorization** with Claude, OpenAI, or local Ollama
- **Manual review & correction** with confidence badges and per-column filters
- **Global & personal reports** — full group totals or one member's allocation share
- **Report generation** in Markdown, PDF, Excel (.xlsx), and CSV with totals by category and balance sheet
- **Dark / light theme**, session persistence across page reloads

## Prerequisites

- **Python 3.11+** (3.14 required only if you use the Tricount direct-fetch feature)
- **Node.js 18+** and npm

## Setup

### Backend

```bash
# (Optional) activate your virtualenv / conda env
conda activate easyexpense

pip install -r backend/requirements.txt

# From the repo root
python -m uvicorn backend.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

### Docker (alternative)

Run backend + frontend together with Docker Compose — no local Python/Node setup needed:

```bash
docker compose up -d --build
```

Open [http://localhost:8080](http://localhost:8080). API keys can be set by copying `.env.example` to `.env` before starting; sessions persist across restarts in a named volume.

## Configuration

Click the **⚙ Settings** button to configure your AI provider:

| Provider | What you need |
|----------|---------------|
| **Ollama (local)** | [Ollama](https://ollama.com) running + a model pulled (`ollama pull llama3.2`) |
| **Claude** | Anthropic API key from [console.anthropic.com](https://console.anthropic.com) |
| **OpenAI** | OpenAI API key from [platform.openai.com](https://platform.openai.com) |

Settings are saved in `settings.json` (gitignored).

For server deployments, API keys can be passed as environment variables instead:

```
OPENAI_API_KEY=sk-...
CLAUDE_API_KEY=sk-ant-...
OLLAMA_BASE_URL=http://localhost:11434
AI_PROVIDER=openai
ALLOWED_ORIGINS=https://yourdomain.com
```

## Usage

| Step | What to do |
|------|-----------|
| **01 — Load** | Upload `data.xlsx` or paste a Tricount share link / registry ID |
| **02 — Categorize** | Click "Auto-categorize with AI", then apply high-confidence suggestions |
| **03 — Review** | Correct any wrong categories; session survives page reloads |
| **04 — Report** | Set trip name, choose Global or Personal mode, download `.md` / `.pdf` / `.xlsx` / `.csv` |

## Categories

```
Estancias · Alquiler de coches · Comidas y cenas · Desayunos y cafés
Entradas · Gasolina · Peajes · Trenes · Autobuses · Barcos y ferrys
Aviones · Gastos personales · Supermercado · Farmacia · Parking
Taxis · Tricount Close · Otros
```

The AI can also propose additional categories when needed.

## Licence

MIT
