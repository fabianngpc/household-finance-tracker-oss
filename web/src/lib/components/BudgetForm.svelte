<script lang="ts">
	import { api, type BudgetStatus, type Category } from '$lib/api.js';
	import { toast } from '$lib/stores/toast.js';
	import { formatSgd } from '$lib/format.js';
	import BudgetBar from './BudgetBar.svelte';
	import Loader2 from '@lucide/svelte/icons/loader-2';

	let {
		status,
		categories,
		onsaved = () => {},
	}: {
		status: BudgetStatus;
		categories: Category[];
		onsaved?: () => void;
	} = $props();

	// ─── Total block ────────────────────────────────────────────────────────────
	let totalAmount = $state('');
	let totalError = $state('');
	let savingTotal = $state(false);

	function validateAmount(value: string): string {
		const trimmed = value.trim();
		if (trimmed === '') return 'Enter a monthly total budget greater than zero.';
		const num = +trimmed;
		if (!isFinite(num) || num <= 0) return 'Enter a valid amount greater than zero.';
		return '';
	}

	async function saveTotal() {
		totalError = validateAmount(totalAmount);
		if (totalError) return;
		savingTotal = true;
		try {
			await api.budgets.set(totalAmount.trim());
			toast.show('Budget saved');
			totalAmount = '';
			onsaved();
		} catch (err) {
			totalError = err instanceof Error ? err.message : 'Failed to save budget.';
		} finally {
			savingTotal = false;
		}
	}

	// ─── Per-category block ─────────────────────────────────────────────────────
	let categoryAmounts = $state<Record<number, string>>({});
	let categoryErrors = $state<Record<number, string>>({});
	let savingCategory = $state<Record<number, boolean>>({});
	let removingCategory = $state<Record<number, boolean>>({});

	function capFor(categoryId: number) {
		return status.categories.find((c) => c.category_id === categoryId) ?? null;
	}

	async function saveCategory(categoryId: number) {
		const value = categoryAmounts[categoryId] ?? '';
		const err = validateAmount(value);
		categoryErrors = { ...categoryErrors, [categoryId]: err };
		if (err) return;
		savingCategory = { ...savingCategory, [categoryId]: true };
		try {
			await api.budgets.set(value.trim(), categoryId);
			toast.show('Budget saved');
			categoryAmounts = { ...categoryAmounts, [categoryId]: '' };
			onsaved();
		} catch (e) {
			categoryErrors = {
				...categoryErrors,
				[categoryId]: e instanceof Error ? e.message : 'Failed to save cap.',
			};
		} finally {
			savingCategory = { ...savingCategory, [categoryId]: false };
		}
	}

	async function removeCategory(categoryId: number) {
		removingCategory = { ...removingCategory, [categoryId]: true };
		try {
			await api.budgets.remove(categoryId);
			toast.show('Budget saved');
			onsaved();
		} catch (e) {
			categoryErrors = {
				...categoryErrors,
				[categoryId]: e instanceof Error ? e.message : 'Failed to remove cap.',
			};
		} finally {
			removingCategory = { ...removingCategory, [categoryId]: false };
		}
	}
</script>

