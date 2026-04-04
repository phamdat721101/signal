export default function ConfidenceBadge({ confidence }: { confidence: number }) {
  const color =
    confidence >= 70 ? 'bg-green-500/20 text-green-400' :
    confidence >= 50 ? 'bg-yellow-500/20 text-yellow-400' :
    'bg-red-500/20 text-red-400';

  return (
    <span className={`text-xs font-mono px-2 py-0.5 rounded ${color}`}>
      {confidence}%
    </span>
  );
}
