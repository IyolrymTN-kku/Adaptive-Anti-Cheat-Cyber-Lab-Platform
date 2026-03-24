import { Link } from 'react-router-dom';

import { useAuth } from '../context/AuthContext';

function StudentPanel() {
  return (
    <div className="terminal-panel rounded-xl p-6">
      <h2 className="font-display text-xl font-semibold text-green-400">Student Operations</h2>
      <p className="mt-2 text-sm text-slate-300 dark:text-slate-300 text-slate-600">
        Launch your assigned challenge, monitor MTD behavior, and submit exploit attempts.
      </p>
      <div className="mt-4 flex gap-2">
        <Link to="/challenge" className="rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white">
          Open Challenge Console
        </Link>
        <Link to="/scoreboard" className="rounded-md border border-green-500/40 px-4 py-2 text-sm">
          View Scoreboard
        </Link>
      </div>
    </div>
  );
}

function InstructorPanel() {
  return (
    <div className="terminal-panel rounded-xl p-6">
      <h2 className="font-display text-xl font-semibold text-green-400">Instructor Command Deck</h2>
      <p className="mt-2 text-sm text-slate-300 dark:text-slate-300 text-slate-600">
        Build AI-generated scenarios, deploy challenge containers, and supervise adaptive defense responses.
      </p>
      <div className="mt-4 flex gap-2">
        <Link to="/studio" className="rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white">
          Open Scenario Studio
        </Link>
        <Link to="/scoreboard" className="rounded-md border border-green-500/40 px-4 py-2 text-sm">
          Monitor Scoreboard
        </Link>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();

  return (
    <div className="mx-auto mt-8 w-full max-w-6xl px-4 animate-fadeIn">
      <div className="mb-6">
        <h1 className="font-display text-3xl font-bold text-green-400">Welcome, {user?.username}</h1>
        <p className="mt-1 text-sm text-slate-300 dark:text-slate-300 text-slate-600">
          Role: <span className="font-mono">{user?.role}</span>
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {user?.role === 'instructor' ? <InstructorPanel /> : <StudentPanel />}
        <div className="terminal-panel rounded-xl p-6">
          <h2 className="font-display text-xl font-semibold text-green-400">Range Status</h2>
          <ul className="mt-4 space-y-2 font-mono text-sm text-slate-300 dark:text-slate-300 text-slate-600">
            <li>Backend API: online</li>
            <li>SSE Event Stream: subscribed on challenge page</li>
            <li>MTD Policy: adaptive state machine active</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
