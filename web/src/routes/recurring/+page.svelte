<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type Category, type RecurringRule } from '$lib/api.js';
	import { auth } from '$lib/stores/auth.js';
	import RecurringList from '$lib/components/RecurringList.svelte';
	import RecurringForm from '$lib/components/RecurringForm.svelte';
	import Plus from '@lucide/svelte/icons/plus';

	let rules = $state<RecurringRule[]>([]);
	let categories = $state<Category[]>([]);
	let loading = $state(true);
	let error = $state('');

	// Partner display name — same documented interim as the rest of the app
	// no partner-scoped categories endpoint yet, so the payer's own
	// category list is reused for the partner-category picker.
	let partnerName = $derived($auth.user?.partner_display_name ?? 'Partner');

	let formOpen = $state(false);
	let editingRule = $state<RecurringRule | null>(null);

	async function load() {
		loading = true;
		error = '';
		try {
			const [rulesResult, categoriesResult] = await Promise.all([
				api.recurring.list(),
				api.categories.list(),
			]);
			rules = rulesResult;
			categories = categoriesResult;
		} catch {
			error = "Couldn't load recurring rules. Refresh to try again.";
		} finally {
			loading = false;
		}
	}

	onMount(load);

	function openAdd() {
		editingRule = null;
		formOpen = true;
	}

	function openEdit(rule: RecurringRule) {
		editingRule = rule;
		formOpen = true;
	}

	async function handleSaved() {
		await load();
	}

	async function handleChanged() {
		await load();
	}
</script>

<div>
	<div class="flex items-start justify-between mb-1 flex-wrap gap-4">
		<h1 class="text-xl font-semibold text-[#0F172A]">Recurring</h1>
		<button
			type="button"
			onclick={openAdd}
			class="h-10 px-4 bg-[#4F46E5] text-white text-sm font-semibold rounded-lg
			       hover:bg-[#4338CA] transition-colors flex items-center gap-2"
		>
			<Plus size={16} />
			Add Recurring
		</button>
	</div>
	<p class="text-sm text-[#64748B] mb-6">
		Rules that log expenses automatically on a schedule. Edits apply to future runs only.
	</p>

	{#if loading}
		<!-- 4 skeleton rows -->
		<div class="rounded-lg border border-[#E2E8F0] overflow-hidden">
			<div class="divide-y divide-[#E2E8F0]">
				{#each { length: 4 } as _, i (i)}
					<div class="flex items-center gap-3 px-4 py-3" style="min-height: 44px">
						<div class="w-3 h-3 rounded-full bg-[#E2E8F0] animate-pulse shrink-0"></div>
						<div class="flex flex-col gap-1 flex-1">
							<div class="h-4 w-48 bg-[#E2E8F0] rounded animate-pulse"></div>
							<div class="h-3 w-32 bg-[#E2E8F0] rounded animate-pulse"></div>
						</div>
					</div>
				{/each}
			</div>
		</div>
	{:else if error}
		<p class="text-sm text-[#64748B]">{error}</p>
	{:else if rules.length === 0}
		<div class="py-16 text-center rounded-lg border border-[#E2E8F0]">
			<p class="text-base font-semibold text-[#0F172A] mb-1">No recurring expenses yet</p>
			<p class="text-sm text-[#64748B]">
				Add a rule for rent, subscriptions, or anything that repeats and it'll log itself on schedule.
			</p>
		</div>
	{:else}
		<RecurringList {rules} {categories} {partnerName} onedit={openEdit} onchanged={handleChanged} />
	{/if}
</div>

<RecurringForm bind:open={formOpen} rule={editingRule} {categories} {partnerName} onsaved={handleSaved} />
