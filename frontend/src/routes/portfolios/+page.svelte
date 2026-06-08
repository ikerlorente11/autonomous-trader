<script lang="ts">
	import { portfoliosApi, strategiesApi } from '$lib/api/endpoints';
	import { getActivePortfolioId, setActivePortfolioId } from '$lib/stores/activePortfolio';
	import { createResource } from '$lib/utils/poller.svelte';
	import { formatDate } from '$lib/utils/format';
	import { t } from '$lib/i18n';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';

	const portfolios = createResource(() => portfoliosApi.list(), { intervalMs: 300_000 });
	const strategies = createResource(() => strategiesApi.list(), { intervalMs: 600_000 });

	let activeId = $derived(getActivePortfolioId() ?? portfolios.data?.[0]?.id ?? null);

	let newName = $state('');
	let newDeposit = $state('');
	let busy = $state(false);
	let msg = $state<string | null>(null);

	function fail(e: unknown): void {
		msg = e instanceof Error ? e.message : t('common.actionFailed');
	}

	async function create() {
		const name = newName.trim();
		if (!name) return;
		const deposit = Number(newDeposit);
		busy = true;
		msg = null;
		try {
			await portfoliosApi.create({ name, initial_deposit: Number.isFinite(deposit) ? deposit : 0 });
			newName = '';
			newDeposit = '';
			await portfolios.refresh();
		} catch (e) {
			fail(e);
		} finally {
			busy = false;
		}
	}

	async function rename(id: number, current: string) {
		const name = prompt(t('portfolios.prompt.rename'), current);
		if (!name || !name.trim()) return;
		busy = true;
		msg = null;
		try {
			await portfoliosApi.rename(id, name.trim());
			await portfolios.refresh();
		} catch (e) {
			fail(e);
		} finally {
			busy = false;
		}
	}

	async function setVersion(id: number, value: string) {
		busy = true;
		msg = null;
		try {
			await portfoliosApi.setStrategy(id, value === '' ? null : value);
			await portfolios.refresh();
		} catch (e) {
			fail(e);
		} finally {
			busy = false;
		}
	}

	async function remove(id: number, name: string) {
		if (!confirm(t('portfolios.prompt.delete', { name }))) return;
		busy = true;
		msg = null;
		try {
			await portfoliosApi.remove(id);
			await portfolios.refresh();
		} catch (e) {
			fail(e);
		} finally {
			busy = false;
		}
	}

	async function move(id: number, kind: 'deposit' | 'withdraw') {
		const raw = prompt(t(kind === 'deposit' ? 'portfolios.prompt.deposit' : 'portfolios.prompt.withdraw'));
		if (raw === null) return;
		const amount = Number(raw);
		if (!Number.isFinite(amount) || amount <= 0) {
			msg = t('portfolios.error.amount');
			return;
		}
		busy = true;
		msg = null;
		try {
			if (kind === 'deposit') await portfoliosApi.deposit(id, amount);
			else await portfoliosApi.withdraw(id, amount);
			await portfolios.refresh();
		} catch (e) {
			fail(e);
		} finally {
			busy = false;
		}
	}
</script>

<h1 class="page-title">{t('portfolios.title')}</h1>

<Card title={t('portfolios.new.title')} caption={t('portfolios.new.caption')}>
	<form class="new" onsubmit={(e) => { e.preventDefault(); void create(); }}>
		<input class="in" bind:value={newName} placeholder={t('portfolios.new.namePlaceholder')} />
		<input class="in" bind:value={newDeposit} type="number" min="0" step="any" placeholder={t('portfolios.new.depositPlaceholder')} />
		<button class="btn" type="submit" disabled={busy}>{t('portfolios.new.create')}</button>
	</form>
</Card>

{#if msg}<p class="msg">{msg}</p>{/if}

<Card title={t('portfolios.list.title')} caption={t('portfolios.list.caption')} span="full">
	<Region resource={portfolios} isEmpty={(d) => d.length === 0} emptyMessage={t('portfolios.list.empty')}>
		{#snippet children(d)}
			<div class="tbl-wrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>{t('portfolios.col.name')}</th>
							<th>{t('portfolios.col.version')}</th>
							<th>{t('portfolios.col.created')}</th>
							<th>{t('portfolios.col.state')}</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each d as p (p.id)}
							<tr class:current={p.id === activeId}>
								<td class="sym">{p.name}</td>
								<td>
									<select
										class="ver"
										disabled={busy}
										value={p.strategy_label ?? ''}
										onchange={(e) => setVersion(p.id, e.currentTarget.value)}
									>
										<option value="">{t('portfolios.version.base')}</option>
										{#each strategies.data ?? [] as s (s.label)}
											<option value={s.label}>{s.label}</option>
										{/each}
									</select>
								</td>
								<td>{formatDate(p.created_at)}</td>
								<td>
									{#if p.id === activeId}<StatusBadge status="active" />{:else}<span class="muted">—</span>{/if}
								</td>
								<td class="actions">
									{#if p.id !== activeId}
										<button class="link" onclick={() => setActivePortfolioId(p.id)}>{t('portfolios.action.select')}</button>
									{/if}
									<button class="link" disabled={busy} onclick={() => move(p.id, 'deposit')}>{t('portfolios.action.deposit')}</button>
									<button class="link" disabled={busy} onclick={() => move(p.id, 'withdraw')}>{t('portfolios.action.withdraw')}</button>
									<button class="link" disabled={busy} onclick={() => rename(p.id, p.name)}>{t('portfolios.action.rename')}</button>
									<button class="link danger" disabled={busy} onclick={() => remove(p.id, p.name)}>{t('portfolios.action.delete')}</button>
								</td>
							</tr>
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
	.new {
		display: flex;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	.in {
		background: var(--color-bg-1);
		border: 1px solid var(--color-bg-4);
		color: var(--color-text-0);
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-sm);
		min-width: 180px;
	}
	.ver {
		background: var(--color-bg-1);
		border: 1px solid var(--color-bg-4);
		color: var(--color-text-0);
		border-radius: var(--radius-md);
		padding: var(--space-1) var(--space-2);
		font-size: var(--text-sm);
	}
	.ver:disabled {
		opacity: 0.6;
		cursor: progress;
	}
	.btn {
		background: var(--color-accent, var(--color-text-0));
		color: var(--color-bg-0);
		border: none;
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-4);
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		cursor: pointer;
	}
	.btn:disabled {
		opacity: 0.6;
		cursor: progress;
	}
	.msg {
		font-size: var(--text-sm);
		color: var(--color-loss, var(--color-text-1));
		margin-bottom: var(--space-3);
	}
	.actions {
		display: flex;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	.link {
		background: none;
		border: none;
		color: var(--color-accent, var(--color-text-1));
		font-size: var(--text-sm);
		cursor: pointer;
		padding: 0;
	}
	.link.danger {
		color: var(--color-loss, var(--color-text-1));
	}
	.link:disabled {
		opacity: 0.5;
		cursor: progress;
	}
	.current {
		background: var(--color-accent-bg);
	}
	.muted {
		color: var(--color-text-2);
	}
</style>
