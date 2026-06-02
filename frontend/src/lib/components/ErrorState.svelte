<script lang="ts">
	import { t } from '$lib/i18n';

	interface Props {
		message?: string;
		code?: string;
		onRetry?: () => void;
		compact?: boolean;
	}
	let { message = 'Something went wrong.', code, onRetry, compact = false }: Props = $props();
</script>

<div class="error-state" class:compact role="alert">
	<span class="icon" aria-hidden="true">⚠</span>
	<div class="body">
		<p class="msg">{message}</p>
		{#if code}<p class="code">{code}</p>{/if}
	</div>
	{#if onRetry}
		<button class="retry" onclick={onRetry}>{t('common.retry')}</button>
	{/if}
</div>

<style>
	.error-state {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-5);
		background: var(--color-error-bg);
		border: 1px solid var(--color-error);
		border-radius: var(--radius-md);
		color: var(--color-text-0);
	}
	.error-state.compact {
		padding: var(--space-3) var(--space-4);
	}
	.icon {
		color: var(--color-error);
		font-size: var(--text-lg);
	}
	.body {
		flex: 1;
	}
	.msg {
		font-size: var(--text-sm);
	}
	.code {
		font-size: var(--text-xs);
		color: var(--color-text-2);
		font-family: var(--font-mono);
		margin-top: var(--space-1);
	}
	.retry {
		background: transparent;
		border: 1px solid var(--color-bg-4);
		color: var(--color-text-0);
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-4);
		font-size: var(--text-sm);
	}
	.retry:hover {
		background: var(--color-bg-3);
	}
</style>
