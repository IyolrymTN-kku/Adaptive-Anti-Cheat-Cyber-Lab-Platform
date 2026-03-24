import { useEffect, useMemo, useState } from 'react';

import apiClient from '../api/client';
import EventLogFeed from '../components/EventLogFeed';
import MtdStatusBadge from '../components/MtdStatusBadge';
import { useAuth } from '../context/AuthContext';

export default function ChallengePage() {
  const { user } = useAuth();
  const [challenge, setChallenge] = useState(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [eventType, setEventType] = useState('attack_detected');
  const [error, setError] = useState('');

  const activeAttack = useMemo(() => eventType === 'attack_detected', [eventType]);

  const loadStatus = async () => {
    setStatusLoading(true);
    setError('');
    try {
      const { data } = await apiClient.get('/api/challenge/status');
      const own = Array.isArray(data) ? data.find((row) => row.team_id === user?.id && row.status === 'active') : null;
      setChallenge(own || null);
    } catch (err) {
      setError(err.message);
    } finally {
      setStatusLoading(false);
    }
  };

  useEffect(() => {
    if (!user) return;
    loadStatus();
  }, [user]);

  const triggerMtd = async () => {
    if (!challenge?.id) return;
    try {
      const { data } = await apiClient.post('/api/challenge/trigger-mtd', {
        challenge_id: challenge.id,
        event_type: eventType
      });
      if (data.new_port) {
        setChallenge((prev) => ({ ...prev, port: data.new_port, current_port: data.new_port }));
      }
    } catch (err) {
      setError(err.message);
    }
  };

  const stopChallenge = async () => {
    if (!challenge?.id) return;
    try {
      await apiClient.post('/api/challenge/stop', { challenge_id: challenge.id });
      await loadStatus();
    } catch (err) {
      setError(err.message);
    }
  };

  const resetChallenge = async () => {
    if (!challenge?.id) return;
    try {
      const { data } = await apiClient.post('/api/challenge/reset', { challenge_id: challenge.id });
      setChallenge((prev) => ({ ...prev, ...data }));
      await loadStatus();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="mx-auto mt-8 w-full max-w-7xl px-4 animate-fadeIn">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-3xl font-bold text-green-400">Challenge Console</h1>
        <MtdStatusBadge
          status={challenge?.status || 'stopped'}
          currentPort={challenge?.current_port || challenge?.port}
          activeAttack={activeAttack}
        />
      </div>

      {statusLoading ? <p className="text-sm text-slate-300">Loading challenge...</p> : null}
      {!statusLoading && !challenge ? (
        <div className="terminal-panel rounded-lg p-4 text-sm text-slate-300 dark:text-slate-300 text-slate-600">
          No active challenge for this student yet. Ask your instructor to deploy one.
        </div>
      ) : null}

      {challenge ? (
        <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
          <div className="terminal-panel rounded-lg p-4">
            <h2 className="font-display text-lg font-semibold text-green-400">MTD Controls</h2>
            <p className="mt-2 text-xs text-slate-300 dark:text-slate-300 text-slate-600">
              Active port: <span className="font-mono">{challenge.current_port || challenge.port}</span>
            </p>

            <select
              value={eventType}
              onChange={(event) => setEventType(event.target.value)}
              className="mt-4 w-full rounded-md border border-green-500/30 bg-gray-900/50 px-3 py-2 text-sm text-green-300 dark:bg-gray-900/50 bg-white"
            >
              <option value="attack_detected">attack_detected</option>
              <option value="honeypot_hit">honeypot_hit</option>
              <option value="system_log">system_log</option>
            </select>

            <div className="mt-4 grid gap-2">
              <button
                type="button"
                onClick={triggerMtd}
                className="rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-500"
              >
                Trigger Adaptive MTD
              </button>
              <button
                type="button"
                onClick={resetChallenge}
                className="rounded-md border border-amber-500/40 px-4 py-2 text-sm text-amber-300"
              >
                Reset Session
              </button>
              <button
                type="button"
                onClick={stopChallenge}
                className="rounded-md border border-red-500/50 px-4 py-2 text-sm text-red-300"
              >
                Stop Challenge
              </button>
            </div>

            {error ? <p className="mt-3 text-sm text-red-400">{error}</p> : null}
          </div>

          <EventLogFeed challengeId={challenge.id} />
        </div>
      ) : null}
    </div>
  );
}
