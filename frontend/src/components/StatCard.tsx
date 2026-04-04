export default function StatCard({
  label,
  value,
  trend,
}: {
  label: string;
  value: string;
  trend?: 'up' | 'down' | 'neutral';
}) {
  const trendColor =
    trend === 'up' ? 'text-green-400' :
    trend === 'down' ? 'text-red-400' :
    'text-[var(--color-text)]';

  return (
    <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-4">
      <div className="text-sm text-[var(--color-muted)] mb-1">{label}</div>
      <div className={`text-2xl font-bold font-mono ${trendColor}`}>{value}</div>
    </div>
  );
}
