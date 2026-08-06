<script lang="ts">
	import { onMount } from 'svelte';
	import Loader2 from '@lucide/svelte/icons/loader-2';
	import { api, type Category, type SplitMethod } from '$lib/api.js';
	import { toast } from '$lib/stores/toast.js';
	import CategoryPicker from './CategoryPicker.svelte';
	import SplitEditor from './SplitEditor.svelte';

	let {
		onAdd = () => {},
		categories = [] as Category[],
		partnerName = 'Partner',
		partnerCategories = [] as Category[],
	}: {
		onAdd?: () => void;
		categories?: Category[];
		partnerName?: string;
		partnerCategories?: Category[];
	} = $props();

	// ─── Form state ───────────────────────────────────────────────────────────────

	// Today's date in YYYY-MM-DD for the date input default
	function todayStr(): string {
		const d = new Date();
		const yyyy = d.getFullYear();
		const mm = String(d.getMonth() + 1).padStart(2, '0');
		const dd = String(d.getDate()).padStart(2, '0');
		return `${yyyy}-${mm}-${dd}`;
	}

	let amount = $state('');
	let currency = $state('SGD');
	let date = $state(todayStr());
	let categoryId = $state<number | null>(null);
	let merchant = $state('');
	let notes = $state('');
	let showNotes = $state(false);
	let submitting = $state(false);

	// ─── Split-with-partner state ─────────────────────────────────────────────────
	let splitOn = $state(false);
	let splitMethod = $state<SplitMethod>('equal');
	let payerPct = $state(50);
	let partnerPct = $state(50);
	let payerAmount = $state('');
	let partnerAmount = $state('');
	let partnerCategoryId = $state<number | null>(null);
	let splitValid = $state(true);

	// ─── Validation errors ────────────────────────────────────────────────────────
	let errors = $state({
		amount: '',
		category: '',
		date: '',
		partnerCategory: '',
	});

	function validate(): boolean {
		errors.amount = '';
		errors.category = '';
		errors.date = '';
		errors.partnerCategory = '';

		let valid = true;

		if (!amount || amount.trim() === '') {
			errors.amount = 'Amount is required. Check the highlighted fields and try again.';
			valid = false;
		} else {
			// Use unary + for validation only — amount is still passed as a string to the API
			const numVal = +amount.trim();
			if (isNaN(numVal) || numVal <= 0) {
				errors.amount = 'Enter a valid amount greater than zero.';
				valid = false;
			}
		}

		if (categoryId === null) {
			errors.category = 'Category is required. Check the highlighted fields and try again.';
			valid = false;
		}

		if (!date) {
			errors.date = 'Date is required. Check the highlighted fields and try again.';
			valid = false;
		}

		if (splitOn && !splitValid) {
			valid = false;
		}

		if (splitOn && partnerCategoryId === null) {
			errors.partnerCategory = `${partnerName}'s category is required. Check the highlighted fields and try again.`;
			valid = false;
		}

		return valid;
	}

	// ─── Submit ───────────────────────────────────────────────────────────────────

	let amountInputRef: HTMLInputElement | null = null;

	async function handleSubmit(e: Event) {
		e.preventDefault();
		if (!validate()) return;

		submitting = true;
		const wasShared = splitOn;
		try {
			if (splitOn) {
				await api.sharedExpenses.create({
					amount: amount.trim(),
					currency,
					occurred_on: date,
					split_method: splitMethod,
					payer_category_id: categoryId!,
					partner_category_id: partnerCategoryId!,
					merchant: merchant.trim() || undefined,
					payer_pct: splitMethod === 'percent' ? payerPct : undefined,
					partner_pct: splitMethod === 'percent' ? partnerPct : undefined,
					payer_amount: splitMethod === 'exact' ? payerAmount.trim() : undefined,
					partner_amount: splitMethod === 'exact' ? partnerAmount.trim() : undefined,
				});
			} else {
				await api.expenses.create({
					amount_str: amount.trim(), // always string — decimal precision preserved
					original_currency: currency,
					category_id: categoryId!,
					occurred_on: date,
					merchant: merchant.trim() || undefined,
					notes: notes.trim() || undefined,
				});
			}

			// Clear form (keep currency and date), re-focus amount
			amount = '';
			categoryId = null;
			merchant = '';
			notes = '';
			showNotes = false;
			splitOn = false;
			splitMethod = 'equal';
			payerPct = 50;
			partnerPct = 50;
			payerAmount = '';
			partnerAmount = '';
			partnerCategoryId = null;

			// Re-focus amount field
			setTimeout(() => amountInputRef?.focus(), 0);

			toast.show(wasShared ? 'Shared expense added' : 'Expense added');
			onAdd();
		} catch (err) {
			errors.amount = err instanceof Error ? err.message : 'Failed to add expense.';
		} finally {
			submitting = false;
		}
	}
</script>

<form
	onsubmit={handleSubmit}
	class="bg-[#F8FAFC] rounded-lg border border-[#E2E8F0] p-4"
