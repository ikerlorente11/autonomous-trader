<script lang="ts">
	import type { ChartConfiguration, ChartDataset } from 'chart.js';
	import ChartCanvas from './ChartCanvas.svelte';

	type MixedDataset = ChartDataset<'candlestick' | 'line'>;
	import { chartTokens, tooltipStyle } from './theme';
	import { toNum } from '$lib/utils/format';
	import type { OHLCVBar } from '$lib/api/types';

	interface Props {
		bars: OHLCVBar[];
		showMA?: boolean;
		height?: number;
	}
	let { bars, showMA = false, height = 360 }: Props = $props();

	function sma(values: (number | null)[], period: number): (number | null)[] {
		const out: (number | null)[] = [];
		for (let i = 0; i < values.length; i++) {
			if (i < period - 1) {
				out.push(null);
				continue;
			}
			let sum = 0;
			let ok = true;
			for (let j = i - period + 1; j <= i; j++) {
				const v = values[j];
				if (v === null) {
					ok = false;
					break;
				}
				sum += v;
			}
			out.push(ok ? sum / period : null);
		}
		return out;
	}

	let config = $derived.by((): ChartConfiguration<'candlestick' | 'line', unknown> => {
		const t = chartTokens();
		const candles = bars.map((b) => ({
			x: new Date(b.ts).getTime(),
			o: toNum(b.open) ?? 0,
			h: toNum(b.high) ?? 0,
			l: toNum(b.low) ?? 0,
			c: toNum(b.close) ?? 0
		}));
		const closes = bars.map((b) => toNum(b.close));
		const xs = candles.map((c) => c.x);

		// chartjs-chart-financial's dataset typing rejects standard props (label);
		// cast just the candlestick entry to the mixed dataset element type.
		const candleDataset = {
			label: 'OHLC',
			type: 'candlestick',
			data: candles,
			color: { up: t.candleUp, down: t.candleDown, unchanged: t.textSecondary }
		} as unknown as MixedDataset;

		const datasets: MixedDataset[] = [candleDataset];

		if (showMA) {
			const ma20 = sma(closes, 20);
			const ma50 = sma(closes, 50);
			datasets.push(
				{
					label: 'MA20',
					type: 'line',
					data: xs.map((x, i) => ({ x, y: ma20[i] })),
					borderColor: t.accent,
					borderWidth: 1.5,
					pointRadius: 0,
					spanGaps: true
				},
				{
					label: 'MA50',
					type: 'line',
					data: xs.map((x, i) => ({ x, y: ma50[i] })),
					borderColor: t.warn,
					borderWidth: 1.5,
					pointRadius: 0,
					spanGaps: true
				}
			);
		}

		return {
			type: 'candlestick',
			data: { datasets },
			options: {
				responsive: true,
				maintainAspectRatio: false,
				scales: {
					x: {
						type: 'time',
						time: { unit: 'week', tooltipFormat: 'PP' },
						grid: { color: t.gridLine, drawTicks: false },
						border: { display: false },
						ticks: { color: t.textSecondary, font: { size: 11 }, maxRotation: 0, maxTicksLimit: 8 }
					},
					y: {
						grid: { color: t.gridLine, drawTicks: false },
						border: { display: false },
						ticks: { color: t.textSecondary, font: { size: 11, family: t.fontMono } }
					}
				},
				plugins: {
					legend: {
						display: showMA,
						align: 'end',
						labels: { color: t.textSecondary, font: { size: 11 }, boxWidth: 16, usePointStyle: true }
					},
					tooltip: tooltipStyle(t)
				}
			}
		};
	});
</script>

<ChartCanvas {config} {height} ariaLabel="Price candlestick chart" />
