<script lang="ts">
	import { portfolioApi, algorithmsApi, tradesApi, systemApi, marketApi } from '$lib/api/endpoints';
	import { createResource } from '$lib/utils/poller.svelte';
	import { formatDate, money, num, percentFrac, qty, toNum } from '$lib/utils/format';
	import { band } from '$lib/utils/thresholds';
	import type { BarsRange, SignalEntry, TradeRecord } from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import MetricCard from '$lib/components/MetricCard.svelte';
	import PriceChange from '$lib/components/PriceChange.svelte';
	import SignalScore from '$lib/components/SignalScore.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import RangeSelector from '$lib/components/RangeSelector.svelte';
	import NavChart from '$lib/charts/NavChart.svelte';
	import CandlestickChart from '$lib/charts/CandlestickChart.svelte';

	// Daily-batch backend: cards/NAV/signals refresh every 5 min (ux §3.1).
	const REFRESH = 300_000;
	const summary = createResource(() => portfolioApi.summary(), { intervalMs: REFRESH });
	const performance = createResource(() => portfolioApi.performance(), { intervalMs: REFRESH });
	const nav = createResource(() => portfolioApi.nav('90d'), { intervalMs: REFRESH });
	const signals = createResource(() => algorithmsApi.signals(20), { intervalMs: REFRESH });

	// Investments over a chosen date range (default today, UTC), with presets.
	function todayStr(): string {
		return new Date().toISOString().slice(0, 10);
	}
	function daysAgoStr(days: number): string {
		const d = new Date();
		d.setUTCDate(d.getUTCDate() - days);
		return d.toISOString().slice(0, 10);
	}
	let invFrom = $state(todayStr());
	let invTo = $state(todayStr());
	function setRange(days: number): void {
		invTo = todayStr();
		invFrom = days <= 1 ? todayStr() : daysAgoStr(days - 1);
	}
	const investments = createResource(
		() => tradesApi.list({ start: `${invFrom}T00:00:00Z`, end: `${invTo}T23:59:59Z`, limit: 200 }),
		{ immediate: false }
	);
	$effect(() => {
		void invFrom;
		void invTo;
		void investments.refresh();
	});

	// Live valuation: refresh held positions and their prices every 60s so the
	// portfolio value tracks the market intraday (display only — trading stays daily).
	const LIVE_REFRESH = 60_000;
	const positions = createResource(() => portfolioApi.positions(), { intervalMs: LIVE_REFRESH });
	let posSymbols = $derived((positions.data ?? []).map((p) => p.symbol));
	const quotes = createResource(() => marketApi.quotes(posSymbols), {
		immediate: false,
		intervalMs: LIVE_REFRESH
	});
	$effect(() => {
		if (posSymbols.length) void quotes.refresh();
	});

	let liveQuoteMap = $derived.by(() => {
		const m = new Map<string, number>();
		for (const q of quotes.data ?? []) {
			const p = toNum(q.price);
			if (p !== null) m.set(q.symbol, p);
		}
		return m;
	});
	let liveInvested = $derived.by(() => {
		const ps = positions.data;
		if (!ps || ps.length === 0) return null;
		let sum = 0;
		for (const p of ps) {
			const q = toNum(p.qty) ?? 0;
			const price = liveQuoteMap.get(p.symbol) ?? toNum(p.current_price) ?? 0;
			sum += q * price;
		}
		return sum;
	});
	let liveCash = $derived(summary.data ? toNum(summary.data.cash) : null);
	let liveTotal = $derived.by(() =>
		liveInvested === null || liveCash === null ? null : liveCash + liveInvested
	);
	let liveChange = $derived.by(() => {
		const base = summary.data ? toNum(summary.data.contributed_capital) : null;
		if (liveTotal === null || base === null) return { val: null as number | null, pct: null as number | null };
		const val = liveTotal - base;
		return { val, pct: base ? (val / base) * 100 : null };
	});

	// Inline price chart: clicking an investment swaps the big card to that symbol.
	let selectedSymbol = $state<string | null>(null);
	let selRange = $state<BarsRange>('90d');
	const selBars = createResource(() => marketApi.bars(selectedSymbol as string, selRange), {
		immediate: false
	});
	$effect(() => {
		void selRange;
		if (selectedSymbol) void selBars.refresh();
	});
	function selectInvestment(sym: string): void {
		selectedSymbol = sym;
		if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' });
	}

	// Total change vs net contributed capital — the headline "how much up/down".
	let totalPct = $derived.by(() => {
		const s = summary.data;
		if (!s) return null;
		const base = toNum(s.contributed_capital);
		const pnl = toNum(s.total_pnl);
		if (base === null || pnl === null || base === 0) return null;
		return (pnl / base) * 100;
	});

	let risk = $derived(performance.data?.risk ?? {});
	let tradeStats = $derived(performance.data?.trades ?? {});

	// Manual pipeline trigger (the daily run, on demand).
	let running = $state(false);
	let runMsg = $state<string | null>(null);
	async function runNow() {
		running = true;
		runMsg = null;
		try {
			const r = await systemApi.run();
			runMsg = r.detail;
		} catch (e) {
			runMsg = e instanceof Error ? e.message : 'Could not start the run.';
		} finally {
			running = false;
		}
	}

	function amountInvested(t: TradeRecord): number | null {
		const q = toNum(t.qty);
		const p = toNum(t.price);
		if (q === null || p === null) return null;
		return q * p;
	}
	function topBuys(d: SignalEntry[]): SignalEntry[] {
		return d
			.filter((s) => s.action === 'buy')
			.sort((a, b) => (toNum(b.score) ?? 0) - (toNum(a.score) ?? 0))
			.slice(0, 5);
	}
