<script lang="ts">
	import type { ChartConfiguration } from 'chart.js';
	import ChartCanvas from './ChartCanvas.svelte';
	import { chartTokens, tooltipStyle } from './theme';
	import { toNum } from '$lib/utils/format';
	import type { OHLCVBar } from '$lib/api/types';

	interface Props {
		bars: OHLCVBar[];
		height?: number;
	}
	let { bars, height = 110 }: Props = $props();

	let config = $derived.by((): ChartConfiguration<'bar'> => {
		const t = chartTokens();
		const labels = bars.map((b) => new Date(b.ts).getTime());
		const data = bars.map((b) => b.volume ?? 0);
		// Up/down coloring by close vs open, dimmed per ui-system §A.7.
		const colors = bars.map((b) => {
			const up = (toNum(b.close) ?? 0) >= (toNum(b.open) ?? 0);
			return up ? t.candleVolUp : t.candleVolDown;
		});

		return {
			type: 'bar',
			data: {
				labels,
				datasets: [{ label: 'Volume', data, backgroundColor: colors, borderWidth: 0 }]
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				scales: {
					x: {
						type: 'time',
						time: { unit: 'week' },
						grid: { display: false },
						border: { display: false },
						ticks: { display: false }
					},
					y: {
						grid: { color: t.gridLine, drawTicks: false },
						border: { display: false },
						ticks: { color: t.textSecondary, font: { size: 10, family: t.fontMono }, maxTicksLimit: 3 }
					}
				},
				plugins: { legend: { display: false }, tooltip: tooltipStyle(t) }
			}
		};
	});
</script>

<ChartCanvas {config} {height} ariaLabel="Trading volume" />
