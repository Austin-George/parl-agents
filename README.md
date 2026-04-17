# PARL Multi-Agent Framework
A multi-agent collaborative software development framework 
grounded in the PARL (Perception–Action–Reasoning–Learning) paradigm.

## Agents
- **Architect** — Reads requirements, produces architecture spec
- **Coder** — Reads spec, generates full MERN source code
- **Tester** — Runs Playwright browser tests, reports failures

## Stack
- LangGraph — agent orchestration
- Groq (Llama 3.3 70B) — LLM for all agents
- Playwright — browser automation for UI testing
- FastAPI — REST + WebSocket backend
- React — dashboard frontend
- LangSmith — observability and tracing

## Setup

### 1. Install Python dependencies
```bash
python -m venv venv
venv\Scripts\activate
pip install langchain langchain-groq langgraph langsmith fastapi uvicorn[standard] playwright python-dotenv requests
playwright install chromium
```

### 2. Install Ollama
Download from https://ollama.com and pull models:
```bash
ollama pull llama3.2
```

### 3. Configure environment
```bash
cp .env.example .env
# Fill in your API keys in .env
```

### 4. Start the dashboard
```bash
cd dashboard && npm install && set PORT=3001 && npm start
```

### 5. Start the API server
```bash
python server.py
```

### 6. Open the dashboard
Navigate to http://localhost:3001

## Usage
1. Enter your app requirements in the text box
2. Click **Run Pipeline**
3. Watch agents work in real time
4. View generated files in the Files tab
5. View test results in the Test Results tab

## Project Structure