>
	<!-- Single-row layout on desktop -->
	<div class="flex items-start gap-2 flex-wrap">
		<!-- Amount -->
		<div class="flex flex-col gap-1 shrink-0" style="width: 96px">
			<input
				bind:this={amountInputRef}
				bind:value={amount}
				type="text"
				inputmode="decimal"
				placeholder="0.00"
				class={[
					'h-10 px-2.5 rounded-lg border text-sm tabular-nums bg-white w-full outline-none transition-colors',
					'focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]',
					errors.amount ? 'border-[#EF4444]' : 'border-[#E2E8F0]',
				].join(' ')}
				disabled={submitting}
			/>
			{#if errors.amount}
				<p class="text-xs text-[#EF4444] leading-tight">{errors.amount}</p>
			{/if}
		</div>

		<!-- Currency select -->
		<div class="shrink-0" style="width: 80px">
			<select
				bind:value={currency}
				class="h-10 px-2 rounded-lg border border-[#E2E8F0] text-sm bg-white text-[#0F172A] w-full outline-none
				       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5] cursor-pointer"
				disabled={submitting}
			>
				<option value="SGD">SGD</option>
				<option value="USD">USD</option>
				<option value="MYR">MYR</option>
				<option value="EUR">EUR</option>
				<option value="JPY">JPY</option>
			</select>
		</div>

		<!-- Date picker -->
		<div class="flex flex-col gap-1 shrink-0" style="width: 140px">
			<input
				bind:value={date}
				type="date"
				class={[
					'h-10 px-2.5 rounded-lg border text-sm bg-white text-[#0F172A] w-full outline-none transition-colors cursor-pointer',
					'focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]',
					errors.date ? 'border-[#EF4444]' : 'border-[#E2E8F0]',
				].join(' ')}
				disabled={submitting}
			/>
			{#if errors.date}
				<p class="text-xs text-[#EF4444] leading-tight">{errors.date}</p>
			{/if}
		</div>

		<!-- Category picker -->
		<div class="flex flex-col gap-1 shrink-0">
			<CategoryPicker bind:categoryId {categories} error={!!errors.category} />
			{#if errors.category}
				<p class="text-xs text-[#EF4444] leading-tight">{errors.category}</p>
			{/if}
		</div>

		<!-- Merchant input (flex-grow) -->
		<div class="flex flex-col gap-1 flex-1 min-w-[140px]">
			<input
				bind:value={merchant}
				type="text"
				placeholder="Expense name (optional)"
				class="h-10 px-2.5 rounded-lg border border-[#E2E8F0] text-sm bg-white text-[#0F172A]
				       placeholder:text-[#64748B] w-full outline-none transition-colors
				       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]"
				disabled={submitting}
			/>
		</div>

		<!-- Split-with-partner toggle -->
		<div class="shrink-0 self-start">
			<button
				type="button"
				role="switch"
				aria-checked={splitOn}
				onclick={() => (splitOn = !splitOn)}
				class={[
					'h-10 px-3 rounded-lg border text-sm font-medium whitespace-nowrap transition-colors flex items-center gap-2',
					splitOn
						? 'border-[#4F46E5] bg-indigo-50 text-[#4F46E5]'
						: 'border-[#E2E8F0] bg-white text-[#64748B] hover:bg-[#F8FAFC]',
				].join(' ')}
				disabled={submitting}
			>
				<span class={['inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0', splitOn ? 'bg-[#4F46E5]' : 'bg-[#E2E8F0]'].join(' ')}>
					<span class={['inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform', splitOn ? 'translate-x-4' : 'translate-x-0.5'].join(' ')}></span>
				</span>
				Split with {partnerName}
			</button>
		</div>

		<!-- Add Expense button -->
		<div class="shrink-0 self-start">
			<button
				type="submit"
				disabled={submitting || (splitOn && !splitValid)}
				class="h-10 px-4 bg-[#4F46E5] text-white text-sm font-semibold rounded-lg whitespace-nowrap
				       hover:bg-[#4338CA] transition-colors disabled:opacity-60 disabled:cursor-not-allowed
				       flex items-center gap-2"
			>
				{#if submitting}
					<Loader2 size={16} class="animate-spin" />
				{/if}
				{splitOn ? 'Add Shared Expense' : 'Add Expense'}
			</button>
		</div>
	</div>

	<!-- Split editor panel (expands when the toggle is on) -->
	{#if splitOn}
		<div class="mt-3">
			<SplitEditor
				total={amount}
				{currency}
				{partnerName}
				{partnerCategories}
				categoryError={!!errors.partnerCategory}
				payerCategoryId={categoryId}
				mirrorPayerCategory={true}
				bind:splitMethod
				bind:payerPct
				bind:partnerPct
				bind:payerAmount
				bind:partnerAmount
				bind:partnerCategoryId
				bind:valid={splitValid}
			/>
			{#if errors.partnerCategory}
				<p class="text-xs text-[#EF4444] leading-tight mt-1">{errors.partnerCategory}</p>
			{/if}
		</div>
	{/if}

	<!-- "Add note" toggle + textarea -->
	{#if !showNotes}
		<button
			type="button"
			onclick={() => (showNotes = true)}
			class="mt-2 text-sm text-[#64748B] hover:text-[#4F46E5] transition-colors"
		>
			Add note
		</button>
	{:else}
		<div class="mt-2">
			<textarea
				bind:value={notes}
				placeholder="Notes (optional)"
				rows={2}
				class="w-full px-2.5 py-2 rounded-lg border border-[#E2E8F0] text-sm bg-white text-[#0F172A]
				       placeholder:text-[#64748B] outline-none resize-none transition-colors
				       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]"
				disabled={submitting}
			></textarea>
		</div>
	{/if}
</form>
