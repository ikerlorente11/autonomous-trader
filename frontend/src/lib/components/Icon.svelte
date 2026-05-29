<script lang="ts">
	// Minimal inline icon set (Lucide-style, stroke 1.5) to avoid a runtime dep.
	interface Props {
		name: string;
		size?: number;
	}
	let { name, size = 18 }: Props = $props();

	const paths: Record<string, string> = {
		grid: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
		briefcase: 'M3 7h18v13H3zM8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18',
		chart: 'M3 3v18h18M7 14l3-3 3 3 5-6',
		swap: 'M7 7h13l-3-3M17 17H4l3 3',
		flask: 'M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M7 15h10',
		activity: 'M3 12h4l3 8 4-16 3 8h4',
		wallet: 'M3 6h15a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H3zM16 11h5v4h-5a2 2 0 0 1 0-4z',
		info: 'M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18zM12 8h.01M11 11h1v5h1'
	};
	let d = $derived(paths[name] ?? '');
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="1.5"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"
>
	<path {d} />
</svg>
