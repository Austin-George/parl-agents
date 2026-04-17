import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './App.css';

const API_URL = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws';

// ── AGENT STATUS CARD ──
function AgentCard({ name, icon, status }) {
  const statusColors = {
    idle: '#666',
    running: '#f0a500',
    complete: '#4ecca3',
    waiting: '#666',
    error: '#e94560'
  };

  const statusLabels = {
    idle: 'Idle',
    running: 'Running...',
    complete: 'Complete',
    waiting: 'Waiting',
    error: 'Error'
  };

  return (
    <div className="agent-card" style={{
      borderColor: statusColors[status] || '#666'
    }}>
      <div className="agent-icon">{icon}</div>
      <div className="agent-info">
        <div className="agent-name">{name}</div>
        <div className="agent-status" style={{
          color: statusColors[status] || '#666'
        }}>
          {status === 'running' && <span className="pulse">●</span>}
          {statusLabels[status] || 'Idle'}
        </div>
      </div>
    </div>
  );
}

// ── COMMUNICATION LOG ITEM ──
function LogItem({ event }) {
  const icons = {
    pipeline_start: '🚀',
    agent_start: '▶️',
    agent_complete: '✅',
    file_created: '📄',
    test_result: '🧪',
    pipeline_complete: '🎉',
    pipeline_error: '❌',
    connection_established: '🔌'
  };

  const colors = {
    pipeline_start: '#4ecca3',
    agent_start: '#f0a500',
    agent_complete: '#4ecca3',
    file_created: '#a8dadc',
    test_result: event.data?.passed ? '#4ecca3' : '#e94560',
    pipeline_complete: '#4ecca3',
    pipeline_error: '#e94560',
    connection_established: '#666'
  };

  return (
    <div className="log-item" style={{
      borderLeftColor: colors[event.type] || '#666'
    }}>
      <span className="log-icon">{icons[event.type] || '📡'}</span>
      <div className="log-content">
        <div className="log-type">{event.type}</div>
        <div className="log-message">
          {event.data?.message ||
           event.data?.agent ||
           JSON.stringify(event.data).slice(0, 80)}
        </div>
        <div className="log-time">
          {new Date(event.timestamp).toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}

// ── FILE VIEWER ──
function FileViewer({ files }) {
  const [selected, setSelected] = useState(null);

  if (!files.length) {
    return (
      <div className="empty-state">
        No files generated yet
      </div>
    );
  }

  return (
    <div className="file-viewer">
      <div className="file-list">
        {files.map(file => (
          <div
            key={file.path}
            className={`file-item ${selected?.path === file.path ? 'active' : ''}`}
            onClick={() => setSelected(file)}
          >
            📄 {file.path}
          </div>
        ))}
      </div>
      {selected && (
        <div className="file-content">
          <div className="file-header">{selected.path}</div>
          <pre className="code-block">{selected.content}</pre>
        </div>
      )}
    </div>
  );
}

// ── TEST RESULTS ──
function TestResults({ report }) {
  if (!report || !report.analysis) {
    return <div className="empty-state">No test results yet</div>;
  }

  const { analysis, raw_results } = report;

  return (
    <div className="test-results">
      <div className={`overall-status ${analysis.overall_status === 'PASS' ? 'pass' : 'fail'}`}>
        {analysis.overall_status === 'PASS' ? '✅' : '❌'} {analysis.overall_status}
        <span className="test-counts">
          {analysis.passed_count} passed / {analysis.failed_count} failed
        </span>
      </div>
      <div className="test-summary">{analysis.summary}</div>
      {raw_results && raw_results.map((result, i) => (
        <div key={i} className={`test-item ${result.passed ? 'pass' : 'fail'}`}>
          <span>{result.passed ? '✓' : '✗'}</span>
          <span className="test-name">{result.scenario}</span>
          <span className="test-detail">
            Expected: {result.expected} | Got: {result.actual}
          </span>
        </div>
      ))}
      {analysis.failures?.length > 0 && (
        <div className="failures-section">
          <div className="section-title">Failure Analysis</div>
          {analysis.failures.map((f, i) => (
            <div key={i} className="failure-item">
              <div className="failure-scenario">✗ {f.scenario}</div>
              <div className="failure-cause">Cause: {f.likely_cause}</div>
              <div className="failure-fix">Fix: {f.fix_needed}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── MAIN APP ──
export default function App() {
  const [requirements, setRequirements] = useState(
    'Build a simple Calculator using MERN stack:\n- Calculator UI with buttons 0-9, +, -, *, /, =, Clear\n- Save each calculation to MongoDB\n- Show calculation history'
  );
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [agentStatuses, setAgentStatuses] = useState({
    Architect: 'idle',
    Coder: 'idle',
    Tester: 'idle'
  });
  const [iteration, setIteration] = useState(0);
  const [events, setEvents] = useState([]);
  const [files, setFiles] = useState([]);
  const [testReport, setTestReport] = useState(null);
  const [activeTab, setActiveTab] = useState('logs');
  const [wsConnected, setWsConnected] = useState(false);
  const [pipelineStatus, setPipelineStatus] = useState('idle');

  const wsRef = useRef(null);
  const logsEndRef = useRef(null);
  const fileInputRef = useRef(null);

  // ── WEBSOCKET CONNECTION ──
  useEffect(() => {
    connectWebSocket();
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  // Auto scroll logs to bottom
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  function connectWebSocket() {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
      console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      handleWebSocketMessage(message);
    };

    ws.onclose = () => {
      setWsConnected(false);
      // Reconnect after 3 seconds
      setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => {
      setWsConnected(false);
    };

    // Keep alive ping
    setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping');
      }
    }, 30000);
  }

  function handleWebSocketMessage(message) {
    // Add to events log
    setEvents(prev => [...prev.slice(-100), message]);

    const { type, data } = message;

    if (type === 'agent_start') {
      setAgentStatuses(prev => ({
        ...prev,
        [data.agent]: 'running'
      }));
    }

    if (type === 'agent_complete') {
      setAgentStatuses(prev => ({
        ...prev,
        [data.agent]: 'complete'
      }));

      // Fetch updated files after Coder completes
      if (data.agent === 'Coder') {
        fetchFiles();
      }

      // Fetch test report after Tester completes
      if (data.agent === 'Tester') {
        fetchTestReport();
      }
    }

    if (type === 'pipeline_start') {
      setPipelineRunning(true);
      setPipelineStatus('running');
      setIteration(0);
      setAgentStatuses({
        Architect: 'waiting',
        Coder: 'waiting',
        Tester: 'waiting'
      });
      setFiles([]);
      setTestReport(null);
    }

    if (type === 'pipeline_complete') {
      setPipelineRunning(false);
      setPipelineStatus('complete');
      setIteration(data.iterations || 0);
      fetchFiles();
      fetchTestReport();
    }

    if (type === 'pipeline_error') {
      setPipelineRunning(false);
      setPipelineStatus('error');
    }
  }

  async function fetchFiles() {
    try {
      const response = await axios.get(`${API_URL}/files`);
      setFiles(response.data.files || []);
    } catch (e) {
      console.error('Failed to fetch files:', e);
    }
  }

  async function fetchTestReport() {
    try {
      const response = await axios.get(`${API_URL}/test-report`);
      setTestReport(response.data);
    } catch (e) {
      console.error('Failed to fetch test report:', e);
    }
  }

  async function handleRunPipeline() {
    if (pipelineRunning) return;

    try {
      await axios.post(`${API_URL}/run-pipeline`, { requirements });
    } catch (e) {
      if (e.response?.status === 409) {
        alert('Pipeline is already running');
      } else {
        alert('Failed to start pipeline: ' + e.message);
      }
    }
  }

  async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      setRequirements(
        `[Uploaded: ${file.name}]\n\n` + event.target.result
      );
    };
    reader.readAsText(file);
  }

  return (
    <div className="app">
      {/* ── HEADER ── */}
      <header className="header">
        <div className="header-title">
          <span className="header-icon">🤖</span>
          PARL Multi-Agent Dashboard
        </div>
        <div className="header-status">
          <span className={`ws-indicator ${wsConnected ? 'connected' : 'disconnected'}`}>
            {wsConnected ? '● Connected' : '○ Disconnected'}
          </span>
          {pipelineRunning && (
            <span className="running-badge">⚡ Pipeline Running</span>
          )}
        </div>
      </header>

      <div className="main-grid">
        {/* ── LEFT PANEL ── */}
        <div className="left-panel">
          {/* Requirements Input */}
          <div className="panel">
            <div className="panel-title">📋 Requirements</div>
            <textarea
              className="requirements-input"
              value={requirements}
              onChange={e => setRequirements(e.target.value)}
              placeholder="Describe the application to build..."
              disabled={pipelineRunning}
            />
            <div className="button-row">
              <button
                className="btn-secondary"
                onClick={() => fileInputRef.current.click()}
                disabled={pipelineRunning}
              >
                📎 Upload SRS
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.md,.pdf"
                style={{ display: 'none' }}
                onChange={handleFileUpload}
              />
              <button
                className={`btn-primary ${pipelineRunning ? 'disabled' : ''}`}
                onClick={handleRunPipeline}
                disabled={pipelineRunning}
              >
                {pipelineRunning ? '⚡ Running...' : '▶ Run Pipeline'}
              </button>
            </div>
          </div>

          {/* Agent Status Cards */}
          <div className="panel">
            <div className="panel-title">
              🤖 Agent Status
              {iteration > 0 && (
                <span className="iteration-badge">
                  Iteration {iteration}
                </span>
              )}
            </div>
            <AgentCard
              name="Architect"
              icon="🏛️"
              status={agentStatuses.Architect}
            />
            <AgentCard
              name="Coder"
              icon="🔨"
              status={agentStatuses.Coder}
            />
            <AgentCard
              name="Tester"
              icon="🧪"
              status={agentStatuses.Tester}
            />

            {pipelineStatus === 'complete' && (
              <div className="pipeline-complete">
                🎉 Pipeline Complete!
              </div>
            )}
            {pipelineStatus === 'error' && (
              <div className="pipeline-error">
                ❌ Pipeline Error
              </div>
            )}
          </div>
        </div>

        {/* ── RIGHT PANEL ── */}
        <div className="right-panel">
          {/* Tabs */}
          <div className="tabs">
            {['logs', 'files', 'tests'].map(tab => (
              <button
                key={tab}
                className={`tab ${activeTab === tab ? 'active' : ''}`}
                onClick={() => {
                  setActiveTab(tab);
                  if (tab === 'files') fetchFiles();
                  if (tab === 'tests') fetchTestReport();
                }}
              >
                {tab === 'logs' && '📡 Agent Comms'}
                {tab === 'files' && `📁 Files (${files.length})`}
                {tab === 'tests' && '🧪 Test Results'}
              </button>
            ))}
          </div>

          <div className="tab-content">
            {activeTab === 'logs' && (
              <div className="logs-panel">
                {events.length === 0 && (
                  <div className="empty-state">
                    Waiting for pipeline events...
                    <br />
                    <small>Start the pipeline to see agent communication</small>
                  </div>
                )}
                {events.map((event, i) => (
                  <LogItem key={i} event={event} />
                ))}
                <div ref={logsEndRef} />
              </div>
            )}

            {activeTab === 'files' && (
              <FileViewer files={files} />
            )}

            {activeTab === 'tests' && (
              <TestResults report={testReport} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}