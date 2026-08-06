<script lang="ts">
	import { api, type Expense, type Category, type SplitMethod } from '$lib/api.js';
	import { formatDate, formatOriginal, formatSgd, minorToInputString } from '$lib/format.js';
	import { toast } from '$lib/stores/toast.js';
	import CategoryPicker from './CategoryPicker.svelte';
	import SplitEditor from './SplitEditor.svelte';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Loader2 from '@lucide/svelte/icons/loader-2';

	let {
		expenses = [] as Expense[],
		categories = [] as Category[],
		loading = false,
		onRefresh = () => {},
		partnerName = 'Partner',
		partnerCategories = [] as Category[],
	}: {
		expenses?: Expense[];
		categories?: Category[];
		loading?: boolean;
		onRefresh?: () => void;
		partnerName?: string;
		partnerCategories?: Category[];
	} = $props();

	// ─── Inline edit state ────────────────────────────────────────────────────────

	let editingId = $state<number | null>(null);
	let editAmount = $state('');
	let editCurrency = $state('SGD');
	let editDate = $state('');
	let editCategoryId = $state<number | null>(null);
	let editMerchant = $state('');
	let editNotes = $state('');
	let saving = $state(false);

	function startEdit(expense: Expense) {
		if (expense.shared_expense_id != null) {
			startSharedEdit(expense.shared_expense_id);
			return;
		}
		sharedEditId = null; // close any open shared-edit panel — only one row edits at a time
		editingId = expense.id;
		editAmount = minorToInputString(expense.original_amount_minor, expense.original_currency);
		editCurrency = expense.original_currency;
		editDate = expense.occurred_on;
		editCategoryId = expense.category_id;
		editMerchant = expense.merchant ?? '';
		editNotes = expense.notes ?? '';
	}

	function cancelEdit() {
		editingId = null;
	}

	// ─── Shared-expense inline edit (split panel, pre-populated) ──────────────────

	let sharedEditId = $state<number | null>(null); // the shared_expense_id being edited
	let sharedEditLoading = $state(false);
	let sharedEditTotal = $state('');
	let sharedEditCurrency = $state('SGD');
	let sharedEditDate = $state('');
	let sharedEditMerchant = $state('');
	let sharedEditSplitMethod = $state<SplitMethod>('equal');
	let sharedEditPayerPct = $state(50);
	let sharedEditPartnerPct = $state(50);
	let sharedEditPayerAmount = $state('');
	let sharedEditPartnerAmount = $state('');
	let sharedEditPayerCategoryId = $state<number | null>(null);
	let sharedEditPartnerCategoryId = $state<number | null>(null);
	let sharedEditValid = $state(true);
	let sharedSaving = $state(false);

	async function startSharedEdit(sharedId: number) {
		editingId = null; // ensure the plain inline editor is closed
		sharedEditId = sharedId;
		sharedEditLoading = true;
		try {
			const detail = await api.sharedExpenses.get(sharedId);
			sharedEditTotal = minorToInputString(detail.total_amount_minor, detail.original_currency);
			sharedEditCurrency = detail.original_currency;
			sharedEditDate = detail.occurred_on;
			sharedEditMerchant = detail.merchant ?? '';
			sharedEditSplitMethod = detail.split_method;
			sharedEditPayerCategoryId = detail.payer_category_id;
			sharedEditPartnerCategoryId = detail.partner_category_id;

			if (detail.split_method === 'exact') {
				sharedEditPayerAmount = minorToInputString(detail.payer_share_minor, detail.original_currency);
				sharedEditPartnerAmount = minorToInputString(detail.partner_share_minor, detail.original_currency);
			} else {
				sharedEditPayerAmount = '';
				sharedEditPartnerAmount = '';
			}

			if (detail.split_method === 'percent' && detail.total_amount_minor > 0) {
				const pct = Math.round((detail.payer_share_minor / detail.total_amount_minor) * 100);
				sharedEditPayerPct = pct;
				sharedEditPartnerPct = 100 - pct;
			} else {
				sharedEditPayerPct = 50;
				sharedEditPartnerPct = 50;
			}
		} catch (err) {
			alert(err instanceof Error ? err.message : 'Failed to load shared expense.');
			sharedEditId = null;
		} finally {
			sharedEditLoading = false;
		}
	}

	function cancelSharedEdit() {
		sharedEditId = null;
	}

	async function saveSharedEdit() {
		if (sharedEditId === null) return;
		sharedSaving = true;
		try {
			await api.sharedExpenses.update(sharedEditId, {
				amount: sharedEditTotal.trim(),
				currency: sharedEditCurrency,
				occurred_on: sharedEditDate,
				split_method: sharedEditSplitMethod,
				payer_category_id: sharedEditPayerCategoryId!,
				partner_category_id: sharedEditPartnerCategoryId!,
				merchant: sharedEditMerchant.trim() || undefined,
				payer_pct: sharedEditSplitMethod === 'percent' ? sharedEditPayerPct : undefined,
				partner_pct: sharedEditSplitMethod === 'percent' ? sharedEditPartnerPct : undefined,
				payer_amount: sharedEditSplitMethod === 'exact' ? sharedEditPayerAmount.trim() : undefined,
				partner_amount: sharedEditSplitMethod === 'exact' ? sharedEditPartnerAmount.trim() : undefined,
			});
			sharedEditId = null;
			toast.show('Shared expense updated');
			onRefresh();
		} catch (err) {
			alert(err instanceof Error ? err.message : 'Failed to save shared expense.');
		} finally {
			sharedSaving = false;
		}
	}

	async function saveEdit(expense: Expense) {
		saving = true;
		try {
			await api.expenses.update(expense.id, {
				amount_str: editAmount.trim(),
				original_currency: editCurrency,
				occurred_on: editDate,
				category_id: editCategoryId ?? undefined,
				merchant: editMerchant.trim() || undefined,
				notes: editNotes.trim() || undefined,
			});
			editingId = null;
			onRefresh();
		} catch (err) {
			alert(err instanceof Error ? err.message : 'Failed to save.');
		} finally {
			saving = false;
		}
	}

	// ─── Delete state ─────────────────────────────────────────────────────────────

	let deletingId = $state<number | null>(null);
	let deleteDialogOpen = $state(false);
	let deleting = $state(false);

	function openDeleteDialog(id: number) {
		deletingId = id;
		deleteDialogOpen = true;
	}

	function cancelDelete() {
		deletingId = null;
		deleteDialogOpen = false;
	}

	async function confirmDelete() {
		if (deletingId === null) return;
		deleting = true;
		try {
			const target = expenses.find((e) => e.id === deletingId);
			if (target?.shared_expense_id != null) {
				// Shared child row — delete via the shared-expense endpoint so both
				// linked per-user rows + the header are removed atomically (never
				// hits the generic delete's 409 guard, never orphans the partner's row).
				await api.sharedExpenses.delete(target.shared_expense_id);
				toast.show('Shared expense deleted');
			} else {
				await api.expenses.delete(deletingId);
				toast.show('Expense deleted');
			}
			deleteDialogOpen = false;
			deletingId = null;
			onRefresh();
		} catch (err) {
			alert(err instanceof Error ? err.message : 'Failed to delete.');
		} finally {
			deleting = false;
		}
	}

	// ─── Helpers ──────────────────────────────────────────────────────────────────

	function getCategoryById(id: number): Category | undefined {
		return categories.find((c) => c.id === id);
	}

	const CURRENCIES = ['SGD', 'USD', 'MYR', 'EUR', 'JPY'];
