import { useEffect, useMemo, useState } from 'react';

const colorMap = {
  attack_detected: 'text-red-400',
  honeypot_hit: 'text-yellow-400',
  mtd_triggered: 'text-green-400',
  score_update: 'text-blue-400',
  system_log: 'text-slate-300'
};

export default function EventLogFeed({ challengeId }) {
  const [events, setEvents] = useState([]);

  useEffect(() => {
    if (!challengeId) return undefined;

    const url = `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000'}/api/events/stream?challenge_id=${challengeId}`;
    const source = new EventSource(url, { withCredentials: true });

    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data);
        setEvents((prev) => [event, ...prev].slice(0, 120));
      } catch {
        // Ignore malformed SSE messages.
      }
    };

    source.onerror = () => {
      source.close();
    };

    return () => source.close();
  }, [challengeId]);

  const rendered = useMemo(
    () =>
      events.map((event) => (
        <div key={event.id} className="border-b border-green-500/10 py-2 font-mono text-xs">
          <span className="text-slate-400">[{new Date(event.timestamp).toLocaleTimeString()}] </span>
          <span className={colorMap[event.type] || 'text-green-400'}>{event.type}</span>
          <span className="ml-2 text-slate-300">{JSON.stringify(event.details)}</span>
        </div>
      )),
    [events]
  );

  return (
    <div className="terminal-panel rounded-lg p-4">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-green-400">Live Event Feed</h3>
      <div className="max-h-[340px] overflow-y-auto pr-1">{rendered}</div>
    </div>
  );
}
