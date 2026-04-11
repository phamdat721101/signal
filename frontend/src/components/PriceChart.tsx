import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, ColorType, CandlestickSeries, createSeriesMarkers } from 'lightweight-charts';

interface PricePoint {
  timestamp: number;
  price: number;
}

interface ChartMarker {
  time: number;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown' | 'circle';
  text: string;
}

interface ChartProps {
  data: PricePoint[];
  entryPrice?: number;
  targetPrice?: number;
  isBull?: boolean;
  markers?: ChartMarker[];
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

function ema(prices: number[], period: number): number[] {
  if (prices.length < period) return [];
  const k = 2 / (period + 1);
  const result = [prices.slice(0, period).reduce((a, b) => a + b, 0) / period];
  for (let i = period; i < prices.length; i++) {
    result.push(prices[i] * k + result[result.length - 1] * (1 - k));
  }
  return result;
}

function computeCrossoverMarkers(data: PricePoint[]): ChartMarker[] {
  if (data.length < 12) return [];
  const closes = data.map(d => d.price);
  const fast = ema(closes, 5);
  const slow = ema(closes, 10);
  // Align: fast starts at index 5, slow at index 10. Overlap starts at index 10.
  const offset = 10;
  const markers: ChartMarker[] = [];
  for (let i = 1; i < slow.length && i + offset < data.length; i++) {
    const fastIdx = i + (offset - 5); // align fast to same data point as slow[i]
    if (fastIdx < 1 || fastIdx >= fast.length) continue;
    const prevDiff = fast[fastIdx - 1] - slow[i - 1];
    const currDiff = fast[fastIdx] - slow[i];
    if (prevDiff <= 0 && currDiff > 0) {
      markers.push({
        time: Math.floor(data[i + offset].timestamp),
        position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: 'Golden Cross',
      });
    } else if (prevDiff >= 0 && currDiff < 0) {
      markers.push({
        time: Math.floor(data[i + offset].timestamp),
        position: 'aboveBar', color: '#ef4444', shape: 'arrowDown', text: 'Death Cross',
      });
    }
  }
  return markers;
}

export default function PriceChart({ data, entryPrice, targetPrice, isBull, markers: externalMarkers }: ChartProps) {
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
    const ohlcData = toOhlc(data);
    candles.setData(ohlcData);

    // Markers: crossover arrows + entry point
    const crossoverMarkers = computeCrossoverMarkers(data);
    const allMarkers = [...crossoverMarkers, ...(externalMarkers || [])];
    if (entryPrice && ohlcData.length > 0) {
      // Find closest candle to entry price for the entry marker
      const lastCandle = ohlcData[ohlcData.length - 1];
      allMarkers.push({
        time: lastCandle.time,
        position: 'belowBar' as const,
        color: '#f59e0b',
        shape: 'circle' as const,
        text: 'Entry',
      });
    }
    if (allMarkers.length > 0) {
      allMarkers.sort((a, b) => (a.time as number) - (b.time as number));
      createSeriesMarkers(candles, allMarkers as any);
    }

    // Price lines
    if (entryPrice) {
      candles.createPriceLine({
        price: entryPrice, color: '#f59e0b', lineWidth: 2, lineStyle: 2,
        title: `Entry $${entryPrice >= 1000 ? entryPrice.toLocaleString(undefined, { maximumFractionDigits: 0 }) : entryPrice.toFixed(4)}`,
      });
    }
    if (targetPrice) {
      candles.createPriceLine({
        price: targetPrice, color: '#22c55e', lineWidth: 1, lineStyle: 0,
        title: `TP $${targetPrice >= 1000 ? targetPrice.toLocaleString(undefined, { maximumFractionDigits: 0 }) : targetPrice.toFixed(4)}`,
      });
    }
    if (entryPrice && targetPrice) {
      const sl = isBull ? entryPrice * 0.985 : entryPrice * 1.015;
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
  }, [data, entryPrice, targetPrice, isBull, externalMarkers]);

  if (data.length < 2) {
    return (
      <div className="h-[350px] flex items-center justify-center text-[var(--color-muted)]">
        Waiting for price data...
      </div>
    );
  }

  return <div ref={containerRef} />;
}
