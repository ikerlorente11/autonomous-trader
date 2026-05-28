<script lang="ts">
	import { onDestroy } from 'svelte';
	import type { Chart, ChartConfiguration } from 'chart.js';
	import { loadChart } from './register';

	interface Props {
		// Accepts any chart type (line/bar/candlestick/ohlc + mixed unions); the
		// concrete typing lives in the typed wrapper components (NavChart, etc).
		// Data param is `any` (not `any[]`) so it accepts the wrappers' concrete
		// ChartConfiguration<T, unknown> return types.
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		config: ChartConfiguration<any, any, any>;
		height?: number;
		ariaLabel?: string;
	}

	let { config, height = 280, ariaLabel = 'Chart' }: Props = $props();

	let canvas = $state<HTMLCanvasElement | null>(null);
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	let chart: Chart<any, any, any> | null = null;
	let generation = 0;

	async function build() {
		if (!canvas) return;
		const gen = ++generation;
		const ChartCtor = await loadChart();
		// Bail if a newer build started (or the component was destroyed) while loading.
		if (gen !== generation || !canvas) return;
		chart?.destroy();
		// New instance per config change; financial charts don't reconcile cleanly
		// via in-place .update() across dataset shapes.
		chart = new ChartCtor(canvas, config);
	}

	$effect(() => {
		// Re-runs when `config` reference changes.
		void config;
		void build();
	});

	onDestroy(() => {
		generation++;
		chart?.destroy();
		chart = null;
	});
</script>

<div class="chart-wrap" style="height: {height}px" role="img" aria-label={ariaLabel}>
	<canvas bind:this={canvas} aria-hidden="true"></canvas>
</div>

<style>
	.chart-wrap {
		position: relative;
		width: 100%;
	}
	canvas {
		max-width: 100%;
	}
</style>
