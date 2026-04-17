import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './App.css';

const API_URL = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws';

// ── AGENT STATUS CARD ──
function AgentCard({ name, icon, status }) {
  const statusColors = {
    idle:     '#666',
    running:  '#f0a500',
    complete: '#4ecca3',
    waiting:  '#666',
    error:    '#e94560'
  };

  const statusLabels = {
    idle:     'Idle',
    running:  'Running...',
    complete: 'Complete',
    waiting:  'Waiting',
    error:    'Error'
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
    pipeline_start:         '🚀',
    agent_start:            '▶️',
    agent_complete:         '✅',
    file_created:           '📄',
    test_result:            '🧪',
    pipeline_complete:      '🎉',
    pipeline_error:         '❌',
    connection_established: '🔌',
    pong:                   '🏓'
  };

  const colors = {
    pipeline_start:         '#4ecca3',
    agent_start:            '#f0a500',
    agent_complete:         '#4ecca3',
    file_created:           '#a8dadc',
    pipeline_complete:      '#4ecca3',
    pipeline_error:         '#e94560',
    connection_established: '#666',
    pong:                   '#333'
  };

  // Safely extract a display message — never crash on undefined
  function getDisplayMessage() {
    if (!event || !event.data) return 'No data';
    const d = event.data;
    if (d.message) return d.message;
    if (d.agent)   return d.agent;
    try {
      const str = JSON.stringify(d);
      return str.length > 80 ? str.slice(0, 80) + '...' : str;
    } catch {
      return 'Event received';
    }
  }

  // Don't render pong or connection noise in the log
  if (event.type === 'pong' || event.type === 'connection_established') {
    return null;
  }

  return (
    <div className="log-item" style={{
      borderLeftColor: colors[event.type] || '#666'
    }}>
      <span className="log-icon">{icons[event.type] || '📡'}</span>
      <div className="log-content">
        <div className="log-type">{event.type}</div>
        <div className="log-message">{getDisplayMessage()}</div>
        <div className="log-time">
          {event.timestamp
            ? new Date(event.timestamp).toLocaleTimeString()
            : ''}
        </div>
      </div>
    </div>
  );
}

