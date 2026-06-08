<script lang="ts">
	import { portfoliosApi } from '$lib/api/endpoints';
	import type { NavRange, PortfolioSnapshot } from '$lib/api/types';
	import { createResource } from '$lib/utils/poller.svelte';
	import ComparisonChart from '$lib/charts/ComparisonChart.svelte';
	import type { CompareSeries } from '$lib/charts/ComparisonChart.svelte';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import { t } from '$lib/i18n';

	const REFRESH = 300_000;

	const portfolios = createResource(() => portfoliosApi.list(), { intervalMs: REFRESH });

	let range = $state<NavRange>('all');
	const ranges: readonly NavRange[] = ['7d', '30d', '90d', '1y', 'all'];
	let mode = $state<'pct' | 'abs'>('pct');

	interface Loaded {
		id: number;
		name: string;
		label: string | null;
		snapshots: PortfolioSnapshot[];
	}

	const navs = createResource<Loaded[]>(
		async () => {
			const ps = portfolios.data ?? [];
			return Promise.all(
				ps.map(async (p) => ({
					id: p.id,
					name: p.name,
					label: p.strategy_label,
					snapshots: await portfoliosApi.navFor(p.id, range)
				}))
			);
		},
		{ immediate: false, intervalMs: REFRESH }
	);

	// Reload curves when the portfolio list arrives or the range changes.
	$effect(() => {
		void range;
		if (portfolios.data) void navs.refresh();
	});

	// All portfolios, ordered by id. Show/hide is done from the chart legend (click a name).
	let series = $derived.by((): CompareSeries[] =>
		(navs.data ?? []).map((l) => ({
			id: l.id,
			name: l.label ? `${l.name} (${l.label})` : l.name,
			snapshots: l.snapshots
		}))
	);
</script>

<h1 class="page-title">{t('compare.title')}</h1>

<Card title={t('compare.chart.title')} caption={t('compare.chart.caption')} span="full">
	<div class="controls">
		<div class="seg" role="group" aria-label={t('compare.mode.label')}>
			<button class="seg-btn" class:on={mode === 'pct'} onclick={() => (mode = 'pct')}>
				{t('compare.mode.pct')}
			</button>
			<button class="seg-btn" class:on={mode === 'abs'} onclick={() => (mode = 'abs')}>
				{t('compare.mode.abs')}
			</button>
		</div>
		<div class="seg" role="group" aria-label={t('compare.range.label')}>
			{#each ranges as r (r)}
				<button class="seg-btn" class:on={range === r} onclick={() => (range = r)}>{r}</button>
			{/each}
		</div>
	</div>

	<Region resource={navs} isEmpty={() => series.length === 0} emptyMessage={t('compare.empty')}>
		{#snippet children()}
			<ComparisonChart {series} {mode} height={460} />
		{/snippet}
	</Region>
</Card>

<style>
	.page-title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		margin-bottom: var(--space-5);
	}
	.controls {
		display: flex;
		gap: var(--space-4);
		flex-wrap: wrap;
		margin-bottom: var(--space-3);
	}
	.seg {
		display: inline-flex;
		gap: 2px;
		background: var(--color-bg-1);
		border: 1px solid var(--color-bg-4);
		border-radius: var(--radius-md);
		padding: 2px;
	}
	.seg-btn {
		background: none;
		border: none;
		color: var(--color-text-1);
		font-size: var(--text-sm);
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}
	.seg-btn.on {
		background: var(--color-accent, var(--color-text-0));
		color: var(--color-bg-0);
		font-weight: var(--weight-semibold);
	}
</style>
