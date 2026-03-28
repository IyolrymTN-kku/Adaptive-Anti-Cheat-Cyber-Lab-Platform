import { useEffect, useState } from 'react';

import apiClient from '../api/client';

export default function ScenarioStudioPage() {
  const [form, setForm] = useState({
    vuln_type: 'sql_injection',
    difficulty: 'easy',
    custom_description: '',
    expected_time_minutes: 5,  // UI uses minutes; sent to API as seconds
  });
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState(null);
  const [scenarioId, setScenarioId] = useState(null);
  const [scenarios, setScenarios] = useState([]);
  const [error, setError] = useState('');
  const [deploying, setDeploying] = useState(false);

  const loadScenarios = async () => {
    try {
      const { data } = await apiClient.get('/api/scenario/list');
      setScenarios(data);
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    loadScenarios();
  }, []);

  const onGenerate = async () => {
    setLoading(true);
    setError('');
    try {
      const payload = {
        ...form,
        expected_time: Math.max(1, Number(form.expected_time_minutes)) * 60,
      };
      const { data } = await apiClient.post('/api/scenario/generate', payload);
      setPreview(data.preview);
      setScenarioId(data.scenario_id);
      await loadScenarios();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const onDelete = async (id) => {
    try {
      await apiClient.delete(`/api/scenario/delete/${id}`);
      await loadScenarios();
    } catch (err) {
      setError(err.message);
    }
  };

  const onSaveDeploy = async () => {
    if (!scenarioId) return;
    setDeploying(true);
    setError('');
    try {
      await apiClient.post('/api/challenge/start', { scenario_id: scenarioId });
      await loadScenarios();
    } catch (err) {
      setError(err.message);
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div className="mx-auto mt-8 w-full max-w-7xl px-4 animate-fadeIn">
      <h1 className="font-display text-3xl font-bold text-green-400">Scenario Studio</h1>
      <p className="mt-2 text-sm text-slate-300 dark:text-slate-300 text-slate-600">
        Gemini-powered challenge builder with terminal-grade previews.
      </p>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.1fr_1fr]">
        <div className="terminal-panel rounded-xl p-5">
          <h2 className="font-display text-lg font-semibold text-green-400">Generate with AI</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <select
              value={form.vuln_type}
              onChange={(event) => setForm((prev) => ({ ...prev, vuln_type: event.target.value }))}
              className="rounded-md border border-green-500/30 bg-gray-900/50 px-3 py-2 text-sm text-green-300 dark:bg-gray-900/50 bg-white"
            >
              <option value="sql_injection">SQL Injection</option>
              <option value="xss">XSS</option>
              <option value="cmd_injection">Command Injection</option>
            </select>
            <select
              value={form.difficulty}
              onChange={(event) => setForm((prev) => ({ ...prev, difficulty: event.target.value }))}
              className="rounded-md border border-green-500/30 bg-gray-900/50 px-3 py-2 text-sm text-green-300 dark:bg-gray-900/50 bg-white"
            >
              <option value="easy">Easy</option>
              <option value="medium">Medium</option>
              <option value="hard">Hard</option>
            </select>
          </div>

          <div className="mt-3">
            <label className="mb-1 block text-xs text-green-400">
              Expected Solve Time (T<sub>expected</sub>) — minutes
            </label>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min={1}
                max={120}
                value={form.expected_time_minutes}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, expected_time_minutes: Number(event.target.value) }))
                }
                className="w-24 rounded-md border border-green-500/30 bg-gray-900/50 px-3 py-2 text-sm text-green-300 dark:bg-gray-900/50 bg-white"
              />
              <span className="text-xs text-slate-400">
                = {form.expected_time_minutes * 60} seconds — used in scoring formula: W<sub>a</sub> × (T<sub>exp</sub> / T<sub>actual</sub>)
              </span>
            </div>
          </div>
          <textarea
            value={form.custom_description}
            onChange={(event) => setForm((prev) => ({ ...prev, custom_description: event.target.value }))}
            placeholder="Custom constraints (optional)"
            className="mt-3 h-24 w-full rounded-md border border-green-500/30 bg-gray-900/50 px-3 py-2 text-sm text-green-300 dark:bg-gray-900/50 bg-white"
          />

          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={onGenerate}
              disabled={loading}
              className="rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-500 disabled:opacity-60"
            >
              {loading ? 'Generating...' : 'Generate with AI'}
            </button>
            <button
              type="button"
              onClick={onSaveDeploy}
              disabled={!scenarioId || deploying}
              className="rounded-md border border-cyan-500/60 px-4 py-2 text-sm text-cyan-300 hover:bg-cyan-500/10 disabled:opacity-50"
            >
              {deploying ? 'Deploying...' : 'Save & Deploy'}
            </button>
          </div>

          {loading ? (
            <div className="mt-6 space-y-3">
              <div className="h-5 animate-pulse rounded bg-green-500/10" />
              <div className="h-5 animate-pulse rounded bg-green-500/10" />
              <div className="h-24 animate-pulse rounded bg-green-500/10" />
            </div>
          ) : null}

          {error ? <p className="mt-4 text-sm text-red-400">{error}</p> : null}
        </div>

        <div className="terminal-panel rounded-xl p-5">
          <h2 className="font-display text-lg font-semibold text-green-400">Preview</h2>
          {preview ? (
            <div className="mt-4 space-y-4">
              <p className="text-sm text-slate-300 dark:text-slate-300 text-slate-600">{preview.challenge_description}</p>
              <div className="rounded-md border border-green-500/20 bg-black/40 p-3 font-mono text-xs text-green-300">
                <div className="mb-1 text-green-500">docker-compose.yml</div>
                <pre className="overflow-x-auto whitespace-pre-wrap">{preview.dockerfile_content}</pre>
              </div>
              <div className="rounded-md border border-amber-500/20 bg-black/30 p-3 text-xs text-amber-300">
                <span className="text-amber-400 font-semibold">Answer (for instructor reference):</span>{' '}
                <span className="font-mono">{preview.answer}</span>
              </div>
            </div>
          ) : (
            <p className="mt-4 text-sm text-slate-300 dark:text-slate-300 text-slate-600">No generated scenario yet.</p>
          )}
        </div>
      </div>

      <div className="terminal-panel mt-6 rounded-xl p-5">
        <h2 className="font-display text-lg font-semibold text-green-400">Saved Scenarios</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-green-500/20 text-green-300">
              <tr>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Difficulty</th>
                <th className="px-3 py-2">T<sub>expected</sub></th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((scenario) => (
                <tr key={scenario.id} className="border-b border-green-500/10">
                  <td className="px-3 py-2">{scenario.name}</td>
                  <td className="px-3 py-2">{scenario.type}</td>
                  <td className="px-3 py-2">{scenario.difficulty}</td>
                  <td className="px-3 py-2 text-amber-300">
                    {scenario.expected_time ? `${Math.round(scenario.expected_time / 60)} min` : '-'}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="mr-2 rounded-md border border-cyan-500/50 px-3 py-1 text-xs text-cyan-300"
                      onClick={() => setScenarioId(scenario.id)}
                    >
                      Deploy
                    </button>
                    <button
                      type="button"
                      className="rounded-md border border-red-500/50 px-3 py-1 text-xs text-red-300"
                      onClick={() => onDelete(scenario.id)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
