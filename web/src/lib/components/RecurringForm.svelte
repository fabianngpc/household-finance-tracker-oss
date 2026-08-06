<script lang="ts">
	import { api, type Category, type RecurringFrequency, type RecurringRule, type SplitMethod } from '$lib/api.js';
	import { minorToInputString } from '$lib/format.js';
	import { toast } from '$lib/stores/toast.js';
	import CategoryPicker from './CategoryPicker.svelte';
	import SplitEditor from './SplitEditor.svelte';
	import Loader2 from '@lucide/svelte/icons/loader-2';

	let {
		rule = null as RecurringRule | null,
		categories = [] as Category[],
		partnerName = 'Partner',
		open = $bindable(false),
		onsaved = () => {},
	}: {
		rule?: RecurringRule | null;
		categories?: Category[];
		partnerName?: string;
		open?: boolean;
		onsaved?: () => void;
	} = $props();

	// Unique per-instance id prefix (this dialog can, in principle, be reused
	// for both the add and edit affordance without id collisions).
	const uid = $props.id();

	function todayStr(): string {
		const d = new Date();
		const yyyy = d.getFullYear();
		const mm = String(d.getMonth() + 1).padStart(2, '0');
		const dd = String(d.getDate()).padStart(2, '0');
		return `${yyyy}-${mm}-${dd}`;
	}

	const FREQUENCY_SEGMENTS: { id: RecurringFrequency; label: string }[] = [
		{ id: 'monthly', label: 'Monthly' },
		{ id: 'weekly', label: 'Weekly' },
		{ id: 'monthly_nth', label: 'Nth of month' },
	];

	const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

	// ─── Form state ───────────────────────────────────────────────────────────────

	let name = $state('');
	let amount = $state('');
	let currency = $state('SGD');
	let categoryId = $state<number | null>(null);
	let frequency = $state<RecurringFrequency>('monthly');
	let dayOfMonth = $state(1);
	let weekday = $state(0);
	let startsOn = $state(todayStr());
	let endDateOn = $state(false);
	let endDate = $state('');
	let splitOn = $state(false);
	let splitMethod = $state<SplitMethod>('equal');
	let payerPct = $state(50);
	let partnerPct = $state(50);
	let payerAmount = $state('');
	let partnerAmount = $state('');
	let partnerCategoryId = $state<number | null>(null);
	let splitValid = $state(true);
	let submitting = $state(false);
	let formError = $state('');

	let isEdit = $derived(rule !== null);

	// Reset form whenever the dialog opens (create or edit mode).
	$effect(() => {
		if (open) {
			formError = '';
			if (rule) {
				name = rule.name ?? '';
				amount = minorToInputString(rule.amount_minor, rule.currency);
				currency = rule.currency;
				categoryId = rule.category_id;
				frequency = rule.frequency;
				dayOfMonth = rule.day_of_month ?? 1;
				weekday = rule.weekday ?? 0;
				startsOn = rule.starts_on;
				endDateOn = rule.end_date != null;
				endDate = rule.end_date ?? '';
				splitOn = rule.is_shared;
				splitMethod = rule.split_method ?? 'equal';
				payerPct = 50;
				partnerPct = 50;
				payerAmount = '';
				partnerAmount = '';
				partnerCategoryId = rule.partner_category_id;
			} else {
				name = '';
				amount = '';
				currency = 'SGD';
				categoryId = null;
				frequency = 'monthly';
				dayOfMonth = 1;
				weekday = 0;
				startsOn = todayStr();
				endDateOn = false;
				endDate = '';
				splitOn = false;
				splitMethod = 'equal';
				payerPct = 50;
				partnerPct = 50;
				payerAmount = '';
				partnerAmount = '';
				partnerCategoryId = null;
			}
		}
	});

	function close() {
		open = false;
	}

	function validate(): boolean {
		formError = '';
		if (!amount.trim() || isNaN(+amount) || +amount <= 0) {
			formError = 'Enter a valid amount greater than zero.';
			return false;
		}
		if (categoryId === null) {
			formError = 'Category is required.';
			return false;
		}
		if ((frequency === 'monthly' || frequency === 'monthly_nth') && (dayOfMonth < 1 || dayOfMonth > 31)) {
			formError = 'Day must be between 1 and 31.';
			return false;
		}
		if (!startsOn) {
			formError = 'A start date is required.';
			return false;
		}
		if (endDateOn && !endDate) {
			formError = 'Enter an end date, or turn off "Set an end date".';
			return false;
		}
		if (splitOn && !splitValid) {
			return false;
		}
		if (splitOn && partnerCategoryId === null) {
			formError = `${partnerName}'s category is required.`;
			return false;
		}
		return true;
	}

	async function handleSubmit(e: Event) {
		e.preventDefault();
		if (!validate()) return;

		submitting = true;
		try {
			const data = {
				name: name.trim() || undefined,
				amount: amount.trim(),
				currency,
				category_id: categoryId!,
				frequency,
				day_of_month: frequency === 'weekly' ? undefined : dayOfMonth,
				weekday: frequency === 'weekly' ? weekday : undefined,
				starts_on: startsOn,
				end_date: endDateOn && endDate ? endDate : undefined,
				is_shared: splitOn,
				split_method: splitOn ? splitMethod : undefined,
				payer_pct: splitOn && splitMethod === 'percent' ? payerPct : undefined,
				partner_pct: splitOn && splitMethod === 'percent' ? partnerPct : undefined,
				payer_amount: splitOn && splitMethod === 'exact' ? payerAmount.trim() : undefined,
				partner_amount: splitOn && splitMethod === 'exact' ? partnerAmount.trim() : undefined,
				partner_category_id: splitOn ? partnerCategoryId! : undefined,
			};

			if (isEdit && rule) {
				await api.recurring.update(rule.id, data);
				toast.show('Recurring expense updated');
			} else {
				await api.recurring.create(data);
				toast.show('Recurring expense added');
			}
			close();
			onsaved();
		} catch (err) {
			formError = err instanceof Error ? err.message : 'Failed to save recurring expense.';
		} finally {
			submitting = false;
		}
	}
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center"
		role="dialog"
		aria-modal="true"
		aria-labelledby="{uid}-title"
	>
		<button
			type="button"
			class="absolute inset-0 bg-black/50 cursor-default"
			onclick={close}
			aria-label="Close dialog"
			tabindex="-1"
		></button>

		<!-- Recurring dialog exception: max-width 480px, max-height 85vh, internal scroll -->
		<div
			class="relative bg-white rounded-lg border border-[#E2E8F0] shadow-xl w-full mx-4 flex flex-col"
			style="max-width: 480px; max-height: 85vh"
		>
			<div class="p-6 pb-4 shrink-0">
				<h2 id="{uid}-title" class="text-lg font-semibold text-[#0F172A]">
					{isEdit ? 'Edit recurring expense' : 'New recurring expense'}
				</h2>
			</div>

			<form onsubmit={handleSubmit} class="flex flex-col overflow-hidden flex-1">
				<div class="px-6 flex flex-col gap-4 overflow-y-auto flex-1">
					<!-- Name -->
					<div class="flex flex-col gap-1">
						<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="{uid}-name">
							Name
						</label>
						<input
							id="{uid}-name"
							bind:value={name}
							type="text"
							placeholder="Rent, Netflix, gym…"
							class="h-10 px-3 rounded-lg border border-[#E2E8F0] text-sm bg-white text-[#0F172A]
							       placeholder:text-[#64748B] outline-none transition-colors
							       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]"
							disabled={submitting}
						/>
					</div>

					<!-- Amount + Currency -->
					<div class="flex items-end gap-2">
						<div class="flex flex-col gap-1 flex-1">
							<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="{uid}-amount">
								Amount
							</label>
							<input
								id="{uid}-amount"
								bind:value={amount}
								type="text"
								inputmode="decimal"
								placeholder="0.00"
								class="h-10 px-3 rounded-lg border border-[#E2E8F0] text-sm bg-white tabular-nums
								       outline-none transition-colors
								       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]"
								disabled={submitting}
							/>
						</div>
						<select
							bind:value={currency}
							class="h-10 px-2 rounded-lg border border-[#E2E8F0] text-sm bg-white text-[#0F172A]
							       outline-none focus:ring-2 focus:ring-[#4F46E5]/30 cursor-pointer"
							style="width: 88px"
							disabled={submitting}
						>
							<option value="SGD">SGD</option>
							<option value="USD">USD</option>
							<option value="MYR">MYR</option>
							<option value="EUR">EUR</option>
							<option value="JPY">JPY</option>
						</select>
					</div>

					<!-- Category -->
					<div class="flex flex-col gap-1">
						<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">Category</span>
						<CategoryPicker bind:categoryId {categories} inputId="{uid}-category" />
					</div>

					<!-- Repeats (frequency segments) -->
					<div class="flex flex-col gap-1.5">
						<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">Repeats</span>
						<div
							class="inline-flex items-center gap-0.5 rounded-lg border border-[#E2E8F0] bg-[#F1F5F9] p-0.5 w-fit"
							role="group"
							aria-label="Frequency"
						>
							{#each FREQUENCY_SEGMENTS as seg (seg.id)}
								<button
									type="button"
									onclick={() => (frequency = seg.id)}
									aria-pressed={frequency === seg.id}
									class={[
										'h-8 px-3 text-sm font-semibold rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-[#4F46E5]/30',
										frequency === seg.id
											? 'bg-white text-[#4F46E5] shadow-sm'
											: 'bg-transparent text-[#64748B] hover:text-[#0F172A]',
									].join(' ')}
									disabled={submitting}
								>
									{seg.label}
								</button>
							{/each}
						</div>
					</div>

					<!-- Conditional: day-of-month (monthly / monthly_nth) or weekday (weekly) -->
					{#if frequency === 'weekly'}
						<div class="flex flex-col gap-1">
							<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="{uid}-weekday">
								On
							</label>
							<select
								id="{uid}-weekday"
								bind:value={weekday}
								class="h-10 px-3 rounded-lg border border-[#E2E8F0] text-sm bg-white text-[#0F172A]
								       outline-none focus:ring-2 focus:ring-[#4F46E5]/30 cursor-pointer w-fit"
								disabled={submitting}
							>
								{#each WEEKDAYS as label, i (i)}
									<option value={i}>{label}</option>
								{/each}
							</select>
						</div>
					{:else}
						<div class="flex flex-col gap-1">
							<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="{uid}-day">
								On day
							</label>
							<input
								id="{uid}-day"
								bind:value={dayOfMonth}
								type="number"
								min="1"
								max="31"
								class="h-10 px-3 rounded-lg border border-[#E2E8F0] text-sm bg-white tabular-nums
								       outline-none focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]"
								style="width: 96px"
								disabled={submitting}
							/>
							<p class="text-xs text-[#64748B]">
								Day 29–31 falls on the last day in shorter months.
							</p>
						</div>
					{/if}

					<!-- Starts -->
					<div class="flex flex-col gap-1">
						<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="{uid}-starts">
							Starts
						</label>
						<input
							id="{uid}-starts"
							bind:value={startsOn}
							type="date"
							class="h-10 px-3 rounded-lg border border-[#E2E8F0] text-sm bg-white text-[#0F172A]
							       outline-none transition-colors cursor-pointer
							       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5] w-fit"
							disabled={submitting}
						/>
						<p class="text-xs text-[#64748B]">
							The first run date. Missed runs are caught up automatically.
						</p>
					</div>

					<!-- Set an end date toggle -->
					<div class="flex flex-col gap-2">
						<button
							type="button"
							role="switch"
							aria-checked={endDateOn}
							onclick={() => (endDateOn = !endDateOn)}
							class="flex items-center gap-2 text-sm text-[#0F172A] w-fit"
							disabled={submitting}
						>
							<span class={['inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0', endDateOn ? 'bg-[#4F46E5]' : 'bg-[#E2E8F0]'].join(' ')}>
								<span class={['inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform', endDateOn ? 'translate-x-4' : 'translate-x-0.5'].join(' ')}></span>
							</span>
							Set an end date
						</button>
						{#if endDateOn}
							<div class="flex flex-col gap-1">
								<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="{uid}-ends">
									Ends
								</label>
								<input
									id="{uid}-ends"
									bind:value={endDate}
									type="date"
									class="h-10 px-3 rounded-lg border border-[#E2E8F0] text-sm bg-white text-[#0F172A]
									       outline-none transition-colors cursor-pointer
									       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5] w-fit"
									disabled={submitting}
								/>
							</div>
						{/if}
					</div>

					<!-- Split with {partner} toggle -->
					<div class="flex flex-col gap-2">
						<button
							type="button"
							role="switch"
							aria-checked={splitOn}
							onclick={() => (splitOn = !splitOn)}
							class="flex items-center gap-2 text-sm text-[#0F172A] w-fit"
							disabled={submitting}
						>
							<span class={['inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0', splitOn ? 'bg-[#4F46E5]' : 'bg-[#E2E8F0]'].join(' ')}>
								<span class={['inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform', splitOn ? 'translate-x-4' : 'translate-x-0.5'].join(' ')}></span>
							</span>
							Split with {partnerName}
						</button>
						{#if splitOn}
							<SplitEditor
								total={amount}
								{currency}
								{partnerName}
								partnerCategories={categories}
								payerCategoryId={categoryId}
								mirrorPayerCategory={!isEdit}
								bind:splitMethod
								bind:payerPct
								bind:partnerPct
								bind:payerAmount
								bind:partnerAmount
								bind:partnerCategoryId
								bind:valid={splitValid}
							/>
						{/if}
					</div>

					{#if formError}
						<p class="text-xs text-[#EF4444]">{formError}</p>
					{/if}
				</div>

				<!-- Footer -->
				<div class="flex items-center justify-between gap-3 p-6 pt-4 shrink-0 border-t border-[#E2E8F0] mt-4">
					<button
						type="button"
						onclick={close}
						class="text-sm text-[#0F172A] hover:text-[#64748B] transition-colors"
						disabled={submitting}
					>
						Cancel
					</button>
					<button
						type="submit"
						disabled={submitting || (splitOn && !splitValid)}
						class="h-10 px-4 bg-[#4F46E5] text-white text-sm font-semibold rounded-lg
						       hover:bg-[#4338CA] transition-colors disabled:opacity-60 flex items-center gap-2"
					>
						{#if submitting}
							<Loader2 size={16} class="animate-spin" />
						{/if}
						{isEdit ? 'Save Rule' : 'Add Rule'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}
