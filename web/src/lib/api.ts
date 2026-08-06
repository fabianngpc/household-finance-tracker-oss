// Typed API client for the Finance Tracker backend.
// All requests include credentials: 'include' so the session cookie is sent automatically.

const AUTH_BASE = '/auth';
const API_BASE = '/api';

// ─── TypeScript Types (mirror backend schemas) ────────────────────────────────

export interface User {
	id: number;
	username: string;
	display_name: string;
	partner_display_name?: string;
}

export interface Category {
	id: number;
	user_id: number;
	name: string;
	color: string;
	icon: string;
	is_protected: boolean;
	expense_count: number;
}

export interface CategoryCreate {
	name: string;
	color: string;
	icon: string;
}

export interface CategoryUpdate {
	name?: string;
	color?: string;
	icon?: string;
}

export interface Expense {
	id: number;
	user_id: number;
	original_amount_minor: number; // integer minor units in original currency
	original_currency: string;     // ISO 4217 e.g. "SGD", "JPY"
	amount_base_minor: number;     // integer SGD cents
	fx_rate: number;
	fx_rate_date: string;          // ISO date string
	category_id: number;
	occurred_on: string;           // ISO date string
	merchant: string | null;
	notes: string | null;
	source: string;
	created_at: string;
	updated_at: string;
	shared_expense_id: number | null; // non-null when this row is one half of a shared expense
}

export interface ExpenseCreate {
	amount_str: string;           // e.g. "42.50" or "1500" for JPY
	original_currency: string;
	category_id: number;
	occurred_on: string;          // ISO date string
	merchant?: string;
	notes?: string;
}

export interface ExpenseUpdate {
	amount_str?: string;
	original_currency?: string;
	category_id?: number;
	occurred_on?: string;
	merchant?: string;
	notes?: string;
}

// Report types — field names mirror backend Pydantic schemas exactly.
export interface CategorySlice {
	name: string;       // matches backend CategorySlice.name
	color: string;
	icon: string;
	total_sgd_minor: number;
	expense_count: number;
}

/** @deprecated Use CategorySlice. Kept for backward compatibility. */
export type CategoryReportRow = CategorySlice & { category_name?: string };

export interface MonthlyReport {
	total_sgd_minor: number;  // matches backend MonthlyReport.total_sgd_minor
	expense_count: number;
	categories: CategorySlice[];
}

export interface MonthRow {
	month: number;
	total_sgd_minor: number;  // matches backend MonthRow.total_sgd_minor
	expense_count: number;
	top_category: string | null;
}

/** @deprecated Use MonthRow. */
export type YearlyMonthRow = MonthRow;

export interface YearlyReport {
	total_sgd_minor: number;  // matches backend YearlyReport.total_sgd_minor
	months: MonthRow[];
}

export type UserFilter = 'mine' | 'partner' | 'both';

// ─── Shared-expense / settlement types (mirror backend Pydantic schemas) ──────

export type SplitMethod = 'equal' | 'percent' | 'exact';

export interface SharedExpenseCreate {
	amount: string; // money crosses the wire as a string — exact Decimal parsing server-side
	currency: string;
	occurred_on: string; // ISO date string
	split_method: SplitMethod;
	payer_category_id: number;
	partner_category_id: number;
	merchant?: string;
	payer_pct?: number;
	partner_pct?: number;
	payer_amount?: string;
	partner_amount?: string;
}

export interface SharedExpenseOut {
	id: number;
	payer_user_id: number;
	total_amount_minor: number;
	original_currency: string;
	split_method: SplitMethod;
	occurred_on: string;
	payer_expense_id: number;
	partner_expense_id: number;
}

/** Full detail view used by the web edit panel to pre-populate the SplitEditor. */
export interface SharedExpenseDetail {
	id: number;
	payer_user_id: number;
	partner_user_id: number;
	total_amount_minor: number;
	original_currency: string;
	split_method: SplitMethod;
	occurred_on: string;
	merchant: string | null;
	payer_expense_id: number;
	partner_expense_id: number;
	payer_share_minor: number;
	partner_share_minor: number;
	payer_category_id: number;
	partner_category_id: number;
}

export interface Settlement {
	id: number;
	from_user_id: number;
	to_user_id: number;
	amount_minor: number;
	currency: string;
	occurred_on: string;
	note: string | null;
	voided_at: string | null;
}

export interface SettlementCreate {
	from_user_id: number;
	to_user_id: number;
	amount: string;
	currency: string;
	occurred_on: string;
	note?: string;
}

export interface BalanceEntry {
	currency: string;
	net_minor: number;
}

export interface BalanceOut {
	partner_user_id: number;
	partner_display_name: string;
	entries: BalanceEntry[];
}

// ─── Budget types (mirror backend app/schemas/budget.py) ──────────────────────

