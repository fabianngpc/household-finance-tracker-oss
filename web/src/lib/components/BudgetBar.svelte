<script lang="ts">
	import type { BudgetBandName } from '$lib/api.js';

	interface Props {
		pct: number;
		band: BudgetBandName;
	}

	let { pct, band }: Props = $props();

	const BAND_COLOR: Record<BudgetBandName, string> = {
		healthy: '#16A34A',
		warning: '#F59E0B',
		over: '#EF4444',
	};

	let fillWidth = $derived(Math.min(pct, 100));
	let fillColor = $derived(BAND_COLOR[band]);
</script>

<!-- Track: 8px, rounded-full, on-system track color -->
<div class="h-2 rounded-full bg-[#E2E8F0] w-full overflow-hidden">
	<div
		class="h-full rounded-full transition-[width]"
		style="width: {fillWidth}%; background-color: {fillColor};"
	></div>
</div>
