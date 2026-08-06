<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api, type BudgetStatus, type BudgetBandName } from '$lib/api.js';
	import { formatSgd } from '$lib/format.js';
	import BudgetBar from './BudgetBar.svelte';

	let status = $state<BudgetStatus | null>(null);
	let loading = $state(true);
	let error = $state('');

	async function load() {
		loading = true;
		error = '';
		try {
			status = await api.budgets.status();
		} catch {
			error = "Couldn't load budget. Refresh to try again.";
		} finally {
			loading = false;
		}
	}

	onMount(load);

	const BAND_COLOR: Record<BudgetBandName, string> = {
		healthy: '#16A34A',
		warning: '#F59E0B',
		over: '#EF4444',
	};

	let total = $derived(status?.total ?? null);
	let pctColor = $derived(total ? BAND_COLOR[total.band] : '#64748B');

	function handleClick() {
		goto('/budgets');
	}
</script>

<button
	type="button"
	onclick={handleClick}
	class="w-full text-left rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-4 hover:border-[#4F46E5]/30 transition-colors"
>
	{#if loading}
		<!-- Skeleton: label bar + 8px bar + figure line -->
		<div class="flex flex-col gap-2">
			<div class="h-3 w-32 bg-[#E2E8F0] rounded animate-pulse"></div>
			<div class="h-2 w-full bg-[#E2E8F0] rounded-full animate-pulse"></div>
			<div class="h-3.5 w-40 bg-[#E2E8F0] rounded animate-pulse"></div>
		</div>
	{:else if error}
		<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">MONTHLY BUDGET</span>
		<p class="text-sm text-[#64748B] mt-2">{error}</p>
	{:else if !total}
		<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">MONTHLY BUDGET</span>
		<p class="text-sm font-semibold text-[#0F172A] mt-2">No budget yet</p>
		<span class="text-sm text-[#4F46E5] hover:underline">Set a monthly budget</span>
	{:else}
		<div class="flex items-center justify-between mb-2">
			<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">MONTHLY BUDGET</span>
			<span class="text-xs font-semibold tabular-nums" style="color: {pctColor};">{total.pct}%</span>
		</div>
		<BudgetBar pct={total.pct} band={total.band} />
		<p class="text-sm mt-2">
			<span class="font-semibold tabular-nums text-[#0F172A]">{formatSgd(total.spent_minor)}</span>
			<span class="text-[#64748B]"> / {formatSgd(total.cap_minor)}</span>
		</p>
		{#if total.band === 'over'}
			<p class="text-xs text-[#EF4444] mt-1">{formatSgd(total.over_minor)} over budget</p>
		{:else}
			<p class="text-xs text-[#64748B] mt-1">{formatSgd(total.left_minor)} left this month</p>
		{/if}
	{/if}
</button>
