<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type Category } from '$lib/api.js';
	import { toast } from '$lib/stores/toast.js';
	import CategoryDialog from '$lib/components/CategoryDialog.svelte';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Loader2 from '@lucide/svelte/icons/loader-2';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';

	let categories = $state<Category[]>([]);
	let loading = $state(true);
	let error = $state('');

	// ─── Add/Edit dialog ─────────────────────────────────────────────────────────
	let dialogOpen = $state(false);
	let editCategory = $state<Category | null>(null);

	function openAddDialog() {
		editCategory = null;
		dialogOpen = true;
	}

	async function handleDialogSave() {
		await loadCategories();
	}

	// ─── Inline rename ───────────────────────────────────────────────────────────
	let renamingId = $state<number | null>(null);
	let renameValue = $state('');
	let renameSaving = $state(false);

	function startRename(cat: Category) {
		renamingId = cat.id;
		renameValue = cat.name;
	}

	function cancelRename() {
		renamingId = null;
	}

	async function saveRename(cat: Category) {
		if (!renameValue.trim()) return;
		renameSaving = true;
		try {
			await api.categories.update(cat.id, { name: renameValue.trim() });
			renamingId = null;
			await loadCategories();
		} catch (err) {
			alert(err instanceof Error ? err.message : 'Failed to rename.');
		} finally {
			renameSaving = false;
		}
	}

	function handleRenameKeydown(e: KeyboardEvent, cat: Category) {
		if (e.key === 'Enter') {
			e.preventDefault();
			saveRename(cat);
		} else if (e.key === 'Escape') {
			cancelRename();
		}
	}

	// ─── Delete ───────────────────────────────────────────────────────────────────
	let deletingId = $state<number | null>(null);
	let deleteDialogOpen = $state(false);
	let deleting = $state(false);

	let deleteTarget = $derived(
		deletingId !== null ? (categories.find((c) => c.id === deletingId) ?? null) : null
	);

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
			await api.categories.delete(deletingId);
			deleteDialogOpen = false;
			deletingId = null;
			toast.show('Category deleted — expenses moved to Other');
			await loadCategories();
		} catch (err) {
			alert(err instanceof Error ? err.message : 'Failed to delete.');
		} finally {
			deleting = false;
		}
	}

	// ─── Load ─────────────────────────────────────────────────────────────────────
	async function loadCategories() {
		try {
			error = '';
			categories = await api.categories.list();
		} catch {
			error = "Couldn't load categories. Refresh the page to try again.";
		}
	}

	onMount(async () => {
		loading = true;
		await loadCategories();
		loading = false;
	});
</script>

<!-- Add dialog -->
<CategoryDialog bind:open={dialogOpen} {editCategory} onSave={handleDialogSave} />

