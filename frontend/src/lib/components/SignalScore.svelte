<script lang="ts">
	import { toNum } from '$lib/utils/format';
	import { scoreBand } from '$lib/utils/thresholds';

	interface Props {
		score: string | number | null | undefined;
		label?: string;
		width?: string;
	}
	let { score, label, width = '120px' }: Props = $props();

	let n = $derived(toNum(score));
	let pct = $derived(n === null ? 0 : Math.max(0, Math.min(100, n)));
	// Color bands per ui-system §5.6.
	let fill = $derived(
		n === null
			? 'var(--color-bg-4)'
			: n >= 80
				? 'var(--color-gain)'
				: n >= 60
					? 'var(--color-gain-dim)'
					: n >= 40
						? 'var(--color-warn)'
						: 'var(--color-loss)'
	);
	let _band = $derived(scoreBand(score));
</script>

<div class="signal-score" title={label}>
	<div class="track" style="width: {width}" role="meter" aria-valuenow={pct} aria-valuemin="0" aria-valuemax="100" aria-label={label ?? 'Signal score'}>
		<div class="fill" style="width: {pct}%; background: {fill}"></div>
	</div>
	<span class="value">{n === null ? '—' : n.toFixed(1)}</span>
</div>

<style>
	.signal-score {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
	}
	.track {
		height: 8px;
		background: var(--color-bg-3);
		border-radius: var(--radius-full);
		overflow: hidden;
	}
	.fill {
		height: 100%;
		border-radius: var(--radius-full);
		transition: width 0.3s ease;
	}
	.value {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-sm);
		color: var(--color-text-0);
		min-width: 36px;
		text-align: right;
	}
</style>
