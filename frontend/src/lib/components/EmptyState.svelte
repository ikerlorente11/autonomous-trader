<script lang="ts">
	interface Props {
		message?: string;
		icon?: string;
	}
	let { message = 'No data yet.', icon = '∅' }: Props = $props();
</script>

<div class="empty-state">
	<span class="icon" aria-hidden="true">{icon}</span>
	<p>{message}</p>
</div>

<style>
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-3);
		padding: var(--space-7) var(--space-5);
		color: var(--color-text-2);
		text-align: center;
	}
	.icon {
		font-size: var(--text-2xl);
		color: var(--color-text-3);
	}
	p {
		font-size: var(--text-sm);
	}
</style>
