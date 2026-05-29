// Client-side active-portfolio selection. The backend is stateless about which
// portfolio the user is "in": every scoped API call sends ?portfolio_id=, and the
// choice lives here (mirrored to localStorage). Switching reloads so all resources
// refetch scoped to the new portfolio — like changing project/environment.

const STORAGE_KEY = 'activePortfolioId';

function readStored(): number | null {
	if (typeof localStorage === 'undefined') return null;
	const raw = localStorage.getItem(STORAGE_KEY);
	if (raw === null) return null;
	const n = Number(raw);
	return Number.isFinite(n) ? n : null;
}

let activeId: number | null = readStored();

export function getActivePortfolioId(): number | null {
	return activeId;
}

export function setActivePortfolioId(id: number): void {
	activeId = id;
	if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, String(id));
	if (typeof location !== 'undefined') location.reload();
}
