<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type BudgetStatus, type Category } from '$lib/api.js';
	import { formatMonthYear } from '$lib/format.js';
	import BudgetForm from '$lib/components/BudgetForm.svelte';

	const now = new Date();
	const year = now.getFullYear();
	const month = now.getMonth() + 1;

	let status = $state<BudgetStatus | null>(null);
	let categories = $state<Category[]>([]);
	let loading = $state(true);
	let error = $state('');

	async function load() {
		loading = true;
		error = '';
		try {
			const [statusResult, categoriesResult] = await Promise.all([
				api.budgets.status(),
				api.categories.list(),
			]);
			status = statusResult;
			categories = categoriesResult;
		} catch {
			error = "Couldn't load budget. Refresh to try again.";
		} finally {
			loading = false;
		}
	}

	onMount(load);
</script>

<div>
	<div class="flex items-start justify-between mb-1 flex-wrap gap-4">
		<h1 class="text-xl font-semibold text-[#0F172A]">Budgets</h1>
	</div>
	<p class="text-sm text-[#64748B] mb-1">
		Set a monthly cap and track your spending against it. Budgets reset on the 1st.
	</p>
	<p class="text-xs text-[#64748B] mb-6">This month: {formatMonthYear(year, month)}</p>

	{#if loading}
		<!-- Loading: skeleton input + skeleton bar + 5 skeleton rows -->
		<div class="rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-4">
			<div class="h-3 w-40 bg-[#E2E8F0] rounded animate-pulse mb-3"></div>
			<div class="h-10 w-40 bg-[#E2E8F0] rounded-lg animate-pulse"></div>
			<div class="h-2 w-full bg-[#E2E8F0] rounded-full animate-pulse mt-4"></div>
		</div>
		<div class="mt-6 rounded-lg border border-[#E2E8F0] overflow-hidden">
			<div class="divide-y divide-[#E2E8F0]">
				{#each { length: 5 } as _, i (i)}
					<div class="flex items-center gap-3 px-4 py-3 min-h-[44px]">
						<div class="h-4 flex-1 bg-[#E2E8F0] rounded animate-pulse"></div>
					</div>
				{/each}
			</div>
		</div>
	{:else if error}
		<p class="text-sm text-[#EF4444]">{error}</p>
	{:else if status}
		{#if !status.total}
			<div class="mb-4">
				<h2 class="text-base font-semibold text-[#0F172A]">No budget set yet</h2>
				<p class="text-sm text-[#64748B] mt-1">
					Set a monthly total below to start tracking your spending against it.
				</p>
			</div>
		{/if}
		<BudgetForm {status} {categories} onsaved={load} />
	{/if}
</div>
