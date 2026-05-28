// Side-effect-only Chart.js date adapter; ships no types. Standalone ambient
// declaration (no imports → global script) so the lazy dynamic import in
// register.ts resolves to `any` instead of erroring under noImplicitAny.
declare module 'chartjs-adapter-date-fns';
