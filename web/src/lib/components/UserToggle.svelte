<script lang="ts">
	import type { UserFilter } from '$lib/api.js';

	interface Props {
		value: UserFilter;
		myName?: string; // display name for 'mine' segment
		partnerName?: string; // display name for 'partner' segment
		onchange: (value: UserFilter) => void;
	}

	let { value, myName = 'Mine', partnerName = 'Partner', onchange }: Props = $props();

	const segments: { id: UserFilter; label: () => string }[] = [
		{ id: 'mine', label: () => myName },
		{ id: 'partner', label: () => partnerName },
		{ id: 'both', label: () => 'Both' },
	];
</script>

<div
	class="inline-flex items-center gap-0.5 rounded-lg border border-[#E2E8F0] bg-[#F1F5F9] p-0.5"
	role="group"
	aria-label="User filter"
>
	{#each segments as seg}
		<button
			type="button"
			onclick={() => onchange(seg.id)}
			aria-pressed={value === seg.id}
			class={[
				'px-3 h-8 text-sm font-semibold rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-[#4F46E5]/30',
				value === seg.id
					? 'bg-white text-[#4F46E5] shadow-sm'
					: 'bg-transparent text-[#64748B] hover:text-[#0F172A]',
			].join(' ')}
		>
			{seg.label()}
		</button>
	{/each}
</div>
