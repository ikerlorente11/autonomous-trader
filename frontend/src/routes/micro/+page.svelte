<script lang="ts">
	import { portfolioByIdApi, systemApi } from '$lib/api/endpoints';
	import { getActiveMicroPortfolioId } from '$lib/stores/activePortfolio';
	import { createResource } from '$lib/utils/poller.svelte';
	import { money, percent, qty, toNum } from '$lib/utils/format';
	import { t } from '$lib/i18n';
	import type { NavRange } from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import NavChart from '$lib/charts/NavChart.svelte';

	// Micro is an intraday track: positions turn over within the session and flatten
	// before the close. Poll faster than the daily dashboard.
	const REFRESH = 60_000;
	const microId = getActiveMicroPortfolioId();

	const summary = createResource(
		() => (microId == null ? Promise.resolve(null) : portfolioByIdApi.summary(microId)),
		{ intervalMs: REFRESH }
	);
	const positions = createResource(
		() => (microId == null ? Promise.resolve([]) : portfolioByIdApi.positions(microId)),
		{ intervalMs: REFRESH }
	);
	const trades = createResource(
		() => (microId == null ? Promise.resolve([]) : portfolioByIdApi.trades(microId, 50)),
		{ intervalMs: REFRESH }
	);
	const system = createResource(() => systemApi.status(), { intervalMs: REFRESH });

	let navRange = $state<NavRange>('30d');
	const nav = createResource(
		() => (microId == null ? Promise.resolve([]) : portfolioByIdApi.nav(microId, navRange)),
		{ immediate: false }
	);
	$effect(() => {
		void navRange;
		if (microId != null) void nav.refresh();
	});

	const microEnabled = $derived(system.data?.micro_enabled ?? null);
	const pnlPct = $derived.by(() => {
		const s = summary.data;
		if (!s) return null;
		const contrib = toNum(s.contributed_capital);
		const total = toNum(s.total);
		if (contrib == null || total == null || contrib <= 0) return null;
		return total / contrib - 1;
	});

	// Today's micro fills (entries + exits within the session).
	const todayTrades = $derived.by(() => {
		const today = new Date().toISOString().slice(0, 10);
		return (trades.data ?? []).filter((tr) => tr.ts.slice(0, 10) === today);
	});
</script>

<h1 class="page-title">{t('micro.title')}</h1>

<Card title={t('micro.about.title')} span="full">
	<p>{@html t('micro.about.text')}</p>
	{#if microEnabled === false}
		<p class="warn">{t('micro.inactive')}</p>
	{/if}
</Card>

{#if microId == null}
	<Card span="full">
		<p class="empty">{t('micro.none')}</p>
	</Card>
{:else}
	<div class="metrics">
		<div class="metric">
			<span class="m-label">{t('micro.nav')}</span>
			<span class="m-value">{summary.data ? money(summary.data.total) : '—'}</span>
		</div>
		<div class="metric">
			<span class="m-label">{t('micro.pnl')}</span>
			<span class="m-value">{pnlPct == null ? '—' : percent(pnlPct)}</span>
		</div>
		<div class="metric">
			<span class="m-label">{t('micro.cash')}</span>
			<span class="m-value">{summary.data ? money(summary.data.cash) : '—'}</span>
		</div>
		<div class="metric">
			<span class="m-label">{t('micro.openPos')}</span>
			<span class="m-value">{summary.data?.positions_count ?? '—'}</span>
		</div>
		<div class="metric">
			<span class="m-label">{t('micro.tradesToday')}</span>
			<span class="m-value">{todayTrades.length}</span>
		</div>
	</div>

	<Card title={t('micro.navChart')} span="full">
		<Region resource={nav} isEmpty={() => (nav.data ?? []).length === 0} emptyMessage={t('micro.noData')}>
			{#snippet children()}
				<NavChart series={nav.data ?? []} height={300} />
			{/snippet}
		</Region>
	</Card>

	<Card title={t('micro.positions')} span="full">
		<Region resource={positions} isEmpty={() => (positions.data ?? []).length === 0} emptyMessage={t('micro.flat')}>
			{#snippet children()}
				<table class="tbl">
					<thead>
						<tr><th>{t('micro.col.symbol')}</th><th>{t('micro.col.qty')}</th><th>{t('micro.col.avg')}</th><th>{t('micro.col.price')}</th><th>{t('micro.col.upnl')}</th></tr>
					</thead>
					<tbody>
						{#each positions.data ?? [] as p (p.symbol)}
							<tr>
								<td class="sym">{p.symbol}</td>
								<td>{qty(p.qty)}</td>
								<td>{money(p.avg_cost)}</td>
								<td>{p.current_price ? money(p.current_price) : '—'}</td>
								<td>{p.unrealized_pnl ? money(p.unrealized_pnl) : '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/snippet}
		</Region>
	</Card>

	<Card title={t('micro.recentTrades')} span="full">
		<Region resource={trades} isEmpty={() => (trades.data ?? []).length === 0} emptyMessage={t('micro.noTrades')}>
			{#snippet children()}
				<table class="tbl">
					<thead>
						<tr><th>{t('micro.col.time')}</th><th>{t('micro.col.symbol')}</th><th>{t('micro.col.side')}</th><th>{t('micro.col.qty')}</th><th>{t('micro.col.price')}</th></tr>
					</thead>
					<tbody>
						{#each trades.data ?? [] as tr (tr.id)}
							<tr>
								<td>{new Date(tr.ts).toLocaleString()}</td>
								<td class="sym">{tr.symbol}</td>
								<td class:buy={tr.side === 'buy'} class:sell={tr.side === 'sell'}>{tr.side}</td>
								<td>{qty(tr.qty)}</td>
								<td>{tr.price ? money(tr.price) : '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/snippet}
		</Region>
	</Card>
{/if}

<style>
	.page-title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		margin-bottom: var(--space-5);
	}
	.metrics {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}
	.metric {
		background: var(--color-bg-0);
		border: 1px solid var(--color-bg-4);
		border-radius: var(--radius-md);
		padding: var(--space-3);
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.m-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-2);
	}
	.m-value {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-lg);
		color: var(--color-text-0);
		font-weight: var(--weight-semibold);
	}
	.tbl {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}
	.tbl th,
	.tbl td {
		text-align: right;
		padding: var(--space-1) var(--space-3);
		border-bottom: 1px solid var(--color-bg-2);
	}
	.tbl th:first-child,
	.tbl td:first-child,
	.tbl .sym {
		text-align: left;
	}
	.buy {
		color: var(--status-ok);
	}
	.sell {
		color: var(--status-critical);
	}
	.warn {
		color: var(--status-warn);
		margin-top: var(--space-2);
	}
	.empty {
		color: var(--color-text-2);
	}
</style>
