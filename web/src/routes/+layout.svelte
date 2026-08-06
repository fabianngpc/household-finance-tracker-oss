<script lang="ts">
	import { goto, beforeNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { Wallet, LayoutDashboard, Receipt, Tag, BarChart2, Target, Repeat, LogOut, Settings } from '@lucide/svelte';
	import '../app.css';
	import { auth } from '$lib/stores/auth.js';
	import { api } from '$lib/api.js';
	import Toast from '$lib/components/Toast.svelte';

	let { children } = $props();

	// Nav items for the sidebar
	const navItems = [
		{ href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
		{ href: '/expenses', label: 'Expenses', icon: Receipt },
		{ href: '/categories', label: 'Categories', icon: Tag },
		{ href: '/reports', label: 'Reports', icon: BarChart2 },
		{ href: '/budgets', label: 'Budgets', icon: Target },
		{ href: '/recurring', label: 'Recurring', icon: Repeat },
		{ href: '/settings', label: 'Settings', icon: Settings },
	];

	// Auth guard state
	let loaded = $state(false);

	onMount(async () => {
		await auth.loadMe();
		loaded = true;
		const currentPath = page.url.pathname;
		const isLoginRoute = currentPath === '/login';

		if (!$auth.user && !isLoginRoute) {
			goto('/login');
		} else if ($auth.user && isLoginRoute) {
			goto('/dashboard');
		}
	});

	// Reactive guard: redirect when navigating to protected routes without auth
	$effect(() => {
		if (!loaded) return;
		const currentPath = page.url.pathname;
		const isLoginRoute = currentPath === '/login';

		if (!$auth.user && !isLoginRoute) {
			goto('/login');
		} else if ($auth.user && isLoginRoute) {
			goto('/dashboard');
		}
	});

	async function handleSignOut() {
		await auth.logout();
		goto('/login');
	}

	// Check if current route is login
	let isLoginRoute = $derived(page.url.pathname === '/login');

	// Check if a nav link is active
	function isActive(href: string): boolean {
		return page.url.pathname.startsWith(href);
	}
</script>

<Toast />

{#if isLoginRoute}
	<!-- Login page: render without sidebar -->
	{@render children()}
{:else if $auth.user}
	<!-- App shell: sidebar + main content -->
	<div class="flex min-h-screen">
		<!-- Fixed sidebar -->
		<aside
			class="fixed top-0 left-0 h-screen w-[240px] bg-[#F8FAFC] border-r border-[#E2E8F0] flex flex-col"
		>
			<!-- Sidebar header: app name + icon -->
			<div class="flex items-center gap-2 px-6 py-6">
				<Wallet size={20} class="text-[#4F46E5] shrink-0" />
				<span class="text-base font-semibold text-[#0F172A]">Finance</span>
			</div>

			<!-- Navigation links -->
			<nav class="flex-1 px-2">
				{#each navItems as { href, label, icon: Icon }}
					<a
						{href}
						class={[
							'flex items-center gap-3 px-4 h-10 rounded-md text-sm transition-colors',
							isActive(href)
								? 'border-l-[3px] border-[#4F46E5] text-[#4F46E5] font-semibold bg-indigo-50'
								: 'text-[#0F172A] font-normal hover:bg-gray-100',
						].join(' ')}
					>
						<Icon size={16} />
						{label}
					</a>
				{/each}
			</nav>

			<!-- Sidebar footer: username + sign out -->
			<div class="px-6 py-6 border-t border-[#E2E8F0]">
				<p class="text-sm text-[#64748B] mb-2 truncate">{$auth.user.display_name}</p>
				<button
					onclick={handleSignOut}
					class="text-sm text-[#0F172A] hover:text-[#4F46E5] transition-colors flex items-center gap-1.5"
				>
					<LogOut size={14} />
					Sign out
				</button>
			</div>
		</aside>

		<!-- Main content area (offset by sidebar width) -->
		<main class="ml-[240px] flex-1 bg-white min-h-screen">
			<div class="max-w-[1200px] mx-auto px-8 py-6">
				{@render children()}
			</div>
		</main>
	</div>
{:else if loaded}
	<!-- Loaded but no user — redirecting to /login (route guard handles it) -->
	<div class="min-h-screen bg-white" aria-live="polite"></div>
{:else}
	<!-- Loading state -->
	<div class="min-h-screen bg-white flex items-center justify-center">
		<div class="text-sm text-[#64748B]">Loading…</div>
	</div>
{/if}
