<script lang="ts">
	import { Settings } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button/index.js';
	import { api } from '$lib/api.js';

	let loading = $state(false);
	let linkCode = $state<string | null>(null);
	let error = $state('');

	async function handleGenerateCode() {
		loading = true;
		error = '';
		linkCode = null;
		try {
			const result = await api.link.generateLinkCode();
			linkCode = result.code;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to generate link code.';
		} finally {
			loading = false;
		}
	}
</script>

<div class="space-y-6">
	<!-- Page heading -->
	<div class="flex items-center gap-3">
		<Settings size={20} class="text-[#4F46E5]" />
		<h1 class="text-xl font-semibold text-[#0F172A]">Settings</h1>
	</div>

	<!-- Link Telegram section -->
	<div class="bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg p-6 max-w-[520px]">
		<h2 class="text-base font-semibold text-[#0F172A] mb-1">Link Telegram</h2>
		<p class="text-sm text-[#64748B] mb-4">
			Connect your Telegram account so the bot can log expenses on your behalf.
		</p>

		<Button
			onclick={handleGenerateCode}
			disabled={loading}
			class="h-10 bg-[#4F46E5] hover:bg-[#4338CA] text-white font-semibold rounded-lg border-0"
		>
			{loading ? 'Generating…' : 'Generate link code'}
		</Button>

		{#if linkCode}
			<div class="mt-4 rounded-lg bg-indigo-50 border border-indigo-200 px-4 py-3 space-y-1">
				<p class="text-xs font-semibold text-[#0F172A]">Your one-time link code:</p>
				<p class="font-mono text-sm text-[#4F46E5] break-all">{linkCode}</p>
				<p class="text-xs text-[#64748B] pt-1">
					Send <span class="font-mono">/link {linkCode}</span> to the bot within 15 minutes.
				</p>
			</div>
		{/if}

		{#if error}
			<div
				class="mt-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700"
				role="alert"
			>
				{error}
			</div>
		{/if}
	</div>
</div>
