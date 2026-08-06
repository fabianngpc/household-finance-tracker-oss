<script lang="ts">
	import { api, type Settlement } from '$lib/api.js';
	import { toast } from '$lib/stores/toast.js';
	import { formatDate, formatMinorPlain } from '$lib/format.js';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import Loader2 from '@lucide/svelte/icons/loader-2';

	let {
		open = $bindable(false),
		partnerName = 'Partner',
		myUserId = 0,
		myName = 'You',
		partnerUserId = 0,
		onChanged = () => {},
	}: {
		open?: boolean;
		partnerName?: string;
		myUserId?: number;
		myName?: string;
		partnerUserId?: number;
		onChanged?: () => void;
	} = $props();

	let settlements = $state<Settlement[]>([]);
	let loading = $state(true);
	let error = $state('');

	async function load() {
		loading = true;
		error = '';
		try {
			const rows = await api.settlements.list();
			settlements = [...rows].sort((a, b) => {
				if (a.occurred_on !== b.occurred_on) return a.occurred_on < b.occurred_on ? 1 : -1;
				return b.id - a.id;
			});
		} catch {
			error = "Couldn't load settlement history. Try again.";
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (open) load();
	});

	function close() {
		open = false;
	}

	function nameFor(userId: number): string {
		if (userId === myUserId) return myName;
		if (userId === partnerUserId) return partnerName;
		return 'Someone';
	}

	// ─── Void confirm ─────────────────────────────────────────────────────────────
	let voidTarget = $state<Settlement | null>(null);
	let voiding = $state(false);

	function openVoidConfirm(s: Settlement) {
		voidTarget = s;
	}

	function cancelVoid() {
		voidTarget = null;
	}

	async function confirmVoid() {
		if (!voidTarget) return;
		voiding = true;
		try {
			await api.settlements.void(voidTarget.id);
			toast.show('Settlement voided');
			voidTarget = null;
			await load();
			onChanged();
		} catch (err) {
			toast.show(err instanceof Error ? err.message : 'Failed to void settlement.');
		} finally {
			voiding = false;
		}
	}
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center"
		role="dialog"
		aria-modal="true"
		aria-labelledby="history-dialog-title"
	>
		<button
			type="button"
			class="absolute inset-0 bg-black/50 cursor-default"
			onclick={close}
			aria-label="Close dialog"
			tabindex="-1"
		></button>

		<div class="relative bg-white rounded-lg border border-[#E2E8F0] shadow-xl w-full max-w-[560px] mx-4 p-6 flex flex-col" style="max-height: 70vh">
			<h2 id="history-dialog-title" class="text-lg font-semibold text-[#0F172A] mb-4 shrink-0">
				Settlement history — {partnerName}
			</h2>

			<div class="overflow-y-auto flex-1 -mx-2 px-2">
				{#if loading}
					<div class="flex flex-col divide-y divide-[#E2E8F0]">
						{#each { length: 4 } as _, i (i)}
							<div class="py-3 flex flex-col gap-1.5" style="min-height: 44px">
								<div class="h-4 w-56 bg-[#E2E8F0] rounded animate-pulse"></div>
								<div class="h-3 w-32 bg-[#E2E8F0] rounded animate-pulse"></div>
							</div>
						{/each}
					</div>
				{:else if error}
					<p class="text-sm text-[#64748B] py-8 text-center">{error}</p>
				{:else if settlements.length === 0}
					<div class="py-12 text-center">
						<p class="text-base font-semibold text-[#0F172A] mb-1">No settlements yet</p>
						<p class="text-sm text-[#64748B]">Settle a balance and it'll show up here.</p>
					</div>
				{:else}
					<div class="flex flex-col divide-y divide-[#E2E8F0]">
						{#each settlements as s (s.id)}
							{@const voided = s.voided_at != null}
							<div class="py-3 flex items-center justify-between gap-3" style="min-height: 44px">
								<div class={['flex flex-col gap-0.5 min-w-0', voided ? 'text-[#64748B]' : ''].join(' ')}>
									<p class={['text-sm', voided ? 'line-through text-[#64748B]' : 'text-[#0F172A]'].join(' ')}>
										{nameFor(s.from_user_id)} paid {nameFor(s.to_user_id)}
										· <span class="tabular-nums font-semibold">{s.currency} {formatMinorPlain(s.amount_minor, s.currency)}</span>
									</p>
									<p class="text-xs text-[#64748B]">
										{formatDate(s.occurred_on)}{s.note ? ` · ${s.note}` : ''}
									</p>
								</div>
								{#if voided}
									<Badge variant="secondary">Voided</Badge>
								{:else}
									<button
										type="button"
										onclick={() => openVoidConfirm(s)}
										class="text-sm text-[#64748B] hover:text-[#EF4444] transition-colors shrink-0"
									>
										Void
									</button>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<!-- Void confirmation -->
{#if voidTarget}
	<div
		class="fixed inset-0 z-[60] flex items-center justify-center"
		role="dialog"
		aria-modal="true"
		aria-labelledby="void-confirm-title"
	>
		<button
			type="button"
			class="absolute inset-0 bg-black/50 cursor-default"
			onclick={cancelVoid}
			aria-label="Close dialog"
			tabindex="-1"
		></button>
		<div class="relative bg-white rounded-lg border border-[#E2E8F0] p-6 shadow-xl max-w-sm w-full mx-4">
			<h2 id="void-confirm-title" class="text-lg font-semibold text-[#0F172A] mb-2">
				Void this settlement?
			</h2>
			<p class="text-sm text-[#64748B] mb-6">
				The balance will reopen by {voidTarget.currency} {formatMinorPlain(voidTarget.amount_minor, voidTarget.currency)}. This can't be redone.
			</p>
			<div class="flex items-center justify-between gap-3">
				<button
					type="button"
					onclick={cancelVoid}
					class="text-sm text-[#0F172A] hover:text-[#64748B] transition-colors"
					disabled={voiding}
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={confirmVoid}
					disabled={voiding}
					class="h-9 px-4 bg-[#EF4444] text-white text-sm font-semibold rounded-lg
					       hover:bg-red-600 transition-colors disabled:opacity-60 flex items-center gap-2"
				>
					{#if voiding}
						<Loader2 size={14} class="animate-spin" />
					{/if}
					Void Settlement
				</button>
			</div>
		</div>
	</div>
{/if}
