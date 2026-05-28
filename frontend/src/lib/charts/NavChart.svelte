<script lang="ts">
	import type { ChartConfiguration, ChartDataset, ScriptableContext } from 'chart.js';
	import ChartCanvas from './ChartCanvas.svelte';
	import { baseScales, chartTokens, tooltipStyle } from './theme';
	import { toNum } from '$lib/utils/format';
	import type { PortfolioSnapshot } from '$lib/api/types';

	interface Props {
		series: PortfolioSnapshot[];
		height?: number;
	}
	let { series, height = 300 }: Props = $props();

	// Benchmark only drawn if at least one snapshot carries a value.
	let hasBenchmark = $derived(series.some((p) => toNum(p.benchmark_value) !== null));

	let config = $derived.by((): ChartConfiguration<'line'> => {
		const t = chartTokens();
		const labels = series.map((p) => new Date(p.ts).getTime());
		const navData = series.map((p) => toNum(p.total) ?? 0);
		const benchData = series.map((p) => toNum(p.benchmark_value));

		const datasets: ChartDataset<'line'>[] = [
			{
				label: 'Portfolio',
				data: navData,
				borderColor: t.accent,
				borderWidth: 2,
				pointRadius: 0,
				tension: 0.2,
				fill: true,
				backgroundColor: (ctx: ScriptableContext<'line'>) => {
					const { ctx: c, chartArea } = ctx.chart;
					if (!chartArea) return t.accentFill;
					const g = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
					g.addColorStop(0, 'rgba(76,141,255,0.18)');
					g.addColorStop(1, 'rgba(76,141,255,0)');
					return g;
				}
			}
		];
		if (hasBenchmark) {
			datasets.push({
				label: 'SPY Benchmark',
				data: benchData,
				borderColor: t.benchmark,
				borderWidth: 1.5,
				borderDash: [4, 4],
				pointRadius: 0,
				tension: 0.2,
				spanGaps: true,
				fill: false
			});
		}

		return {
			type: 'line',
			data: { labels, datasets },
			options: {
				responsive: true,
				maintainAspectRatio: false,
				interaction: { mode: 'index', intersect: false },
				scales: {
					x: {
						type: 'time',
						time: { unit: 'day', tooltipFormat: 'PP' },
						grid: baseScales(t).x.grid,
						border: { display: false },
						ticks: { ...baseScales(t).x.ticks, maxTicksLimit: 8 }
					},
					y: baseScales(t).y
				},
				plugins: {
					legend: {
						display: hasBenchmark,
						align: 'end',
						labels: { color: t.textSecondary, font: { size: 11 }, boxWidth: 16, usePointStyle: true }
					},
					tooltip: tooltipStyle(t)
				}
			}
		};
	});
</script>

<ChartCanvas {config} {height} ariaLabel="Portfolio NAV vs SPY benchmark over time" />
