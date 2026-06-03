<script lang="ts">
	import { portfolioApi } from '$lib/api/endpoints';
	import { createResource } from '$lib/utils/poller.svelte';
	import { changeClass, money, percent } from '$lib/utils/format';
	import { t } from '$lib/i18n';
	import type {
		AttributionAxis,
		AttributionReport,
		FpaPeriod,
		PeriodPerformance,
		SectorAttributionItem,
		SymbolAttributionItem
	} from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import MetricCard from '$lib/components/MetricCard.svelte';
	import RangeSelector from '$lib/components/RangeSelector.svelte';
	import Region from '$lib/components/Region.svelte';

	const REFRESH = 300_000; // daily-batch backend: 5 min is plenty (ux §3.1)
	const PERIODS: readonly FpaPeriod[] = ['wtd', 'mtd', 'ytd', 'inception'];
	const AXES: readonly AttributionAxis[] = ['symbol', 'sector'];

	const periods = createResource(() => portfolioApi.performancePeriods(), { intervalMs: REFRESH });

	let selectedPeriod = $state<FpaPeriod>('mtd');
	let axis = $state<AttributionAxis>('symbol');

	const attribution = createResource(
		() => portfolioApi.attribution(selectedPeriod, axis),
		{ immediate: false }
	);
	$effect(() => {
		void selectedPeriod;
		void axis;
		void attribution.refresh();
	});

	let periodLabels = $derived<Record<FpaPeriod, string>>({
		wtd: t('reports.period.wtd'),
		mtd: t('reports.period.mtd'),
		ytd: t('reports.period.ytd'),
		inception: t('reports.period.inception')
	});
	let axisLabels = $derived<Record<AttributionAxis, string>>({
		symbol: t('reports.axis.symbol'),
		sector: t('reports.axis.sector')
	});

	type AttributionRow = SymbolAttributionItem | SectorAttributionItem;
	function rows(d: AttributionReport): AttributionRow[] {
		return d.axis === 'sector' ? d.sectors : d.symbols;
	}
	function rowName(r: AttributionRow): string {
		return 'symbol' in r ? r.symbol : r.sector;
	}
</script>

<h1 class="page-title">{t('reports.title')}</h1>

<Card title={t('reports.periods.title')} caption={t('reports.periods.caption')} span="full">
	<Region resource={periods} skeleton isEmpty={(d) => d.length === 0} emptyMessage={t('reports.empty')}>
		{#snippet children(d: PeriodPerformance[])}
			<div class="tiles">
				{#each d as p (p.period)}
					<MetricCard
						label={periodLabels[p.period]}
						value={money(p.pnl, true)}
						delta={percent(p.return_pct)}
						deltaClass={changeClass(p.pnl)}
					/>
				{/each}
			</div>
		{/snippet}
	</Region>
</Card>

<Card title={t('reports.attribution.title')} caption={t('reports.attribution.caption')} span="full">
	{#snippet actions()}
		<RangeSelector
			options={PERIODS}
			value={selectedPeriod}
			labels={periodLabels}
			onChange={(v) => (selectedPeriod = v as FpaPeriod)}
		/>
		<RangeSelector
			options={AXES}
			value={axis}
			labels={axisLabels}
			onChange={(v) => (axis = v as AttributionAxis)}
		/>
	{/snippet}

	<Region resource={attribution} isEmpty={(d) => rows(d).length === 0} emptyMessage={t('reports.empty')}>
		{#snippet children(d: AttributionReport)}
			<div class="total">
				<span class="total-label">{t('reports.total')}</span>
				<span class="total-value {changeClass(d.total_pnl)}">{money(d.total_pnl, true)}</span>
			</div>
			<div class="tbl-wrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>{d.axis === 'sector' ? t('reports.col.sector') : t('reports.col.symbol')}</th>
							<th class="num">{t('reports.col.realized')}</th>
							<th class="num">{t('reports.col.unrealized')}</th>
							<th class="num">{t('reports.col.total')}</th>
							<th class="num">{t('reports.col.contribution')}</th>
						</tr>
					</thead>
					<tbody>
						{#each rows(d) as r (rowName(r))}
							<tr>
								<td class="sym">{rowName(r)}</td>
								<td class="num {changeClass(r.realized_pnl)}">{money(r.realized_pnl, true)}</td>
								<td class="num {changeClass(r.unrealized_pnl)}">{money(r.unrealized_pnl, true)}</td>
								<td class="num {changeClass(r.total_pnl)}">{money(r.total_pnl, true)}</td>
								<td class="num">{percent(r.contribution_pct)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="note">{t('reports.note')}</p>
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
	.tiles {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: var(--space-4);
	}
	.total {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}
	.total-label {
		font-size: var(--text-sm);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-2);
	}
	.total-value {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-lg);
		font-weight: var(--weight-semibold);
	}
	.note {
		margin-top: var(--space-3);
		font-size: var(--text-xs);
		color: var(--color-text-2);
	}
	.gain {
		color: var(--color-gain);
	}
	.loss {
		color: var(--color-loss);
	}
	.flat {
		color: var(--color-flat);
	}
</style>
