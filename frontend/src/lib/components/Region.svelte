<script lang="ts" generics="T">
	import type { Snippet } from 'svelte';
	import type { Resource } from '$lib/utils/poller.svelte';
	import { ApiError } from '$lib/api/client';
	import LoadingSpinner from './LoadingSpinner.svelte';
	import ErrorState from './ErrorState.svelte';
	import EmptyState from './EmptyState.svelte';
	import Skeleton from './Skeleton.svelte';

	interface Props {
		resource: Resource<T>;
		isEmpty?: (data: T) => boolean;
		emptyMessage?: string;
		skeleton?: boolean;
		// Treat 404 as a soft "not available yet" rather than a hard error.
		notReadyOn404?: boolean;
		notReadyMessage?: string;
		children: Snippet<[T]>;
	}
	let {
		resource,
		isEmpty,
		emptyMessage = 'No data yet.',
		skeleton = false,
		notReadyOn404 = false,
		notReadyMessage = 'Not available yet.',
		children
	}: Props = $props();

	let is404 = $derived(resource.error instanceof ApiError && resource.error.status === 404);
</script>

{#if resource.data !== null}
	{#if isEmpty && isEmpty(resource.data)}
		<EmptyState message={emptyMessage} />
	{:else}
		{@render children(resource.data)}
	{/if}
{:else if resource.loading}
	{#if skeleton}
		<Skeleton rows={4} height="20px" />
	{:else}
		<LoadingSpinner />
	{/if}
{:else if resource.error}
	{#if notReadyOn404 && is404}
		<EmptyState message={notReadyMessage} icon="⏳" />
	{:else}
		<ErrorState
			message={resource.error.message}
			code={resource.error instanceof ApiError ? resource.error.code : undefined}
			onRetry={resource.refresh}
		/>
	{/if}
{:else}
	<EmptyState message={emptyMessage} />
{/if}
