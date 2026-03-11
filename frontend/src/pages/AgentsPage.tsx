import { useEffect, useState, useCallback } from 'react';
import { useAppStore } from '../lib/store';
import {
  fetchManagedAgents,
  fetchAgentTasks,
  fetchAgentChannels,
  fetchTemplates,
  createManagedAgent,
  pauseManagedAgent,
  resumeManagedAgent,
  deleteManagedAgent,
} from '../lib/api';
import type { AgentTask, ChannelBinding, AgentTemplate } from '../lib/api';
import { Plus, Bot, Pause, Play, Trash2, ChevronLeft, ListTodo, Hash, Brain } from 'lucide-react';

export function AgentsPage() {
  const managedAgents = useAppStore((s) => s.managedAgents);
  const setManagedAgents = useAppStore((s) => s.setManagedAgents);
  const selectedAgentId = useAppStore((s) => s.selectedAgentId);
  const setSelectedAgentId = useAppStore((s) => s.setSelectedAgentId);
  const [loading, setLoading] = useState(true);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [channels, setChannels] = useState<ChannelBinding[]>([]);
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [detailTab, setDetailTab] = useState<'overview' | 'tasks' | 'memory' | 'learning'>('overview');

  const refresh = useCallback(async () => {
    try {
      const agents = await fetchManagedAgents();
      setManagedAgents(agents);
    } catch {
      // Server may be down
    } finally {
      setLoading(false);
    }
  }, [setManagedAgents]);

  useEffect(() => {
    refresh();
    fetchTemplates().then(setTemplates).catch(() => {});
  }, [refresh]);

  const selectedAgent = managedAgents.find((a) => a.id === selectedAgentId);

  useEffect(() => {
    if (selectedAgentId) {
      fetchAgentTasks(selectedAgentId).then(setTasks).catch(() => setTasks([]));
      fetchAgentChannels(selectedAgentId).then(setChannels).catch(() => setChannels([]));
    }
  }, [selectedAgentId]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      await createManagedAgent({
        name: newName,
        template_id: selectedTemplate || undefined,
      });
      setNewName('');
      setSelectedTemplate('');
      setShowCreate(false);
      await refresh();
    } catch {
      /* error handling */
    }
  };

  const handlePause = async (id: string) => {
    await pauseManagedAgent(id);
    await refresh();
  };

  const handleResume = async (id: string) => {
    await resumeManagedAgent(id);
    await refresh();
  };

  const handleDelete = async (id: string) => {
    await deleteManagedAgent(id);
    if (selectedAgentId === id) setSelectedAgentId(null);
    await refresh();
  };

  const statusColor = (s: string) =>
    ({
      idle: 'var(--color-text-tertiary)',
      running: '#22c55e',
      paused: '#eab308',
      error: '#ef4444',
      archived: 'var(--color-text-tertiary)',
    })[s] || 'var(--color-text-tertiary)';

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ color: 'var(--color-text-tertiary)' }}>
        Loading agents...
      </div>
    );
  }

  // Detail view
  if (selectedAgent) {
    return (
      <div className="flex-1 overflow-y-auto p-6">
        <button
          onClick={() => setSelectedAgentId(null)}
          className="flex items-center gap-1 mb-4 text-sm cursor-pointer"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          <ChevronLeft size={16} /> Back to agents
        </button>

        <div className="flex items-center gap-3 mb-6">
          <Bot size={24} style={{ color: 'var(--color-accent)' }} />
          <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
            {selectedAgent.name}
          </h1>
          <span
            className="px-2 py-0.5 rounded-full text-xs font-medium"
            style={{
              background: statusColor(selectedAgent.status) + '20',
              color: statusColor(selectedAgent.status),
            }}
          >
            {selectedAgent.status}
          </span>
        </div>

        {/* Sub-tabs */}
        <div className="flex gap-1 mb-6 p-1 rounded-lg" style={{ background: 'var(--color-bg-secondary)' }}>
          {(['overview', 'tasks', 'memory', 'learning'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setDetailTab(tab)}
              className="px-4 py-2 rounded-md text-sm capitalize cursor-pointer transition-colors"
              style={{
                background: detailTab === tab ? 'var(--color-bg)' : 'transparent',
                color: detailTab === tab ? 'var(--color-text)' : 'var(--color-text-secondary)',
                fontWeight: detailTab === tab ? 500 : 400,
              }}
            >
              {tab}
            </button>
          ))}
        </div>

        {detailTab === 'overview' && (
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}
          >
            {/* Agent Info Card */}
            <div
              className="p-4 rounded-lg"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-secondary)' }}>
                Agent Info
              </h3>
              <div className="space-y-2 text-sm">
                <div>
                  <span style={{ color: 'var(--color-text-secondary)' }}>Type:</span>{' '}
                  <span style={{ color: 'var(--color-text)' }}>{selectedAgent.agent_type}</span>
                </div>
                <div>
                  <span style={{ color: 'var(--color-text-secondary)' }}>ID:</span>{' '}
                  <span className="font-mono text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    {selectedAgent.id}
                  </span>
                </div>
              </div>
            </div>

            {/* Tasks Summary */}
            <div
              className="p-4 rounded-lg"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-secondary)' }}>
                <ListTodo size={14} className="inline mr-1" /> Tasks ({tasks.length})
              </h3>
              {tasks.slice(0, 3).map((t) => (
                <div key={t.id} className="text-sm py-1" style={{ color: 'var(--color-text)' }}>
                  <span className="font-mono text-xs mr-2" style={{ color: statusColor(t.status) }}>
                    [{t.status}]
                  </span>
                  {t.description.slice(0, 50)}
                </div>
              ))}
            </div>

            {/* Channels */}
            <div
              className="p-4 rounded-lg"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-secondary)' }}>
                <Hash size={14} className="inline mr-1" /> Channels ({channels.length})
              </h3>
              {channels.map((b) => (
                <div key={b.id} className="text-sm py-1" style={{ color: 'var(--color-text)' }}>
                  {b.channel_type}: {JSON.stringify(b.config)}
                </div>
              ))}
              {channels.length === 0 && (
                <div className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                  No channels bound
                </div>
              )}
            </div>

            {/* Summary Memory */}
            <div
              className="p-4 rounded-lg"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-secondary)' }}>
                <Brain size={14} className="inline mr-1" /> Summary Memory
              </h3>
              <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--color-text)' }}>
                {selectedAgent.summary_memory || 'No memory yet.'}
              </p>
            </div>
          </div>
        )}

        {detailTab === 'tasks' && (
          <div>
            <div className="space-y-2">
              {tasks.map((t) => (
                <div
                  key={t.id}
                  className="p-3 rounded-lg"
                  style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                >
                  <div className="flex justify-between items-center">
                    <span style={{ color: 'var(--color-text)' }}>{t.description}</span>
                    <span
                      className="text-xs px-2 py-0.5 rounded"
                      style={{
                        background: statusColor(t.status) + '20',
                        color: statusColor(t.status),
                      }}
                    >
                      {t.status}
                    </span>
                  </div>
                </div>
              ))}
              {tasks.length === 0 && (
                <div className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                  No tasks assigned.
                </div>
              )}
            </div>
          </div>
        )}

        {detailTab === 'memory' && (
          <div
            className="p-4 rounded-lg"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <p className="whitespace-pre-wrap text-sm" style={{ color: 'var(--color-text)' }}>
              {selectedAgent.summary_memory || 'Agent has no stored memory yet.'}
            </p>
          </div>
        )}

        {detailTab === 'learning' && (
          <div
            className="p-4 rounded-lg"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
              Learning stats will be available after the agent has run and accumulated traces.
            </p>
          </div>
        )}
      </div>
    );
  }

  // List view
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
          Agents
        </h1>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium cursor-pointer transition-colors"
          style={{ background: 'var(--color-accent)', color: '#fff' }}
        >
          <Plus size={16} /> New Agent
        </button>
      </div>

      {/* Create modal */}
      {showCreate && (
        <div
          className="mb-6 p-4 rounded-lg"
          style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
        >
          <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text)' }}>
            Create Agent
          </h3>
          <div className="space-y-3">
            <input
              type="text"
              placeholder="Agent name..."
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm bg-transparent outline-none"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            />
            {templates.length > 0 && (
              <select
                value={selectedTemplate}
                onChange={(e) => setSelectedTemplate(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm"
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                }}
              >
                <option value="">No template (blank)</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} — {t.description?.slice(0, 50)}
                  </option>
                ))}
              </select>
            )}
            <div className="flex gap-2">
              <button
                onClick={handleCreate}
                className="px-4 py-2 rounded-lg text-sm cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                Create
              </button>
              <button
                onClick={() => setShowCreate(false)}
                className="px-4 py-2 rounded-lg text-sm cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Agent cards */}
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
        {managedAgents.map((a) => (
          <div
            key={a.id}
            onClick={() => setSelectedAgentId(a.id)}
            className="p-4 rounded-lg cursor-pointer transition-colors"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-accent)')}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-border)')}
          >
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Bot size={18} style={{ color: 'var(--color-accent)' }} />
                <span className="font-medium" style={{ color: 'var(--color-text)' }}>
                  {a.name}
                </span>
              </div>
              <span
                className="w-2 h-2 rounded-full"
                style={{ background: statusColor(a.status) }}
                title={a.status}
              />
            </div>
            <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {a.agent_type} · {a.status}
            </div>
            <div className="flex gap-2 mt-3">
              {a.status === 'running' || a.status === 'idle' ? (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handlePause(a.id);
                  }}
                  className="p-1 rounded cursor-pointer"
                  style={{ color: 'var(--color-text-secondary)' }}
                  title="Pause"
                >
                  <Pause size={14} />
                </button>
              ) : a.status === 'paused' ? (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleResume(a.id);
                  }}
                  className="p-1 rounded cursor-pointer"
                  style={{ color: '#22c55e' }}
                  title="Resume"
                >
                  <Play size={14} />
                </button>
              ) : null}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(a.id);
                }}
                className="p-1 rounded cursor-pointer"
                style={{ color: 'var(--color-text-tertiary)' }}
                title="Delete"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>

      {managedAgents.length === 0 && !showCreate && (
        <div className="text-center py-12" style={{ color: 'var(--color-text-tertiary)' }}>
          <Bot size={48} className="mx-auto mb-4 opacity-30" />
          <p className="mb-2">No agents yet</p>
          <p className="text-sm">Create your first agent to get started with autonomous task management.</p>
        </div>
      )}
    </div>
  );
}
