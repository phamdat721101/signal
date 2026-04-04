import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, ColorType, LineSeries } from 'lightweight-charts';

interface PricePoint {
  timestamp: number;
  price: number;
}

export default function PriceChart({
  data,
  entryPrice,
  targetPrice,
}: {
  data: PricePoint[];
  entryPrice?: number;
  targetPrice?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#71717a',
      },
      grid: {
        vertLines: { color: '#1e1e2e' },
        horzLines: { color: '#1e1e2e' },
      },
      width: containerRef.current.clientWidth,
      height: 300,
      timeScale: { borderColor: '#1e1e2e' },
      rightPriceScale: { borderColor: '#1e1e2e' },
    });

    const series = chart.addSeries(LineSeries, {
      color: '#6366f1',
      lineWidth: 2,
    });

    const chartData = data.map((d) => ({
      time: Math.floor(d.timestamp) as any,
      value: d.price,
    }));
    series.setData(chartData);

    if (entryPrice) {
      series.createPriceLine({ price: entryPrice, color: '#71717a', lineWidth: 1, lineStyle: 2, title: 'Entry' });
    }
    if (targetPrice) {
      series.createPriceLine({ price: targetPrice, color: '#6366f1', lineWidth: 1, lineStyle: 2, title: 'Target' });
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [data, entryPrice, targetPrice]);

  if (data.length === 0) {
    return (
      <div className="h-[300px] flex items-center justify-center text-[var(--color-muted)]">
        No price data available
      </div>
    );
  }

  return <div ref={containerRef} />;
}
