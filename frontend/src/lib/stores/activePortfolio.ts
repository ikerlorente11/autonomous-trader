// Client-side active-portfolio selection. The backend is stateless about which
// portfolio the user is "in": every scoped API call sends ?portfolio_id=, and the
// choice lives here (mirrored to localStorage). Switching reloads so all resources
// refetch scoped to the new portfolio — like changing project/environment.
//
// Two independent tracks run in parallel (CLAUDE.md: micro is an addition, not an
// alternative): the DAILY portfolio drives the main dashboard; the MICRO portfolio
// drives the /micro section. Each has its own stored selection so picking one never
// replaces the other.

const STORAGE_KEY = 'activePortfolioId';
const MICRO_STORAGE_KEY = 'activeMicroPortfolioId';

function readStored(key: string): number | null {
	if (typeof localStorage === 'undefined') return null;
	const raw = localStorage.getItem(key);
	if (raw === null) return null;
	const n = Number(raw);
	return Number.isFinite(n) ? n : null;
}

let activeId: number | null = readStored(STORAGE_KEY);
let activeMicroId: number | null = readStored(MICRO_STORAGE_KEY);

export function getActivePortfolioId(): number | null {
	return activeId;
}

export function setActivePortfolioId(id: number): void {
	activeId = id;
	if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, String(id));
	if (typeof location !== 'undefined') location.reload();
}

export function getActiveMicroPortfolioId(): number | null {
	return activeMicroId;
}

export function setActiveMicroPortfolioId(id: number): void {
	activeMicroId = id;
	if (typeof localStorage !== 'undefined') localStorage.setItem(MICRO_STORAGE_KEY, String(id));
	if (typeof location !== 'undefined') location.reload();
}
