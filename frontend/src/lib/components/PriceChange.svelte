<script lang="ts">
	import { arrow, changeClass, money, percent } from '$lib/utils/format';

	interface Props {
		// Provide pct and/or absolute value. At least one.
		pct?: string | number | null;
		value?: string | number | null;
		// 'money' renders the absolute value with $; 'pct' renders percent.
		showValue?: boolean;
		showPct?: boolean;
		size?: 'sm' | 'base' | 'lg';
	}

	let {
		pct = null,
		value = null,
		showValue = value !== null,
		showPct = pct !== null,
		size = 'base'
	}: Props = $props();

	// Direction driven by whichever signed source is present (prefer pct).
	let dir = $derived(changeClass(pct ?? value));
	let glyph = $derived(arrow(pct ?? value));
</script>

<span class="pc {dir} {size}">
	{#if glyph}<span class="glyph" aria-hidden="true">{glyph}</span>{/if}
	{#if showValue && value !== null}<span class="mono">{money(value, true)}</span>{/if}
	{#if showValue && showPct && value !== null && pct !== null}<span class="sep">·</span>{/if}
	{#if showPct && pct !== null}<span class="mono">{percent(pct)}</span>{/if}
</span>

<style>
	.pc {
		display: inline-flex;
		align-items: baseline;
		gap: var(--space-1);
		font-variant-numeric: tabular-nums;
	}
	.mono {
		font-family: var(--font-mono);
	}
	.glyph {
		font-size: 0.8em;
	}
	.sep {
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
	.sm {
		font-size: var(--text-sm);
	}
	.lg {
		font-size: var(--text-lg);
	}
</style>
