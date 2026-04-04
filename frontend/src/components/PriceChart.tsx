import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, ColorType, CandlestickSeries, LineSeries } from 'lightweight-charts';

interface PricePoint {
  timestamp: number;
  price: number;
}

interface ChartProps {
  data: PricePoint[];
  entryPrice?: number;
  targetPrice?: number;
  isBull?: boolean;
}

function toOhlc(data: PricePoint[]) {
  if (data.length < 2) return [];
  return data.slice(1).map((d, i) => {
    const prev = data[i].price;
    const cur = d.price;
    const spread = Math.abs(cur - prev) * 0.3 || cur * 0.001;
    return {
      time: Math.floor(d.timestamp) as any,
      open: prev,
      high: Math.max(prev, cur) + spread,
      low: Math.min(prev, cur) - spread,
      close: cur,
    };
  });
}

export default function PriceChart({ data, entryPrice, targetPrice, isBull }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || data.length < 2) return;

    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#71717a' },
      grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
      width: containerRef.current.clientWidth,
      height: 350,
      timeScale: { borderColor: '#1e1e2e' },
      rightPriceScale: { borderColor: '#1e1e2e' },
      crosshair: { mode: 0 },
    });

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e', downColor: '#ef4444',
      borderUpColor: '#22c55e', borderDownColor: '#ef4444',
      wickUpColor: '#22c55e80', wickDownColor: '#ef444480',
    });
    candles.setData(toOhlc(data));

    // Entry price line
    if (entryPrice) {
      candles.createPriceLine({
        price: entryPrice, color: '#f59e0b', lineWidth: 2, lineStyle: 2,
        title: `Entry $${entryPrice >= 1000 ? entryPrice.toLocaleString(undefined, { maximumFractionDigits: 0 }) : entryPrice.toFixed(4)}`,
      });
    }

    // Take-profit line (target)
    if (targetPrice) {
      candles.createPriceLine({
        price: targetPrice, color: '#22c55e', lineWidth: 1, lineStyle: 0,
        title: `TP $${targetPrice >= 1000 ? targetPrice.toLocaleString(undefined, { maximumFractionDigits: 0 }) : targetPrice.toFixed(4)}`,
      });
    }

    // Stop-loss line (entry ± 5% opposite of target)
    if (entryPrice && targetPrice) {
      const sl = isBull ? entryPrice * 0.95 : entryPrice * 1.05;
      candles.createPriceLine({
        price: sl, color: '#ef4444', lineWidth: 1, lineStyle: 0,
        title: `SL $${sl >= 1000 ? sl.toLocaleString(undefined, { maximumFractionDigits: 0 }) : sl.toFixed(4)}`,
      });
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => { window.removeEventListener('resize', handleResize); chart.remove(); };
  }, [data, entryPrice, targetPrice, isBull]);

  if (data.length < 2) {
    return (
      <div className="h-[350px] flex items-center justify-center text-[var(--color-muted)]">
        Waiting for price data...
      </div>
    );
  }

  return <div ref={containerRef} />;
}