<!-- ── Total block ─────────────────────────────────────────────────────────── -->
<div class="rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-4">
	<label for="total-budget-input" class="text-sm font-semibold text-[#0F172A]">
		Monthly total budget
	</label>
	<p class="text-xs text-[#64748B] mt-1">Your overall cap for the month, in SGD. Required.</p>

	<div class="flex items-center gap-2 mt-3 flex-wrap">
		<div class="relative shrink-0" style="width: 140px">
			<span
				class="absolute left-2.5 top-1/2 -translate-y-1/2 text-sm text-[#64748B] pointer-events-none"
			>
				S$
			</span>
			<input
				id="total-budget-input"
				bind:value={totalAmount}
				type="text"
				inputmode="decimal"
				placeholder={status.total ? String(status.total.cap_minor / 100) : '0.00'}
				class={[
					'h-10 pl-7 pr-2.5 rounded-lg border text-sm tabular-nums bg-white w-full outline-none transition-colors',
					'focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]',
					totalError ? 'border-[#EF4444]' : 'border-[#E2E8F0]',
				].join(' ')}
				disabled={savingTotal}
			/>
		</div>
		<button
			type="button"
			onclick={saveTotal}
			disabled={savingTotal}
			class="h-10 px-4 bg-[#4F46E5] text-white text-sm font-semibold rounded-lg
			       hover:bg-[#4338CA] transition-colors disabled:opacity-60 flex items-center gap-2"
		>
			{#if savingTotal}
				<Loader2 size={14} class="animate-spin" />
			{/if}
			{status.total ? 'Save Budget' : 'Set Budget'}
		</button>
	</div>
	{#if totalError}
		<p class="text-xs text-[#EF4444] leading-tight mt-1">{totalError}</p>
	{/if}

	{#if status.total}
		<div class="mt-4">
			<BudgetBar pct={status.total.pct} band={status.total.band} />
			<p class="text-sm text-[#64748B] mt-2 tabular-nums">
				{formatSgd(status.total.spent_minor)} / {formatSgd(status.total.cap_minor)} · {status.total.pct}%
			</p>
		</div>
	{/if}
</div>

<!-- ── Per-category block ──────────────────────────────────────────────────── -->
{#if status.total}
	<div class="mt-6">
		<h2 class="text-sm font-semibold text-[#0F172A]">Category caps (optional)</h2>
		<p class="text-xs text-[#64748B] mt-1">
			Set caps on the categories you want to watch. These are tracked for you but don't send alerts.
		</p>

		<div class="mt-3 rounded-lg border border-[#E2E8F0] overflow-hidden">
			<div class="divide-y divide-[#E2E8F0]">
				{#each categories as category (category.id)}
					{@const cap = capFor(category.id)}
					<div class="flex items-center justify-between gap-3 px-4 py-2.5 min-h-[44px] flex-wrap">
						<div class="flex items-center gap-2 min-w-0">
							<span
								class="w-3 h-3 rounded-full shrink-0"
								style="background-color: {category.color}"
							></span>
							<span class="text-sm font-semibold text-[#0F172A] truncate">{category.name}</span>
						</div>

						{#if cap}
							<div class="flex items-center gap-3 flex-wrap">
								<div class="w-24 hidden sm:block">
									<BudgetBar pct={cap.pct} band={cap.band} />
								</div>
								<span class="text-sm text-[#64748B] tabular-nums whitespace-nowrap">
									{formatSgd(cap.spent_minor)} / {formatSgd(cap.cap_minor)} · {cap.pct}%
								</span>
								<button
									type="button"
									onclick={() => removeCategory(category.id)}
									disabled={removingCategory[category.id]}
									class="text-sm text-[#64748B] hover:text-[#EF4444] transition-colors disabled:opacity-60"
								>
									Remove cap
								</button>
							</div>
						{:else}
							<div class="flex items-center gap-2 flex-wrap">
								<span class="text-sm text-[#64748B]">No cap set</span>
								<input
									bind:value={categoryAmounts[category.id]}
									type="text"
									inputmode="decimal"
									placeholder="S$ amount"
									class={[
										'h-10 px-2.5 rounded-lg border text-sm tabular-nums bg-white w-28 outline-none transition-colors',
										'focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]',
										categoryErrors[category.id] ? 'border-[#EF4444]' : 'border-[#E2E8F0]',
									].join(' ')}
									disabled={savingCategory[category.id]}
								/>
								<button
									type="button"
									onclick={() => saveCategory(category.id)}
									disabled={savingCategory[category.id]}
									class="h-10 px-3 bg-[#4F46E5] text-white text-sm font-semibold rounded-lg
									       hover:bg-[#4338CA] transition-colors disabled:opacity-60 flex items-center gap-2"
								>
									{#if savingCategory[category.id]}
										<Loader2 size={14} class="animate-spin" />
									{/if}
									Set cap
								</button>
							</div>
						{/if}
						{#if categoryErrors[category.id]}
							<p class="text-xs text-[#EF4444] leading-tight w-full">{categoryErrors[category.id]}</p>
						{/if}
					</div>
				{/each}
			</div>
		</div>
	</div>
{/if}
