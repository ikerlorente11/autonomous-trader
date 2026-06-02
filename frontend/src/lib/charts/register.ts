// Chart.js + financial plugin are loaded lazily (browser-only). A static top-level
// import breaks SSR/prerender: chartjs-chart-financial touches Chart internals at
// module-eval time and throws under Node. Pages that prerender (/) import chart components,
// so the heavy libs must only evaluate in the browser via loadChart().
type ChartCtor = (typeof import('chart.js'))['Chart'];

let registered = false;
let chartCtor: ChartCtor | null = null;

export async function loadChart(): Promise<ChartCtor> {
	if (chartCtor) return chartCtor;
	const chartjs = await import('chart.js');
	if (!registered) {
		await import('chartjs-adapter-date-fns');
		const fin = await import('chartjs-chart-financial');
		chartjs.Chart.register(
			chartjs.LineController,
			chartjs.LineElement,
			chartjs.PointElement,
			chartjs.BarController,
			chartjs.BarElement,
			chartjs.LinearScale,
			chartjs.CategoryScale,
			chartjs.TimeScale,
			chartjs.Filler,
			chartjs.Legend,
			chartjs.Tooltip,
			fin.CandlestickController,
			fin.CandlestickElement,
			fin.OhlcController,
			fin.OhlcElement
		);
		registered = true;
	}
	chartCtor = chartjs.Chart;
	return chartCtor;
}
