<script lang="ts">
	import { algorithmsApi, portfoliosApi } from '$lib/api/endpoints';
	import type {
		Leaderboard,
		NavRange,
		PortfolioComparison,
		PortfolioSnapshot
	} from '$lib/api/types';
	import { createResource } from '$lib/utils/poller.svelte';
	import ComparisonChart from '$lib/charts/ComparisonChart.svelte';
	import type { CompareSeries } from '$lib/charts/ComparisonChart.svelte';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import { t } from '$lib/i18n';

	const REFRESH = 300_000;

	const portfolios = createResource(() => portfoliosApi.list(), { intervalMs: REFRESH });
	// The only fair ranking: every arm over the sessions they all share.
	const board = createResource<Leaderboard>(() => algorithmsApi.leaderboard(), {
		intervalMs: REFRESH
	});

	let range = $state<NavRange>('all');
	const ranges: readonly NavRange[] = ['7d', '30d', '90d', '1y', 'all'];
	let mode = $state<'pct' | 'abs'>('pct');

	// Statistical A/B verdict between two chosen portfolios.
	let aId = $state<number | null>(null);
	let bId = $state<number | null>(null);
	let cmp = $state<PortfolioComparison | null>(null);
	let cmpError = $state<string | null>(null);

	// Default the picker to the first two portfolios once the list arrives.
	$effect(() => {
		const ps = portfolios.data ?? [];
		if (aId === null && ps.length >= 1) aId = ps[0].id;
		if (bId === null && ps.length >= 2) bId = ps[1].id;
	});

	async function runComparison() {
		cmpError = null;
		cmp = null;
		if (aId === null || bId === null || aId === bId) {
			cmpError = t('compare.ab.pickTwo');
			return;
		}
		try {
			cmp = await algorithmsApi.compare(aId, bId);
		} catch (e) {
			cmpError = e instanceof Error ? e.message : String(e);
		}
	}

	const pct = (v: number | null) => (v == null ? '—' : `${(v * 100).toFixed(2)}%`);
	const num = (v: number | null, d = 2) => (v == null ? '—' : v.toFixed(d));
	const verdictKey = (v: string) => `compare.ab.verdict.${v}`;

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

