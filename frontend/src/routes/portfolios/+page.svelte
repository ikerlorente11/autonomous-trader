<script lang="ts">
	import { portfoliosApi } from '$lib/api/endpoints';
	import { getActivePortfolioId, setActivePortfolioId } from '$lib/stores/activePortfolio';
	import { createResource } from '$lib/utils/poller.svelte';
	import { formatDate } from '$lib/utils/format';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';

	const portfolios = createResource(() => portfoliosApi.list(), { intervalMs: 300_000 });

	let activeId = $derived(getActivePortfolioId() ?? portfolios.data?.[0]?.id ?? null);

	let newName = $state('');
	let newDeposit = $state('');
	let busy = $state(false);
	let msg = $state<string | null>(null);

	function fail(e: unknown): void {
		msg = e instanceof Error ? e.message : 'Action failed.';
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
		const name = prompt('New portfolio name', current);
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

	async function remove(id: number, name: string) {
		if (!confirm(`Delete "${name}" and all its trades, positions and history? This cannot be undone.`))
			return;
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
		const raw = prompt(`${kind === 'deposit' ? 'Deposit' : 'Withdraw'} amount (EUR)`);
		if (raw === null) return;
		const amount = Number(raw);
		if (!Number.isFinite(amount) || amount <= 0) {
			msg = 'Amount must be a positive number.';
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

<h1 class="page-title">Portfolios</h1>

<Card title="New portfolio" caption="Create a portfolio with an initial budget (editable later)">
	<form class="new" onsubmit={(e) => { e.preventDefault(); void create(); }}>
		<input class="in" bind:value={newName} placeholder="Name (e.g. Cartera 5000)" />
		<input class="in" bind:value={newDeposit} type="number" min="0" step="any" placeholder="Initial budget €" />
		<button class="btn" type="submit" disabled={busy}>Create</button>
	</form>
</Card>

{#if msg}<p class="msg">{msg}</p>{/if}

<Card title="Your portfolios" caption="Switch, fund, rename or delete" span="full">
	<Region resource={portfolios} isEmpty={(d) => d.length === 0} emptyMessage="No portfolios yet.">
		{#snippet children(d)}
			<div class="tbl-wrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>Name</th>
							<th>Created</th>
							<th>State</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each d as p (p.id)}
							<tr class:current={p.id === activeId}>
								<td class="sym">{p.name}</td>
								<td>{formatDate(p.created_at)}</td>
								<td>
									{#if p.id === activeId}<StatusBadge status="active" />{:else}<span class="muted">—</span>{/if}
								</td>
								<td class="actions">
									{#if p.id !== activeId}
										<button class="link" onclick={() => setActivePortfolioId(p.id)}>Select</button>
									{/if}
									<button class="link" disabled={busy} onclick={() => move(p.id, 'deposit')}>Deposit</button>
									<button class="link" disabled={busy} onclick={() => move(p.id, 'withdraw')}>Withdraw</button>
									<button class="link" disabled={busy} onclick={() => rename(p.id, p.name)}>Rename</button>
									<button class="link danger" disabled={busy} onclick={() => remove(p.id, p.name)}>Delete</button>
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
