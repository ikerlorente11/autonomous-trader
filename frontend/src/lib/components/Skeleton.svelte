<script lang="ts">
	interface Props {
		width?: string;
		height?: string;
		rows?: number;
		radius?: string;
	}
	let { width = '100%', height = '16px', rows = 1, radius = 'var(--radius-sm)' }: Props = $props();
</script>

<div class="skeleton-group" aria-hidden="true">
	{#each Array(rows) as _, i (i)}
		<span class="skeleton" style="width: {width}; height: {height}; border-radius: {radius}"></span>
	{/each}
</div>

<style>
	.skeleton-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.skeleton {
		display: block;
		background: linear-gradient(
			90deg,
			var(--color-bg-3) 25%,
			var(--color-bg-4) 50%,
			var(--color-bg-3) 75%
		);
		background-size: 200% 100%;
		animation: shimmer 1.4s ease infinite;
	}
	@keyframes shimmer {
		from {
			background-position: 200% 0;
		}
		to {
			background-position: -200% 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.skeleton {
			animation: none;
			background: var(--color-bg-3);
		}
	}
</style>