export type BudgetBandName = 'healthy' | 'warning' | 'over';

export interface BudgetBandStatus {
	cap_minor: number;
	spent_minor: number;
	pct: number;
	band: BudgetBandName;
	left_minor: number;
	over_minor: number;
}

export interface CategoryBudgetStatus {
	category_id: number;
	name: string;
	color: string;
	icon: string;
	cap_minor: number;
	spent_minor: number;
	pct: number;
	band: BudgetBandName;
}

export interface BudgetStatus {
	period: string; // "YYYY-MM"
	total: BudgetBandStatus | null;
	categories: CategoryBudgetStatus[];
}

/** Raw cap row for form pre-fill (GET /api/budgets). */
export interface BudgetCap {
	category_id: number | null; // null = the user-total cap
	amount_minor: number;
}

// ─── Recurring-rule types (mirror backend app/schemas/recurring.py) ───────────

export type RecurringFrequency = 'monthly' | 'weekly' | 'monthly_nth';

export interface RecurringRule {
	id: number;
	name: string | null;
	amount_minor: number;
	currency: string;
	category_id: number;
	frequency: RecurringFrequency;
	day_of_month: number | null;
	weekday: number | null;
	starts_on: string; // ISO date string
	end_date: string | null;
	paused: boolean;
	is_shared: boolean;
	split_method: SplitMethod | null;
	partner_category_id: number | null;
	next_run: string | null; // ISO date string, null if the rule is exhausted
}

export interface RecurringRuleCreate {
	name?: string;
	amount: string; // money crosses the wire as a string — exact Decimal parsing server-side
	currency: string;
	category_id: number;
	frequency: RecurringFrequency;
	day_of_month?: number;
	weekday?: number;
	starts_on: string; // ISO date string
	end_date?: string;
	is_shared: boolean;
	split_method?: SplitMethod;
	payer_pct?: number;
	partner_pct?: number;
	payer_amount?: string;
	partner_amount?: string;
	partner_category_id?: number;
}

// ─── Core fetch helper ────────────────────────────────────────────────────────

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
	const res = await fetch(path, {
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		...init,
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: res.statusText }));
		throw new Error(err.detail ?? 'Request failed');
	}
	// 204 No Content
	if (res.status === 204) return undefined as unknown as T;
	return res.json();
}

// ─── API object ───────────────────────────────────────────────────────────────

