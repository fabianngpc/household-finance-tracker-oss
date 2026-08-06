<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type BalanceOut } from '$lib/api.js';
	import { auth } from '$lib/stores/auth.js';
	import { formatMinorPlain } from '$lib/format.js';
	import SettleDialog from './SettleDialog.svelte';
	import SettlementHistory from './SettlementHistory.svelte';

	let balance = $state<BalanceOut | null>(null);
	let loading = $state(true);
	let error = $state('');

	async function load() {
		loading = true;
		error = '';
		try {
			balance = await api.balance.get();
		} catch {
			error = "Couldn't load balance. Refresh to try again.";
		} finally {
			loading = false;
		}
	}

	onMount(load);

	let partnerName = $derived(balance?.partner_display_name ?? 'Partner');
	let myUserId = $derived($auth.user?.id ?? 0);
	let myName = $derived($auth.user?.display_name ?? 'You');

	// ─── Settle dialog ────────────────────────────────────────────────────────────
	let settleOpen = $state(false);
	let settleCurrency = $state('');
	let settleNetMinor = $state(0); // signed, from the logged-in user's perspective

	function openSettle(currency: string, netMinor: number) {
		settleCurrency = currency;
		settleNetMinor = netMinor;
		settleOpen = true;
	}

	// ─── Settlement history dialog ────────────────────────────────────────────────
	let historyOpen = $state(false);
</script>

<div class="rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-4">
	<!-- Label row -->
	<div class="flex items-center justify-between mb-3 gap-3 flex-wrap">
		<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">
			Balance with {partnerName}
		</span>
		<button
			type="button"
			onclick={() => (historyOpen = true)}
			class="text-sm text-[#4F46E5] hover:underline"
		>
			View settlement history
		</button>
	</div>

	{#if loading}
		<!-- Skeleton: label bar + one 20px line -->
		<div class="flex flex-col gap-2">
			<div class="h-3 w-32 bg-[#E2E8F0] rounded animate-pulse"></div>
			<div class="h-5 w-64 bg-[#E2E8F0] rounded animate-pulse"></div>
		</div>
	{:else if error}
		<p class="text-sm text-[#64748B]">{error}</p>
	{:else if !balance || balance.entries.length === 0}
		<p class="text-sm text-[#64748B]">All settled up</p>
	{:else}
		<div class="flex flex-col gap-2">
			{#each balance.entries as entry (entry.currency)}
				<div class="flex items-center justify-between gap-3 flex-wrap">
					<p class="text-sm text-[#0F172A]">
						{#if entry.net_minor > 0}
							{partnerName} owes you
							<span class="font-semibold tabular-nums">
								{entry.currency} {formatMinorPlain(entry.net_minor, entry.currency)}
							</span>
						{:else}
							You owe {partnerName}
							<span class="font-semibold tabular-nums">
								{entry.currency} {formatMinorPlain(-entry.net_minor, entry.currency)}
							</span>
						{/if}
					</p>
					<button
						type="button"
						onclick={() => openSettle(entry.currency, entry.net_minor)}
						class="h-8 px-3 bg-[#4F46E5] text-white text-sm font-semibold rounded-lg
						       hover:bg-[#4338CA] transition-colors shrink-0"
					>
						Settle {entry.currency}
					</button>
				</div>
			{/each}
		</div>
	{/if}
</div>

<SettleDialog
	bind:open={settleOpen}
	currency={settleCurrency}
	netMinor={settleNetMinor}
	{partnerName}
	partnerUserId={balance?.partner_user_id ?? 0}
	{myUserId}
	onSettled={load}
/>

<SettlementHistory
	bind:open={historyOpen}
	{partnerName}
	{myUserId}
	{myName}
	partnerUserId={balance?.partner_user_id ?? 0}
	onChanged={load}
/>
