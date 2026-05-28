<script lang="ts">
	interface Props {
		label?: string;
		size?: number;
	}
	let { label = 'Loading…', size = 24 }: Props = $props();
</script>

<div class="spinner-wrap" role="status" aria-live="polite">
	<span class="spinner" style="width: {size}px; height: {size}px"></span>
	<span class="label">{label}</span>
</div>

<style>
	.spinner-wrap {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-3);
		padding: var(--space-6);
		color: var(--color-text-2);
		font-size: var(--text-sm);
	}
	.spinner {
		border: 2px solid var(--color-bg-4);
		border-top-color: var(--color-accent);
		border-radius: var(--radius-full);
		animation: spin 0.7s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation: none;
			border-top-color: var(--color-accent);
		}
	}
</style>
