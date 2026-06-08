<script lang="ts">
	import '$lib/styles/tokens.css';
	import '$lib/styles/base.css';
	import '$lib/styles/aliases.css';
	import '$lib/styles/table.css';
	import { page } from '$app/stores';
	import { startSystemPolling, systemStatus, healthLevel } from '$lib/stores/systemStatus.svelte';
	import { portfolioApi, portfoliosApi } from '$lib/api/endpoints';
	import { getActivePortfolioId, setActivePortfolioId } from '$lib/stores/activePortfolio';
	import { createResource } from '$lib/utils/poller.svelte';
	import { money, relativeFromNow } from '$lib/utils/format';
	import { t, getLocale, setLocale, initLocale, LOCALES } from '$lib/i18n';
	import Icon from '$lib/components/Icon.svelte';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	initLocale();
	startSystemPolling();

	// Persistent portfolio-value anchor in the header; refreshes every 5 min.
	const summary = createResource(() => portfolioApi.summary(), { intervalMs: 300_000 });
	const portfolios = createResource(() => portfoliosApi.list(), { intervalMs: 300_000 });

	// Active portfolio for the switcher: stored choice, else the first listed.
	let selectedId = $derived(getActivePortfolioId() ?? portfolios.data?.[0]?.id ?? null);
	function onSwitch(event: Event) {
		const id = Number((event.currentTarget as HTMLSelectElement).value);
		if (Number.isFinite(id) && id !== getActivePortfolioId()) setActivePortfolioId(id);
	}

	const nav = [
		{ href: '/', labelKey: 'nav.dashboard', icon: 'grid' },
		{ href: '/portfolios', labelKey: 'nav.portfolios', icon: 'wallet' },
		{ href: '/compare', labelKey: 'nav.compare', icon: 'layers' },
		{ href: '/market', labelKey: 'nav.market', icon: 'chart' },
		{ href: '/trades', labelKey: 'nav.trades', icon: 'swap' },
		{ href: '/reports', labelKey: 'nav.reports', icon: 'briefcase' },
		{ href: '/experiments', labelKey: 'nav.experiments', icon: 'flask' },
		{ href: '/system', labelKey: 'nav.system', icon: 'activity' },
		{ href: '/info', labelKey: 'nav.info', icon: 'info' }
	];

	let pathname = $derived($page.url.pathname);
	function isActive(href: string): boolean {
		if (href === '/') return pathname === '/';
		return pathname === href || pathname.startsWith(`${href}/`);
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

<svelte:window onkeydown={(e) => { if (e.key === 'Escape') mobileOpen = false; }} />

<div class="shell">
	{#if mobileOpen}
		<button class="overlay" aria-label={t('layout.closeMenu')} onclick={() => (mobileOpen = false)}></button>
	{/if}
	<aside class="sidebar" class:open={mobileOpen}>
		<div class="brand">
			<span class="brand-mark" aria-hidden="true">◢</span>
			<span class="brand-name">{t('layout.brand')}</span>
		</div>
		<nav aria-label={t('layout.primaryNav')}>
			{#each nav as item (item.href)}
				<a
					href={item.href}
					class="nav-item"
					class:active={isActive(item.href)}
					aria-current={isActive(item.href) ? 'page' : undefined}
					onclick={() => (mobileOpen = false)}
				>
					<Icon name={item.icon} />
					<span>{t(item.labelKey)}</span>
				</a>
			{/each}
		</nav>
		<div class="sidebar-foot">
			<span class="badge-phase">Phase 1 · Paper</span>
		</div>
	</aside>

	<div class="main">
		<header class="topbar">
			<button class="hamburger" aria-label={t('layout.toggleNav')} onclick={() => (mobileOpen = !mobileOpen)}>≡</button>
			<div class="status">
				<span class="dot {healthDot}" aria-hidden="true"></span>
				<span class="status-text">
					{systemStatus.available ? t('layout.updated') : t('layout.offline')}
					{updatedLabel}
				</span>
			</div>
			<div class="lang" role="group" aria-label={t('layout.language')}>
				{#each LOCALES as code (code)}
					<button
						type="button"
						class:active={getLocale() === code}
						aria-pressed={getLocale() === code}
						onclick={() => setLocale(code)}>{code.toUpperCase()}</button
					>
				{/each}
			</div>
			<div class="pf-switch">
				<Icon name="wallet" size={16} />
				<select aria-label={t('layout.activePortfolio')} value={selectedId} onchange={onSwitch}>
					{#each portfolios.data ?? [] as p (p.id)}
						<option value={p.id}>{p.name}</option>
					{/each}
				</select>
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
					{t('layout.bannerStale')}
					<a href="/system">{t('layout.bannerLink')}</a>
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
		min-height: 64px;
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3) var(--space-4);
		padding: var(--space-2) var(--space-6);
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
	.lang {
		margin-left: auto;
		display: inline-flex;
		gap: 2px;
		background: var(--color-bg-2);
		border: 1px solid var(--color-bg-4);
		border-radius: var(--radius-md);
		padding: 2px;
	}
	.lang button {
		background: transparent;
		border: none;
		color: var(--color-text-2);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		letter-spacing: 0.04em;
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}
	.lang button:hover {
		color: var(--color-text-0);
	}
	.lang button.active {
		background: var(--color-accent-bg);
		color: var(--color-accent);
	}
	.pf-switch {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		color: var(--color-text-2);
	}
	.pf-switch select {
		background: var(--color-bg-2);
		border: 1px solid var(--color-bg-4);
		color: var(--color-text-0);
		border-radius: var(--radius-md);
		padding: var(--space-1) var(--space-2);
		font-size: var(--text-sm);
	}
	.anchor {
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

	.overlay {
		display: none;
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
		/* Backdrop: tap anywhere outside the drawer to close it. */
		.overlay {
			display: block;
			position: fixed;
			inset: 0;
			z-index: 15;
			border: none;
			padding: 0;
			background: rgba(0, 0, 0, 0.5);
			cursor: pointer;
		}
	}
	@media (max-width: 640px) {
		.topbar {
			padding: var(--space-2) var(--space-3);
			gap: var(--space-2) var(--space-3);
		}
		/* Keep the health dot, drop the long "Updated …" text to save room. */
		.status-text {
			display: none;
		}
		.pf-switch {
			margin-left: 0;
		}
		.pf-switch select {
			max-width: 44vw;
		}
		.anchor {
			margin-left: auto;
		}
		.content {
			padding: var(--space-4);
		}
	}
</style>
