// Minimal typings for chartjs-chart-financial (ships no .d.ts) + augmentation of
// Chart.js's ChartTypeRegistry so 'candlestick' and 'ohlc' are valid chart types.
import type { ChartComponent, CartesianScaleTypeRegistry, Point } from 'chart.js';

declare module 'chartjs-chart-financial' {
	export const CandlestickController: ChartComponent;
	export const CandlestickElement: ChartComponent;
	export const OhlcController: ChartComponent;
	export const OhlcElement: ChartComponent;
}

interface FinancialDataPoint {
	x: number;
	o: number;
	h: number;
	l: number;
	c: number;
}

interface FinancialColorOptions {
	color?: { up?: string; down?: string; unchanged?: string };
}

declare module 'chart.js' {
	interface ChartTypeRegistry {
		candlestick: {
			chartOptions: unknown;
			datasetOptions: FinancialColorOptions;
			defaultDataPoint: FinancialDataPoint;
			metaExtensions: object;
			parsedDataType: FinancialDataPoint & Point;
			scales: keyof CartesianScaleTypeRegistry;
		};
		ohlc: {
			chartOptions: unknown;
			datasetOptions: FinancialColorOptions;
			defaultDataPoint: FinancialDataPoint;
			metaExtensions: object;
			parsedDataType: FinancialDataPoint & Point;
			scales: keyof CartesianScaleTypeRegistry;
		};
	}
}
