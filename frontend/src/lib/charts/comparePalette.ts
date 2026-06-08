// Stable per-portfolio colour for the comparison view, shared by the chart lines and
// the selector swatches so a portfolio keeps the same colour everywhere.
export const COMPARE_PALETTE = [
	'#4c8dff', '#26a269', '#e5484d', '#f5a623',
	'#9b5de5', '#00bbf9', '#f15bb5', '#8fd14f'
];

export function compareColor(id: number): string {
	return COMPARE_PALETTE[id % COMPARE_PALETTE.length];
}
