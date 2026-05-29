<script lang="ts">
	import { tradesApi, type TradeFilters } from '$lib/api/endpoints';
	import { createResource } from '$lib/utils/poller.svelte';
	import { changeClass, formatDateTime, money, qty } from '$lib/utils/format';
	import type { TradeRecord } from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';

	// Server-side filters: symbol, start, end, limit. Side is filtered client-side
	// (backend /api/trades has no side param).
	let symbolInput = $state('');
	let startInput = $state('');
	let endInput = $state('');
	let sideFilter = $state<'' | 'buy' | 'sell'>('');
	let applied = $state<TradeFilters>({ limit: 200 });

	const trades = createResource(() => tradesApi.list(applied), { immediate: false });
	$effect(() => {
		void applied;
		void trades.refresh();
	});

	function apply() {
		const f: TradeFilters = { limit: 200 };
		if (symbolInput.trim()) f.symbol = symbolInput.trim().toUpperCase();
		if (startInput) f.start = new Date(startInput).toISOString();
		if (endInput) f.end = new Date(endInput).toISOString();
		applied = f;
	}
	function reset() {
		symbolInput = '';
		startInput = '';
		endInput = '';
		sideFilter = '';
		applied = { limit: 200 };
	}

	function rows(data: TradeRecord[]): TradeRecord[] {
		return sideFilter ? data.filter((t) => t.side === sideFilter) : data;
	}

	let expanded = $state<number | null>(null);
	function toggle(id: number) {
		expanded = expanded === id ? null : id;
	}
</script>

<h1 class="page-title">Trades</h1>

<Card title="Filters" span="full">
	<form class="filters" onsubmit={(e) => { e.preventDefault(); apply(); }}>
		<label>
			<span>Symbol</span>
			<input bind:value={symbolInput} placeholder="e.g. AAPL" />
		</label>
		<label>
			<span>From</span>
			<input type="date" bind:value={startInput} />
		</label>
		<label>
			<span>To</span>
			<input type="date" bind:value={endInput} />
		</label>
		<label>
			<span>Side</span>
			<select bind:value={sideFilter}>
				<option value="">All</option>
				<option value="buy">Buy</option>
				<option value="sell">Sell</option>
			</select>
		</label>
		<div class="filter-actions">
			<button type="submit" class="btn primary">Apply</button>
			<button type="button" class="btn" onclick={reset}>Reset</button>
		</div>
	</form>
</Card>

<Card title="Trade Ledger" caption="Click a row to see the signal that triggered it" span="full">
	<Region resource={trades} isEmpty={(d) => rows(d).length === 0} emptyMessage="No trades match these filters.">
		{#snippet children(d)}
			<div class="tbl-wrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>Timestamp</th>
							<th>Symbol</th>
							<th>Side</th>
							<th class="num">Qty</th>
							<th class="num">Price</th>
							<th class="num">Total</th>
							<th>Status</th>
							<th>Strategy</th>
						</tr>
					</thead>
					<tbody>
						{#each rows(d) as t (t.id)}
							<tr class="clickable" onclick={() => toggle(t.id)}>
								<td>{formatDateTime(t.ts)}</td>
								<td class="sym">{t.symbol}</td>
								<td class={changeClass(t.side === 'buy' ? 1 : -1)}>{t.side.toUpperCase()}</td>
								<td class="num">{qty(t.qty)}</td>
								<td class="num">{money(t.price)}</td>
								<td class="num">
									{#if t.price}{money(Number(t.qty) * Number(t.price))}{:else}—{/if}
								</td>
								<td><StatusBadge status={t.status} /></td>
								<td class="strategy">{t.strategy_version ?? '—'}</td>
							</tr>
							{#if expanded === t.id}
								<tr class="detail-row">
									<td colspan="8">
										<div class="detail">
											<span class="detail-label">Order #{t.id} — triggering reason</span>
											<p class="reason">{t.reason ?? 'No reason recorded for this order.'}</p>
										</div>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
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
	.filters {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-4);
	}
	.filters label {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-xs);
		color: var(--color-text-2);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.filters input,
	.filters select {
		background: var(--color-bg-1);
		border: 1px solid var(--color-bg-4);
		color: var(--color-text-0);
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-base);
		text-transform: none;
	}
	.filter-actions {
		display: flex;
		gap: var(--space-2);
	}
	.btn {
		border: 1px solid var(--color-bg-4);
		background: var(--color-bg-3);
		color: var(--color-text-0);
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-4);
		font-size: var(--text-sm);
	}
	.btn.primary {
		background: var(--color-accent-bg);
		color: var(--color-accent);
		border-color: transparent;
	}
	.btn:hover {
		filter: brightness(1.1);
	}
	.strategy {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--color-text-2);
	}
	.detail-row td {
		background: var(--color-bg-1);
	}
	.detail {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-2) 0;
	}
	.detail-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-2);
	}
	.reason {
		font-size: var(--text-sm);
		color: var(--color-text-1);
		white-space: normal;
	}
	.gain {
		color: var(--color-gain);
	}
	.loss {
		color: var(--color-loss);
	}
</style>
