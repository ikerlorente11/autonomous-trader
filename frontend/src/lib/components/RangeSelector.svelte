<script lang="ts">
	interface Props {
		options: readonly string[];
		value: string;
		onChange: (v: string) => void;
		labels?: Record<string, string>;
	}
	let { options, value, onChange, labels }: Props = $props();
</script>

<div class="range-selector" role="tablist" aria-label="Range">
	{#each options as opt (opt)}
		<button
			role="tab"
			aria-selected={opt === value}
			class:active={opt === value}
			onclick={() => onChange(opt)}
		>
			{labels?.[opt] ?? opt}
		</button>
	{/each}
</div>

<style>
	.range-selector {
		display: inline-flex;
		gap: 2px;
		background: var(--color-bg-1);
		border: 1px solid var(--color-bg-4);
		border-radius: var(--radius-md);
		padding: 2px;
	}
	button {
		background: transparent;
		border: none;
		color: var(--color-text-1);
		font-size: var(--text-sm);
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-sm);
	}
	button:hover {
		color: var(--color-text-0);
	}
	button.active {
		background: var(--color-accent-bg);
		color: var(--color-accent);
	}
</style>
