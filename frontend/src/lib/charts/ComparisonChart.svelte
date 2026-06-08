<script lang="ts">
	import type { ChartConfiguration, ChartDataset, TooltipItem } from 'chart.js';
	import ChartCanvas from './ChartCanvas.svelte';
	import { baseScales, chartTokens, tooltipStyle } from './theme';
	import { compareColor } from './comparePalette';
	import { toNum } from '$lib/utils/format';
	import type { PortfolioSnapshot } from '$lib/api/types';

	export interface CompareSeries {
		id: number;
		name: string;
		snapshots: PortfolioSnapshot[];
	}

	interface Props {
		series: CompareSeries[];
		// 'pct' rebases each line to its own first point (comparable across budgets);
		// 'abs' plots raw NAV in €.
		mode?: 'pct' | 'abs';
		height?: number;
	}
	let { series, mode = 'pct', height = 380 }: Props = $props();

	let config = $derived.by((): ChartConfiguration<'line'> => {
		const t = chartTokens();
		// Union of all timestamps so the index-mode tooltip lines every portfolio up
		// on the same date even when their histories start on different days.
		const tsSet = new Set<number>();
		for (const s of series)
			for (const p of s.snapshots) tsSet.add(new Date(p.ts).getTime());
		const labels = [...tsSet].sort((a, b) => a - b);

		const datasets: ChartDataset<'line'>[] = series.map((s) => {
			const byTs = new Map<number, number>();
			for (const p of s.snapshots) {
				const v = toNum(p.total);
				if (v !== null) byTs.set(new Date(p.ts).getTime(), v);
			}
			// First real value = the rebasing anchor for % mode.
			const firstTs = labels.find((ts) => byTs.has(ts));
			const base = firstTs !== undefined ? byTs.get(firstTs)! : null;
			const data = labels.map((ts) => {
				const v = byTs.get(ts);
				if (v === undefined) return null;
				if (mode === 'pct') return base && base !== 0 ? (v / base - 1) * 100 : 0;
				return v;
			});
			const c = compareColor(s.id);
			return {
				label: s.name,
				data,
				borderColor: c,
				backgroundColor: c,
				borderWidth: 2,
				pointRadius: 0,
				pointHoverRadius: 3,
				tension: 0.2,
				spanGaps: true,
				fill: false
			};
		});

		const fmt = (v: number) =>
			mode === 'pct'
				? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
				: `€${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

		return {
			type: 'line',
			data: { labels, datasets },
			options: {
				responsive: true,
				maintainAspectRatio: false,
				// Shared crosshair: hovering a date surfaces every portfolio's value at once.
				interaction: { mode: 'index', intersect: false },
				scales: {
					x: {
						type: 'time',
						time: { unit: 'day', tooltipFormat: 'PP' },
						grid: baseScales(t).x.grid,
						border: { display: false },
						ticks: { ...baseScales(t).x.ticks, maxTicksLimit: 8 }
					},
					y: {
						...baseScales(t).y,
						ticks: {
							...baseScales(t).y.ticks,
							callback: (v) => fmt(Number(v))
						}
					}
				},
				plugins: {
					legend: {
						display: true,
						align: 'end',
						labels: {
							color: t.textSecondary,
							font: { size: 11 },
							boxWidth: 16,
							usePointStyle: true
						}
					},
					tooltip: {
						...tooltipStyle(t),
						itemSort: (a: TooltipItem<'line'>, b: TooltipItem<'line'>) =>
							(b.parsed.y ?? 0) - (a.parsed.y ?? 0),
						callbacks: {
							label: (item: TooltipItem<'line'>) => {
								const y = item.parsed.y;
								if (y === null || y === undefined) return undefined;
								return `${item.dataset.label}: ${fmt(y)}`;
							}
						}
					}
				}
			}
		};
	});
</script>

<ChartCanvas {config} {height} ariaLabel="Portfolio comparison over time" />
