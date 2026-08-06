<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { Combobox } from 'bits-ui';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import { api, type Category } from '$lib/api.js';

	let {
		categoryId = $bindable<number | null>(null),
		error = false,
		categories: propCategories = null as Category[] | null,
		inputId = undefined as string | undefined,
		onUserChange = undefined as (() => void) | undefined,
	}: {
		categoryId?: number | null;
		error?: boolean;
		categories?: Category[] | null;
		inputId?: string;
		/** Fires only on explicit user interaction (pick or clear), NOT on an
		 * external `bind:categoryId` update — lets a parent distinguish a manual
		 * override from a programmatic default. */
		onUserChange?: () => void;
	} = $props();

	let fetched = $state<Category[]>([]);
	// Prefer the parent-provided list once it has loaded; otherwise fall back to our own
	// fetch. The parent passes an empty array initially (still loading), so a plain
	// `propCategories ?? fetched` would latch onto [] — derive on length instead so the
	// picker reactively picks up categories whenever either source becomes populated.
	let categories = $derived(
		propCategories && propCategories.length > 0 ? propCategories : fetched
	);
	let inputText = $state('');
	let comboValue = $state('');
	let open = $state(false);
	let loading = $state(true);

	onMount(async () => {
		// Fetch our own copy unless the parent already handed us a populated list.
		if (!propCategories || propCategories.length === 0) {
			try {
				fetched = await api.categories.list();
			} catch {
				// non-fatal — parent may still supply the list reactively
			}
		}
		loading = false;
	});

	// Sync the input/combo display when a value is set externally and categories arrive.
	$effect(() => {
		if (categoryId !== null && categories.length > 0) {
			const cat = categories.find((c) => c.id === categoryId);
			if (cat && comboValue !== String(cat.id)) {
				untrack(() => {
					comboValue = String(cat.id);
					inputText = cat.name;
				});
			}
		}
	});

	// Direction 1: combobox selection → categoryId
	$effect(() => {
		const parsed = comboValue ? Number(comboValue) : null;
		untrack(() => {
			categoryId = parsed;
		});
	});

	// Direction 2: parent resets categoryId → clear combobox
	$effect(() => {
		if (categoryId === null) {
			untrack(() => {
				if (comboValue !== '') {
					comboValue = '';
					inputText = '';
				}
			});
		}
	});

	let filteredItems = $derived(
		inputText.trim() === ''
			? categories.map((c) => ({ value: String(c.id), label: c.name, color: c.color }))
			: categories
					.filter((c) => c.name.toLowerCase().includes(inputText.toLowerCase()))
					.map((c) => ({ value: String(c.id), label: c.name, color: c.color }))
	);

	let selectedCategory = $derived(
		comboValue ? categories.find((c) => String(c.id) === comboValue) ?? null : null
	);

	function handleSelect(value: string) {
		comboValue = value;
		const cat = categories.find((c) => String(c.id) === value);
		if (cat) {
			inputText = cat.name;
		}
		open = false;
		onUserChange?.();
	}

	function handleInput(e: Event) {
		inputText = (e.target as HTMLInputElement).value;
		// If user clears the text, reset selection
		if (inputText === '') {
			comboValue = '';
			untrack(() => {
				categoryId = null;
			});
			onUserChange?.();
		}
		open = true;
	}
</script>

<div class="relative w-[160px]">
	<div
		class={[
			'flex items-center gap-1.5 h-10 px-2.5 rounded-lg border bg-white text-sm cursor-pointer transition-colors',
			error
				? 'border-[#EF4444] focus-within:ring-2 focus-within:ring-[#EF4444]/30'
				: 'border-[#E2E8F0] focus-within:ring-2 focus-within:ring-[#4F46E5]/30 focus-within:border-[#4F46E5]',
		].join(' ')}
		role="combobox"
		aria-expanded={open}
		aria-controls="category-listbox"
		aria-haspopup="listbox"
	>
		{#if selectedCategory}
			<span
				class="w-3 h-3 rounded-full shrink-0"
				style="background-color: {selectedCategory.color}"
			></span>
		{/if}
		<input
			id={inputId}
			class="flex-1 bg-transparent outline-none text-[#0F172A] placeholder:text-[#64748B] min-w-0 text-sm"
			placeholder="Category"
			value={inputText}
			oninput={handleInput}
			onfocus={() => (open = true)}
			onblur={() => setTimeout(() => (open = false), 150)}
			autocomplete="off"
			disabled={loading}
		/>
		<ChevronDown size={14} class="text-[#64748B] shrink-0 pointer-events-none" />
	</div>

	{#if open && filteredItems.length > 0}
		<div
			id="category-listbox"
			role="listbox"
			aria-label="Categories"
			class="absolute z-50 top-full mt-1 left-0 w-full bg-white border border-[#E2E8F0] rounded-lg shadow-lg overflow-auto max-h-48"
		>
			{#each filteredItems as item (item.value)}
				<button
					type="button"
					class={[
						'w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-[#F8FAFC] transition-colors',
						comboValue === item.value ? 'bg-[#F8FAFC] text-[#4F46E5] font-medium' : 'text-[#0F172A]',
					].join(' ')}
					onmousedown={(e) => {
						e.preventDefault();
						handleSelect(item.value);
					}}
				>
					<span class="w-3 h-3 rounded-full shrink-0" style="background-color: {item.color}"></span>
					{item.label}
				</button>
			{/each}
		</div>
	{/if}
</div>
