<script lang="ts">
	import type { Category, SplitMethod } from '$lib/api.js';
	import { allocateShares, formatOriginal, parseToMinorUnits } from '$lib/format.js';
	import CategoryPicker from './CategoryPicker.svelte';

	let {
		total = '',
		currency = 'SGD',
		partnerName = 'Partner',
		partnerCategories = [] as Category[],
		splitMethod = $bindable<SplitMethod>('equal'),
		payerPct = $bindable(50),
		partnerPct = $bindable(50),
		payerAmount = $bindable(''),
		partnerAmount = $bindable(''),
		partnerCategoryId = $bindable<number | null>(null),
		valid = $bindable(true),
		categoryError = false,
		payerCategoryId = null,
		mirrorPayerCategory = false,
	}: {
		total?: string;
		currency?: string;
		partnerName?: string;
		partnerCategories?: Category[];
		splitMethod?: SplitMethod;
		payerPct?: number;
		partnerPct?: number;
		payerAmount?: string;
		partnerAmount?: string;
		partnerCategoryId?: number | null;
		valid?: boolean;
		categoryError?: boolean;
		/** The payer's selected category — the partner category mirrors this. */
		payerCategoryId?: number | null;
		/** When true, the partner category defaults to (and follows) the payer's
		 * choice until the user manually picks a partner category. */
		mirrorPayerCategory?: boolean;
	} = $props();

	// Track whether the user has explicitly chosen a partner category. Until then
	// (in mirror mode) the partner category follows the payer's selection.
	let partnerCategoryTouched = $state(false);

	$effect(() => {
		if (mirrorPayerCategory && !partnerCategoryTouched) {
			if (partnerCategoryId !== payerCategoryId) {
				partnerCategoryId = payerCategoryId;
			}
		}
	});

	// Unique per-instance id prefix — SplitEditor can render more than once at a
	// time (e.g. the add-expense panel + an in-table edit panel), so field ids
	// must not collide across instances.
	const uid = $props.id();

	const SEGMENTS: { id: SplitMethod; label: string }[] = [
		{ id: 'equal', label: 'Equal' },
		{ id: 'percent', label: 'Percentage' },
		{ id: 'exact', label: 'Exact' },
	];

	let totalMinor = $derived(parseToMinorUnits(total, currency));

	// Percent-mode sum + validity
	let percentSum = $derived(payerPct + partnerPct);
	let percentValid = $derived(percentSum === 100);

	// Exact-mode remaining + validity
	let payerExactMinor = $derived(parseToMinorUnits(payerAmount, currency));
	let partnerExactMinor = $derived(parseToMinorUnits(partnerAmount, currency));
	let exactRemaining = $derived(totalMinor - (payerExactMinor + partnerExactMinor));
	let exactValid = $derived(exactRemaining === 0);

	// Live share preview — always visible, exact largest-remainder allocation.
	let previewShares = $derived.by((): [number, number] => {
		if (splitMethod === 'exact') {
			return [payerExactMinor, partnerExactMinor];
		}
		const weights =
			splitMethod === 'percent'
				? [Math.max(payerPct, 0.01), Math.max(partnerPct, 0.01)]
				: [1, 1];
		try {
			const [a, b] = allocateShares(totalMinor, weights);
			return [a, b];
		} catch {
			return [0, 0];
		}
	});

	function fmtSigned(minor: number): string {
		const sign = minor < 0 ? '-' : '';
		return sign + formatOriginal(Math.abs(minor), currency);
	}

	// Overall validity forwarded to the parent (bind:valid) — gates submit.
	$effect(() => {
		valid = splitMethod === 'percent' ? percentValid : splitMethod === 'exact' ? exactValid : true;
	});
</script>