export const api = {
	auth: {
		login: (username: string, password: string) =>
			fetchJSON<{ ok: boolean; user: User }>(`${AUTH_BASE}/login`, {
				method: 'POST',
				body: JSON.stringify({ username, password }),
			}),

		logout: () =>
			fetchJSON<{ ok: boolean }>(`${AUTH_BASE}/logout`, { method: 'POST' }),

		me: () => fetchJSON<User>(`${AUTH_BASE}/me`),
	},

	expenses: {
		list: (params?: { year?: number; month?: number; user?: UserFilter }) => {
			const qs = new URLSearchParams();
			if (params?.year != null) qs.set('year', String(params.year));
			if (params?.month != null) qs.set('month', String(params.month));
			if (params?.user) qs.set('user', params.user);
			const q = qs.toString();
			return fetchJSON<Expense[]>(`${API_BASE}/expenses${q ? `?${q}` : ''}`);
		},

		create: (data: ExpenseCreate) =>
			fetchJSON<Expense>(`${API_BASE}/expenses`, {
				method: 'POST',
				// Backend ExpenseCreate uses `amount`/`currency`; the client models them as
				// `amount_str`/`original_currency`. Map to the wire contract here.
				body: JSON.stringify({
					amount: data.amount_str,
					currency: data.original_currency,
					category_id: data.category_id,
					occurred_on: data.occurred_on,
					merchant: data.merchant,
					notes: data.notes,
				}),
			}),

		update: (id: number, data: ExpenseUpdate) =>
			fetchJSON<Expense>(`${API_BASE}/expenses/${id}`, {
				method: 'PATCH',
				// Map client field names to the backend ExpenseUpdate contract.
				// Undefined fields are dropped by JSON.stringify, preserving PATCH semantics.
				body: JSON.stringify({
					amount: data.amount_str,
					currency: data.original_currency,
					category_id: data.category_id,
					occurred_on: data.occurred_on,
					merchant: data.merchant,
					notes: data.notes,
				}),
			}),

		delete: (id: number) =>
			fetchJSON<{ ok: boolean }>(`${API_BASE}/expenses/${id}`, { method: 'DELETE' }),
	},

	categories: {
		list: () => fetchJSON<Category[]>(`${API_BASE}/categories`),

		create: (data: CategoryCreate) =>
			fetchJSON<Category>(`${API_BASE}/categories`, {
				method: 'POST',
				body: JSON.stringify(data),
			}),

		update: (id: number, data: CategoryUpdate) =>
			fetchJSON<Category>(`${API_BASE}/categories/${id}`, {
				method: 'PATCH',
				body: JSON.stringify(data),
			}),

		delete: (id: number) =>
			fetchJSON<{ ok: boolean; reassigned: number }>(`${API_BASE}/categories/${id}`, {
				method: 'DELETE',
			}),
	},

	link: {
		generateLinkCode: (): Promise<{ code: string; expires_in_minutes: number }> =>
			fetchJSON<{ code: string; expires_in_minutes: number }>(`${API_BASE}/link/generate`, {
				method: 'POST',
			}),
	},

	sharedExpenses: {
		create: (data: SharedExpenseCreate) =>
			fetchJSON<SharedExpenseOut>(`${API_BASE}/shared-expenses`, {
				method: 'POST',
				body: JSON.stringify(data),
			}),

		get: (id: number) =>
			fetchJSON<SharedExpenseDetail>(`${API_BASE}/shared-expenses/${id}`),

		update: (id: number, data: SharedExpenseCreate) =>
			fetchJSON<SharedExpenseOut>(`${API_BASE}/shared-expenses/${id}`, {
				method: 'PATCH',
				body: JSON.stringify(data),
			}),

		delete: (id: number) =>
			fetchJSON<{ ok: boolean }>(`${API_BASE}/shared-expenses/${id}`, { method: 'DELETE' }),
	},

	settlements: {
		list: () => fetchJSON<Settlement[]>(`${API_BASE}/settlements`),

		create: (data: SettlementCreate) =>
			fetchJSON<Settlement>(`${API_BASE}/settlements`, {
				method: 'POST',
				body: JSON.stringify(data),
			}),

		void: (id: number) =>
			fetchJSON<{ ok: boolean }>(`${API_BASE}/settlements/${id}`, { method: 'DELETE' }),
	},

	balance: {
		get: () => fetchJSON<BalanceOut>(`${API_BASE}/balance`),
	},

	budgets: {
		status: (year?: number, month?: number) => {
			const qs = new URLSearchParams();
			if (year != null) qs.set('year', String(year));
			if (month != null) qs.set('month', String(month));
			const q = qs.toString();
			return fetchJSON<BudgetStatus>(`${API_BASE}/budgets/status${q ? `?${q}` : ''}`);
		},

		set: (amount: string, category_id?: number) =>
			fetchJSON<BudgetStatus>(`${API_BASE}/budgets`, {
				method: 'PUT',
				body: JSON.stringify({ amount, category_id }),
			}),

		remove: (category_id?: number) => {
			const qs = new URLSearchParams();
			if (category_id != null) qs.set('category_id', String(category_id));
			const q = qs.toString();
			return fetchJSON<{ ok: boolean }>(`${API_BASE}/budgets${q ? `?${q}` : ''}`, {
				method: 'DELETE',
			});
		},

		list: () => fetchJSON<BudgetCap[]>(`${API_BASE}/budgets`),
	},

	recurring: {
		list: () => fetchJSON<RecurringRule[]>(`${API_BASE}/recurring`),

		create: (data: RecurringRuleCreate) =>
			fetchJSON<RecurringRule>(`${API_BASE}/recurring`, {
				method: 'POST',
				body: JSON.stringify(data),
			}),

		update: (id: number, data: Partial<RecurringRuleCreate>) =>
			fetchJSON<RecurringRule>(`${API_BASE}/recurring/${id}`, {
				method: 'PATCH',
				body: JSON.stringify(data),
			}),

		pause: (id: number) =>
			fetchJSON<RecurringRule>(`${API_BASE}/recurring/${id}/pause`, { method: 'POST' }),

		resume: (id: number) =>
			fetchJSON<RecurringRule>(`${API_BASE}/recurring/${id}/resume`, { method: 'POST' }),

		delete: (id: number) =>
			fetchJSON<{ ok: boolean }>(`${API_BASE}/recurring/${id}`, { method: 'DELETE' }),
	},

	reports: {
		monthly: (year: number, month: number, user?: UserFilter) => {
			const qs = new URLSearchParams({ year: String(year), month: String(month) });
			if (user) qs.set('user', user);
			return fetchJSON<MonthlyReport>(`${API_BASE}/reports/monthly?${qs}`);
		},

		yearly: (year: number, user?: UserFilter) => {
			const qs = new URLSearchParams({ year: String(year) });
			if (user) qs.set('user', user);
			return fetchJSON<YearlyReport>(`${API_BASE}/reports/yearly?${qs}`);
		},

		category: (start: string, end: string, user?: UserFilter) => {
			const qs = new URLSearchParams({ start, end });
			if (user) qs.set('user', user);
			return fetchJSON<CategoryReportRow[]>(`${API_BASE}/reports/category?${qs}`);
		},
	},
};
