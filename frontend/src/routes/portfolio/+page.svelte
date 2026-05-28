<script lang="ts">
	import { portfolioApi } from '$lib/api/endpoints';
	import { createResource } from '$lib/utils/poller.svelte';
	import { money, num, percent, toNum } from '$lib/utils/format';
	import {
		band,
		metricLabels,
		metricTooltips,
		percentMetrics,
		signedMetrics
	} from '$lib/utils/thresholds';
	import type { NavRange, Position } from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import MetricCard from '$lib/components/MetricCard.svelte';
	import PriceChange from '$lib/components/PriceChange.svelte';
	import RangeSelector from '$lib/components/RangeSelector.svelte';
	import NavChart from '$lib/charts/NavChart.svelte';

	const REFRESH = 300_000;
	const summary = createResource(() => portfolioApi.summary(), { intervalMs: REFRESH });
	const positions = createResource(() => portfolioApi.positions(), { intervalMs: REFRESH });
	const performance = createResource(() => portfolioApi.performance(), { intervalMs: REFRESH });

	let navRange = $state<NavRange>('90d');
	const navRanges: readonly NavRange[] = ['7d', '30d', '90d', '1y', 'all'];
	const nav = createResource(() => portfolioApi.nav(navRange), { immediate: false });
	$effect(() => {
		void navRange;
		void nav.refresh();
	});

	function pnl(p: Position): number | null {
		return toNum(p.unrealized_pnl);
	}
	function pctChange(p: Position): number | null {
		const cur = toNum(p.current_price);
		const cost = toNum(p.avg_cost);
		if (cur === null || cost === null || cost === 0) return null;
		return ((cur - cost) / cost) * 100;
	}
	function marketValue(p: Position): number | null {
		const cur = toNum(p.current_price);
		const q = toNum(p.qty);
		if (cur === null || q === null) return null;
		return cur * q;
	}

	// Render the three metric dicts (returns/risk/trades) in a stable order.
	function metricRows(group: Record<string, number> | undefined): [string, number][] {
		if (!group) return [];
		return Object.entries(group);
	}
	function fmtMetric(key: string, value: number): string {
		if (percentMetrics.has(key)) return percent(value * 100, signedMetrics.has(key));
		return num(value, 2);
	}
</script>

<h1 class="page-title">Portfolio</h1>

<section class="cards">
	<MetricCard label="NAV" value={summary.data ? money(summary.data.total) : '—'} emphasis />
	<MetricCard label="Cash" value={summary.data ? money(summary.data.cash) : '—'} />
	<MetricCard label="Positions Value" value={summary.data ? money(summary.data.equity) : '—'} />
	<MetricCard
		label="Total P&L"
		value={summary.data ? money(summary.data.total_pnl, true) : '—'}
		deltaClass={summary.data ? (toNum(summary.data.total_pnl) ?? 0) >= 0 ? 'gain' : 'loss' : 'flat'}
	/>
	<MetricCard
		label="Unrealized P&L"
		value={summary.data ? money(summary.data.unrealized_pnl, true) : '—'}
		deltaClass={summary.data ? (toNum(summary.data.unrealized_pnl) ?? 0) >= 0 ? 'gain' : 'loss' : 'flat'}
	/>
</section>

<Card title="NAV" caption="Portfolio value vs SPY benchmark" span="full">
	{#snippet actions()}
		<RangeSelector options={navRanges} value={navRange} onChange={(v) => (navRange = v as NavRange)} />
	{/snippet}
	<Region resource={nav} isEmpty={(d) => d.length === 0} emptyMessage="No NAV history for this range.">
		{#snippet children(d)}
			<NavChart series={d} height={320} />
		{/snippet}
	</Region>
</Card>

<Card title="Open Positions" caption="Current holdings and unrealized P&L" span="full">
	<Region resource={positions} isEmpty={(d) => d.length === 0} emptyMessage="No open positions.">
		{#snippet children(d)}
			<div class="tbl-wrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>Symbol</th>
							<th class="num">Qty</th>
							<th class="num">Avg Cost</th>
							<th class="num">Current</th>
							<th class="num">Mkt Value</th>
							<th class="num">Unrealized P&L</th>
							<th class="num">% Change</th>
						</tr>
					</thead>
					<tbody>
						{#each d as p (p.symbol)}
							<tr class="clickable" onclick={() => (location.href = `/market/${p.symbol}`)}>
								<td class="sym">{p.symbol}</td>
								<td class="num">{num(p.qty, 0)}</td>
								<td class="num">{money(p.avg_cost)}</td>
								<td class="num">{money(p.current_price)}</td>
								<td class="num">{money(marketValue(p))}</td>
								<td class="num"><PriceChange value={pnl(p)} /></td>
								<td class="num"><PriceChange pct={pctChange(p)} /></td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/snippet}
	</Region>
</Card>

<Card title="Performance Metrics" caption="Returns, risk, and trade statistics" span="full">
	<Region resource={performance}>
		{#snippet children(m)}
			<div class="metric-groups">
				{#each [['Returns', m.returns], ['Risk', m.risk], ['Trades', m.trades]] as [groupName, group] (groupName)}
					<div class="metric-group">
						<h3>{groupName}</h3>
						<dl>
							{#each metricRows(group as Record<string, number>) as [key, value] (key)}
								<dt title={metricTooltips[key] ?? ''}>{metricLabels[key] ?? key}</dt>
								<dd class={band(key, value)}>{fmtMetric(key, value)}</dd>
							{/each}
						</dl>
					</div>
				{/each}
			</div>
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
	.cards {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: var(--space-4);
		margin-bottom: var(--space-4);
	}
	.metric-groups {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-6);
	}
	.metric-group h3 {
		font-size: var(--text-sm);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-2);
		margin-bottom: var(--space-3);
	}
	dl {
		display: grid;
		grid-template-columns: 1fr max-content;
		gap: var(--space-2) var(--space-4);
	}
	dt {
		color: var(--color-text-1);
		font-size: var(--text-sm);
	}
	dd {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-sm);
		text-align: right;
		color: var(--color-text-0);
	}
	dd.gain {
		color: var(--color-gain);
	}
	dd.loss {
		color: var(--color-loss);
	}
	dd.warn {
		color: var(--color-warn);
	}
	@media (max-width: 1100px) {
		.cards {
			grid-template-columns: repeat(3, 1fr);
		}
	}
	@media (max-width: 900px) {
		.cards {
			grid-template-columns: repeat(2, 1fr);
		}
		.metric-groups {
			grid-template-columns: 1fr;
		}
	}
</style>
