<script lang="ts">
	import { api, type MonthlyReport, type YearlyReport, type UserFilter } from '$lib/api.js';
	import { auth } from '$lib/stores/auth.js';
	import { formatSgd, formatMonthYear } from '$lib/format.js';
	import CategoryDonut from '$lib/components/CategoryDonut.svelte';
	import SpendBar from '$lib/components/SpendBar.svelte';
	import PeriodNav from '$lib/components/PeriodNav.svelte';
	import UserToggle from '$lib/components/UserToggle.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { Tabs, TabsList, TabsTrigger, TabsContent } from '$lib/components/ui/tabs/index.js';

	// ── Period & user state ─────────────────────────────────────────────────────
	const now = new Date();
	let year = $state(now.getFullYear());
	let month = $state(now.getMonth() + 1);
	let activeTab = $state<'monthly' | 'yearly'>('monthly');
	let userFilter = $state<UserFilter>('both');

	// ── Data state ──────────────────────────────────────────────────────────────
	let monthlyReport = $state<MonthlyReport | null>(null);
	let yearlyReport = $state<YearlyReport | null>(null);
	let loadingMonthly = $state(false);
	let loadingYearly = $state(false);
	let errorMonthly = $state('');
	let errorYearly = $state('');

	// ── Auth ────────────────────────────────────────────────────────────────────
	let myName = $derived($auth.user?.display_name ?? 'Mine');

	// ── Monthly derived ─────────────────────────────────────────────────────────
	let monthlySlices = $derived(
		monthlyReport
			? monthlyReport.categories.map((c) => ({
					name: c.name,
					color: c.color,
					total_sgd_minor: c.total_sgd_minor,
				}))
			: []
	);
	let monthlyBarLabels = $derived(monthlyReport ? monthlyReport.categories.map((c) => c.name) : []);
	let monthlyBarData = $derived(monthlyReport ? monthlyReport.categories.map((c) => c.total_sgd_minor) : []);
	let monthlyTotal = $derived(monthlyReport ? monthlyReport.total_sgd_minor : 0);
	let monthlyCount = $derived(monthlyReport ? monthlyReport.expense_count : 0);
	let monthlyEmpty = $derived(!loadingMonthly && (!monthlyReport || monthlyReport.categories.length === 0));

	// ── Yearly derived ──────────────────────────────────────────────────────────
	const MONTH_NAMES_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
	// 12-bar chart: one bar per calendar month (0 for months with no data)
	let yearlyBars = $derived(() => {
		const filled = Array(12).fill(0);
		if (yearlyReport) {
			for (const row of yearlyReport.months) {
				filled[row.month - 1] = row.total_sgd_minor;
			}
		}
		return filled;
	});
	let yearlyTotal = $derived(yearlyReport ? yearlyReport.total_sgd_minor : 0);
	let yearlyCount = $derived(yearlyReport ? yearlyReport.months.reduce((s, m) => s + m.expense_count, 0) : 0);
	let yearlyEmpty = $derived(!loadingYearly && (!yearlyReport || yearlyReport.months.length === 0));

	// ── Load functions ──────────────────────────────────────────────────────────
	async function loadMonthly() {
		loadingMonthly = true;
		errorMonthly = '';
		try {
			monthlyReport = await api.reports.monthly(year, month, userFilter);
		} catch {
			errorMonthly = "Couldn't load report data. Refresh the page to try again.";
		} finally {
			loadingMonthly = false;
		}
	}

	async function loadYearly() {
		loadingYearly = true;
		errorYearly = '';
		try {
			yearlyReport = await api.reports.yearly(year, userFilter);
		} catch {
			errorYearly = "Couldn't load report data. Refresh the page to try again.";
		} finally {
			loadingYearly = false;
		}
	}

	// Re-fetch whenever relevant state changes
	$effect(() => {
		void year;
		void month;
		void userFilter;
		loadMonthly();
	});

	$effect(() => {
		void year;
		void userFilter;
		loadYearly();
	});

	function handleMonthlyPeriodChange(period: { year: number; month?: number }) {
		year = period.year;
		if (period.month != null) month = period.month;
	}

	function handleYearlyPeriodChange(period: { year: number; month?: number }) {
		year = period.year;
	}

	function handleUserChange(value: UserFilter) {
		userFilter = value;
	}

	function handleTabChange(tab: string) {
		activeTab = tab as 'monthly' | 'yearly';
	}

	// Shared empty-state copy (Copywriting Contract)
	const EMPTY_HEADING = 'No data for this period';
	const EMPTY_BODY = "Add expenses and they'll appear here.";
