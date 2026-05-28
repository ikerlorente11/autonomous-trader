// Static adapter. Prerender each static route's shell (this is what adapter-static
// consumes). Component data still loads client-side from /api at runtime; any fetch
// attempted during prerender fails gracefully into the resource's error state and is
// replaced on hydration.
export const prerender = true;
export const trailingSlash = 'ignore';
