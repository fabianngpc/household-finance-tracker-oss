<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type Expense, type Category } from '$lib/api.js';
	import { auth } from '$lib/stores/auth.js';
	import ExpenseForm from '$lib/components/ExpenseForm.svelte';
	import ExpenseTable from '$lib/components/ExpenseTable.svelte';

	let expenses = $state<Expense[]>([]);
	let categories = $state<Category[]>([]);
	let loading = $state(true);
	let error = $state('');

	// Partner display name for the split-editor's "Split with {partner}" affordances.
	// NOTE: the backend has no partner-scoped categories endpoint yet — the payer's own category list is reused for the
	// partner-category picker until a dedicated endpoint exists.
	let partnerName = $derived($auth.user?.partner_display_name ?? 'Partner');

	async function loadExpenses() {
		try {
			error = '';
			expenses = await api.expenses.list();
		} catch {
			error = "Couldn't load expenses. Refresh the page to try again.";
		}
	}

	async function loadCategories() {
		try {
			categories = await api.categories.list();
		} catch {
			// non-fatal — CategoryPicker will fetch its own list if needed
		}
	}

	onMount(async () => {
		loading = true;
		await Promise.all([loadExpenses(), loadCategories()]);
		loading = false;
	});

	async function handleAdd() {
		await loadExpenses();
	}

	async function handleRefresh() {
		await loadExpenses();
	}
</script>

<div>
	<h1 class="text-xl font-semibold text-[#0F172A] mb-6">Expenses</h1>

	<!-- Inline entry form -->
	<ExpenseForm onAdd={handleAdd} {categories} {partnerName} partnerCategories={categories} />

	<!-- Table (24px gap) -->
	<div class="mt-6">
		{#if error}
			<p class="text-sm text-[#EF4444]">{error}</p>
		{:else}
			<ExpenseTable
				{expenses}
				{categories}
				{loading}
				onRefresh={handleRefresh}
				{partnerName}
				partnerCategories={categories}
			/>
		{/if}
	</div>
</div>
