<script lang="ts">
	import { api, type Category, type RecurringRule } from '$lib/api.js';
	import { formatDate, formatOriginal } from '$lib/format.js';
	import { toast } from '$lib/stores/toast.js';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import Loader2 from '@lucide/svelte/icons/loader-2';
	import Pause from '@lucide/svelte/icons/pause';
	import Play from '@lucide/svelte/icons/play';

	let {
		rules = [] as RecurringRule[],
		categories = [] as Category[],
		partnerName = 'Partner',
		onedit = (_rule: RecurringRule) => {},
		onchanged = () => {},
	}: {
		rules?: RecurringRule[];
		categories?: Category[];
		partnerName?: string;
		onedit?: (rule: RecurringRule) => void;
		onchanged?: () => void;
	} = $props();

	function getCategory(id: number): Category | undefined {
		return categories.find((c) => c.id === id);
	}

	function cadence(rule: RecurringRule): string {
		if (rule.frequency === 'weekly') return 'week';
		if (rule.frequency === 'monthly_nth') return `day ${rule.day_of_month}`;
		return 'month';
	}

	// ─── Pause / resume ───────────────────────────────────────────────────────────

	let togglingId = $state<number | null>(null);

	async function togglePause(rule: RecurringRule) {
		togglingId = rule.id;
		try {
			if (rule.paused) {
				await api.recurring.resume(rule.id);
				toast.show('Recurring resumed');
			} else {
				await api.recurring.pause(rule.id);
				toast.show("Recurring paused — it won't generate until resumed");
			}
			onchanged();
		} catch (err) {
			toast.show(err instanceof Error ? err.message : 'Failed to update recurring rule.');
		} finally {
			togglingId = null;
		}
	}

	// ─── Delete-confirm ───────────────────────────────────────────────────────────

	let deleteTarget = $state<RecurringRule | null>(null);
	let deleting = $state(false);

	function openDeleteConfirm(rule: RecurringRule) {
		deleteTarget = rule;
	}

	function cancelDelete() {
		deleteTarget = null;
	}

	async function confirmDelete() {
		if (!deleteTarget) return;
		deleting = true;
		try {
			await api.recurring.delete(deleteTarget.id);
			toast.show('Recurring rule deleted');
			deleteTarget = null;
			onchanged();
		} catch (err) {
			toast.show(err instanceof Error ? err.message : 'Failed to delete recurring rule.');
		} finally {
			deleting = false;
		}
	}
</script>

<div class="rounded-lg border border-[#E2E8F0] overflow-hidden">
	<div class="flex flex-col divide-y divide-[#E2E8F0]">
		{#each rules as rule (rule.id)}
			{@const category = getCategory(rule.category_id)}
			<div
				class={[
					'flex items-center justify-between gap-3 px-4 py-3 transition-colors',
					rule.paused ? 'bg-[#F8FAFC]' : 'hover:bg-[#F8FAFC]',
				].join(' ')}
				style="min-height: 44px"
			>
				<!-- Left: swatch + primary/secondary lines -->
				<div class="flex items-center gap-2.5 min-w-0">
					<span
						class="w-3 h-3 rounded-full shrink-0"
						style="background-color: {category?.color ?? '#6B7280'}"
					></span>
					<div class={['flex flex-col min-w-0', rule.paused ? 'text-[#64748B]' : '']}>
						<p class="text-sm font-medium truncate">
							<span class={rule.paused ? '' : 'text-[#0F172A]'}>
								{rule.name ?? category?.name ?? 'Recurring'}
							</span>
							· <span class="tabular-nums font-semibold">{formatOriginal(rule.amount_minor, rule.currency)}</span>
							/ {cadence(rule)}
						</p>
						<p class="text-xs text-[#64748B] truncate">
							{#if rule.paused}
								Paused
							{:else if rule.next_run}
								Next: {formatDate(rule.next_run)}
							{:else}
								No upcoming runs
							{/if}
							{#if rule.is_shared}
								&nbsp;·&nbsp;Shared 50/50 with {partnerName}
							{/if}
							{#if rule.end_date}
								&nbsp;·&nbsp;Ends {formatDate(rule.end_date)}
							{/if}
						</p>
					</div>
					{#if rule.paused}
						<Badge variant="secondary" class="shrink-0">Paused</Badge>
					{/if}
				</div>

				<!-- Right: pause/resume, edit, delete -->
				<div class="flex items-center gap-3 shrink-0">
					<button
						type="button"
						onclick={() => togglePause(rule)}
						disabled={togglingId === rule.id}
						class="text-sm text-[#64748B] hover:text-[#0F172A] transition-colors flex items-center gap-1 disabled:opacity-60"
					>
						{#if togglingId === rule.id}
							<Loader2 size={13} class="animate-spin" />
						{:else if rule.paused}
							<Play size={13} />
						{:else}
							<Pause size={13} />
						{/if}
						{rule.paused ? 'Resume' : 'Pause'}
					</button>
					<button
						type="button"
						onclick={() => onedit(rule)}
						class="text-sm text-[#4F46E5] hover:text-[#4338CA] transition-colors"
					>
						Edit
					</button>
					<button
						type="button"
						onclick={() => openDeleteConfirm(rule)}
						class="text-sm text-[#64748B] hover:text-[#EF4444] transition-colors"
					>
						Delete
					</button>
				</div>
			</div>
		{/each}
	</div>
</div>

<!-- Delete confirmation dialog -->
{#if deleteTarget}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center"
		role="dialog"
		aria-modal="true"
		aria-labelledby="delete-recurring-title"
	>
		<button
			type="button"
			class="absolute inset-0 bg-black/50 cursor-default"
			onclick={cancelDelete}
			aria-label="Close dialog"
			tabindex="-1"
		></button>
		<div class="relative bg-white rounded-lg border border-[#E2E8F0] p-6 shadow-xl max-w-sm w-full mx-4">
			<h2 id="delete-recurring-title" class="text-lg font-semibold text-[#0F172A] mb-2">
				Delete this recurring rule?
			</h2>
			<p class="text-sm text-[#64748B] mb-6">
				It will stop generating new expenses. Expenses already logged from it are kept.
			</p>
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
					Delete Rule
				</button>
			</div>
		</div>
	</div>
{/if}
