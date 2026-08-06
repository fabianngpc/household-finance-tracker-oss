<script lang="ts">
	interface Props {
		label: string;
		value: string;
		accent?: string; // Optional color swatch (hex) shown next to value
	}

	let { label, value, accent }: Props = $props();
</script>

<div class="rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-4 flex flex-col gap-1">
	<!-- Label: 12px semibold muted -->
	<span class="text-[12px] font-semibold text-[#64748B] leading-[1.4] uppercase tracking-wide">
		{label}
	</span>
	<!-- Value: 30px semibold, tabular-nums -->
	<div class="flex items-center gap-2 mt-1">
		{#if accent}
			<span
				class="inline-block w-3 h-3 rounded-full flex-shrink-0"
				style="background-color: {accent};"
			></span>
		{/if}
		<span class="text-[30px] font-semibold text-[#0F172A] leading-[1.1] tabular-nums">
			{value}
		</span>
	</div>
</div>
