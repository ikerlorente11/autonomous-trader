<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { marketApi } from '$lib/api/endpoints';
	import { createResource } from '$lib/utils/poller.svelte';
	import { money, toNum } from '$lib/utils/format';
	import { marketPollMs } from '$lib/utils/marketHours';
	import { t } from '$lib/i18n';
	import type { WatchlistEntry } from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import SignalScore from '$lib/components/SignalScore.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';

	// Marks are daily closes; poll 60s during the US session, 5 min off-hours (ux §3.3).
	// Self-scheduling tick so the cadence re-evaluates each cycle and adapts across the
	// session open/close boundary (a fixed intervalMs would freeze at the mount-time value).
	const watchlist = createResource(() => marketApi.watchlist(), { immediate: false });
	onMount(() => {
		let timer: ReturnType<typeof setTimeout> | null = null;
		let stopped = false;
		async function tick() {
			if (stopped) return;
			if (typeof document === 'undefined' || !document.hidden) await watchlist.refresh();
			if (stopped) return;
			timer = setTimeout(tick, marketPollMs());
		}
		void tick();
		return () => {
			stopped = true;
			if (timer) clearTimeout(timer);
		};
	});

	let search = $state('');
	let sortKey = $state<'score' | 'symbol' | 'price'>('score');
	let sortDir = $state<'asc' | 'desc'>('desc');

	let newSymbol = $state('');
	let editMsg = $state<string | null>(null);
	let busy = $state(false);

	async function addSymbol() {
		const symbol = newSymbol.trim().toUpperCase();
		if (!symbol) return;
		busy = true;
		editMsg = null;
		try {
			await marketApi.addSymbol({ symbol });
			newSymbol = '';
			await watchlist.refresh();
		} catch (e) {
			editMsg = e instanceof Error ? e.message : t('market.addFailed');
		} finally {
			busy = false;
		}
	}

	async function removeSymbol(symbol: string, ev: Event) {
		ev.stopPropagation();
		busy = true;
		editMsg = null;
		try {
			await marketApi.removeSymbol(symbol);
			await watchlist.refresh();
		} catch (e) {
			editMsg = e instanceof Error ? e.message : t('market.removeFailed');
		} finally {
			busy = false;
		}
	}

	function setSort(key: 'score' | 'symbol' | 'price') {
		if (sortKey === key) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		else {
			sortKey = key;
			sortDir = key === 'symbol' ? 'asc' : 'desc';
		}
	}
	function onSortKey(ev: KeyboardEvent, key: 'score' | 'symbol' | 'price') {
		if (ev.key === 'Enter' || ev.key === ' ') {
			ev.preventDefault();
			setSort(key);
		}
	}
	function openSymbol(symbol: string) {
		void goto(`/market/${symbol}`);
	}
	function onRowKey(ev: KeyboardEvent, symbol: string) {
		if (ev.key === 'Enter' || ev.key === ' ') {
			ev.preventDefault();
			openSymbol(symbol);
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

<h1 class="page-title">{t('market.title')}</h1>

<Card title={t('market.watchlist.title')} caption={t('market.watchlist.caption')} span="full">
	{#snippet actions()}
		<input class="search" bind:value={search} placeholder={t('market.search')} />
		<form class="add" onsubmit={(e) => { e.preventDefault(); void addSymbol(); }}>
			<input class="add-in" bind:value={newSymbol} placeholder={t('market.addPlaceholder')} />
			<button class="add-btn" type="submit" disabled={busy}>{t('market.add')}</button>
		</form>
	{/snippet}
	<Region resource={watchlist} isEmpty={(d) => d.length === 0} emptyMessage={t('market.watchlist.empty')}>
		{#snippet children(d)}
			<div class="tbl-wrap">
				<table class="tbl">
					<thead>
						<tr>
							<th
								class="sortable"
								role="button"
								tabindex="0"
								aria-sort={sortKey === 'symbol' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
								onclick={() => setSort('symbol')}
								onkeydown={(e) => onSortKey(e, 'symbol')}>{t('market.col.symbol')}{arrowFor('symbol')}</th>
							<th>{t('market.col.sector')}</th>
							<th>{t('market.col.assetClass')}</th>
							<th
								class="num sortable"
								role="button"
								tabindex="0"
								aria-sort={sortKey === 'price' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
								onclick={() => setSort('price')}
								onkeydown={(e) => onSortKey(e, 'price')}>{t('market.col.last')}{arrowFor('price')}</th>
							<th
								class="num sortable"
								role="button"
								tabindex="0"
								aria-sort={sortKey === 'score' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
								onclick={() => setSort('score')}
								onkeydown={(e) => onSortKey(e, 'score')}>{t('market.col.score')}{arrowFor('score')}</th>
							<th>{t('market.col.action')}</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each rows(d) as w (w.symbol)}
							<tr
								class="clickable"
								role="button"
								tabindex="0"
								onclick={() => openSymbol(w.symbol)}
								onkeydown={(e) => onRowKey(e, w.symbol)}
							>
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
								<td>
									<button
										class="rm"
										title={t('market.remove')}
										disabled={busy}
										onclick={(e) => removeSymbol(w.symbol, e)}>×</button
									>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{#if rows(d).length === 0}
				<p class="no-match">{t('market.noMatch', { q: search })}</p>
			{/if}
		{/snippet}
	</Region>
</Card>

{#if editMsg}<p class="edit-msg">{editMsg}</p>{/if}

<p class="note">{t('market.note')}</p>

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
	.add {
		display: flex;
		gap: var(--space-2);
	}
	.add-in {
		background: var(--color-bg-1);
		border: 1px solid var(--color-bg-4);
		color: var(--color-text-0);
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-sm);
		min-width: 160px;
	}
	.add-btn {
		background: var(--color-accent, var(--color-text-0));
		color: var(--color-bg-0);
		border: none;
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		cursor: pointer;
	}
	.add-btn:disabled {
		opacity: 0.6;
		cursor: progress;
	}
	.rm {
		background: none;
		border: none;
		color: var(--color-text-2);
		font-size: var(--text-lg);
		line-height: 1;
		cursor: pointer;
		padding: 0 var(--space-2);
	}
	.rm:hover {
		color: var(--color-loss, var(--color-text-0));
	}
	.edit-msg {
		font-size: var(--text-sm);
		color: var(--color-loss, var(--color-text-1));
		margin-bottom: var(--space-3);
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
</style>
