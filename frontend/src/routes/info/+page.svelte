<script lang="ts">
	import Card from '$lib/components/Card.svelte';
	import { t } from '$lib/i18n';

	// Página estática (sin llamadas a la API). Describe lo que el sistema hace HOY,
	// no el objetivo a futuro: análisis solo técnico, paper trading, sin dinero real.
	// Copy with inline markup lives in the i18n dictionary and is rendered with {@html}.
	const flowSteps = [1, 2, 3, 4, 5, 6, 7];
</script>

<h1 class="page-title">{t('info.title')}</h1>

<Card span="full">
	<p class="lead">{@html t('info.lead')}</p>
</Card>

<Card title={t('info.flow.title')} caption={t('info.flow.caption')} span="full">
	<div class="flow">
		{#each flowSteps as step, i (step)}
			<div class="node">
				<span class="num">{step}</span>
				<span class="node-title">{t(`info.flow.${step}.title`)}</span>
				<span class="node-text">{t(`info.flow.${step}.text`)}</span>
			</div>
			{#if i < flowSteps.length - 1}<span class="arrow" aria-hidden="true">→</span>{/if}
		{/each}
	</div>
</Card>

<Card title={t('info.s1.title')} span="full">
	<ul class="list">
		<li>{@html t('info.s1.li1')}</li>
		<li>{@html t('info.s1.li2')}</li>
		<li>{@html t('info.s1.li3')}</li>
	</ul>
	<p class="note">{@html t('info.s1.note')}</p>
</Card>

<Card title={t('info.s2.title')} span="full">
	<p>{@html t('info.s2.p1')}</p>
	<ul class="list">
		<li>{@html t('info.s2.li1')}</li>
		<li>{@html t('info.s2.li2')}</li>
		<li>{@html t('info.s2.li3')}</li>
	</ul>
	<p>{@html t('info.s2.p2')}</p>
</Card>

<Card title={t('info.s3.title')} span="full">
	<ul class="list">
		<li>{@html t('info.s3.li1')}</li>
		<li>{@html t('info.s3.li2')}</li>
		<li>{@html t('info.s3.li3')}</li>
		<li>{@html t('info.s3.li4')}</li>
	</ul>
</Card>

<Card title={t('info.s4.title')} span="full">
	<ul class="list">
		<li>{@html t('info.s4.li1')}</li>
		<li>{@html t('info.s4.li2')}</li>
		<li>{@html t('info.s4.li3')}</li>
		<li>{@html t('info.s4.li4')}</li>
	</ul>
</Card>

<Card title={t('info.s5.title')} span="full">
	<ul class="list">
		<li>{@html t('info.s5.li1')}</li>
		<li>{@html t('info.s5.li2')}</li>
		<li>{@html t('info.s5.li3')}</li>
		<li>{@html t('info.s5.li4')}</li>
	</ul>
</Card>

<Card title={t('info.s6.title')} span="full">
	<ul class="list">
		<li>{@html t('info.s6.li1')}</li>
		<li>{@html t('info.s6.li2')}</li>
		<li>{@html t('info.s6.li3')}</li>
	</ul>
</Card>

<Card title={t('info.limits.title')} span="full">
	<p class="warn">{@html t('info.limits.text')}</p>
</Card>

<style>
	.page-title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		margin-bottom: var(--space-5);
	}
	:global(.card) {
		margin-bottom: var(--space-4);
	}
	.lead {
		font-size: var(--text-base);
		line-height: 1.6;
		color: var(--color-text-1);
	}
	.list {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding-left: var(--space-4);
		line-height: 1.55;
		color: var(--color-text-1);
	}
	.list li {
		list-style: disc;
	}
	p {
		line-height: 1.6;
		color: var(--color-text-1);
	}
	/* Code chips arrive via {@html} from the i18n dictionary, so they carry no
	   scope class — target them globally but only within this page's lists/paragraphs. */
	.list :global(code),
	.lead :global(code),
	.note :global(code),
	p :global(code) {
		font-family: var(--font-mono);
		font-size: 0.9em;
		background: var(--color-bg-2);
		padding: 1px 5px;
		border-radius: var(--radius-sm);
		color: var(--color-text-0);
	}
	.note {
		margin-top: var(--space-3);
		font-size: var(--text-sm);
		color: var(--color-text-2);
		border-left: 3px solid var(--color-bg-4);
		padding-left: var(--space-3);
	}
	.warn {
		font-size: var(--text-sm);
		color: var(--color-text-1);
		border-left: 3px solid var(--status-warn, var(--color-warn));
		padding-left: var(--space-3);
	}
	.flow {
		display: flex;
		flex-wrap: wrap;
		align-items: stretch;
		gap: var(--space-2);
	}
	.node {
		display: flex;
		flex-direction: column;
		gap: 2px;
		background: var(--color-bg-2);
		border: 1px solid var(--color-bg-4);
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-3);
		min-width: 120px;
	}
	.num {
		font-size: var(--text-xs);
		color: var(--color-accent, var(--color-text-2));
		font-weight: var(--weight-semibold);
	}
	.node-title {
		font-weight: var(--weight-semibold);
		color: var(--color-text-0);
		font-size: var(--text-sm);
	}
	.node-text {
		font-size: var(--text-xs);
		color: var(--color-text-2);
	}
	.arrow {
		display: flex;
		align-items: center;
		color: var(--color-text-2);
	}
	@media (max-width: 700px) {
		.arrow {
			display: none;
		}
	}
</style>