<div class="bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg p-4 flex flex-col gap-3">
	<!-- Split-method segmented control -->
	<div
		class="inline-flex items-center gap-0.5 rounded-lg border border-[#E2E8F0] bg-[#F1F5F9] p-0.5 w-fit"
		role="group"
		aria-label="Split method"
	>
		{#each SEGMENTS as seg (seg.id)}
			<button
				type="button"
				onclick={() => (splitMethod = seg.id)}
				aria-pressed={splitMethod === seg.id}
				class={[
					'h-8 px-3 text-sm font-semibold rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-[#4F46E5]/30',
					splitMethod === seg.id
						? 'bg-white text-[#4F46E5] shadow-sm'
						: 'bg-transparent text-[#64748B] hover:text-[#0F172A]',
				].join(' ')}
			>
				{seg.label}
			</button>
		{/each}
	</div>

	<!-- Percentage inputs -->
	{#if splitMethod === 'percent'}
		<div class="flex items-start gap-3 flex-wrap">
			<div class="flex flex-col gap-1">
				<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="{uid}-payer-pct">
					You %
				</label>
				<input
					id="{uid}-payer-pct"
					type="number"
					inputmode="decimal"
					bind:value={payerPct}
					class="h-10 px-2.5 rounded-lg border border-[#E2E8F0] text-sm bg-white tabular-nums outline-none
					       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5] transition-colors"
					style="width: 88px"
				/>
			</div>
			<div class="flex flex-col gap-1">
				<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="{uid}-partner-pct">
					{partnerName} %
				</label>
				<input
					id="{uid}-partner-pct"
					type="number"
					inputmode="decimal"
					bind:value={partnerPct}
					class="h-10 px-2.5 rounded-lg border border-[#E2E8F0] text-sm bg-white tabular-nums outline-none
					       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5] transition-colors"
					style="width: 88px"
				/>
			</div>
		</div>
		{#if percentValid}
			<p class="text-xs text-[#64748B]">Adds up to 100%</p>
		{:else}
			<p class="text-xs text-[#EF4444]">Must add up to 100% (now {percentSum}%)</p>
		{/if}
	{/if}

	<!-- Exact-amount inputs -->
	{#if splitMethod === 'exact'}
		<div class="flex items-start gap-3 flex-wrap">
			<div class="flex flex-col gap-1">
				<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="{uid}-payer-amount">
					Your share
				</label>
				<input
					id="{uid}-payer-amount"
					type="text"
					inputmode="decimal"
					bind:value={payerAmount}
					placeholder="0.00"
					class="h-10 px-2.5 rounded-lg border border-[#E2E8F0] text-sm bg-white tabular-nums outline-none
					       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5] transition-colors"
					style="width: 110px"
				/>
			</div>
			<div class="flex flex-col gap-1">
				<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="{uid}-partner-amount">
					{partnerName}'s share
				</label>
				<input
					id="{uid}-partner-amount"
					type="text"
					inputmode="decimal"
					bind:value={partnerAmount}
					placeholder="0.00"
					class="h-10 px-2.5 rounded-lg border border-[#E2E8F0] text-sm bg-white tabular-nums outline-none
					       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5] transition-colors"
					style="width: 110px"
				/>
			</div>
		</div>
		{#if exactValid}
			<p class="text-xs text-[#64748B]">Remaining to allocate: {fmtSigned(exactRemaining)}</p>
		{:else}
			<p class="text-xs text-[#EF4444]">Remaining to allocate: {fmtSigned(exactRemaining)}</p>
		{/if}
	{/if}

	<!-- Partner category picker -->
	<div class="flex flex-col gap-1">
		<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="{uid}-partner-category">
			{partnerName}'s category
		</label>
		<CategoryPicker
			bind:categoryId={partnerCategoryId}
			categories={partnerCategories}
			error={categoryError}
			inputId="{uid}-partner-category"
			onUserChange={() => (partnerCategoryTouched = true)}
		/>
		<p class="text-xs text-[#64748B]">
			Pick which of {partnerName}'s categories their half lands in.
		</p>
	</div>

	<!-- Live share preview -->
	<p class="text-sm tabular-nums text-[#0F172A]">
		You: {fmtSigned(previewShares[0])}&nbsp;&nbsp;·&nbsp;&nbsp;{partnerName}: {fmtSigned(previewShares[1])}
	</p>
</div>
