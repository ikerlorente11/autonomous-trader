<script lang="ts">
	import { portfolioApi, algorithmsApi, tradesApi } from '$lib/api/endpoints';
	import { createResource } from '$lib/utils/poller.svelte';
	import { money, num, percentFrac, changeClass, formatDateTime, formatDate, toNum } from '$lib/utils/format';
	import { band } from '$lib/utils/thresholds';
	import type { PortfolioSnapshot, SignalEntry, TradeRecord } from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import MetricCard from '$lib/components/MetricCard.svelte';
	import PriceChange from '$lib/components/PriceChange.svelte';
	import SignalScore from '$lib/components/SignalScore.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import NavChart from '$lib/charts/NavChart.svelte';

	// Daily-batch backend: cards/NAV/signals/trades refresh every 5 min (ux §3.1).
	const REFRESH = 300_000;
	const summary = createResource(() => portfolioApi.summary(), { intervalMs: REFRESH });
	const performance = createResource(() => portfolioApi.performance(), { intervalMs: REFRESH });
	const nav = createResource(() => portfolioApi.nav('90d'), { intervalMs: REFRESH });
	const signals = createResource(() => algorithmsApi.signals(20), { intervalMs: REFRESH });
	const trades = createResource(() => tradesApi.list({ limit: 10 }), { intervalMs: REFRESH });

	// "Daily" P&L from the last two NAV snapshots (no intraday feed exists).
	let dayDelta = $derived.by(() => {
		const s = nav.data;
		if (!s || s.length < 2) return { abs: null as number | null, pct: null as number | null };
		const last = toNum(s[s.length - 1].total);
		const prev = toNum(s[s.length - 2].total);
		if (last === null || prev === null || prev === 0) return { abs: null, pct: null };
		return { abs: last - prev, pct: ((last - prev) / prev) * 100 };
	});

	let risk = $derived(performance.data?.risk ?? {});
	let tradeStats = $derived(performance.data?.trades ?? {});
	let returns = $derived(performance.data?.returns ?? {});

	function topBuys(d: SignalEntry[]): SignalEntry[] {
		return d
			.filter((s) => s.action === 'buy')
			.sort((a, b) => (toNum(b.score) ?? 0) - (toNum(a.score) ?? 0))
			.slice(0, 5);
	}
	function navOk(d: PortfolioSnapshot[]): boolean {
		return d.length > 0;
	}
	function recent(d: TradeRecord[]): TradeRecord[] {
		return d.slice(0, 10);
	}
</script>

<h1 class="page-title">Dashboard</h1>

<section class="hero">
	<div class="hero-main">
		<span class="hero-label">Portfolio Value</span>
		<span class="hero-value">{summary.data ? money(summary.data.total) : '—'}</span>
	</div>
	<div class="hero-delta">
		<span class="hero-label">Today</span>
		<PriceChange value={dayDelta.abs} pct={dayDelta.pct} size="lg" />
	</div>
	<div class="hero-delta">
		<span class="hero-label">Total P&L</span>
		<PriceChange value={summary.data ? toNum(summary.data.total_pnl) : null} size="lg" />
	</div>
</section>

<section class="cards">
	<MetricCard
		label="Sharpe (90d)"
		value={num(risk.sharpe, 2)}
		band={band('sharpe', risk.sharpe)}
		tooltip="Annualized risk-adjusted return."
	/>
	<MetricCard
		label="Max Drawdown"
		value={percentFrac(risk.max_drawdown)}
		band={band('max_drawdown', risk.max_drawdown)}
		tooltip="Largest peak-to-trough NAV decline."
	/>
	<MetricCard
		label="Win Rate"
		value={percentFrac(tradeStats.win_rate, false)}
		band={band('win_rate', tradeStats.win_rate)}
		tooltip="Share of closed round-trips that were profitable."
	/>
	<MetricCard
		label="Open Positions"
		value={summary.data ? String(summary.data.positions_count) : '—'}
		tooltip="Number of currently held positions."
	/>
</section>

<Card title="NAV Performance" caption="Portfolio value vs SPY benchmark · last 90 days" span="full">
	<Region resource={nav} isEmpty={(d) => !navOk(d)} emptyMessage="No NAV history yet — run the daily NAV snapshot job.">
		{#snippet children(d)}
			<NavChart series={d} height={320} />
		{/snippet}
	</Region>
</Card>

<div class="grid-2">
	<Card title="Today's Top Signals" caption="Highest-scoring buy signals">
		<Region resource={signals} isEmpty={(d) => topBuys(d).length === 0} emptyMessage="No buy signals today.">
			{#snippet children(d)}
				<div class="tbl-wrap">
					<table class="tbl">
						<thead>
							<tr>
								<th>Symbol</th>
								<th>Action</th>
								<th class="num">Score</th>
							</tr>
						</thead>
						<tbody>
							{#each topBuys(d) as s (s.symbol)}
								<tr class="clickable" onclick={() => (location.href = `/market/${s.symbol}`)}>
									<td class="sym">{s.symbol}</td>
									<td><StatusBadge status={s.action} /></td>
									<td class="num"><SignalScore score={s.score} width="90px" /></td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/snippet}
		</Region>
	</Card>

	<Card title="Recent Trades" caption="Last 10 executions">
		<Region resource={trades} isEmpty={(d) => d.length === 0} emptyMessage="No trades executed yet.">
			{#snippet children(d)}
				<div class="tbl-wrap">
					<table class="tbl">
						<thead>
							<tr>
								<th>Date</th>
								<th>Symbol</th>
								<th>Side</th>
								<th class="num">Qty</th>
								<th class="num">Price</th>
								<th>Status</th>
							</tr>
						</thead>
						<tbody>
							{#each recent(d) as t (t.id)}
								<tr>
									<td>{formatDate(t.ts)}</td>
									<td class="sym">{t.symbol}</td>
									<td class={changeClass(t.side === 'buy' ? 1 : -1)}>{t.side.toUpperCase()}</td>
									<td class="num">{num(t.qty, 0)}</td>
									<td class="num">{money(t.price)}</td>
									<td><StatusBadge status={t.status} /></td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/snippet}
		</Region>
	</Card>
</div>

<style>
	.page-title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		margin-bottom: var(--space-5);
	}
	:global(.card) {
		margin-bottom: var(--space-4);
	}
	.hero {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-6);
		background: var(--color-bg-2);
		border: 1px solid var(--color-bg-4);
		border-radius: var(--radius-lg);
		padding: var(--space-5);
		margin-bottom: var(--space-4);
	}
	.hero-main {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.hero-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-2);
	}
	.hero-value {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-2xl);
		font-weight: var(--weight-semibold);
		color: var(--color-text-0);
	}
	.hero-delta {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.cards {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-4);
		margin-bottom: var(--space-4);
	}
	.grid-2 {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-4);
	}
	@media (max-width: 900px) {
		.cards {
			grid-template-columns: repeat(2, 1fr);
		}
		.grid-2 {
			grid-template-columns: 1fr;
		}
	}
</style>
