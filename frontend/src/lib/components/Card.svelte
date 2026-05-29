<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title?: string;
		caption?: string;
		span?: 1 | 2 | 3 | 'full';
		actions?: Snippet;
		children: Snippet;
	}
	let { title, caption, span = 1, actions, children }: Props = $props();
</script>

<section class="card span-{span}">
	{#if title || actions}
		<header>
			<div class="titles">
				{#if title}<h2>{title}</h2>{/if}
				{#if caption}<p class="caption">{caption}</p>{/if}
			</div>
			{#if actions}<div class="actions">{@render actions()}</div>{/if}
		</header>
	{/if}
	<div class="content">
		{@render children()}
	</div>
</section>

<style>
	.card {
		background: var(--color-bg-2);
		border: 1px solid var(--color-bg-4);
		border-radius: var(--radius-lg);
		padding: var(--space-5);
		box-shadow: var(--shadow-card);
		min-width: 0;
	}
	header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}
	h2 {
		font-size: var(--text-lg);
		font-weight: var(--weight-semibold);
		color: var(--color-text-0);
	}
	.caption {
		font-size: var(--text-sm);
		color: var(--color-text-1);
		margin-top: var(--space-1);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
		flex-shrink: 0;
		flex-wrap: wrap;
	}
	.span-2 {
		grid-column: span 2;
	}
	.span-3,
	.span-full {
		grid-column: 1 / -1;
	}
	@media (max-width: 900px) {
		.span-2,
		.span-3 {
			grid-column: 1 / -1;
		}
	}
	/* On phones, stack the header so wide action controls (search, date, range
	   selectors) wrap to full width instead of overflowing the title row. */
	@media (max-width: 640px) {
		.card {
			padding: var(--space-4);
		}
		header {
			flex-direction: column;
			align-items: stretch;
		}
		.actions {
			width: 100%;
		}
	}
</style>
