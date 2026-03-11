import React, { useState, useEffect } from 'react';

interface ManagedAgent {
  id: string;
  name: string;
  agent_type: string;
  status: string;
  summary_memory: string;
  config: Record<string, unknown>;
}

interface AgentTask {
  id: string;
  description: string;
  status: string;
}

const colors = {
  bg: '#1e1e2e',
  surface: '#282840',
  surfaceHover: '#313150',
  text: '#cdd6f4',
  textDim: '#6c7086',
  accent: '#89b4fa',
  green: '#a6e3a1',
  yellow: '#f9e2af',
  red: '#f38ba8',
  border: '#45475a',
};

const statusColor = (s: string) =>
  ({
    idle: colors.textDim,
    running: colors.green,
    paused: colors.yellow,
    error: colors.red,
  })[s] || colors.textDim;

interface Props {
  apiUrl: string;
}

export function AgentsPanel({ apiUrl }: Props) {
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${apiUrl}/v1/managed-agents`)
      .then((r) => r.json())
      .then((d) => setAgents(d.agents || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [apiUrl]);

  useEffect(() => {
    if (selectedId) {
      fetch(`${apiUrl}/v1/managed-agents/${selectedId}/tasks`)
        .then((r) => r.json())
        .then((d) => setTasks(d.tasks || []))
        .catch(() => setTasks([]));
    }
  }, [apiUrl, selectedId]);

  const selected = agents.find((a) => a.id === selectedId);

  const listStyle: React.CSSProperties = {
    width: 320,
    borderRight: `1px solid ${colors.border}`,
    overflowY: 'auto',
    padding: 12,
  };

  const detailStyle: React.CSSProperties = {
    flex: 1,
    overflowY: 'auto',
    padding: 20,
  };

  const cardStyle: React.CSSProperties = {
    background: colors.surface,
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
    cursor: 'pointer',
    border: `1px solid ${colors.border}`,
    transition: 'border-color 0.15s',
  };

  if (loading) {
    return (
      <div style={{ padding: 40, color: colors.textDim, textAlign: 'center' }}>
        Loading agents...
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      {/* Left panel — agent list */}
      <div style={listStyle}>
        <h3
          style={{
            color: colors.text,
            fontSize: 14,
            fontWeight: 600,
            marginBottom: 12,
          }}
        >
          Agents ({agents.length})
        </h3>
        {agents.map((a) => (
          <div
            key={a.id}
            style={{
              ...cardStyle,
              borderColor: selectedId === a.id ? colors.accent : colors.border,
            }}
            onClick={() => setSelectedId(a.id)}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <span style={{ color: colors.text, fontSize: 13, fontWeight: 500 }}>
                {a.name}
              </span>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: statusColor(a.status),
                }}
              />
            </div>
            <div style={{ color: colors.textDim, fontSize: 11, marginTop: 4 }}>
              {a.agent_type} · {a.status}
            </div>
          </div>
        ))}
        {agents.length === 0 && (
          <div
            style={{
              color: colors.textDim,
              fontSize: 13,
              textAlign: 'center',
              marginTop: 40,
            }}
          >
            No agents found
          </div>
        )}
      </div>

      {/* Right panel — detail */}
      <div style={detailStyle}>
        {selected ? (
          <>
            <h2
              style={{
                color: colors.text,
                fontSize: 18,
                fontWeight: 600,
                marginBottom: 4,
              }}
            >
              {selected.name}
            </h2>
            <div style={{ color: colors.textDim, fontSize: 12, marginBottom: 16 }}>
              {selected.agent_type} ·{' '}
              <span style={{ color: statusColor(selected.status) }}>{selected.status}</span>
            </div>

            {/* Tasks */}
            <h3
              style={{
                color: colors.text,
                fontSize: 14,
                fontWeight: 600,
                marginBottom: 8,
              }}
            >
              Tasks ({tasks.length})
            </h3>
            {tasks.map((t) => (
              <div key={t.id} style={{ ...cardStyle, cursor: 'default' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: colors.text, fontSize: 13 }}>{t.description}</span>
                  <span style={{ color: statusColor(t.status), fontSize: 11 }}>{t.status}</span>
                </div>
              </div>
            ))}

            {/* Summary Memory */}
            <h3
              style={{
                color: colors.text,
                fontSize: 14,
                fontWeight: 600,
                marginTop: 16,
                marginBottom: 8,
              }}
            >
              Summary Memory
            </h3>
            <div style={{ ...cardStyle, cursor: 'default' }}>
              <pre
                style={{
                  color: colors.text,
                  fontSize: 12,
                  whiteSpace: 'pre-wrap',
                  margin: 0,
                  fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                }}
              >
                {selected.summary_memory || 'No memory stored yet.'}
              </pre>
            </div>
          </>
        ) : (
          <div style={{ color: colors.textDim, textAlign: 'center', marginTop: 80 }}>
            Select an agent to view details
          </div>
        )}
      </div>
    </div>
  );
}