<!-- Delete confirmation dialog -->
{#if deleteDialogOpen && deleteTarget}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center"
		role="dialog"
		aria-modal="true"
		aria-labelledby="cat-delete-title"
	>
		<button
			type="button"
			class="absolute inset-0 bg-black/50 cursor-default"
			onclick={cancelDelete}
			aria-label="Close dialog"
			tabindex="-1"
		></button>
		<div class="relative bg-white rounded-lg border border-[#E2E8F0] p-6 shadow-xl max-w-sm w-full mx-4">
			<h2 id="cat-delete-title" class="text-lg font-semibold text-[#0F172A] mb-2">
				Delete '{deleteTarget.name}'?
			</h2>
			<p class="text-sm text-[#64748B] mb-6">
				{#if (deleteTarget.expense_count ?? 0) > 0}
					Expenses in this category will be moved to Other.
				{:else}
					This cannot be undone.
				{/if}
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
					Delete Category
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- Page -->
<div>
	<div class="flex items-center justify-between mb-6">
		<h1 class="text-xl font-semibold text-[#0F172A]">Categories</h1>
		<button
			type="button"
			onclick={openAddDialog}
			class="h-10 px-4 bg-[#4F46E5] text-white text-sm font-semibold rounded-lg
			       hover:bg-[#4338CA] transition-colors flex items-center gap-2"
		>
			Add Category
		</button>
	</div>

	{#if error}
		<p class="text-sm text-[#EF4444]">{error}</p>
	{:else}
		<div class="rounded-lg border border-[#E2E8F0] overflow-hidden">
			<!-- Header row -->
			<div class="grid bg-[#F8FAFC] border-b border-[#E2E8F0] px-4 py-2"
			     style="grid-template-columns: 2rem 2rem 1fr 8rem 5rem">
				<span class="text-xs font-semibold text-[#64748B]"></span>
				<span class="text-xs font-semibold text-[#64748B]"></span>
				<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">Name</span>
				<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">Expenses</span>
				<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide text-right">Actions</span>
			</div>

			{#if loading}
				{#each Array(5) as _, i (i)}
					<div
						class="grid px-4 py-3 border-b border-[#E2E8F0] last:border-b-0 items-center gap-2"
						style="grid-template-columns: 2rem 2rem 1fr 8rem 5rem; min-height: 44px"
					>
						<div class="w-4 h-4 rounded-full bg-[#E2E8F0] animate-pulse"></div>
						<div class="w-4 h-4 bg-[#E2E8F0] rounded animate-pulse"></div>
						<div class="h-4 w-32 bg-[#E2E8F0] rounded animate-pulse"></div>
						<div class="h-4 w-16 bg-[#E2E8F0] rounded animate-pulse"></div>
						<div class="h-4 w-10 bg-[#E2E8F0] rounded animate-pulse ml-auto"></div>
					</div>
				{/each}
			{:else}
				{#each categories as cat (cat.id)}
					<div
						class="grid px-4 border-b border-[#E2E8F0] last:border-b-0 items-center gap-2"
						style="grid-template-columns: 2rem 2rem 1fr 8rem 5rem; min-height: 44px"
					>
						<!-- Color swatch -->
						<span
							class="w-4 h-4 rounded-full shrink-0"
							style="background-color: {cat.color}"
						></span>

						<!-- Icon (displayed as a colored dot with abbreviated label for now) -->
						<span
							class="w-4 h-4 text-xs flex items-center justify-center"
							style="color: {cat.color}"
							title={cat.icon}
						>
							{cat.icon.slice(0, 1)}
						</span>

						<!-- Name / inline rename -->
						<div class="flex items-center gap-2">
							{#if renamingId === cat.id}
								<input
									bind:value={renameValue}
									type="text"
									class="h-8 px-2 rounded-lg border border-[#E2E8F0] text-sm bg-white text-[#0F172A]
									       focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5] outline-none"
									style="width: 180px"
									onkeydown={(e) => handleRenameKeydown(e, cat)}
									onblur={() => saveRename(cat)}
									disabled={renameSaving}
								/>
								<button
									type="button"
									onclick={() => saveRename(cat)}
									class="w-7 h-7 flex items-center justify-center rounded text-[#4F46E5] hover:bg-indigo-50"
									disabled={renameSaving}
									aria-label="Save rename"
								>
									{#if renameSaving}
										<Loader2 size={13} class="animate-spin" />
									{:else}
										<Check size={13} />
									{/if}
								</button>
								<button
									type="button"
									onclick={cancelRename}
									class="w-7 h-7 flex items-center justify-center rounded text-[#64748B] hover:bg-[#F8FAFC]"
									aria-label="Cancel rename"
								>
									<X size={13} />
								</button>
							{:else}
								<span class="text-sm font-semibold text-[#0F172A]">{cat.name}</span>
								{#if cat.is_protected}
									<span class="text-xs text-[#64748B]">(protected)</span>
								{/if}
							{/if}
						</div>

						<!-- Expense count -->
						<span class="text-xs text-[#64748B]">
							{cat.expense_count ?? 0} expense{(cat.expense_count ?? 0) !== 1 ? 's' : ''}
						</span>

						<!-- Actions (hidden for protected) -->
						<div class="flex items-center justify-end gap-1">
							{#if !cat.is_protected}
								<button
									type="button"
									onclick={() => startRename(cat)}
									class="w-8 h-8 flex items-center justify-center rounded-md text-[#64748B]
									       hover:text-[#4F46E5] hover:bg-[#F8FAFC] transition-colors"
									aria-label="Rename {cat.name}"
								>
									<Pencil size={15} />
								</button>
								<button
									type="button"
									onclick={() => openDeleteDialog(cat.id)}
									class="w-8 h-8 flex items-center justify-center rounded-md text-[#64748B]
									       hover:text-[#EF4444] hover:bg-red-50 transition-colors"
									aria-label="Delete {cat.name}"
								>
									<Trash2 size={15} />
								</button>
							{/if}
						</div>
					</div>
				{/each}
			{/if}
		</div>
	{/if}
</div>
