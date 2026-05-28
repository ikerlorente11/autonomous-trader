// US equity regular session check (Mon–Fri, 09:30–16:00 ET). Backend marks are
// daily closes, so this only governs UI refresh cadence (60s during the session,
// slower otherwise) — it is not a trading-calendar source and ignores holidays.
export function isUsMarketHours(now: Date = new Date()): boolean {
	const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
	const day = et.getDay();
	if (day === 0 || day === 6) return false;
	const minutes = et.getHours() * 60 + et.getMinutes();
	return minutes >= 9 * 60 + 30 && minutes < 16 * 60;
}

// Refresh interval (ms) for market price views: fast during the session, slow off-hours.
export function marketPollMs(now: Date = new Date()): number {
	return isUsMarketHours(now) ? 60_000 : 300_000;
}