// ── ARCHITECTURE VIEWER ──
function ArchitectureViewer({ content }) {
  if (!content) {
    return (
      <div className="empty-state">
        No architecture yet
        <br />
        <small>Run the pipeline to see the Architect's design</small>
      </div>
    );
  }

  return (
    <div className="architecture-panel">
      <pre className="architecture-content">{content}</pre>
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
    'Build a simple Todo app using MERN stack:\n- Add a new todo with a text input and Add button\n- Display list of all todos\n- Mark a todo as complete by clicking it\n- Delete a todo with a delete button\n- Save all todos to MongoDB\n- No authentication needed'
  );
  const [pipelineRunning, setPipelineRunning]   = useState(false);
  const [agentStatuses, setAgentStatuses]       = useState({
    Architect: 'idle',
    Coder:     'idle',
    Tester:    'idle'
  });
  const [iteration, setIteration]               = useState(0);
  const [events, setEvents]                     = useState([]);
  const [files, setFiles]                       = useState([]);
  const [architecture, setArchitecture]         = useState(null);
  const [testReport, setTestReport]             = useState(null);
  const [activeTab, setActiveTab]               = useState('logs');
  const [wsConnected, setWsConnected]           = useState(false);
  const [pipelineStatus, setPipelineStatus]     = useState('idle');

  const pingIntervalRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const wsRef        = useRef(null);
  const logsEndRef   = useRef(null);
  const fileInputRef = useRef(null);

  // ── WEBSOCKET CONNECTION ──
  useEffect(() => {
    connectWebSocket();
    return () => {
        // Clean up everything on unmount
        if (wsRef.current) wsRef.current.close();
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
        if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    };
  }, []);

  // Auto scroll logs to bottom on new events
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  function connectWebSocket() {
    // Don't create a new connection if one already exists and is open
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        return;
    }

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
        setWsConnected(true);
        console.log('WebSocket connected');

        // Clear any existing ping interval before creating a new one
        if (pingIntervalRef.current) {
            clearInterval(pingIntervalRef.current);
        }

        // Keep connection alive with ping every 30 seconds
        pingIntervalRef.current = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send('ping');
            }
        }, 30000);
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        handleWebSocketMessage(message);
    };

    ws.onclose = () => {
        setWsConnected(false);
        console.log('WebSocket disconnected — reconnecting in 3s');

        // Clear ping interval when disconnected
        if (pingIntervalRef.current) {
            clearInterval(pingIntervalRef.current);
            pingIntervalRef.current = null;
        }

        // Clear any existing reconnect timer before setting a new one
        if (reconnectTimerRef.current) {
            clearTimeout(reconnectTimerRef.current);
        }

        // Attempt reconnect after 3 seconds
        reconnectTimerRef.current = setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = (error) => {
        setWsConnected(false);
        console.error('WebSocket error:', error);
        ws.close(); // trigger onclose which handles reconnect
    };
  }

  function handleWebSocketMessage(message) {
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

      // Fetch relevant data as each agent completes
      if (data.agent === 'Architect') fetchArchitecture();
      if (data.agent === 'Coder')     fetchFiles();
      if (data.agent === 'Tester')    fetchTestReport();
    }

    if (type === 'pipeline_start') {
      setPipelineRunning(true);
      setPipelineStatus('running');
      setIteration(0);
      setAgentStatuses({
        Architect: 'waiting',
        Coder:     'waiting',
        Tester:    'waiting'
      });
      // Clear previous run data
      setFiles([]);
      setArchitecture(null);
      setTestReport(null);
      setEvents([]);
    }

    if (type === 'pipeline_complete') {
      setPipelineRunning(false);
      setPipelineStatus('complete');
      setIteration(data.iterations || 0);
      fetchFiles();
      fetchArchitecture();
      fetchTestReport();
    }

    if (type === 'pipeline_error') {
      setPipelineRunning(false);
      setPipelineStatus('error');
    }
  }

  // ── DATA FETCHERS ──

  async function fetchArchitecture() {
    try {
      const response = await axios.get(`${API_URL}/architecture`);
      setArchitecture(response.data.content || null);
    } catch (e) {
      console.error('Failed to fetch architecture:', e);
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
      setRequirements(`[Uploaded: ${file.name}]\n\n` + event.target.result);
    };
    reader.readAsText(file);
  }

  // ── TAB DEFINITIONS ──
  // Centralised so adding a new tab only needs one change here
  const tabs = [
    {
      id:    'logs',
      label: '📡 Agent Comms',
      onSelect: () => {}
    },
    {
      id:    'architecture',
      label: '🏛️ Architecture',
      onSelect: fetchArchitecture
    },
    {
      id:    'files',
      label: `📁 Files (${files.length})`,
      onSelect: fetchFiles
    },
    {
      id:    'tests',
      label: '🧪 Test Results',
      onSelect: fetchTestReport
    },
  ];

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
            <AgentCard name="Architect" icon="🏛️" status={agentStatuses.Architect} />
            <AgentCard name="Coder"     icon="🔨" status={agentStatuses.Coder}     />
            <AgentCard name="Tester"    icon="🧪" status={agentStatuses.Tester}    />

            {pipelineStatus === 'complete' && (
              <div className="pipeline-complete">🎉 Pipeline Complete!</div>
            )}
            {pipelineStatus === 'error' && (
              <div className="pipeline-error">❌ Pipeline Error</div>
            )}
          </div>
        </div>

        {/* ── RIGHT PANEL ── */}
        <div className="right-panel">

          {/* Tabs */}
          <div className="tabs">
            {tabs.map(tab => (
              <button
                key={tab.id}
                className={`tab ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => {
                  setActiveTab(tab.id);
                  tab.onSelect();
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab Content */}
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

            {activeTab === 'architecture' && (
              <ArchitectureViewer content={architecture} />
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