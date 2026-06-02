<script lang="ts">
	import { systemStatus, healthLevel } from '$lib/stores/systemStatus.svelte';
	import { formatDateTime, relativeFromNow } from '$lib/utils/format';
	import type { JobStatus } from '$lib/api/types';
	import Card from '$lib/components/Card.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import ErrorState from '$lib/components/ErrorState.svelte';

	// Reads the shared 30s poller from the layout store — no extra polling here
	// (ux §4: one health source). Status palette only — never the P&L palette.
	let s = $derived(systemStatus.value);
	let level = $derived(healthLevel(s));

	const levelLabel: Record<string, string> = {
		ok: 'OK',
		degraded: 'DEGRADED',
		broken: 'BROKEN',
		unknown: 'UNKNOWN'
	};

	function jobLabel(j: JobStatus): string {
		return j.job.replace(/_/g, ' ');
	}
	function durMs(ms: number | null): string {
		if (ms === null) return '—';
		return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
	}
</script>

<h1 class="page-title">System</h1>

{#if !systemStatus.available}
	<ErrorState
		message="System status is unavailable. The /api/system/status endpoint did not respond."
		code="SYSTEM_OFFLINE"
		onRetry={systemStatus.refresh}
	/>
{:else if !s}
	<EmptyState message="Loading system status…" icon="⏳" />
{:else}
	<section class="rollup status-{level}">
		<div>
			<span class="rollup-label">Simulation Health</span>
			<span class="rollup-value">{levelLabel[level]}</span>
		</div>
		<span class="server-time">Server time {formatDateTime(s.server_time)}</span>
	</section>

	<Card title="Daily Jobs" caption="Scheduler status per job" span="full">
		<div class="tbl-wrap">
			<table class="tbl">
				<thead>
					<tr>
						<th>Job</th>
						<th>Status</th>
						<th>Last Run</th>
						<th class="num">Duration</th>
						<th>Next Run</th>
					</tr>
				</thead>
				<tbody>
					{#each s.jobs as j (j.job)}
						<tr>
							<td class="job">{jobLabel(j)}</td>
							<td><StatusBadge status={j.status ?? 'unknown'} withDot /></td>
							<td>
								{#if j.last_run_at}
									{formatDateTime(j.last_run_at)}
									<span class="rel">({relativeFromNow(j.last_run_at)})</span>
								{:else}never{/if}
							</td>
							<td class="num">{durMs(j.duration_ms)}</td>
							<td>{j.next_run_at ? formatDateTime(j.next_run_at) : '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</Card>

	<Card title="Recent Errors" caption="Failed or degraded job runs" span="full">
		{#if s.recent_errors.length === 0}
			<EmptyState message="No recent errors. All jobs healthy." icon="✓" />
		{:else}
			<ul class="errors">
				{#each s.recent_errors as e (`${e.job}:${e.last_run_at ?? ''}`)}
					<li>
						<div class="err-head">
							<StatusBadge status={e.status ?? 'failed'} />
							<span class="err-job">{jobLabel(e)}</span>
							<span class="err-time">{formatDateTime(e.last_run_at)}</span>
						</div>
						{#if e.error}<p class="err-msg">{e.error}</p>{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</Card>

	<p class="note">
		Data-freshness per symbol (last bar timestamp) and NAV-continuity checks are not yet exposed by
		the API; this page reflects what /api/system/status currently returns.
	</p>
{/if}

<style>
	.page-title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		margin-bottom: var(--space-5);
	}
	:global(.card) {
		margin-bottom: var(--space-4);
	}
	.rollup {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		background: var(--color-bg-2);
		border: 1px solid var(--color-bg-4);
		border-left-width: 3px;
		border-radius: var(--radius-lg);
		padding: var(--space-5);
		margin-bottom: var(--space-4);
	}
	/* Status palette only (ux §3.6). */
	.rollup.status-ok {
		border-left-color: var(--status-ok);
	}
	.rollup.status-degraded {
		border-left-color: var(--status-warn);
	}
	.rollup.status-broken {
		border-left-color: var(--status-critical);
	}
	.rollup.status-unknown {
		border-left-color: var(--color-text-3);
	}
	.rollup-label {
		display: block;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-2);
	}
	.rollup-value {
		font-size: var(--text-2xl);
		font-weight: var(--weight-semibold);
		color: var(--color-text-0);
	}
	.server-time {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--color-text-2);
	}
	.job {
		text-transform: capitalize;
		color: var(--color-text-0);
	}
	.rel {
		color: var(--color-text-2);
		font-size: var(--text-xs);
	}
	.errors {
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.err-head {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.err-job {
		text-transform: capitalize;
		color: var(--color-text-0);
	}
	.err-time {
		margin-left: auto;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--color-text-2);
	}
	.err-msg {
		margin-top: var(--space-2);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--color-loss);
		white-space: normal;
	}
	.note {
		font-size: var(--text-xs);
		color: var(--color-text-2);
	}
</style>
