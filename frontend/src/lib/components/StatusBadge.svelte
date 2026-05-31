<script lang="ts">
	// Maps order/position/job/data states to semantic tokens per ui-system §2.4.
	interface Props {
		status: string;
		withDot?: boolean;
	}
	let { status, withDot = false }: Props = $props();

	type Tone = 'gain' | 'loss' | 'warn' | 'accent' | 'info' | 'error' | 'neutral';

	const map: Record<string, Tone> = {
		filled: 'gain',
		success: 'gain',
		fresh: 'gain',
		buy: 'gain',
		sell: 'loss',
		hold: 'neutral',
		closed: 'neutral',
		pending: 'warn',
		running: 'info',
		stale: 'warn',
		open: 'accent',
		rejected: 'error',
		failed: 'error',
		error: 'error'
	};

	let key = $derived(status?.toLowerCase?.() ?? '');
	let tone = $derived(map[key] ?? 'neutral');
	let text = $derived(status ? status.toUpperCase() : '—');
</script>

<span class="badge {tone}">
	{#if withDot}<span class="dot" aria-hidden="true"></span>{/if}
	{text}
</span>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		padding: 2px 10px;
		border-radius: var(--radius-full);
		letter-spacing: 0.02em;
	}
	.dot {
		width: 6px;
		height: 6px;
		border-radius: var(--radius-full);
		background: currentColor;
	}
	.gain {
		background: var(--color-gain-bg);
		color: var(--color-gain);
	}
	.loss {
		background: var(--color-loss-bg);
		color: var(--color-loss);
	}
	.warn {
		background: var(--color-warn-bg);
		color: var(--color-warn);
	}
	.error {
		background: var(--color-error-bg);
		color: var(--color-error);
	}
	.accent {
		background: var(--color-accent-bg);
		color: var(--color-accent);
	}
	.info {
		background: rgba(96, 165, 250, 0.12);
		color: var(--color-info);
	}
	.neutral {
		background: var(--color-bg-3);
		color: var(--color-text-2);
	}
</style>
