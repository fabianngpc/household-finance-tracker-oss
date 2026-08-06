<script lang="ts">
	import { api, type Category } from '$lib/api.js';
	import { toast } from '$lib/stores/toast.js';
	import Loader2 from '@lucide/svelte/icons/loader-2';
	import X from '@lucide/svelte/icons/x';

	// Category color palette (10 fixed slots per UI-SPEC)
	const PALETTE = [
		'#F97316', // Food & Dining
		'#22C55E', // Groceries
		'#3B82F6', // Transport
		'#8B5CF6', // Housing/Rent
		'#06B6D4', // Utilities
		'#EC4899', // Shopping
		'#EF4444', // Health
		'#F59E0B', // Entertainment
		'#14B8A6', // Travel
		'#6B7280', // Other
	];

	// Curated icon grid (18+ icons per UI-SPEC)
	const ICONS = [
		'UtensilsCrossed',
		'ShoppingCart',
		'Car',
		'Home',
		'Zap',
		'ShoppingBag',
		'HeartPulse',
		'Tv2',
		'Plane',
		'Tag',
		'Briefcase',
		'Coffee',
		'Gift',
		'Music',
		'Gamepad2',
		'Heart',
		'Star',
		'Dumbbell',
	];

	let {
		open = $bindable(false),
		editCategory = null as Category | null,
		onSave = () => {},
	}: {
		open?: boolean;
		editCategory?: Category | null;
		onSave?: () => void;
	} = $props();

	let name = $state('');
	let selectedColor = $state(PALETTE[0]);
	let selectedIcon = $state(ICONS[0]);
	let submitting = $state(false);
	let nameError = $state('');

	// Reset form when dialog opens or editCategory changes
	$effect(() => {
		if (open) {
			if (editCategory) {
				name = editCategory.name;
				selectedColor = editCategory.color;
				selectedIcon = editCategory.icon;
			} else {
				name = '';
				selectedColor = PALETTE[0];
				selectedIcon = ICONS[0];
			}
			nameError = '';
		}
	});

	function close() {
		open = false;
	}

	async function handleSubmit(e: Event) {
		e.preventDefault();
		nameError = '';

		if (!name.trim()) {
			nameError = 'Name is required. Check the highlighted fields and try again.';
			return;
		}

		submitting = true;
		try {
			if (editCategory) {
				await api.categories.update(editCategory.id, {
					name: name.trim(),
					color: selectedColor,
					icon: selectedIcon,
				});
			} else {
				await api.categories.create({
					name: name.trim(),
					color: selectedColor,
					icon: selectedIcon,
				});
			}
			close();
			onSave();
		} catch (err) {
			nameError = err instanceof Error ? err.message : 'Failed to save category.';
		} finally {
			submitting = false;
		}
	}

	// Dynamically load icon component
	// We render icons as colored squares since importing all dynamically is complex;
	// we use a simple icon name label approach with a custom icon renderer.
	// For the icon picker, we'll show the icon name abbreviated as a visual grid.
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center"
		role="dialog"
		aria-modal="true"
		aria-labelledby="category-dialog-title"
	>
		<!-- Overlay -->
		<button
			type="button"
			class="absolute inset-0 bg-black/50 cursor-default"
			onclick={close}
			aria-label="Close dialog"
			tabindex="-1"
		></button>

		<!-- Dialog panel -->
		<div class="relative bg-white rounded-lg border border-[#E2E8F0] shadow-xl w-full max-w-md mx-4 p-6">
			<!-- Close button -->
			<button
				type="button"
				onclick={close}
				class="absolute top-4 right-4 w-8 h-8 flex items-center justify-center rounded-md
				       text-[#64748B] hover:text-[#0F172A] hover:bg-[#F8FAFC] transition-colors"
				aria-label="Close"
			>
				<X size={16} />
			</button>

			<h2 id="category-dialog-title" class="text-lg font-semibold text-[#0F172A] mb-4">
				{editCategory ? 'Edit Category' : 'Add Category'}
			</h2>

			<form onsubmit={handleSubmit} class="flex flex-col gap-4">
				<!-- Name field -->
				<div class="flex flex-col gap-1">
					<label class="text-xs font-semibold text-[#64748B] uppercase tracking-wide" for="cat-name">
						Name
					</label>
					<input
						id="cat-name"
						bind:value={name}
						type="text"
						placeholder="Category name"
						class={[
							'h-10 px-3 rounded-lg border text-sm bg-white text-[#0F172A]',
							'placeholder:text-[#64748B] outline-none transition-colors',
							'focus:ring-2 focus:ring-[#4F46E5]/30 focus:border-[#4F46E5]',
							nameError ? 'border-[#EF4444]' : 'border-[#E2E8F0]',
						].join(' ')}
						disabled={submitting}
					/>
					{#if nameError}
						<p class="text-xs text-[#EF4444]">{nameError}</p>
					{/if}
				</div>

				<!-- Color picker -->
				<div class="flex flex-col gap-2">
					<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">
						Color
					</span>
					<div class="flex gap-2 flex-wrap">
						{#each PALETTE as color (color)}
							<button
								type="button"
								onclick={() => (selectedColor = color)}
								class={[
									'w-6 h-6 rounded-full border-2 transition-all hover:scale-110',
									selectedColor === color
										? 'border-[#0F172A] scale-110'
										: 'border-transparent',
								].join(' ')}
								style="background-color: {color}"
								aria-label="Select color {color}"
								aria-pressed={selectedColor === color}
							></button>
						{/each}
					</div>
				</div>

				<!-- Icon picker -->
				<div class="flex flex-col gap-2">
					<span class="text-xs font-semibold text-[#64748B] uppercase tracking-wide">
						Icon
					</span>
					<div class="flex gap-1.5 flex-wrap">
						{#each ICONS as icon (icon)}
							<button
								type="button"
								onclick={() => (selectedIcon = icon)}
								class={[
									'w-10 h-10 flex items-center justify-center rounded-lg border text-xs font-medium transition-colors',
									selectedIcon === icon
										? 'border-[#4F46E5] bg-indigo-50 text-[#4F46E5]'
										: 'border-[#E2E8F0] text-[#64748B] hover:bg-[#F8FAFC]',
								].join(' ')}
								aria-label="Select icon {icon}"
								aria-pressed={selectedIcon === icon}
								title={icon}
							>
								<span class="truncate" style="font-size: 9px;">{icon.slice(0, 3)}</span>
							</button>
						{/each}
					</div>
				</div>

				<!-- Submit -->
				<div class="flex justify-end pt-2">
					<button
						type="submit"
						disabled={submitting}
						class="h-10 px-5 bg-[#4F46E5] text-white text-sm font-semibold rounded-lg
						       hover:bg-[#4338CA] transition-colors disabled:opacity-60 flex items-center gap-2"
					>
						{#if submitting}
							<Loader2 size={16} class="animate-spin" />
						{/if}
						Add Category
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}
