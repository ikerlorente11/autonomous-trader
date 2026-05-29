<script lang="ts">
	import { page } from '$app/stores';
	import { marketApi, tradesApi } from '$lib/api/endpoints';
	import { createResource } from '$lib/utils/poller.svelte';
	import { changeClass, formatDate, money, num, qty } from '$lib/utils/format';
	import type { BarsRange } from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import MetricCard from '$lib/components/MetricCard.svelte';
	import SignalScore from '$lib/components/SignalScore.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import RangeSelector from '$lib/components/RangeSelector.svelte';
	import CandlestickChart from '$lib/charts/CandlestickChart.svelte';
	import VolumeChart from '$lib/charts/VolumeChart.svelte';

	let symbol = $derived((($page.params.symbol as string | undefined) ?? '').toUpperCase());

	let barsRange = $state<BarsRange>('90d');
	const barsRanges: readonly BarsRange[] = ['30d', '90d', '1y'];
	let showMA = $state(false);

	const bars = createResource(() => marketApi.bars(symbol, barsRange), { immediate: false });
	const trades = createResource(() => tradesApi.list({ symbol, limit: 20 }), { immediate: false });
	// No per-symbol score endpoint exists; pull this symbol's score from the watchlist.
	const watchlist = createResource(() => marketApi.watchlist(), { immediate: false });

	$effect(() => {
		void symbol;
		void barsRange;
		if (symbol) void bars.refresh();
	});
	$effect(() => {
		void symbol;
		if (symbol) {
			void trades.refresh();
			void watchlist.refresh();
		}
	});

	let entry = $derived(watchlist.data?.find((w) => w.symbol === symbol) ?? null);
	let lastClose = $derived.by(() => {
		const b = bars.data;
		const last = b && b.length ? b[b.length - 1] : null;
		return last ? last.close : null;
	});
</script>

<div class="head">
	<a class="back" href="/market">← Watchlist</a>
	<h1 class="page-title">{symbol}</h1>
	{#if entry?.sector}<span class="sector">{entry.sector}</span>{/if}
	{#if lastClose}<span class="last">{money(lastClose)}</span>{/if}
</div>

<Card span="full">
	{#snippet actions()}
		<label class="ma-toggle">
			<input type="checkbox" bind:checked={showMA} /> MA20 / MA50
		</label>
		<RangeSelector
			options={barsRanges}
			value={barsRange}
			onChange={(v) => (barsRange = v as BarsRange)}
		/>
	{/snippet}
	<Region resource={bars} isEmpty={(d) => d.length === 0} emptyMessage="No price data for this symbol.">
		{#snippet children(d)}
			<CandlestickChart bars={d} {showMA} />
			<div class="vol"><VolumeChart bars={d} /></div>
		{/snippet}
	</Region>
</Card>

<div class="grid-2">
	<Card title="Signal" caption="Latest composite score from the watchlist">
		<Region resource={watchlist}>
			{#snippet children(_)}
				{#if entry}
					<div class="composite">
						<MetricCard label="Composite Score" value={num(entry.score, 1)} />
					</div>
					<div class="sig-row">
						<span class="sig-label">Action</span>
						{#if entry.action}<StatusBadge status={entry.action} />{:else}<span>—</span>{/if}
					</div>
					<div class="sig-row">
						<span class="sig-label">Score</span>
						<SignalScore score={entry.score} width="160px" />
					</div>
					{#if entry.ts}<p class="as-of">As of {formatDate(entry.ts)}</p>{/if}
				{:else}
					<p class="as-of">{symbol} is not on the active watchlist.</p>
				{/if}
			{/snippet}
		</Region>
	</Card>

	<Card title="Recent Trades" caption={`${symbol} only`}>
		<Region resource={trades} isEmpty={(d) => d.length === 0} emptyMessage="No trades for this symbol.">
			{#snippet children(d)}
				<div class="tbl-wrap">
					<table class="tbl">
						<thead>
							<tr>
								<th>Date</th>
								<th>Side</th>
								<th class="num">Qty</th>
								<th class="num">Price</th>
								<th>Status</th>
							</tr>
						</thead>
						<tbody>
							{#each d as t (t.id)}
								<tr>
									<td>{formatDate(t.ts)}</td>
									<td class={changeClass(t.side === 'buy' ? 1 : -1)}>{t.side.toUpperCase()}</td>
									<td class="num">{qty(t.qty)}</td>
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
	.head {
		display: flex;
		align-items: baseline;
		gap: var(--space-4);
		margin-bottom: var(--space-5);
		flex-wrap: wrap;
	}
	.back {
		font-size: var(--text-sm);
		color: var(--color-text-1);
	}
	.page-title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		font-family: var(--font-mono);
	}
	.sector {
		color: var(--color-text-2);
		font-size: var(--text-sm);
	}
	.last {
		font-family: var(--font-mono);
		color: var(--color-text-0);
		font-size: var(--text-lg);
		margin-left: auto;
	}
	:global(.card) {
		margin-bottom: var(--space-4);
	}
	.vol {
		margin-top: var(--space-3);
	}
	.ma-toggle {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--color-text-1);
	}
	.grid-2 {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-4);
	}
	.composite {
		margin-bottom: var(--space-4);
	}
	.sig-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		margin-bottom: var(--space-3);
	}
	.sig-label {
		font-size: var(--text-sm);
		color: var(--color-text-1);
	}
	.as-of {
		margin-top: var(--space-3);
		font-size: var(--text-xs);
		color: var(--color-text-2);
	}
	@media (max-width: 900px) {
		.grid-2 {
			grid-template-columns: 1fr;
		}
	}
</style>
