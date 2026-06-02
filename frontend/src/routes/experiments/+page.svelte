<script lang="ts">
	import { algorithmsApi } from '$lib/api/endpoints';
	import { createResource } from '$lib/utils/poller.svelte';
	import { formatDate } from '$lib/utils/format';
	import { t } from '$lib/i18n';
	import type { ExperimentEntry } from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import Region from '$lib/components/Region.svelte';

	// Experiment Tracker comparison data is not fully wired (CLAUDE.md / ux §3.5).
	// The live /api/algorithms/experiments returns run metadata only — no metrics
	// envelope yet — so we render the runs and a not-ready notice for comparison.
	const experiments = createResource(() => algorithmsApi.experiments());

	let selected = $state<Set<number>>(new Set());
	function toggle(id: number) {
		const next = new Set(selected);
		if (next.has(id)) next.delete(id);
		else if (next.size < 2) next.add(id);
		selected = next;
	}

	function chosen(rows: ExperimentEntry[]): ExperimentEntry[] {
		return rows.filter((r) => selected.has(r.id));
	}
	function configEntries(c: Record<string, unknown> | null): [string, string][] {
		if (!c) return [];
		return Object.entries(c).map(([k, v]) => [k, JSON.stringify(v)]);
	}
</script>

<h1 class="page-title">{t('experiments.title')}</h1>

<Card title={t('experiments.runs.title')} caption={t('experiments.runs.caption')} span="full">
	<Region
		resource={experiments}
		isEmpty={(d) => d.length === 0}
		notReadyOn404
		notReadyMessage={t('experiments.runs.notReady')}
		emptyMessage={t('experiments.runs.empty')}
	>
		{#snippet children(d)}
			<div class="tbl-wrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>{t('experiments.col.compare')}</th>
							<th>{t('experiments.col.version')}</th>
							<th>{t('experiments.col.started')}</th>
							<th>{t('experiments.col.ended')}</th>
							<th>{t('experiments.col.notes')}</th>
						</tr>
					</thead>
					<tbody>
						{#each d as e (e.id)}
							<tr>
								<td>
									<input
										type="checkbox"
										checked={selected.has(e.id)}
										disabled={!selected.has(e.id) && selected.size >= 2}
										onchange={() => toggle(e.id)}
										aria-label={t('experiments.compareAria', { version: e.strategy_version })}
									/>
								</td>
								<td class="sym">{e.strategy_version}</td>
								<td>{formatDate(e.started_at)}</td>
								<td>{e.ended_at ? formatDate(e.ended_at) : t('common.active')}</td>
								<td class="notes">{e.notes ?? '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/snippet}
	</Region>
</Card>

{#if experiments.data && selected.size > 0}
	<Card title={t('experiments.compare.title')} caption={t('experiments.compare.caption')} span="full">
		<div class="compare">
			{#each chosen(experiments.data) as e (e.id)}
				<div class="compare-col">
					<h3>{e.strategy_version}</h3>
					<dl>
						<dt>{t('experiments.compare.started')}</dt>
						<dd>{formatDate(e.started_at)}</dd>
						<dt>{t('experiments.compare.ended')}</dt>
						<dd>{e.ended_at ? formatDate(e.ended_at) : t('common.active')}</dd>
						{#each configEntries(e.config) as [k, v] (k)}
							<dt>{k}</dt>
							<dd>{v}</dd>
						{/each}
					</dl>
				</div>
			{/each}
		</div>
		<p class="note">{t('experiments.compare.note')}</p>
	</Card>
{/if}

<style>
	.page-title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		margin-bottom: var(--space-5);
	}
	:global(.card) {
		margin-bottom: var(--space-4);
	}
	.notes {
		color: var(--color-text-1);
		font-size: var(--text-sm);
		white-space: normal;
	}
	.compare {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--space-5);
	}
	.compare-col h3 {
		font-family: var(--font-mono);
		margin-bottom: var(--space-3);
	}
	dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: var(--space-2) var(--space-4);
	}
	dt {
		color: var(--color-text-2);
		font-size: var(--text-sm);
	}
	dd {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--color-text-0);
	}
	.note {
		margin-top: var(--space-4);
		font-size: var(--text-xs);
		color: var(--color-text-2);
	}
	@media (max-width: 700px) {
		.compare {
			grid-template-columns: 1fr;
		}
	}
</style>
