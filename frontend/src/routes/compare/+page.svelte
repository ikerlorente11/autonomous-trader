<script lang="ts">
	import { portfoliosApi } from '$lib/api/endpoints';
	import type { NavRange, PortfolioSnapshot } from '$lib/api/types';
	import { createResource } from '$lib/utils/poller.svelte';
	import { compareColor } from '$lib/charts/comparePalette';
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

	// Which portfolios are overlaid. Null = "not yet initialised" → default to all once loaded.
	let selected = $state<Set<number> | null>(null);
	let order = $state<number[]>([]);

	$effect(() => {
		const ps = portfolios.data;
		if (ps && selected === null) {
			selected = new Set(ps.map((p) => p.id));
			order = ps.map((p) => p.id);
		}
	});

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

	function toggle(id: number): void {
		if (!selected) return;
		const next = new Set(selected);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		selected = next;
	}

	function move(id: number, dir: -1 | 1): void {
		const i = order.indexOf(id);
		const j = i + dir;
		if (i < 0 || j < 0 || j >= order.length) return;
		const next = [...order];
		[next[i], next[j]] = [next[j], next[i]];
		order = next;
	}

	let series = $derived.by((): CompareSeries[] => {
		const loaded = navs.data ?? [];
		const byId = new Map(loaded.map((l) => [l.id, l]));
		const sel = selected ?? new Set<number>();
		return order
			.filter((id) => sel.has(id) && byId.has(id))
			.map((id) => {
				const l = byId.get(id)!;
				return {
					id: l.id,
					name: l.label ? `${l.name} (${l.label})` : l.name,
					snapshots: l.snapshots
				};
			});
	});
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
			<ComparisonChart {series} {mode} height={420} />
		{/snippet}
	</Region>
</Card>

<Card title={t('compare.select.title')} caption={t('compare.select.caption')} span="full">
	<Region resource={portfolios} isEmpty={(d) => d.length === 0} emptyMessage={t('compare.empty')}>
		{#snippet children(d)}
			<ul class="picks">
				{#each order.filter((id) => d.some((p) => p.id === id)) as id (id)}
					{@const p = d.find((x) => x.id === id)!}
					<li class="pick">
						<label class="lbl">
							<input
								type="checkbox"
								checked={selected?.has(id) ?? false}
								onchange={() => toggle(id)}
							/>
							<span class="dot" style="background:{compareColor(id)}"></span>
							<span class="nm">{p.name}</span>
							{#if p.strategy_label}<span class="ver">{p.strategy_label}</span>{/if}
						</label>
						<span class="ord">
							<button class="link" onclick={() => move(id, -1)} aria-label={t('compare.moveUp')}>↑</button>
							<button class="link" onclick={() => move(id, 1)} aria-label={t('compare.moveDown')}>↓</button>
						</span>
					</li>
				{/each}
			</ul>
		{/snippet}
	</Region>
</Card>

<style>
	.page-title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		margin-bottom: var(--space-5);
	}
	:global(.card) {
		margin-bottom: var(--space-4);
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
	.picks {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.pick {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
	}
	.lbl {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		cursor: pointer;
		font-size: var(--text-sm);
	}
	.dot {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		display: inline-block;
	}
	.ver {
		font-size: var(--text-xs);
		color: var(--color-text-2);
		border: 1px solid var(--color-bg-4);
		border-radius: var(--radius-sm);
		padding: 0 var(--space-2);
	}
	.ord {
		display: inline-flex;
		gap: var(--space-2);
	}
	.link {
		background: none;
		border: none;
		color: var(--color-accent, var(--color-text-1));
		cursor: pointer;
		font-size: var(--text-md);
		padding: 0 var(--space-1);
	}
</style>