</script>

<div>
	<!-- ── Heading row ─────────────────────────────────────────────────────────── -->
	<div class="flex items-center justify-between mb-4 flex-wrap gap-3">
		<h1 class="text-xl font-semibold text-[#0F172A]">Reports</h1>
		<UserToggle value={userFilter} {myName} onchange={handleUserChange} />
	</div>

	<!-- ── Tabs ────────────────────────────────────────────────────────────────── -->
	<Tabs value={activeTab} onValueChange={handleTabChange}>
		<TabsList class="mb-4">
			<TabsTrigger value="monthly">Monthly</TabsTrigger>
			<TabsTrigger value="yearly">Yearly</TabsTrigger>
		</TabsList>

		<!-- ── Monthly tab ───────────────────────────────────────────────────────── -->
		<TabsContent value="monthly">
			<div class="flex items-center justify-between mb-4 flex-wrap gap-2">
				<span class="text-sm text-[#64748B]">{formatMonthYear(year, month)}</span>
				<PeriodNav {year} {month} mode="monthly" onchange={handleMonthlyPeriodChange} />
			</div>

			{#if errorMonthly}
				<div class="rounded-md bg-[#FEF2F2] border border-[#EF4444] text-[#EF4444] text-sm px-4 py-3 mb-4">
					{errorMonthly}
				</div>
			{/if}

			{#if monthlyEmpty}
				<!-- Empty state -->
				<div class="flex flex-col items-center justify-center py-16 gap-2 text-center">
					<p class="text-sm font-semibold text-[#0F172A]">{EMPTY_HEADING}</p>
					<p class="text-sm text-[#64748B]">{EMPTY_BODY}</p>
				</div>
			{:else}
				<!-- Charts row -->
				<div class="grid grid-cols-2 gap-6 mb-6">
					{#if loadingMonthly}
						<Skeleton class="h-[240px] rounded-lg" />
						<Skeleton class="h-[240px] rounded-lg" />
					{:else}
						<div class="rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-4">
							<p class="text-sm font-semibold text-[#0F172A] mb-3">Spend by Category</p>
							<CategoryDonut slices={monthlySlices} height={240} />
						</div>
						<div class="rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-4">
							<p class="text-sm font-semibold text-[#0F172A] mb-3">Daily Spend</p>
							<SpendBar labels={monthlyBarLabels} data={monthlyBarData} title="Daily Spend" height={240} />
						</div>
					{/if}
				</div>

				<!-- Monthly breakdown table -->
				<div class="rounded-lg border border-[#E2E8F0] bg-white overflow-hidden">
					<div class="px-4 py-3 border-b border-[#E2E8F0]">
						<h2 class="text-base font-semibold text-[#0F172A]">Category Breakdown</h2>
					</div>
					{#if loadingMonthly}
						<div class="p-4">
							<Skeleton class="h-40 rounded" />
						</div>
					{:else}
						<table class="w-full text-sm">
							<thead>
								<tr class="bg-[#F8FAFC] border-b border-[#E2E8F0]">
									<th class="text-left px-4 py-2 text-[12px] font-semibold text-[#64748B]">Category</th>
									<th class="text-right px-4 py-2 text-[12px] font-semibold text-[#64748B]">Amount</th>
									<th class="text-right px-4 py-2 text-[12px] font-semibold text-[#64748B]">% of Total</th>
									<th class="text-right px-4 py-2 text-[12px] font-semibold text-[#64748B]"># Expenses</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-[#E2E8F0]">
								{#each (monthlyReport?.categories ?? []) as cat}
									<tr class="min-h-[44px]">
										<td class="px-4 py-3">
											<div class="flex items-center gap-2">
												<span class="inline-block w-3 h-3 rounded-full flex-shrink-0" style="background-color: {cat.color};"></span>
												<span class="text-[#0F172A]">{cat.name}</span>
											</div>
										</td>
										<td class="px-4 py-3 text-right tabular-nums text-[#0F172A]">
											{formatSgd(cat.total_sgd_minor)}
										</td>
										<td class="px-4 py-3 text-right tabular-nums text-[#64748B]">
											{monthlyTotal > 0 ? ((cat.total_sgd_minor / monthlyTotal) * 100).toFixed(1) + '%' : '0%'}
										</td>
										<td class="px-4 py-3 text-right tabular-nums text-[#0F172A]">
											{cat.expense_count}
										</td>
									</tr>
								{/each}
							</tbody>
							<!-- Footer: Total row -->
							<tfoot>
								<tr class="border-t-2 border-[#E2E8F0] bg-[#F8FAFC]">
									<td class="px-4 py-3 text-sm font-semibold text-[#0F172A]">Total</td>
									<td class="px-4 py-3 text-right tabular-nums font-semibold text-[#0F172A]">
										{formatSgd(monthlyTotal)}
									</td>
									<td class="px-4 py-3 text-right tabular-nums font-semibold text-[#0F172A]">100%</td>
									<td class="px-4 py-3 text-right tabular-nums font-semibold text-[#0F172A]">
										{monthlyCount}
									</td>
								</tr>
							</tfoot>
						</table>
					{/if}
				</div>
			{/if}
		</TabsContent>

		<!-- ── Yearly tab ─────────────────────────────────────────────────────────── -->
		<TabsContent value="yearly">
			<div class="flex items-center justify-between mb-4 flex-wrap gap-2">
				<span class="text-sm text-[#64748B]">{year}</span>
				<PeriodNav {year} mode="yearly" onchange={handleYearlyPeriodChange} />
			</div>

			{#if errorYearly}
				<div class="rounded-md bg-[#FEF2F2] border border-[#EF4444] text-[#EF4444] text-sm px-4 py-3 mb-4">
					{errorYearly}
				</div>
			{/if}

			{#if yearlyEmpty}
				<!-- Empty state -->
				<div class="flex flex-col items-center justify-center py-16 gap-2 text-center">
					<p class="text-sm font-semibold text-[#0F172A]">{EMPTY_HEADING}</p>
					<p class="text-sm text-[#64748B]">{EMPTY_BODY}</p>
				</div>
			{:else}
				<!-- Full-width bar chart: 12 monthly bars -->
				<div class="rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-4 mb-6">
					<p class="text-sm font-semibold text-[#0F172A] mb-3">Monthly Spend {year}</p>
					{#if loadingYearly}
						<Skeleton class="h-[240px] rounded" />
					{:else}
						<SpendBar
							labels={MONTH_NAMES_SHORT}
							data={yearlyBars()}
							title="Monthly Spend {year}"
							height={240}
						/>
					{/if}
				</div>

				<!-- Month by Month table -->
				<div class="rounded-lg border border-[#E2E8F0] bg-white overflow-hidden">
					<div class="px-4 py-3 border-b border-[#E2E8F0]">
						<h2 class="text-base font-semibold text-[#0F172A]">Month by Month</h2>
					</div>
					{#if loadingYearly}
						<div class="p-4">
							<Skeleton class="h-40 rounded" />
						</div>
					{:else}
						<table class="w-full text-sm">
							<thead>
								<tr class="bg-[#F8FAFC] border-b border-[#E2E8F0]">
									<th class="text-left px-4 py-2 text-[12px] font-semibold text-[#64748B]">Month</th>
									<th class="text-right px-4 py-2 text-[12px] font-semibold text-[#64748B]">Total</th>
									<th class="text-left px-4 py-2 text-[12px] font-semibold text-[#64748B]">Top Category</th>
									<th class="text-right px-4 py-2 text-[12px] font-semibold text-[#64748B]"># Expenses</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-[#E2E8F0]">
								{#each (yearlyReport?.months ?? []) as row}
									<tr class="min-h-[44px]">
										<td class="px-4 py-3 text-[#0F172A]">
											{formatMonthYear(year, row.month)}
										</td>
										<td class="px-4 py-3 text-right tabular-nums text-[#0F172A]">
											{formatSgd(row.total_sgd_minor)}
										</td>
										<td class="px-4 py-3 text-[#64748B]">
											{row.top_category ?? '—'}
										</td>
										<td class="px-4 py-3 text-right tabular-nums text-[#0F172A]">
											{row.expense_count}
										</td>
									</tr>
								{/each}
							</tbody>
							<!-- Footer -->
							<tfoot>
								<tr class="border-t-2 border-[#E2E8F0] bg-[#F8FAFC]">
									<td class="px-4 py-3 text-sm font-semibold text-[#0F172A]">Total</td>
									<td class="px-4 py-3 text-right tabular-nums font-semibold text-[#0F172A]">
										{formatSgd(yearlyTotal)}
									</td>
									<td class="px-4 py-3 text-[#64748B]">—</td>
									<td class="px-4 py-3 text-right tabular-nums font-semibold text-[#0F172A]">
										{yearlyCount}
									</td>
								</tr>
							</tfoot>
						</table>
					{/if}
				</div>
			{/if}
		</TabsContent>
	</Tabs>
</div>