</script>

<!-- Delete confirmation dialog -->
{#if deleteDialogOpen}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center"
		role="dialog"
		aria-modal="true"
		aria-labelledby="delete-dialog-title"
	>
		<!-- Overlay -->
		<button
			type="button"
			class="absolute inset-0 bg-black/50 cursor-default"
			onclick={cancelDelete}
			aria-label="Close dialog"
			tabindex="-1"
		></button>
		<!-- Dialog content -->
		<div class="relative bg-white rounded-lg border border-[#E2E8F0] p-6 shadow-xl max-w-sm w-full mx-4">
			<h2 id="delete-dialog-title" class="text-lg font-semibold text-[#0F172A] mb-2">
				Delete expense?
			</h2>
			<p class="text-sm text-[#64748B] mb-6">This cannot be undone.</p>
			<div class="flex items-center justify-between gap-3">
				<button
					type="button"
					onclick={cancelDelete}
					class="text-sm text-[#0F172A] hover:text-[#64748B] transition-colors"
					disabled={deleting}
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={confirmDelete}
					disabled={deleting}
					class="h-9 px-4 bg-[#EF4444] text-white text-sm font-semibold rounded-lg
					       hover:bg-red-600 transition-colors disabled:opacity-60 flex items-center gap-2"
				>
					{#if deleting}
						<Loader2 size={14} class="animate-spin" />
					{/if}
					Delete Expense
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- Expense table -->
<div class="rounded-lg border border-[#E2E8F0] overflow-hidden">
	<!-- Header row -->
	<div
		class="grid bg-[#F8FAFC] border-b border-[#E2E8F0] px-4 py-2"
		style="grid-template-columns: 120px 1fr 120px 110px 80px"
	>
		<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">Date</span>
		<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">Expense name</span>
		<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide text-right">Amount</span>
		<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide text-right">SGD</span>
		<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide text-right">Actions</span>
	</div>

	{#if loading}
		<!-- 5 skeleton rows -->
		{#each Array(5) as _, i (i)}
			<div
				class="grid px-4 py-3 border-b border-[#E2E8F0] last:border-b-0 items-center"
				style="grid-template-columns: 120px 1fr 120px 110px 80px; min-height: 56px"
			>
				<div class="h-4 w-20 bg-[#E2E8F0] rounded animate-pulse"></div>
				<div class="flex items-center gap-2.5">
					<div class="w-8 h-8 rounded-full bg-[#E2E8F0] animate-pulse shrink-0"></div>
					<div class="h-4 w-32 bg-[#E2E8F0] rounded animate-pulse"></div>
				</div>
				<div class="h-4 w-16 bg-[#E2E8F0] rounded animate-pulse ml-auto"></div>
				<div class="h-4 w-16 bg-[#E2E8F0] rounded animate-pulse ml-auto"></div>
				<div class="h-4 w-12 bg-[#E2E8F0] rounded animate-pulse ml-auto"></div>
			</div>
		{/each}
	{:else if expenses.length === 0}
		<!-- Empty state -->
		<div class="py-16 text-center">
			<p class="text-base font-semibold text-[#0F172A] mb-1">No expenses yet</p>
			<p class="text-sm text-[#64748B]">Add your first expense above to start tracking this month.</p>
		</div>
	{:else}
		{#each expenses as expense (expense.id)}
			{@const category = getCategoryById(expense.category_id)}
			{#if expense.shared_expense_id != null && sharedEditId === expense.shared_expense_id}
				<!-- Shared-expense edit panel (pre-populated split editor) -->
				<div class="px-4 py-3 border-b border-[#E2E8F0] last:border-b-0 bg-[#F8FAFC] flex flex-col gap-3">
					{#if sharedEditLoading}
						<p class="text-sm text-[#64748B]">Loading shared expense…</p>
					{:else}
						<div class="flex items-start gap-2 flex-wrap">
							<input
								bind:value={sharedEditTotal}
								type="text"
								inputmode="decimal"
								class="h-9 px-2.5 rounded-lg border border-[#E2E8F0] text-sm bg-white tabular-nums
								       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5] outline-none"
								style="width: 96px"
								disabled={sharedSaving}
							/>
							<select
								bind:value={sharedEditCurrency}
								class="h-9 px-2 rounded-lg border border-[#E2E8F0] text-sm bg-white
								       focus:ring-2 focus:ring-[#4F46E5]/30 outline-none cursor-pointer"
								style="width: 80px"
								disabled={sharedSaving}
							>
								{#each CURRENCIES as c (c)}
									<option value={c}>{c}</option>
								{/each}
							</select>
							<input
								bind:value={sharedEditDate}
								type="date"
								class="h-9 px-2.5 rounded-lg border border-[#E2E8F0] text-sm bg-white
								       focus:ring-2 focus:ring-[#4F46E5]/30 outline-none cursor-pointer"
								style="width: 136px"
								disabled={sharedSaving}
							/>
							<CategoryPicker bind:categoryId={sharedEditPayerCategoryId} {categories} />
							<input
								bind:value={sharedEditMerchant}
								type="text"
								placeholder="Expense name (optional)"
								class="h-9 px-2.5 rounded-lg border border-[#E2E8F0] text-sm bg-white flex-1
								       focus:ring-2 focus:ring-[#4F46E5]/30 outline-none min-w-[120px]"
								disabled={sharedSaving}
							/>
						</div>

						<SplitEditor
							total={sharedEditTotal}
							currency={sharedEditCurrency}
							{partnerName}
							partnerCategories={partnerCategories.length ? partnerCategories : categories}
							bind:splitMethod={sharedEditSplitMethod}
							bind:payerPct={sharedEditPayerPct}
							bind:partnerPct={sharedEditPartnerPct}
							bind:payerAmount={sharedEditPayerAmount}
							bind:partnerAmount={sharedEditPartnerAmount}
							bind:partnerCategoryId={sharedEditPartnerCategoryId}
							bind:valid={sharedEditValid}
						/>

						<div class="flex items-center gap-2">
							<button
								type="button"
								onclick={saveSharedEdit}
								disabled={sharedSaving || !sharedEditValid}
								class="h-9 px-3 bg-[#4F46E5] text-white text-sm font-medium rounded-lg
								       hover:bg-[#4338CA] transition-colors disabled:opacity-60 flex items-center gap-1"
							>
								{#if sharedSaving}
									<Loader2 size={13} class="animate-spin" />
								{/if}
								Save
							</button>
							<button
								type="button"
								onclick={cancelSharedEdit}
								disabled={sharedSaving}
								class="h-9 px-3 text-sm text-[#64748B] hover:text-[#0F172A] transition-colors"
							>
								Cancel
							</button>
						</div>
					{/if}
				</div>
			{:else if editingId === expense.id}
				<!-- Inline edit row -->
				<div
					class="px-4 py-2 border-b border-[#E2E8F0] last:border-b-0 bg-[#F8FAFC]"
					style="min-height: 44px"
				>
					<div class="flex items-start gap-2 flex-wrap">
						<!-- Amount -->
						<input
							bind:value={editAmount}
							type="text"
							inputmode="decimal"
							class="h-9 px-2.5 rounded-lg border border-[#E2E8F0] text-sm bg-white tabular-nums
							       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5] outline-none"
							style="width: 88px"
							disabled={saving}
						/>
						<!-- Currency -->
						<select
							bind:value={editCurrency}
							class="h-9 px-2 rounded-lg border border-[#E2E8F0] text-sm bg-white
							       focus:ring-2 focus:ring-[#4F46E5]/30 outline-none cursor-pointer"
							style="width: 76px"
							disabled={saving}
						>
							{#each CURRENCIES as c (c)}
								<option value={c}>{c}</option>
							{/each}
						</select>
						<!-- Date -->
						<input
							bind:value={editDate}
							type="date"
							class="h-9 px-2.5 rounded-lg border border-[#E2E8F0] text-sm bg-white
							       focus:ring-2 focus:ring-[#4F46E5]/30 outline-none cursor-pointer"
							style="width: 136px"
							disabled={saving}
						/>
						<!-- Category -->
						<CategoryPicker bind:categoryId={editCategoryId} {categories} />
						<!-- Expense name -->
						<input
							bind:value={editMerchant}
							type="text"
							placeholder="Expense name (optional)"
							class="h-9 px-2.5 rounded-lg border border-[#E2E8F0] text-sm bg-white flex-1
							       focus:ring-2 focus:ring-[#4F46E5]/30 outline-none min-w-[120px]"
							disabled={saving}
						/>
						<!-- Save / Cancel -->
						<div class="flex items-center gap-2 shrink-0">
							<button
								type="button"
								onclick={() => saveEdit(expense)}
								disabled={saving}
								class="h-9 px-3 bg-[#4F46E5] text-white text-sm font-medium rounded-lg
								       hover:bg-[#4338CA] transition-colors disabled:opacity-60 flex items-center gap-1"
							>
								{#if saving}
									<Loader2 size={13} class="animate-spin" />
								{/if}
								Save
							</button>
							<button
								type="button"
								onclick={cancelEdit}
								disabled={saving}
								class="h-9 px-3 text-sm text-[#64748B] hover:text-[#0F172A] transition-colors"
							>
								Cancel
							</button>
						</div>
					</div>
				</div>
			{:else}
				<!-- Normal display row -->
				<div
					class="grid px-4 border-b border-[#E2E8F0] last:border-b-0 items-center"
					style="grid-template-columns: 120px 1fr 120px 110px 80px; min-height: 56px"
				>
					<!-- Date -->
					<span class="text-sm text-[#0F172A]">{formatDate(expense.occurred_on)}</span>

					<!-- Merchant + category (circular avatar monogram) -->
					<div class="flex items-center gap-2.5 min-w-0">
						<span
							class="w-8 h-8 rounded-full shrink-0 flex items-center justify-center text-xs font-semibold text-white"
							style="background-color: {category?.color ?? '#6B7280'}"
							title={category?.name ?? 'Uncategorized'}
						>
							{(category?.name ?? expense.merchant ?? '?').slice(0, 1).toUpperCase()}
						</span>
						<div class="flex flex-col min-w-0">
							<span class="text-sm font-medium text-[#0F172A] leading-tight truncate flex items-center gap-1.5">
								{expense.merchant ?? category?.name ?? '—'}
								{#if expense.shared_expense_id != null}
									<Badge variant="secondary" class="shrink-0">Split</Badge>
								{/if}
							</span>
							<span class="text-xs text-[#64748B] leading-tight truncate">
								{category?.name ?? 'Uncategorized'}
							</span>
						</div>
					</div>

					<!-- Amount (original) -->
					<span class="text-sm font-medium tabular-nums text-[#0F172A] text-right">
						{formatOriginal(expense.original_amount_minor, expense.original_currency)}
					</span>

					<!-- SGD Amount (only when currency != SGD) -->
					<span class="text-sm tabular-nums text-[#64748B] text-right">
						{#if expense.original_currency !== 'SGD'}
							{formatSgd(expense.amount_base_minor)}
						{/if}
					</span>

					<!-- Actions -->
					<div class="flex items-center justify-end gap-1">
						<button
							type="button"
							onclick={() => startEdit(expense)}
							class="w-10 h-10 flex items-center justify-center rounded-md text-[#64748B]
							       hover:text-[#4F46E5] hover:bg-[#F8FAFC] transition-colors"
							aria-label="Edit expense"
						>
							<Pencil size={16} />
						</button>
						<button
							type="button"
							onclick={() => openDeleteDialog(expense.id)}
							class="w-10 h-10 flex items-center justify-center rounded-md text-[#64748B]
							       hover:text-[#EF4444] hover:bg-red-50 transition-colors"
							aria-label="Delete expense"
						>
							<Trash2 size={16} />
						</button>
					</div>
				</div>
			{/if}
		{/each}
	{/if}
</div>
