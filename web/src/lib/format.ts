// Financial formatting helpers for the Finance Tracker.
// All amounts are stored as integer minor units; these functions convert for display.

// ─── Currency configuration ───────────────────────────────────────────────────

/** Number of decimal places for each supported currency. JPY has 0 (no minor unit). */
const CURRENCY_DECIMALS: Record<string, number> = {
	SGD: 2,
	USD: 2,
	MYR: 2,
	EUR: 2,
	JPY: 0,
};

/** Currency symbol prefixes for display. */
const CURRENCY_SYMBOLS: Record<string, string> = {
	SGD: 'S$',
	USD: 'US$',
	MYR: 'RM',
	EUR: '€',
	JPY: '¥',
};

// ─── Formatters ───────────────────────────────────────────────────────────────

/**
 * Format a SGD minor-unit integer to a display string.
 * Example: 4250 → "S$42.50", 100000 → "S$1,000.00"
 */
export function formatSgd(minor: number): string {
	const value = minor / 100;
	return (
		'S$' +
		value.toLocaleString('en-SG', {
			minimumFractionDigits: 2,
			maximumFractionDigits: 2,
		})
	);
}

/**
 * Format any supported currency from minor units.
 * Handles JPY (0 decimal places) and all other supported currencies (2 decimal places).
 * Example: formatOriginal(1500, 'JPY') → "¥1,500"
 *          formatOriginal(4250, 'SGD') → "S$42.50"
 */
export function formatOriginal(minor: number, currency: string): string {
	const decimals = CURRENCY_DECIMALS[currency] ?? 2;
	const divisor = Math.pow(10, decimals);
	const value = minor / divisor;
	const symbol = CURRENCY_SYMBOLS[currency] ?? currency + ' ';

	const formatted = value.toLocaleString('en-SG', {
		minimumFractionDigits: decimals,
		maximumFractionDigits: decimals,
	});

	return symbol + formatted;
}

/**
 * Format an ISO date string to the app's canonical display format.
 * Example: "2026-06-28" → "28 Jun 2026"
 */
export function formatDate(iso: string): string {
	// Parse the date as a local date (not UTC) to avoid timezone offset issues.
	const [year, month, day] = iso.split('-').map(Number);
	const date = new Date(year, month - 1, day);
	return date.toLocaleDateString('en-SG', {
		day: '2-digit',
		month: 'short',
		year: 'numeric',
	});
}

/**
 * Format a month/year for headings (e.g. "June 2026").
 */
export function formatMonthYear(year: number, month: number): string {
	const date = new Date(year, month - 1, 1);
	return date.toLocaleDateString('en-SG', { month: 'long', year: 'numeric' });
}

/**
 * Format minor units as a plain decimal number, no currency symbol.
 * Used where the ISO code is already rendered as its own token, e.g. the
 * Balance & Settle-Up copy contract: "{partner} owes you {cur} {amt}" ->
 * "Bob owes you EUR 50.00" (cur="EUR", amt=formatMinorPlain(5000,"EUR")).
 */
export function formatMinorPlain(minor: number, currency: string): string {
	const decimals = CURRENCY_DECIMALS[currency] ?? 2;
	const divisor = Math.pow(10, decimals);
	const value = minor / divisor;
	return value.toLocaleString('en-SG', {
		minimumFractionDigits: decimals,
		maximumFractionDigits: decimals,
	});
}

/**
 * Convert minor units to a decimal number for use in inputs.
 * Handles JPY (no decimals) and standard 2-decimal currencies.
 * Example: 4250, 'SGD' → "42.50"
 *          1500, 'JPY' → "1500"
 */
export function minorToInputString(minor: number, currency: string): string {
	const decimals = CURRENCY_DECIMALS[currency] ?? 2;
	const divisor = Math.pow(10, decimals);
	const value = minor / divisor;
	return value.toFixed(decimals);
}

/**
 * Parse a user-entered amount string to integer minor units — client-side
 * mirror of the backend's `parse_to_minor_units` (app/services/money.py),
 * used only for the SplitEditor's instant preview. The server re-parses and
 * is the source of truth for what actually gets persisted.
 * Example: parseToMinorUnits("12.50", "SGD") -> 1250
 *          parseToMinorUnits("1500", "JPY")  -> 1500
 */
export function parseToMinorUnits(amountStr: string, currency: string): number {
	const decimals = CURRENCY_DECIMALS[currency] ?? 2;
	const trimmed = (amountStr ?? '').trim();
	const num = Number(trimmed);
	if (trimmed === '' || !isFinite(num)) return 0;
	const factor = Math.pow(10, decimals);
	const scaled = num * factor;
	// Round-half-up, nudged to counter binary float drift (e.g. 100.005 * 100).
	return Math.round(scaled + (scaled >= 0 ? 1e-7 : -1e-7));
}

/**
 * Largest-remainder (Hamilton) apportionment of `totalMinor` across `weights`.
 * Client-side TS port of `allocate_shares` (app/services/money.py) — shares
 * always sum EXACTLY to totalMinor; ties broken by largest fractional
 * remainder then ascending weight index.
 */
export function allocateShares(totalMinor: number, weights: number[]): number[] {
	if (totalMinor < 0) throw new Error('totalMinor must be >= 0');
	if (weights.length === 0 || weights.some((w) => w <= 0)) {
		throw new Error('weights must be non-empty and all positive');
	}
	const weightSum = weights.reduce((a, b) => a + b, 0);
	const n = weights.length;
	const raw = weights.map((w) => (totalMinor * w) / weightSum);
	const floors = raw.map((r) => Math.floor(r));
	const remainders = raw.map((r, i) => r - floors[i]);
	const leftover = totalMinor - floors.reduce((a, b) => a + b, 0);
	const order = Array.from({ length: n }, (_, i) => i).sort((a, b) =>
		remainders[b] !== remainders[a] ? remainders[b] - remainders[a] : a - b
	);
	const shares = [...floors];
	for (let i = 0; i < leftover; i++) {
		shares[order[i]] += 1;
	}
	return shares;
}
