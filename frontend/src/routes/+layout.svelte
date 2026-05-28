<script lang="ts">
	import '$lib/styles/tokens.css';
	import '$lib/styles/base.css';
	import '$lib/styles/aliases.css';
	import '$lib/styles/table.css';
	import { page } from '$app/stores';
	import { startSystemPolling, systemStatus, healthLevel } from '$lib/stores/systemStatus.svelte';
	import { portfolioApi } from '$lib/api/endpoints';
	import { createResource } from '$lib/utils/poller.svelte';
	import { money, relativeFromNow } from '$lib/utils/format';
	import Icon from '$lib/components/Icon.svelte';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	startSystemPolling();

	// Persistent portfolio-value anchor in the header; refreshes every 5 min.
	const summary = createResource(() => portfolioApi.summary(), { intervalMs: 300_000 });

	const nav = [
		{ href: '/', label: 'Dashboard', icon: 'grid' },
		{ href: '/portfolio', label: 'Portfolio', icon: 'briefcase' },
		{ href: '/market', label: 'Market', icon: 'chart' },
		{ href: '/trades', label: 'Trades', icon: 'swap' },
		{ href: '/experiments', label: 'Experiments', icon: 'flask' },
		{ href: '/system', label: 'System', icon: 'activity' }
	];

	let pathname = $derived($page.url.pathname);
	function isActive(href: string): boolean {
		return href === '/' ? pathname === '/' : pathname.startsWith(href);
	}

	let mobileOpen = $state(false);

	// Header status dot uses the STATUS palette (health/regime), never money.
	let healthDot = $derived.by(() => {
		if (!systemStatus.available) return 'neutral';
		const lvl = healthLevel(systemStatus.value);
		if (lvl === 'broken') return 'critical';
		if (lvl === 'degraded') return 'warn';
		if (lvl === 'ok') return 'ok';
		return 'neutral';
	});
	let healthBroken = $derived(systemStatus.available && healthLevel(systemStatus.value) === 'broken');
	let updatedLabel = $derived(
		systemStatus.lastUpdated ? relativeFromNow(new Date(systemStatus.lastUpdated).toISOString()) : '—'
	);
</script>

<div class="shell">
	<aside class="sidebar" class:open={mobileOpen}>
		<div class="brand">
			<span class="brand-mark" aria-hidden="true">◢</span>
			<span class="brand-name">Autonomous Trader</span>
		</div>
		<nav aria-label="Primary">
			{#each nav as item (item.href)}
				<a
					href={item.href}
					class="nav-item"
					class:active={isActive(item.href)}
					aria-current={isActive(item.href) ? 'page' : undefined}
					onclick={() => (mobileOpen = false)}
				>
					<Icon name={item.icon} />
					<span>{item.label}</span>
				</a>
			{/each}
		</nav>
		<div class="sidebar-foot">
			<span class="badge-phase">Phase 1 · Paper</span>
		</div>
	</aside>

	<div class="main">
		<header class="topbar">
			<button class="hamburger" aria-label="Toggle navigation" onclick={() => (mobileOpen = !mobileOpen)}>≡</button>
			<div class="status">
				<span class="dot {healthDot}" aria-hidden="true"></span>
				<span class="status-text">
					{systemStatus.available ? 'Updated' : 'System offline ·'}
					{updatedLabel}
				</span>
			</div>
			<div class="anchor">
				<span class="anchor-label">NAV</span>
				<span class="anchor-value" class:muted={!summary.data}>
					{summary.data ? money(summary.data.total) : '—'}
				</span>
			</div>
		</header>

		{#if healthBroken}
			<div class="health-banner" role="alert">
				<span class="banner-icon" aria-hidden="true">⚠</span>
				<span>
					A daily job failed — performance figures may be stale.
					<a href="/system">View system status →</a>
				</span>
			</div>
		{/if}

		<main class="content">
			{@render children()}
		</main>
	</div>
</div>

<style>
	.shell {
		display: grid;
		grid-template-columns: 220px 1fr;
		min-height: 100vh;
		background: var(--color-bg-1);
	}
	.sidebar {
		background: var(--color-bg-0);
		border-right: 1px solid var(--color-bg-4);
		display: flex;
		flex-direction: column;
		padding: var(--space-4);
		gap: var(--space-5);
		position: sticky;
		top: 0;
		height: 100vh;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2);
	}
	.brand-mark {
		color: var(--color-accent);
		font-size: var(--text-lg);
	}
	.brand-name {
		font-weight: var(--weight-semibold);
		font-size: var(--text-base);
		color: var(--color-text-0);
	}
	nav {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.nav-item {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		color: var(--color-text-1);
		font-size: var(--text-base);
	}
	.nav-item:hover {
		background: var(--color-bg-2);
		color: var(--color-text-0);
		text-decoration: none;
	}
	.nav-item.active {
		background: var(--color-accent-bg);
		color: var(--color-accent);
	}
	.nav-item :global(svg) {
		flex-shrink: 0;
		opacity: 0.85;
	}
	.sidebar-foot {
		margin-top: auto;
	}
	.badge-phase {
		font-size: var(--text-xs);
		color: var(--color-text-2);
		background: var(--color-bg-2);
		border: 1px solid var(--color-bg-4);
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-full);
	}
	.main {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.topbar {
		height: 64px;
		display: flex;
		align-items: center;
		gap: var(--space-4);
		padding: 0 var(--space-6);
		background: var(--color-bg-1);
		border-bottom: 1px solid var(--color-bg-4);
		position: sticky;
		top: 0;
		z-index: 10;
	}
	.hamburger {
		display: none;
		background: transparent;
		border: none;
		color: var(--color-text-0);
		font-size: var(--text-xl);
	}
	.status {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--color-text-1);
	}
	.status-text {
		font-variant-numeric: tabular-nums;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-full);
	}
	.dot.ok {
		background: var(--status-ok);
	}
	.dot.warn {
		background: var(--status-warn);
	}
	.dot.critical {
		background: var(--status-critical);
	}
	.dot.neutral {
		background: var(--color-neutral);
	}
	.health-banner {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-6);
		background: var(--surface-overlay);
		border-left: 3px solid var(--status-critical);
		color: var(--color-text-0);
		font-size: var(--text-sm);
	}
	.banner-icon {
		color: var(--status-critical);
	}
	.health-banner a {
		color: var(--status-warn);
	}
	.anchor {
		margin-left: auto;
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
	}
	.anchor-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-2);
	}
	.anchor-value {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-lg);
		color: var(--color-text-0);
		font-weight: var(--weight-semibold);
	}
	.muted {
		color: var(--color-text-2);
	}
	.content {
		padding: var(--space-6);
		max-width: var(--width-max);
		width: 100%;
	}

	@media (max-width: 900px) {
		.shell {
			grid-template-columns: 1fr;
		}
		.sidebar {
			position: fixed;
			z-index: 20;
			transform: translateX(-100%);
			transition: transform 0.2s ease;
			width: 220px;
		}
		.sidebar.open {
			transform: translateX(0);
		}
		.hamburger {
			display: block;
		}
	}
</style>