</script>

<div class="page-head">
	<h1 class="page-title">Dashboard</h1>
	<div class="run">
		<button class="run-btn" onclick={runNow} disabled={running}>
			{running ? 'Starting…' : 'Run now'}
		</button>
		{#if runMsg}<span class="run-msg">{runMsg}</span>{/if}
	</div>
</div>

<section class="hero">
	<div class="hero-block">
		<span class="hero-label">Capital aportado</span>
		<span class="hero-sub">{summary.data ? money(summary.data.contributed_capital) : '—'}</span>
	</div>
	<div class="hero-block">
		<span class="hero-label">Current value {#if liveTotal !== null}<span class="live-dot" title="Precios en vivo (cada 60s)">● en vivo</span>{/if}</span>
		<span class="hero-value">{liveTotal !== null ? money(liveTotal) : summary.data ? money(summary.data.total) : '—'}</span>
		{#if liveInvested !== null && liveCash !== null}
			<span class="hero-split">Cash {money(liveCash)} · Invertido {money(liveInvested)}</span>
		{:else if summary.data}
			<span class="hero-split">Cash {money(summary.data.cash)} · Invertido {money(summary.data.equity)}</span>
		{/if}
	</div>
	<div class="hero-block">
		<span class="hero-label">Change</span>
		<PriceChange
			value={liveChange.val ?? (summary.data ? toNum(summary.data.total_pnl) : null)}
			pct={liveChange.pct ?? totalPct}
			size="lg"
		/>
	</div>
</section>

<Card
	title={selectedSymbol ? `${selectedSymbol} · precio` : 'Value over time'}
	caption={selectedSymbol
		? 'Evolución del precio de tu inversión'
		: 'Portfolio value vs SPY benchmark · last 90 days'}
	span="full"
>
	{#snippet actions()}
		{#if selectedSymbol}
			<RangeSelector
				options={['30d', '90d', '1y']}
				value={selRange}
				onChange={(v) => (selRange = v as BarsRange)}
			/>
			<a class="preset" href={`/market/${selectedSymbol}`}>Detalle</a>
			<button type="button" class="preset" onclick={() => (selectedSymbol = null)}>← Cartera</button>
		{/if}
	{/snippet}
	{#if selectedSymbol}
		<Region resource={selBars} isEmpty={(d) => d.length === 0} emptyMessage="No price data for this symbol.">
			{#snippet children(d)}
				<CandlestickChart bars={d} />
			{/snippet}
		</Region>
	{:else}
		<Region resource={nav} isEmpty={(d) => d.length === 0} emptyMessage="No history yet — run the pipeline to take the first NAV snapshot.">
			{#snippet children(d)}
				<NavChart series={d} height={320} />
			{/snippet}
		</Region>
	{/if}
</Card>

<Card title="Investments" span="full">
	{#snippet actions()}
		<div class="date-pick">
			<button type="button" class="preset" onclick={() => setRange(1)}>Hoy</button>
			<button type="button" class="preset" onclick={() => setRange(7)}>7d</button>
			<button type="button" class="preset" onclick={() => setRange(30)}>30d</button>
			<label>Desde <input type="date" bind:value={invFrom} max={invTo} /></label>
			<label>Hasta <input type="date" bind:value={invTo} max={todayStr()} /></label>
		</div>
	{/snippet}
	<Region resource={investments} isEmpty={(d) => d.length === 0} emptyMessage="No investments in this range.">
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
							<th class="num">Invested</th>
							<th>Status</th>
						</tr>
					</thead>
					<tbody>
						{#each d as t (t.id)}
							<tr class="clickable" onclick={() => selectInvestment(t.symbol)} title="Ver evolución del precio">
								<td>{formatDate(t.ts)}</td>
								<td class="sym">{t.symbol}</td>
								<td>{t.side.toUpperCase()}</td>
								<td class="num">{qty(t.qty)}</td>
								<td class="num">{money(t.price)}</td>
								<td class="num">{money(amountInvested(t))}</td>
								<td><StatusBadge status={t.status} /></td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="hint">Click a row to see the price trend of what you invested in.</p>
		{/snippet}
	</Region>
</Card>

<section class="cards">
	<MetricCard
		label="Sharpe (90d)"
		value={num(risk.sharpe, 2)}
		band={band('sharpe', risk.sharpe)}
		tooltip="Return earned for the risk taken. Higher is better; above 1 is good."
	/>
	<MetricCard
		label="Max Drawdown"
		value={percentFrac(risk.max_drawdown)}
		band={band('max_drawdown', risk.max_drawdown)}
		tooltip="Worst drop from a peak so far. Closer to 0% is better."
	/>
	<MetricCard
		label="Win Rate"
		value={percentFrac(tradeStats.win_rate, false)}
		band={band('win_rate', tradeStats.win_rate)}
		tooltip="Share of closed trades that made money."
	/>
	<MetricCard
		label="Open Positions"
		value={summary.data ? String(summary.data.positions_count) : '—'}
		tooltip="How many holdings you have right now."
	/>
</section>

<Card title="Today's Top Signals" caption="Highest-scoring buy candidates">
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
							<tr class="clickable" onclick={() => selectInvestment(s.symbol)}>
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

<style>
	.page-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		margin-bottom: var(--space-5);
		flex-wrap: wrap;
	}
	.page-title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
	}
	.run {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.run-btn {
		background: var(--color-accent, var(--color-text-0));
		color: var(--color-bg-0);
		border: none;
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-4);
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		cursor: pointer;
	}
	.run-btn:disabled {
		opacity: 0.6;
		cursor: progress;
	}
	.run-msg {
		font-size: var(--text-xs);
		color: var(--color-text-2);
		max-width: 360px;
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
	.hero-block {
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
	.hero-sub {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-lg);
		color: var(--color-text-1);
	}
	.hero-split {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-sm);
		color: var(--color-text-2);
		margin-top: var(--space-1);
	}
	.live-dot {
		text-transform: none;
		letter-spacing: 0;
		color: var(--color-up, #34d399);
		margin-left: var(--space-2);
	}
	.date-pick {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--color-text-1);
	}
	.date-pick label {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.date-pick input {
		background: var(--color-bg-1);
		border: 1px solid var(--color-bg-4);
		color: var(--color-text-0);
		border-radius: var(--radius-md);
		padding: var(--space-1) var(--space-2);
		font-size: var(--text-sm);
	}
	.preset {
		background: var(--color-bg-1);
		border: 1px solid var(--color-bg-4);
		color: var(--color-text-1);
		border-radius: var(--radius-md);
		padding: var(--space-1) var(--space-3);
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.preset:hover {
		color: var(--color-text-0);
		border-color: var(--color-text-2);
	}
	.hint {
		padding: var(--space-3) 0 0;
		font-size: var(--text-xs);
		color: var(--color-text-2);
	}
	.cards {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-4);
		margin-bottom: var(--space-4);
	}
	@media (max-width: 900px) {
		.cards {
			grid-template-columns: repeat(2, 1fr);
		}
	}
</style>
