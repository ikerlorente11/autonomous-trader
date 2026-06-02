<script lang="ts">
	import { tradesApi, type TradeFilters } from '$lib/api/endpoints';
	import { createResource } from '$lib/utils/poller.svelte';
	import { changeClass, formatDateTime, money, qty } from '$lib/utils/format';
	import { t } from '$lib/i18n';
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
	function onRowKey(ev: KeyboardEvent, id: number) {
		if (ev.key === 'Enter' || ev.key === ' ') {
			ev.preventDefault();
			toggle(id);
		}
	}
</script>

<h1 class="page-title">{t('trades.title')}</h1>

<Card title={t('trades.filters.title')} span="full">
	<form class="filters" onsubmit={(e) => { e.preventDefault(); apply(); }}>
		<label>
			<span>{t('trades.filters.symbol')}</span>
			<input bind:value={symbolInput} placeholder={t('trades.filters.symbolPlaceholder')} />
		</label>
		<label>
			<span>{t('trades.filters.from')}</span>
			<input type="date" bind:value={startInput} />
		</label>
		<label>
			<span>{t('trades.filters.to')}</span>
			<input type="date" bind:value={endInput} />
		</label>
		<label>
			<span>{t('trades.filters.side')}</span>
			<select bind:value={sideFilter}>
				<option value="">{t('common.all')}</option>
				<option value="buy">{t('trades.side.buy')}</option>
				<option value="sell">{t('trades.side.sell')}</option>
			</select>
		</label>
		<div class="filter-actions">
			<button type="submit" class="btn primary">{t('trades.filters.apply')}</button>
			<button type="button" class="btn" onclick={reset}>{t('trades.filters.reset')}</button>
		</div>
	</form>
</Card>

<Card title={t('trades.ledger.title')} caption={t('trades.ledger.caption')} span="full">
	<Region resource={trades} isEmpty={(d) => rows(d).length === 0} emptyMessage={t('trades.ledger.empty')}>
		{#snippet children(d)}
			<div class="tbl-wrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>{t('trades.col.timestamp')}</th>
							<th>{t('trades.col.symbol')}</th>
							<th>{t('trades.col.side')}</th>
							<th class="num">{t('trades.col.qty')}</th>
							<th class="num">{t('trades.col.price')}</th>
							<th class="num">{t('trades.col.total')}</th>
							<th>{t('trades.col.status')}</th>
							<th>{t('trades.col.strategy')}</th>
						</tr>
					</thead>
					<tbody>
						{#each rows(d) as tr (tr.id)}
							<tr
								class="clickable"
								role="button"
								tabindex="0"
								aria-expanded={expanded === tr.id}
								onclick={() => toggle(tr.id)}
								onkeydown={(e) => onRowKey(e, tr.id)}
							>
								<td>{formatDateTime(tr.ts)}</td>
								<td class="sym">{tr.symbol}</td>
								<td class={changeClass(tr.side === 'buy' ? 1 : -1)}>{tr.side.toUpperCase()}</td>
								<td class="num">{qty(tr.qty)}</td>
								<td class="num">{money(tr.price)}</td>
								<td class="num">
									{#if tr.price}{money(Number(tr.qty) * Number(tr.price))}{:else}—{/if}
								</td>
								<td><StatusBadge status={tr.status} /></td>
								<td class="strategy">{tr.strategy_version ?? '—'}</td>
							</tr>
							{#if expanded === tr.id}
								<tr class="detail-row">
									<td colspan="8">
										<div class="detail">
											<span class="detail-label">{t('trades.detail.label', { id: tr.id })}</span>
											<p class="reason">{tr.reason ?? t('trades.detail.noReason')}</p>
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
