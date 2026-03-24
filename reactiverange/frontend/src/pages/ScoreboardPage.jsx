import { useEffect, useState } from 'react';

import apiClient from '../api/client';
import ScoreCard from '../components/ScoreCard';

export default function ScoreboardPage() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');

  const loadLiveScores = async () => {
    try {
      const { data } = await apiClient.get('/api/scores/live');
      setRows(data);
      setError('');
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    loadLiveScores();
    const timer = setInterval(loadLiveScores, 3000);
    return () => clearInterval(timer);
  }, []);

  const rankClass = (rank) => {
    if (rank === 1) return 'bg-yellow-500/20';
    if (rank === 2) return 'bg-slate-300/20';
    if (rank === 3) return 'bg-amber-700/20';
    return '';
  };

  return (
    <div className="mx-auto mt-8 w-full max-w-7xl px-4 animate-fadeIn">
      <h1 className="font-display text-3xl font-bold text-green-400">Live Scoreboard</h1>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">Auto-refresh every 3 seconds.</p>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {rows.slice(0, 3).map((item) => (
          <ScoreCard key={item.user_id} item={item} />
        ))}
      </div>

      <div className="terminal-panel mt-6 rounded-xl p-4">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-green-500/20 text-green-300">
              <tr>
                <th className="px-2 py-2">Rank</th>
                <th className="px-2 py-2">Team/User</th>
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
                  <td className="px-2 py-2 text-xs text-slate-400">{row.last_activity ? new Date(row.last_activity).toLocaleString() : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {error ? <p className="mt-3 text-sm text-red-400">{error}</p> : null}
    </div>
  );
}
