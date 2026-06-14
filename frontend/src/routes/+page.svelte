<script lang="ts">
	import { onDestroy } from 'svelte';
	import { portfolioApi, portfolioByIdApi, algorithmsApi, systemApi, marketApi } from '$lib/api/endpoints';
	import { getActiveMicroPortfolioId } from '$lib/stores/activePortfolio';
	import { createResource } from '$lib/utils/poller.svelte';
	import { money, num, percent, qty, toNum } from '$lib/utils/format';
	import { band, percentMetrics, signedMetrics, metricTooltips } from '$lib/utils/thresholds';
	import { t } from '$lib/i18n';
	import type { BarsRange, NavRange, Position, Quote, SignalEntry } from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import MetricCard from '$lib/components/MetricCard.svelte';
	import PriceChange from '$lib/components/PriceChange.svelte';
	import SignalScore from '$lib/components/SignalScore.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import RangeSelector from '$lib/components/RangeSelector.svelte';
	import NavChart from '$lib/charts/NavChart.svelte';
	import CandlestickChart from '$lib/charts/CandlestickChart.svelte';

	// Daily-batch backend: cards/signals/performance refresh every 5 min (ux §3.1).
	const REFRESH = 300_000;
	const summary = createResource(() => portfolioApi.summary(), { intervalMs: REFRESH });
	const signals = createResource(() => algorithmsApi.signals(20), { intervalMs: REFRESH });
	const performance = createResource(() => portfolioApi.performance(), { intervalMs: REFRESH });

	// Parallel micro track: a compact companion shown alongside the daily portfolio so
	// the header's Micro switcher drives something visible here too. Full detail: /micro.
	const microId = getActiveMicroPortfolioId();
	const microSummary = createResource(
		() => (microId == null ? Promise.resolve(null) : portfolioByIdApi.summary(microId)),
		{ intervalMs: 60_000 }
	);
	const microTrades = createResource(
		() => (microId == null ? Promise.resolve([]) : portfolioByIdApi.trades(microId, 50)),
		{ intervalMs: 60_000 }
	);
	let microPnlPct = $derived.by(() => {
		const s = microSummary.data;
		if (!s) return null;
		const c = toNum(s.contributed_capital);
		const tot = toNum(s.total);
		return c == null || tot == null || c <= 0 ? null : (tot / c - 1) * 100;
	});
	let microTradesToday = $derived.by(() => {
		const today = new Date().toISOString().slice(0, 10);
		return (microTrades.data ?? []).filter((tr) => tr.ts.slice(0, 10) === today).length;
	});

	let navRange = $state<NavRange>('90d');
	const navRanges: readonly NavRange[] = ['7d', '30d', '90d', '1y', 'all'];
	const nav = createResource(() => portfolioApi.nav(navRange), { immediate: false });
	$effect(() => {
		void navRange;
		void nav.refresh();
	});

	// Live valuation: refresh held positions and their prices every 60s so the
	// portfolio value tracks the market intraday (display only — trading stays daily).
	const LIVE_REFRESH = 60_000;
	const positions = createResource(() => portfolioApi.positions(), { intervalMs: LIVE_REFRESH });
	let posSymbols = $derived((positions.data ?? []).map((p) => p.symbol));
	const quotes = createResource(
		() => (posSymbols.length ? marketApi.quotes(posSymbols) : Promise.resolve([] as Quote[])),
		{ intervalMs: LIVE_REFRESH }
	);

	let liveQuoteMap = $derived.by(() => {
		const m = new Map<string, number>();
		for (const q of quotes.data ?? []) {
			const p = toNum(q.price);
			if (p !== null) m.set(q.symbol, p);
		}
		return m;
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
	function onRowKey(ev: KeyboardEvent, sym: string): void {
		if (ev.key === 'Enter' || ev.key === ' ') {
			ev.preventDefault();
			selectInvestment(sym);
		}
	}

	// Per-holding figures: what was spent (qty × avg cost) vs current value
	// (qty × live price, falling back to last stored price).
	function priceOf(p: Position): number | null {
		return liveQuoteMap.get(p.symbol) ?? toNum(p.current_price);
	}
	function investedOf(p: Position): number {
		return (toNum(p.qty) ?? 0) * (toNum(p.avg_cost) ?? 0);
	}
	function valueOf(p: Position): number | null {
		const price = priceOf(p);
		return price === null ? null : (toNum(p.qty) ?? 0) * price;
	}
	function pnlOf(p: Position): number | null {
		const v = valueOf(p);
		return v === null ? null : v - investedOf(p);
	}
	function pctOf(p: Position): number | null {
		const inv = investedOf(p);
		const g = pnlOf(p);
		return g === null || inv === 0 ? null : (g / inv) * 100;
	}
	let totals = $derived.by(() => {
		const ps = positions.data ?? [];
		let invested = 0;
		let value = 0;
		let hasValue = false;
		for (const p of ps) {
			invested += investedOf(p);
			const v = valueOf(p);
			if (v !== null) {
				value += v;
				hasValue = true;
			}
		}
		const g = hasValue ? value - invested : null;
		const pct = g !== null && invested !== 0 ? (g / invested) * 100 : null;
		return { invested, value: hasValue ? value : null, pnl: g, pct };
	});

	// Headline return: total P&L over net contributed capital.
	let totalPct = $derived.by(() => {
		const s = summary.data;
		if (!s) return null;
		const base = toNum(s.contributed_capital);
		const pnl = toNum(s.total_pnl);
		if (base === null || pnl === null || base === 0) return null;
		return (pnl / base) * 100;
	});

	// Performance metrics, rendered in a stable returns/risk/trades order.
	function metricRows(group: Record<string, number> | undefined): [string, number][] {
		if (!group) return [];
		return Object.entries(group);
	}
	function fmtMetric(key: string, value: number): string {
		if (percentMetrics.has(key)) return percent(value * 100, signedMetrics.has(key));
		return num(value, 2);
	}

	// Manual pipeline trigger (the daily run, on demand).
	let running = $state(false);
	let refreshing = $state(false);
	let runMsg = $state<string | null>(null);
	let destroyed = false;
	onDestroy(() => {
		destroyed = true;
	});

	function refreshAll(): void {
		void summary.refresh();
		void nav.refresh();
		void signals.refresh();
		void performance.refresh();
		void positions.refresh();
		void quotes.refresh();
	}

	async function runNow() {
		running = true;
		runMsg = null;
		// Remember the last NAV-job run so we can tell when *this* pipeline finishes.
		let navBefore: string | null = null;
		try {
			try {
				const before = await systemApi.status();
				navBefore =
					before.jobs.find((j) => j.job === 'update_portfolio_nav')?.last_run_at ?? null;
			} catch {
				navBefore = null;
			}
			const r = await systemApi.run();
			runMsg = r.detail;
		} catch (e) {
			runMsg = e instanceof Error ? e.message : t('action.runFailed');
			running = false;
			return;
		}
		running = false;
		// The run executes in the background, so the POST returns before any data
		// changes. Poll the pipeline's final job until it records a fresh run, then
		// pull the new numbers in — the page updates itself, no manual reload.
		refreshing = true;
		for (let i = 0; i < 20; i++) {
			await new Promise((res) => setTimeout(res, 3000));
			if (destroyed) return;
			try {
				const st = await systemApi.status();
				const navNow =
					st.jobs.find((j) => j.job === 'update_portfolio_nav')?.last_run_at ?? null;
				if (navNow && navNow !== navBefore) {
					refreshAll();
					refreshing = false;
					return;
				}
			} catch {
				// transient — keep polling
			}
		}
		refreshAll();
		refreshing = false;
	}

	function topBuys(d: SignalEntry[]): SignalEntry[] {
		return d
			.filter((s) => s.action === 'buy')
			.sort((a, b) => (toNum(b.score) ?? 0) - (toNum(a.score) ?? 0))
			.slice(0, 5);
	}
</script>

<div class="page-head">
	<h1 class="page-title">{t('home.title')}</h1>
	<div class="run">
		<button class="run-btn" onclick={runNow} disabled={running || refreshing}>
			{running ? t('action.starting') : refreshing ? t('action.refreshing') : t('action.runNow')}
		</button>
		{#if runMsg}<span class="run-msg">{runMsg}</span>{/if}
	</div>
</div>

<section class="cards">
	<MetricCard label="NAV" value={summary.data ? money(summary.data.total) : '—'} emphasis />
	<MetricCard label={t('home.metric.cash')} value={summary.data ? money(summary.data.cash) : '—'} />
	<MetricCard label={t('home.metric.positionsValue')} value={summary.data ? money(summary.data.equity) : '—'} />
	<MetricCard
		label={t('home.metric.totalPnl')}
		value={summary.data ? money(summary.data.total_pnl, true) : '—'}
		deltaClass={summary.data ? ((toNum(summary.data.total_pnl) ?? 0) >= 0 ? 'gain' : 'loss') : 'flat'}
	/>
	<MetricCard
		label={t('home.metric.return')}
		value={totalPct !== null ? percent(totalPct) : '—'}
		deltaClass={summary.data ? ((toNum(summary.data.total_pnl) ?? 0) >= 0 ? 'gain' : 'loss') : 'flat'}
	/>
</section>

{#if microId != null}
	<Card title={t('home.micro.title')} caption={t('home.micro.caption')} span="full">
		{#snippet actions()}
			<a class="preset" href="/micro">{t('home.micro.detail')}</a>
		{/snippet}
		<div class="micro-strip">
			<div class="ms-item">
				<span class="ms-label">{t('home.micro.who')}</span>
				<span class="ms-value">{microSummary.data?.name ?? '—'}</span>
			</div>
			<div class="ms-item">
				<span class="ms-label">NAV</span>
				<span class="ms-value">{microSummary.data ? money(microSummary.data.total) : '—'}</span>
			</div>
			<div class="ms-item">
				<span class="ms-label">{t('home.micro.pnl')}</span>
				<span class="ms-value" class:gain={(microPnlPct ?? 0) > 0} class:loss={(microPnlPct ?? 0) < 0}>
					{microPnlPct !== null ? percent(microPnlPct) : '—'}
				</span>
			</div>
			<div class="ms-item">
				<span class="ms-label">{t('home.micro.openPos')}</span>
				<span class="ms-value">{microSummary.data?.positions_count ?? '—'}</span>
			</div>
			<div class="ms-item">
				<span class="ms-label">{t('home.micro.tradesToday')}</span>
				<span class="ms-value">{microTradesToday}</span>
			</div>
		</div>
	</Card>
{/if}

<Card
	title={selectedSymbol ? t('home.chart.priceTitle', { symbol: selectedSymbol }) : t('home.chart.navTitle')}
	caption={selectedSymbol ? t('home.chart.priceCaption') : t('home.chart.navCaption')}
	span="full"
>
	{#snippet actions()}
		{#if selectedSymbol}
			<RangeSelector
				options={['30d', '90d', '1y']}
				value={selRange}
				onChange={(v) => (selRange = v as BarsRange)}
			/>
			<a class="preset" href={`/market/${selectedSymbol}`}>{t('home.chart.detail')}</a>
			<button type="button" class="preset" onclick={() => (selectedSymbol = null)}>{t('home.chart.backToPortfolio')}</button>
		{:else}
			<RangeSelector
				options={navRanges}
				value={navRange}
				labels={{ all: t('common.all') }}
				onChange={(v) => (navRange = v as NavRange)}
			/>
		{/if}
	{/snippet}
	{#if selectedSymbol}
		<Region resource={selBars} isEmpty={(d) => d.length === 0} emptyMessage={t('symbol.noPriceData')}>
			{#snippet children(d)}
				<CandlestickChart bars={d} />
			{/snippet}
		</Region>
	{:else}
		<Region resource={nav} isEmpty={(d) => d.length === 0} emptyMessage={t('home.navEmpty')}>
			{#snippet children(d)}
				<NavChart series={d} height={320} />
			{/snippet}
		</Region>
	{/if}
</Card>

<Card title={t('home.positions.title')} caption={t('home.positions.caption')} span="full">
	<Region resource={positions} isEmpty={(d) => d.length === 0} emptyMessage={t('home.positions.empty')}>
		{#snippet children(d)}
			<div class="tbl-wrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>{t('home.positions.symbol')}</th>
							<th class="num">{t('home.positions.qty')}</th>
							<th class="num">{t('home.positions.invested')}</th>
							<th class="num">{t('home.positions.value')}</th>
							<th class="num">{t('home.positions.pnl')}</th>
						</tr>
					</thead>
					<tbody>
						{#each d as p (p.symbol)}
							<tr
								class="clickable"
								role="button"
								tabindex="0"
								onclick={() => selectInvestment(p.symbol)}
								onkeydown={(e) => onRowKey(e, p.symbol)}
								title={t('home.positions.rowHint')}
							>
								<td class="sym">{p.symbol}</td>
								<td class="num">{qty(p.qty)}</td>
								<td class="num">{money(investedOf(p))}</td>
								<td class="num">{money(valueOf(p))}</td>
								<td class="num"><PriceChange value={pnlOf(p)} pct={pctOf(p)} /></td>
							</tr>
						{/each}
					</tbody>
					<tfoot>
						<tr class="total-row">
							<td>{t('home.positions.total')}</td>
							<td class="num"></td>
							<td class="num">{money(totals.invested)}</td>
							<td class="num">{money(totals.value)}</td>
							<td class="num"><PriceChange value={totals.pnl} pct={totals.pct} /></td>
						</tr>
					</tfoot>
				</table>
			</div>
			<p class="hint">{t('home.positions.hint')}</p>
		{/snippet}
	</Region>
</Card>

<Card title={t('home.signals.title')} caption={t('home.signals.caption')}>
	<Region resource={signals} isEmpty={(d) => topBuys(d).length === 0} emptyMessage={t('home.signals.empty')}>
		{#snippet children(d)}
			<div class="tbl-wrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>{t('home.signals.symbol')}</th>
							<th>{t('home.signals.action')}</th>
							<th class="num">{t('home.signals.score')}</th>
						</tr>
					</thead>
					<tbody>
						{#each topBuys(d) as s (s.symbol)}
							<tr
								class="clickable"
								role="button"
								tabindex="0"
								onclick={() => selectInvestment(s.symbol)}
								onkeydown={(e) => onRowKey(e, s.symbol)}
							>
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

<Card title={t('home.perf.title')} caption={t('home.perf.caption')} span="full">
	<Region
		resource={performance}
		isEmpty={(m) =>
			metricRows(m.returns).length === 0 &&
			metricRows(m.risk).length === 0 &&
			metricRows(m.trades).length === 0}
		emptyMessage={t('home.perf.empty')}
	>
		{#snippet children(m)}
			<div class="metric-groups">
				{#each [['home.perf.group.returns', m.returns], ['home.perf.group.risk', m.risk], ['home.perf.group.trades', m.trades]] as [groupKey, group] (groupKey)}
					<div class="metric-group">
						<h3>{t(groupKey as string)}</h3>
						<dl>
							{#each metricRows(group as Record<string, number>) as [key, value] (key)}
								<dt title={metricTooltips[key] ?? ''}>{t(`metric.${key}`)}</dt>
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
	.cards {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: var(--space-4);
		margin-bottom: var(--space-4);
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
	.total-row td {
		border-top: 1px solid var(--color-bg-4);
		font-weight: var(--weight-semibold);
		color: var(--color-text-0);
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
	.micro-strip {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
		gap: var(--space-3);
	}
	.ms-item {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.ms-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-2);
	}
	.ms-value {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-base);
		color: var(--color-text-0);
		font-weight: var(--weight-semibold);
	}
	.ms-value.gain {
		color: var(--color-gain);
	}
	.ms-value.loss {
		color: var(--color-loss);
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
