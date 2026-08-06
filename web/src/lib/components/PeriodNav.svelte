<script lang="ts">
	import { ChevronLeft, ChevronRight } from '@lucide/svelte';

	interface Props {
		year: number;
		month?: number; // required when mode === 'monthly'
		mode: 'monthly' | 'yearly';
		onchange: (period: { year: number; month?: number }) => void;
	}

	let { year, month = 1, mode, onchange }: Props = $props();

	// Month names for quick-picker
	const MONTH_NAMES = [
		'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
		'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
	];

	// ── Navigation helpers ──────────────────────────────────────────────────────

	function prev() {
		if (mode === 'monthly') {
			const m = month - 1;
			if (m < 1) {
				onchange({ year: year - 1, month: 12 });
			} else {
				onchange({ year, month: m });
			}
		} else {
			onchange({ year: year - 1 });
		}
	}

	function next() {
		if (mode === 'monthly') {
			const m = month + 1;
			if (m > 12) {
				onchange({ year: year + 1, month: 1 });
			} else {
				onchange({ year, month: m });
			}
		} else {
			onchange({ year: year + 1 });
		}
	}

	function pickMonth(m: number) {
		onchange({ year, month: m });
	}

	function pickYear(y: number) {
		onchange({ year: y });
	}

	// Year range for yearly picker
	const CURRENT_YEAR = new Date().getFullYear();
	const yearOptions = Array.from({ length: 5 }, (_, i) => CURRENT_YEAR - 2 + i);

	// Label text
	let label = $derived(
		mode === 'monthly'
			? `${MONTH_NAMES[(month ?? 1) - 1]} ${year}`
			: `${year}`
	);
</script>

<div class="flex items-center gap-1">
	<!-- Prev arrow: 40px touch target -->
	<button
		type="button"
		onclick={prev}
		class="flex items-center justify-center w-10 h-10 rounded-md text-[#64748B] hover:bg-[#F8FAFC] hover:text-[#0F172A] transition-colors"
		aria-label="Previous period"
	>
		<ChevronLeft size={16} />
	</button>

	<!-- Quick picker -->
	{#if mode === 'monthly'}
		<!-- Month + year select -->
		<div class="flex items-center gap-1">
			<select
				class="text-sm text-[#0F172A] bg-transparent border-none outline-none cursor-pointer font-medium"
				value={month}
				onchange={(e) => {
					const t = e.target as HTMLSelectElement;
					pickMonth(Number(t.value));
				}}
				aria-label="Select month"
			>
				{#each MONTH_NAMES as name, i}
					<option value={i + 1}>{name}</option>
				{/each}
			</select>
			<select
				class="text-sm text-[#0F172A] bg-transparent border-none outline-none cursor-pointer font-medium"
				value={year}
				onchange={(e) => {
					const t = e.target as HTMLSelectElement;
					pickYear(Number(t.value));
				}}
				aria-label="Select year"
			>
				{#each yearOptions as y}
					<option value={y}>{y}</option>
				{/each}
			</select>
		</div>
	{:else}
		<!-- Year select -->
		<select
			class="text-sm text-[#0F172A] bg-transparent border-none outline-none cursor-pointer font-medium"
			value={year}
			onchange={(e) => {
				const t = e.target as HTMLSelectElement;
				pickYear(Number(t.value));
			}}
			aria-label="Select year"
		>
			{#each yearOptions as y}
				<option value={y}>{y}</option>
			{/each}
		</select>
	{/if}

	<!-- Next arrow: 40px touch target -->
	<button
		type="button"
		onclick={next}
		class="flex items-center justify-center w-10 h-10 rounded-md text-[#64748B] hover:bg-[#F8FAFC] hover:text-[#0F172A] transition-colors"
		aria-label="Next period"
	>
		<ChevronRight size={16} />
	</button>
</div>
