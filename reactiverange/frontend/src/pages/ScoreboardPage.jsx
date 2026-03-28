import { useEffect, useState } from 'react';

import apiClient from '../api/client';
import ScoreCard from '../components/ScoreCard';
import { useAuth } from '../context/AuthContext';

export default function ScoreboardPage() {
  const { user } = useAuth();
  const [rows, setRows] = useState([]);
  const [students, setStudents] = useState([]);
  const [confirmReset, setConfirmReset] = useState(null); // student object | null
  const [resetLoading, setResetLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState('');
  const [error, setError] = useState('');

  const loadLiveScores = async () => {
    try {
      const { data } = await apiClient.get('/api/scores/live');
      setRows(data);
    } catch (err) {
      setError(err.message);
    }
  };

  const loadStudents = async () => {
    try {
      const { data } = await apiClient.get('/api/admin/students');
      setStudents(data);
    } catch {
      // Non-fatal — only instructors can reach this endpoint.
    }
  };

  useEffect(() => {
    loadLiveScores();
    const timer = setInterval(loadLiveScores, 3000);
    if (user?.role === 'instructor') {
      loadStudents();
    }
    return () => clearInterval(timer);
  }, [user]);

  const handleReset = async () => {
    if (!confirmReset) return;
    setResetLoading(true);
    setError('');
    try {
      const { data } = await apiClient.post('/api/admin/reset-student', {
        student_id: confirmReset.id,
      });
      setConfirmReset(null);
      setSuccessMsg(data.message);
      setTimeout(() => setSuccessMsg(''), 5000);
      // Refresh both lists after a reset.
      await Promise.all([loadLiveScores(), loadStudents()]);
    } catch (err) {
      setError(err.response?.data?.error || err.message);
      setConfirmReset(null);
    } finally {
      setResetLoading(false);
    }
  };

  const rankClass = (rank) => {
    if (rank === 1) return 'bg-yellow-500/20';
    if (rank === 2) return 'bg-slate-300/20';
    if (rank === 3) return 'bg-amber-700/20';
    return '';
  };

  return (
    <div className="mx-auto mt-8 w-full max-w-7xl px-4 animate-fadeIn pb-12">
      <h1 className="font-display text-3xl font-bold text-green-400">Live Scoreboard</h1>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">Auto-refresh every 3 seconds.</p>

      {/* Top-3 score cards */}
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {rows.slice(0, 3).map((item) => (
          <ScoreCard key={item.user_id} item={item} />
        ))}
      </div>

      {/* Full rankings table */}
      <div className="terminal-panel mt-6 rounded-xl p-4">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-green-500/20 text-green-300">
              <tr>
                <th className="px-2 py-2">Rank</th>
                <th className="px-2 py-2">Team / User</th>
                <th className="px-2 py-2">Net Score</th>
                <th className="px-2 py-2">Solved</th>
                <th className="px-2 py-2">Deception Hits</th>
                <th className="px-2 py-2">MTD Evasions</th>
                <th className="px-2 py-2">Last Activity</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.user_id} className={`border-b border-green-500/10 ${rankClass(row.rank)}`}>
                  <td className="px-2 py-2 font-mono">{row.rank}</td>
                  <td className="px-2 py-2">{row.team}</td>
                  <td className="px-2 py-2 font-semibold">{row.net_score}</td>
                  <td className="px-2 py-2">{row.solved}</td>
                  <td className="px-2 py-2">{row.deception_hits}</td>
                  <td className="px-2 py-2">{row.mtd_evasions}</td>
                  <td className="px-2 py-2 text-xs text-slate-400">
                    {row.last_activity ? new Date(row.last_activity).toLocaleString() : '-'}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-2 py-6 text-center text-sm text-slate-500">
                    No scores yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Instructor-only: Student Management ─────────────────────────── */}
      {user?.role === 'instructor' && (
        <div className="terminal-panel mt-6 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="font-display text-lg font-semibold text-green-400">Student Management</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Reset a student's score and challenge history so they can start fresh.
              </p>
            </div>
            <button
              onClick={loadStudents}
              className="text-xs text-slate-400 hover:text-green-400 transition border border-slate-600 hover:border-green-500/50 rounded px-2 py-1"
            >
              ↻ Refresh
            </button>
          </div>

          {successMsg && (
            <div className="mb-4 rounded-lg border border-green-500/40 bg-green-500/10 px-4 py-2 text-sm text-green-400 animate-fadeIn">
              ✓ {successMsg}
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-green-500/20 text-green-300">
                <tr>
                  <th className="px-3 py-2">Username</th>
                  <th className="px-3 py-2">Email</th>
                  <th className="px-3 py-2">Net Score</th>
                  <th className="px-3 py-2">Solved</th>
                  <th className="px-3 py-2">Joined</th>
                  <th className="px-3 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {students.map((s) => (
                  <tr key={s.id} className="border-b border-green-500/10 hover:bg-green-500/5 transition">
                    <td className="px-3 py-2 font-semibold text-white">{s.username}</td>
                    <td className="px-3 py-2 text-slate-400 text-xs">{s.email}</td>
                    <td className="px-3 py-2">
                      <span className={`font-mono font-semibold ${s.net_score > 0 ? 'text-green-400' : 'text-slate-500'}`}>
                        {s.net_score}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`font-mono ${s.solved > 0 ? 'text-blue-400' : 'text-slate-500'}`}>
                        {s.solved}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {s.created_at ? new Date(s.created_at).toLocaleDateString() : '-'}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        onClick={() => setConfirmReset(s)}
                        disabled={s.net_score === 0 && s.solved === 0}
                        className={`inline-flex items-center gap-1.5 rounded px-3 py-1 text-xs font-semibold transition ${
                          s.net_score === 0 && s.solved === 0
                            ? 'text-slate-600 border border-slate-700 cursor-not-allowed'
                            : 'text-red-400 border border-red-500/50 hover:bg-red-500/10 hover:text-red-300'
                        }`}
                      >
                        {/* Refresh / reset icon */}
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2"
                            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        Reset
                      </button>
                    </td>
                  </tr>
                ))}
                {students.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-3 py-6 text-center text-sm text-slate-500">
                      No student accounts found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

      {/* ── Confirmation modal ───────────────────────────────────────────── */}
      {confirmReset && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-fadeIn">
          <div className="w-full max-w-md rounded-2xl border border-red-500/40 bg-slate-900 p-6 shadow-2xl">
            {/* Icon */}
            <div className="flex items-center justify-center w-12 h-12 rounded-full bg-red-500/15 border border-red-500/30 mx-auto mb-4">
              <svg className="w-6 h-6 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2"
                  d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              </svg>
            </div>

            <h3 className="text-center text-lg font-bold text-white mb-1">
              Reset Student Progress
            </h3>
            <p className="text-center text-sm text-slate-400 mb-6">
              Are you sure you want to reset{' '}
              <span className="font-semibold text-white">{confirmReset.username}</span>'s progress?
              <br />
              This will permanently delete all their answers, scores, and challenge history.
              <br />
              <span className="text-red-400 font-medium">This action cannot be undone.</span>
            </p>

            <div className="flex gap-3">
              <button
                onClick={() => setConfirmReset(null)}
                disabled={resetLoading}
                className="flex-1 rounded-lg border border-slate-600 py-2.5 text-sm font-semibold text-slate-300 hover:bg-slate-700 transition disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleReset}
                disabled={resetLoading}
                className="flex-1 rounded-lg bg-red-600 py-2.5 text-sm font-semibold text-white hover:bg-red-500 transition disabled:opacity-60"
              >
                {resetLoading ? 'Resetting...' : `Yes, Reset ${confirmReset.username}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
