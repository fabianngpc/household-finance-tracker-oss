<script lang="ts">
	import { goto } from '$app/navigation';
	import { Wallet } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button/index.js';
	import { Input } from '$lib/components/ui/input/index.js';
	import { auth } from '$lib/stores/auth.js';

	let username = $state('');
	let password = $state('');
	let submitting = $state(false);
	let error = $state('');

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		error = '';
		submitting = true;

		try {
			await auth.login(username, password);
			goto('/dashboard');
		} catch {
			error = 'Invalid username or password. Check your credentials and try again.';
		} finally {
			submitting = false;
		}
	}
</script>

<!-- Centered login card on white background -->
<div class="min-h-screen bg-white flex items-center justify-center p-4">
	<div class="w-full max-w-[440px]">
		<!-- App name + icon above the card -->
		<div class="flex items-center justify-center gap-3 mb-6">
			<Wallet size={28} class="text-[#4F46E5]" />
			<span class="text-xl font-semibold text-[#0F172A]">Finance</span>
		</div>

		<!-- Login card -->
		<div
			class="bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg p-8"
		>
			<h1 class="text-xl font-semibold text-[#0F172A] mb-6">Sign in to your account</h1>

			<form onsubmit={handleSubmit} class="space-y-4">
				<!-- Username field -->
				<div class="space-y-1.5">
					<label for="username" class="block text-xs font-semibold text-[#0F172A]">
						Username
					</label>
					<Input
						id="username"
						type="text"
						bind:value={username}
						required
						disabled={submitting}
						autocomplete="username"
						class="h-10"
					/>
				</div>

				<!-- Password field -->
				<div class="space-y-1.5">
					<label for="password" class="block text-xs font-semibold text-[#0F172A]">
						Password
					</label>
					<Input
						id="password"
						type="password"
						bind:value={password}
						required
						disabled={submitting}
						autocomplete="current-password"
						class="h-10"
					/>
				</div>

				<!-- Submit button -->
				<Button
					type="submit"
					disabled={submitting}
					class="w-full h-10 bg-[#4F46E5] hover:bg-[#4338CA] text-white font-semibold rounded-lg border-0 mt-2"
				>
					{submitting ? 'Signing in…' : 'Sign In'}
				</Button>

				<!-- Error banner -->
				{#if error}
					<div
						class="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700"
						role="alert"
					>
						{error}
					</div>
				{/if}
			</form>
		</div>
	</div>
</div>
