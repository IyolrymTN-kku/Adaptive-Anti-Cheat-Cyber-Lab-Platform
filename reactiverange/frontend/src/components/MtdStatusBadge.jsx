import { CheckCircle2 } from 'lucide-react';

export default function MtdStatusBadge({ status, currentPort, activeAttack }) {
  return (
    <div className="terminal-panel flex items-center gap-3 rounded-lg px-3 py-2">
      {activeAttack ? (
        <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-red-500" title="Active attack" />
      ) : (
        <CheckCircle2 className="h-4 w-4 text-green-400" />
      )}
      <div className="text-xs">
        <div className="font-semibold text-green-400">MTD {status || 'idle'}</div>
        <div className="font-mono text-slate-300 dark:text-slate-300 text-slate-600">Port {currentPort || 'N/A'}</div>
      </div>
    </div>
  );
}
