<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type MonthlyReport, type Expense, type Category, type UserFilter } from '$lib/api.js';
	import { auth } from '$lib/stores/auth.js';
	import { formatSgd, formatDate, formatMonthYear } from '$lib/format.js';
	import CategoryDonut from '$lib/components/CategoryDonut.svelte';
	import SpendBar from '$lib/components/SpendBar.svelte';
	import PeriodNav from '$lib/components/PeriodNav.svelte';
	import UserToggle from '$lib/components/UserToggle.svelte';
	import BalanceCard from '$lib/components/BalanceCard.svelte';
	import BudgetCard from '$lib/components/BudgetCard.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { Plus } from '@lucide/svelte';

	// ── Period & user state ─────────────────────────────────────────────────────
	const now = new Date();
	let year = $state(now.getFullYear());
	let month = $state(now.getMonth() + 1);
	let userFilter = $state<UserFilter>('both');

	// ── Data state ──────────────────────────────────────────────────────────────
	let bothReport = $state<MonthlyReport | null>(null);
	let mineReport = $state<MonthlyReport | null>(null);
	let partnerReport = $state<MonthlyReport | null>(null);
	let recentExpenses = $state<Expense[]>([]);
	let categories = $state<Category[]>([]);
	let loading = $state(true);
	let error = $state('');

	// ── Auth ────────────────────────────────────────────────────────────────────
	let myName = $derived($auth.user?.display_name ?? 'Mine');
	let partnerName = $derived($auth.user?.partner_display_name ?? 'Partner');

	// ── Chart report follows the toggle ───────────────────────────────────────────
	let chartReport = $derived(
		userFilter === 'mine' ? mineReport : userFilter === 'partner' ? partnerReport : bothReport
	);

	// ── Summary-rail figures (independent of the toggle) ──────────────────────────
	let totalSpend = $derived(bothReport ? formatSgd(bothReport.total_sgd_minor) : 'S$0.00');
	let mineSpend = $derived(mineReport ? formatSgd(mineReport.total_sgd_minor) : 'S$0.00');
	let partnerSpend = $derived(partnerReport ? formatSgd(partnerReport.total_sgd_minor) : 'S$0.00');
	let expenseCount = $derived(bothReport ? bothReport.expense_count : 0);
	let topCategory = $derived(
		bothReport && bothReport.categories.length > 0 ? bothReport.categories[0] : null
	);

	// ── Chart data ────────────────────────────────────────────────────────────────
	let donutSlices = $derived(
		chartReport
			? chartReport.categories.map((c) => ({ name: c.name, color: c.color, total_sgd_minor: c.total_sgd_minor }))
			: []
	);
	let barLabels = $derived(chartReport ? chartReport.categories.map((c) => c.name) : []);
	let barData = $derived(chartReport ? chartReport.categories.map((c) => c.total_sgd_minor) : []);

	// ── Category lookup helpers ─────────────────────────────────────────────────
	function getCategory(id: number): Category | undefined {
		return categories.find((c) => c.id === id);
	}

	// ── Load functions ──────────────────────────────────────────────────────────
	async function loadReport() {
		loading = true;
		error = '';
		try {
			const [both, mine, partner, expenses] = await Promise.all([
				api.reports.monthly(year, month, 'both'),
				api.reports.monthly(year, month, 'mine'),
				api.reports.monthly(year, month, 'partner'),
				api.expenses.list({ year, month, user: userFilter }),
			]);
			bothReport = both;
			mineReport = mine;
			partnerReport = partner;
			recentExpenses = expenses.slice(0, 5);
		} catch {
			error = "Couldn't load data. Refresh the page to try again.";
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		api.categories.list().then((cats) => { categories = cats; }).catch(() => {});
	});

	// Re-fetch whenever period or user filter changes (also runs on mount)
	$effect(() => {
		void year;
		void month;
		void userFilter;
		loadReport();
	});

	function handlePeriodChange(period: { year: number; month?: number }) {
		year = period.year;
		if (period.month != null) month = period.month;
	}

	function handleUserChange(value: UserFilter) {
		userFilter = value;
	}
</script>

