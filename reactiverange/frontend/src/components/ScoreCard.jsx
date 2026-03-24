export default function ScoreCard({ item }) {
  const medalClass =
    item.rank === 1
      ? 'border-yellow-400/60 bg-yellow-500/10'
      : item.rank === 2
        ? 'border-slate-300/50 bg-slate-400/10'
        : item.rank === 3
          ? 'border-amber-600/50 bg-amber-600/10'
          : 'border-green-500/20 bg-gray-900/30 dark:bg-gray-900/30 bg-white';

  return (
    <div className={`rounded-lg border p-4 transition hover:-translate-y-0.5 ${medalClass}`}>
      <div className="flex items-center justify-between">
        <h4 className="font-display text-sm font-semibold">#{item.rank} {item.team}</h4>
        <span className="font-mono text-lg font-bold">{item.net_score}</span>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-slate-300 dark:text-slate-300 text-slate-600">
        <div>Solved: {item.solved}</div>
        <div>Decoys: {item.deception_hits}</div>
        <div>MTD: {item.mtd_evasions}</div>
      </div>
    </div>
  );
}
