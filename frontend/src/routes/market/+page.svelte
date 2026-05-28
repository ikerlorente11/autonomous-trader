<script lang="ts">
	import { marketApi } from '$lib/api/endpoints';
	import { createResource } from '$lib/utils/poller.svelte';
	import { money, toNum } from '$lib/utils/format';
	import { marketPollMs } from '$lib/utils/marketHours';
	import type { WatchlistEntry } from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import SignalScore from '$lib/components/SignalScore.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';

	// Marks are daily closes; poll 60s during the US session, 5 min off-hours (ux §3.3).
	const watchlist = createResource(() => marketApi.watchlist(), { intervalMs: marketPollMs() });

	let search = $state('');
	let sortKey = $state<'score' | 'symbol' | 'price'>('score');
	let sortDir = $state<'asc' | 'desc'>('desc');

	function setSort(key: 'score' | 'symbol' | 'price') {
		if (sortKey === key) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		else {
			sortKey = key;
			sortDir = key === 'symbol' ? 'asc' : 'desc';
		}
	}

	function rows(d: WatchlistEntry[]): WatchlistEntry[] {
		const q = search.trim().toUpperCase();
		const filtered = q
			? d.filter(
					(w) => w.symbol.toUpperCase().includes(q) || (w.sector ?? '').toUpperCase().includes(q)
				)
			: d;
		const dir = sortDir === 'asc' ? 1 : -1;
		return [...filtered].sort((a, b) => {
			if (sortKey === 'symbol') return a.symbol.localeCompare(b.symbol) * dir;
			const av = toNum(sortKey === 'score' ? a.score : a.latest_price) ?? -Infinity;
			const bv = toNum(sortKey === 'score' ? b.score : b.latest_price) ?? -Infinity;
			return (av - bv) * dir;
		});
	}

	function arrowFor(key: string): string {
		if (sortKey !== key) return '';
		return sortDir === 'asc' ? ' ▲' : ' ▼';
	}
</script>

<h1 class="page-title">Market</h1>

<Card title="Watchlist" caption="Tracked universe · click a row for per-symbol detail" span="full">
	{#snippet actions()}
		<input class="search" bind:value={search} placeholder="Search symbol or sector" />
	{/snippet}
	<Region resource={watchlist} isEmpty={(d) => d.length === 0} emptyMessage="Watchlist is empty — populate it at runtime.">
		{#snippet children(d)}
			<div class="tbl-wrap">
				<table class="tbl">
					<thead>
						<tr>
							<th class="sortable" onclick={() => setSort('symbol')}>Symbol{arrowFor('symbol')}</th>
							<th>Sector</th>
							<th>Asset Class</th>
							<th class="num sortable" onclick={() => setSort('price')}>Last{arrowFor('price')}</th>
							<th class="num sortable" onclick={() => setSort('score')}>Score{arrowFor('score')}</th>
							<th>Action</th>
						</tr>
					</thead>
					<tbody>
						{#each rows(d) as w (w.symbol)}
							<tr class="clickable" onclick={() => (location.href = `/market/${w.symbol}`)}>
								<td class="sym">{w.symbol}</td>
								<td>{w.sector ?? '—'}</td>
								<td class="muted">{w.asset_class ?? '—'}</td>
								<td class="num">{money(w.latest_price)}</td>
								<td class="num">
									{#if w.score !== null}
										<SignalScore score={w.score} width="90px" />
									{:else}—{/if}
								</td>
								<td>{#if w.action}<StatusBadge status={w.action} />{:else}—{/if}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{#if rows(d).length === 0}
				<p class="no-match">No symbols match "{search}".</p>
			{/if}
		{/snippet}
	</Region>
</Card>

<p class="note">
	Daily price change is not exposed by <code>/api/market/watchlist</code> (marks are daily closes).
	Open a symbol for its candlestick history and indicator detail.
</p>

<style>
	.page-title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		margin-bottom: var(--space-5);
	}
	:global(.card) {
		margin-bottom: var(--space-4);
	}
	.search {
		background: var(--color-bg-1);
		border: 1px solid var(--color-bg-4);
		color: var(--color-text-0);
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-sm);
		min-width: 220px;
	}
	.muted {
		color: var(--color-text-2);
	}
	.no-match {
		padding: var(--space-4);
		color: var(--color-text-2);
		font-size: var(--text-sm);
	}
	.note {
		font-size: var(--text-xs);
		color: var(--color-text-2);
	}
	.note code {
		font-family: var(--font-mono);
	}
</style>