<div>
	<!-- ── Heading row ─────────────────────────────────────────────────────────── -->
	<div class="flex items-start justify-between mb-6 flex-wrap gap-4">
		<div>
			<h1 class="text-[30px] font-bold text-[#0F172A] leading-[1.1]">Dashboard</h1>
			<p class="text-sm text-[#64748B] mt-1">{formatMonthYear(year, month)}</p>
		</div>
		<a
			href="/expenses"
			class="h-10 px-4 inline-flex items-center gap-2 bg-[#4F46E5] text-white text-sm font-semibold rounded-lg hover:bg-[#4338CA] transition-colors"
		>
			<Plus size={16} />
			Add expense
		</a>
	</div>

	<!-- ── Controls row ────────────────────────────────────────────────────────── -->
	<div class="flex items-center justify-between mb-6 flex-wrap gap-3">
		<UserToggle value={userFilter} {myName} {partnerName} onchange={handleUserChange} />
		<PeriodNav {year} {month} mode="monthly" onchange={handlePeriodChange} />
	</div>

	{#if error}
		<div class="rounded-md bg-[#FEF2F2] border border-[#EF4444] text-[#EF4444] text-sm px-4 py-3 mb-6">
			{error}
		</div>
	{/if}

	<!-- ── Balance with partner — full width, above the stat cards, independent of the toggle ── -->
	<div class="mb-6">
		<BalanceCard />
	</div>

	<!-- ── Two-column layout: main content + summary rail ──────────────────────── -->
	<div class="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6 items-start">
		<!-- ── Main column ─────────────────────────────────────────────────────── -->
		<div class="flex flex-col gap-6 min-w-0">
			<!-- Charts row -->
			<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
				{#if loading}
					<Skeleton class="h-[200px] rounded-lg" />
					<Skeleton class="h-[200px] rounded-lg" />
				{:else}
					<div class="rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-4">
						<p class="text-sm font-semibold text-[#0F172A] mb-3">Spend by Category</p>
						<CategoryDonut slices={donutSlices} />
					</div>
					<div class="rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-4">
						<p class="text-sm font-semibold text-[#0F172A] mb-3">This Month</p>
						<SpendBar labels={barLabels} data={barData} title="This Month" />
					</div>
				{/if}
			</div>

			<!-- Recent expenses (avatar rows) -->
			<div class="rounded-lg border border-[#E2E8F0] bg-white overflow-hidden">
				<div class="flex items-center justify-between px-4 py-3 border-b border-[#E2E8F0]">
					<h2 class="text-base font-semibold text-[#0F172A]">Recent Transactions</h2>
					<a href="/expenses" class="text-sm font-medium text-[#4F46E5] hover:underline">View all →</a>
				</div>

				{#if loading}
					<div class="divide-y divide-[#E2E8F0]">
						{#each { length: 5 } as _, i (i)}
							<div class="flex items-center gap-3 px-4 py-3">
								<Skeleton class="w-8 h-8 rounded-full shrink-0" />
								<Skeleton class="h-4 flex-1 rounded" />
							</div>
						{/each}
					</div>
				{:else if recentExpenses.length === 0}
					<div class="px-4 py-8 text-center">
						<p class="text-sm text-[#64748B]">No transactions yet this period.</p>
					</div>
				{:else}
					<div class="divide-y divide-[#E2E8F0]">
						{#each recentExpenses as expense (expense.id)}
							{@const cat = getCategory(expense.category_id)}
							<div class="flex items-center gap-3 px-4 py-3 min-h-[56px]">
								<!-- Circular category-color avatar (monogram) -->
								<span
									class="w-8 h-8 rounded-full shrink-0 flex items-center justify-center text-xs font-semibold text-white"
									style="background-color: {cat?.color ?? '#6B7280'}"
									title={cat?.name ?? 'Uncategorized'}
								>
									{(cat?.name ?? expense.merchant ?? '?').slice(0, 1).toUpperCase()}
								</span>
								<!-- Merchant + category -->
								<div class="flex flex-col min-w-0 flex-1">
									<span class="text-sm font-medium text-[#0F172A] leading-tight truncate">
										{expense.merchant ?? cat?.name ?? '—'}
									</span>
									<span class="text-xs text-[#64748B] leading-tight truncate">
										{cat?.name ?? 'Uncategorized'} · {formatDate(expense.occurred_on)}
									</span>
								</div>
								<!-- Amount -->
								<span class="text-sm font-semibold tabular-nums text-[#0F172A] text-right whitespace-nowrap">
									{formatSgd(expense.amount_base_minor)}
								</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<!-- ── Summary rail ─────────────────────────────────────────────────────── -->
		<aside class="rounded-lg border border-[#E2E8F0] bg-white p-5 lg:sticky lg:top-6">
			<!-- Budget card — independent of the Mine/Partner/Both toggle, sits at the top of the rail -->
			<div class="mb-5">
				<BudgetCard />
			</div>

			<div class="flex items-center justify-between mb-5">
				<h2 class="text-base font-semibold text-[#0F172A]">This month</h2>
				<span class="text-xs text-[#64748B]">{formatMonthYear(year, month)}</span>
			</div>

			{#if loading}
				<div class="flex flex-col gap-5">
					{#each { length: 3 } as _, i (i)}
						<div class="flex flex-col gap-1.5">
							<Skeleton class="h-3 w-20 rounded" />
							<Skeleton class="h-7 w-28 rounded" />
						</div>
					{/each}
				</div>
			{:else}
				<div class="flex flex-col divide-y divide-[#E2E8F0]">
					<!-- Total spend (hero) -->
					<div class="pb-4">
						<p class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">Total Spend</p>
						<p class="text-[30px] font-bold text-[#0F172A] leading-[1.1] tabular-nums mt-1">{totalSpend}</p>
						<p class="text-xs text-[#64748B] mt-1">{expenseCount} transaction{expenseCount === 1 ? '' : 's'}</p>
					</div>

					<!-- Per-person breakdown -->
					<div class="py-4 flex items-center justify-between">
						<span class="text-sm text-[#64748B]">{myName}</span>
						<span class="text-lg font-bold text-[#0F172A] tabular-nums">{mineSpend}</span>
					</div>
					<div class="py-4 flex items-center justify-between">
						<span class="text-sm text-[#64748B]">{partnerName}</span>
						<span class="text-lg font-bold text-[#0F172A] tabular-nums">{partnerSpend}</span>
					</div>

					<!-- Top category -->
					<div class="pt-4 flex items-center justify-between">
						<span class="text-sm text-[#64748B]">Top Category</span>
						<span class="inline-flex items-center gap-1.5">
							{#if topCategory}
								<span class="w-3 h-3 rounded-full shrink-0" style="background-color: {topCategory.color}"></span>
								<span class="text-sm font-semibold text-[#0F172A]">{topCategory.name}</span>
							{:else}
								<span class="text-sm font-semibold text-[#0F172A]">—</span>
							{/if}
						</span>
					</div>
				</div>
			{/if}
		</aside>
	</div>
</div>
