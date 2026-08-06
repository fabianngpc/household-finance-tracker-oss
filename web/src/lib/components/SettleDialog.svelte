<script lang="ts">
	import { api } from '$lib/api.js';
	import { toast } from '$lib/stores/toast.js';
	import { formatMinorPlain, parseToMinorUnits } from '$lib/format.js';
	import Loader2 from '@lucide/svelte/icons/loader-2';

	let {
		open = $bindable(false),
		currency = '',
		netMinor = 0, // signed, from the logged-in user's perspective (>0 partner owes me)
		partnerName = 'Partner',
		partnerUserId = 0,
		myUserId = 0,
		onSettled = () => {},
	}: {
		open?: boolean;
		currency?: string;
		netMinor?: number;
		partnerName?: string;
		partnerUserId?: number;
		myUserId?: number;
		onSettled?: () => void;
	} = $props();

	let netAbsMinor = $derived(Math.abs(netMinor));
	let owerIsMe = $derived(netMinor < 0);
	let direction = $derived(
		owerIsMe ? `You pay ${partnerName}` : `${partnerName} pays you`
	);

	function todayStr(): string {
		const d = new Date();
		return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
	}

	let amount = $state('');
	let date = $state(todayStr());
	let note = $state('');
	let submitting = $state(false);
	let amountError = $state('');

	// Reset the form every time the dialog opens for a (possibly new) currency/net.
	$effect(() => {
		if (open) {
			amount = formatMinorPlain(netAbsMinor, currency);
			date = todayStr();
			note = '';
			amountError = '';
		}
	});

	function close() {
		open = false;
	}

	async function handleSubmit(e: Event) {
		e.preventDefault();
		amountError = '';

		const trimmed = amount.trim();
		const numVal = +trimmed;
		if (!trimmed || isNaN(numVal) || numVal <= 0) {
			amountError = 'Enter a valid amount greater than zero.';
			return;
		}
		const enteredMinor = parseToMinorUnits(trimmed, currency);
		if (enteredMinor > netAbsMinor) {
			amountError = `Amount cannot exceed the outstanding balance (${currency} ${formatMinorPlain(netAbsMinor, currency)}).`;
			return;
		}

		const fromUserId = owerIsMe ? myUserId : partnerUserId;
		const toUserId = owerIsMe ? partnerUserId : myUserId;

		submitting = true;
		try {
			await api.settlements.create({
				from_user_id: fromUserId,
				to_user_id: toUserId,
				amount: trimmed,
				currency,
				occurred_on: date,
				note: note.trim() || undefined,
			});
			toast.show('Settlement recorded');
			close();
			onSettled();
		} catch (err) {
			amountError = err instanceof Error ? err.message : 'Failed to record settlement.';
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
		aria-labelledby="settle-dialog-title"
	>
		<button
			type="button"
			class="absolute inset-0 bg-black/50 cursor-default"
			onclick={close}
			aria-label="Close dialog"
			tabindex="-1"
		></button>

		<div class="relative bg-white rounded-lg border border-[#E2E8F0] shadow-xl w-full max-w-[440px] mx-4 p-6">
			<h2 id="settle-dialog-title" class="text-lg font-semibold text-[#0F172A] mb-1">
				Settle up — {currency}
			</h2>
			<p class="text-sm text-[#64748B] mb-4">{direction}</p>

			<form onsubmit={handleSubmit} class="flex flex-col gap-4">
				<!-- Amount -->
				<div class="flex flex-col gap-1">
					<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="settle-amount">
						Amount
					</label>
					<input
						id="settle-amount"
						bind:value={amount}
						type="text"
						inputmode="decimal"
						class={[
							'h-10 px-3 rounded-lg border text-sm tabular-nums bg-white w-full outline-none transition-colors',
							'focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]',
							amountError ? 'border-[#EF4444]' : 'border-[#E2E8F0]',
						].join(' ')}
						disabled={submitting}
					/>
					{#if amountError}
						<p class="text-xs text-[#EF4444]">{amountError}</p>
					{/if}
				</div>

				<!-- Date -->
				<div class="flex flex-col gap-1">
					<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="settle-date">
						Date
					</label>
					<input
						id="settle-date"
						bind:value={date}
						type="date"
						class="h-10 px-3 rounded-lg border border-[#E2E8F0] text-sm bg-white text-[#0F172A] w-full outline-none
						       transition-colors focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5] cursor-pointer"
						disabled={submitting}
					/>
				</div>

				<!-- Note -->
				<div class="flex flex-col gap-1">
					<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="settle-note">
						Note (optional)
					</label>
					<input
						id="settle-note"
						bind:value={note}
						type="text"
						placeholder="Note (optional)"
						class="h-10 px-3 rounded-lg border border-[#E2E8F0] text-sm bg-white text-[#0F172A]
						       placeholder:text-[#64748B] w-full outline-none transition-colors
						       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]"
						disabled={submitting}
					/>
				</div>

				<!-- Footer -->
				<div class="flex items-center justify-between gap-3 pt-2">
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
						disabled={submitting}
						class="h-10 px-4 bg-[#4F46E5] text-white text-sm font-semibold rounded-lg
						       hover:bg-[#4338CA] transition-colors disabled:opacity-60 flex items-center gap-2"
					>
						{#if submitting}
							<Loader2 size={16} class="animate-spin" />
						{/if}
						Record Settlement
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}
