<script lang="ts">
	import type { Band } from '$lib/utils/thresholds';

	interface Props {
		label: string;
		value: string;
		band?: Band;
		tooltip?: string;
		delta?: string;
		deltaClass?: 'gain' | 'loss' | 'flat';
		emphasis?: boolean;
	}

	let {
		label,
		value,
		band = 'neutral',
		tooltip,
		delta,
		deltaClass = 'flat',
		emphasis = false
	}: Props = $props();

	const bandText: Record<Band, string> = {
		good: 'Good',
		warn: 'Warn',
		bad: 'Bad',
		neutral: ''
	};
</script>

<div class="metric-card" title={tooltip}>
	<div class="top">
		<span class="label">{label}</span>
		{#if band !== 'neutral'}
			<span class="badge {band}">{bandText[band]}</span>
		{/if}
	</div>
	<div class="value" class:emphasis>{value}</div>
	{#if delta}
		<div class="delta {deltaClass}">{delta}</div>
	{/if}
</div>

<style>
	.metric-card {
		background: var(--color-bg-2);
		border: 1px solid var(--color-bg-4);
		border-radius: var(--radius-lg);
		padding: var(--space-5);
		box-shadow: var(--shadow-card);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.label {
		font-size: var(--text-sm);
		color: var(--color-text-1);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.value {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-xl);
		color: var(--color-text-0);
		font-weight: var(--weight-semibold);
	}
	.value.emphasis {
		font-size: var(--text-2xl);
		line-height: var(--lh-2xl);
	}
	.delta {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
	}
	.badge {
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		padding: 2px 8px;
		border-radius: var(--radius-full);
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
	.badge.good {
		background: var(--color-gain-bg);
		color: var(--color-gain);
	}
	.badge.warn {
		background: var(--color-warn-bg);
		color: var(--color-warn);
	}
	.badge.bad {
		background: var(--color-loss-bg);
		color: var(--color-loss);
	}
</style>