<Card title={t('compare.board.title')} caption={t('compare.board.caption')} span="full">
	<Region
		resource={board}
		isEmpty={() => (board.data?.entries.length ?? 0) === 0}
		emptyMessage={t('compare.board.empty')}
	>
		{#snippet children()}
			<p class="ab-note">
				{t('compare.board.window')}: {board.data?.start} → {board.data?.end}
				({board.data?.sessions} {t('compare.board.sessions')})
			</p>
			<table class="ab-table">
				<thead>
					<tr>
						<th>{t('compare.board.name')}</th>
						<th>{t('compare.board.return')}</th>
						<th>{t('compare.board.benchmark')}</th>
						<th>{t('compare.board.excess')}</th>
						<th>Sharpe</th>
						<th>{t('compare.board.maxDD')}</th>
					</tr>
				</thead>
				<tbody>
					{#each board.data?.entries ?? [] as e (e.portfolio_id)}
						<tr>
							<td>{e.strategy_label ? `${e.name} (${e.strategy_label})` : e.name}</td>
							<td>{pct(e.total_return)}</td>
							<td>{pct(e.benchmark_return)}</td>
							<td class:up={(e.excess ?? 0) > 0} class:down={(e.excess ?? 0) < 0}>
								{pct(e.excess)}
							</td>
							<td>{num(e.sharpe)}</td>
							<td>{pct(e.max_drawdown)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
			{#if (board.data?.excluded.length ?? 0) > 0}
				<p class="ab-note">
					{t('compare.board.excluded')}: {board.data?.excluded.join(', ')}
				</p>
			{/if}
		{/snippet}
	</Region>
</Card>

<Card title={t('compare.ab.title')} caption={t('compare.ab.caption')} span="full">
	<div class="controls">
		<label class="ab-pick">
			A
			<select bind:value={aId}>
				{#each portfolios.data ?? [] as p (p.id)}
					<option value={p.id}>{p.strategy_label ? `${p.name} (${p.strategy_label})` : p.name}</option>
				{/each}
			</select>
		</label>
		<label class="ab-pick">
			B
			<select bind:value={bId}>
				{#each portfolios.data ?? [] as p (p.id)}
					<option value={p.id}>{p.strategy_label ? `${p.name} (${p.strategy_label})` : p.name}</option>
				{/each}
			</select>
		</label>
		<button class="seg-btn run" onclick={runComparison}>{t('compare.ab.run')}</button>
	</div>

	{#if cmpError}
		<p class="ab-note">{cmpError}</p>
	{:else if cmp}
		<div class="verdict" class:sig={cmp.returns_significance.significant}>
			{t(verdictKey(cmp.verdict))}
		</div>
		<table class="ab-table">
			<thead>
				<tr>
					<th></th>
					<th>{cmp.a.strategy_label ?? cmp.a.name} (A)</th>
					<th>{cmp.b.strategy_label ?? cmp.b.name} (B)</th>
				</tr>
			</thead>
			<tbody>
				<tr><td>{t('compare.ab.pnl')}</td><td>{pct(cmp.a.pnl_pct)}</td><td>{pct(cmp.b.pnl_pct)}</td></tr>
				<tr><td>{t('compare.ab.totalReturn')}</td><td>{pct(cmp.a.total_return)}</td><td>{pct(cmp.b.total_return)}</td></tr>
				<tr><td>Sharpe</td><td>{num(cmp.a.sharpe)}</td><td>{num(cmp.b.sharpe)}</td></tr>
				<tr><td>{t('compare.ab.maxDD')}</td><td>{pct(cmp.a.max_drawdown)}</td><td>{pct(cmp.b.max_drawdown)}</td></tr>
			</tbody>
		</table>
		<p class="ab-note">
			{t('compare.ab.pairedDays')}: {cmp.paired_days} ·
			{t('compare.ab.pReturns')}: {num(cmp.returns_significance.p_value, 3)} ·
			{t('compare.ab.pSharpe')}: {num(cmp.sharpe_significance.p_value, 3)}
		</p>
	{:else}
		<p class="ab-note">{t('compare.ab.hint')}</p>
	{/if}
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
	.ab-table td.up {
		color: var(--color-up, #16a34a);
	}
	.ab-table td.down {
		color: var(--color-down, #dc2626);
	}
	.ab-pick {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--color-text-1);
	}
	.ab-pick select {
		background: var(--color-bg-1);
		border: 1px solid var(--color-bg-4);
		color: var(--color-text-0);
		border-radius: var(--radius-sm);
		padding: var(--space-1) var(--space-2);
		font-size: var(--text-sm);
	}
	.seg-btn.run {
		background: var(--color-accent, var(--color-text-0));
		color: var(--color-bg-0);
		font-weight: var(--weight-semibold);
		border-radius: var(--radius-sm);
	}
	.verdict {
		font-weight: var(--weight-semibold);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		background: var(--color-bg-1);
		border: 1px solid var(--color-bg-4);
		margin-bottom: var(--space-3);
		display: inline-block;
	}
	.verdict.sig {
		border-color: var(--color-accent, var(--color-text-0));
	}
	.ab-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}
	.ab-table th,
	.ab-table td {
		text-align: right;
		padding: var(--space-1) var(--space-3);
		border-bottom: 1px solid var(--color-bg-2);
	}
	.ab-table th:first-child,
	.ab-table td:first-child {
		text-align: left;
		color: var(--color-text-1);
	}
	.ab-note {
		font-size: var(--text-sm);
		color: var(--color-text-2);
		margin-top: var(--space-3);
	}
</style>
