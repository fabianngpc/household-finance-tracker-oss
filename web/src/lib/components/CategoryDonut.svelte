<script lang="ts">
	import '$lib/chart.js';
	import { Doughnut } from 'svelte-chartjs';
	import { formatSgd } from '$lib/format.js';
	import type { ChartData, ChartOptions } from 'chart.js';

	interface Slice {
		name: string;
		color: string;
		total_sgd_minor: number;
	}

	interface Props {
		slices: Slice[];
		height?: number; // px, default 220
	}

	let { slices, height = 220 }: Props = $props();

	let chartData = $derived<ChartData<'doughnut', number[], string>>({
		labels: slices.map((s) => s.name),
		datasets: [
			{
				data: slices.map((s) => s.total_sgd_minor),
				backgroundColor: slices.map((s) => s.color),
				borderWidth: 2,
				borderColor: '#FFFFFF',
			},
		],
	});

	const chartOptions: ChartOptions<'doughnut'> = {
		responsive: true,
		maintainAspectRatio: false,
		plugins: {
			legend: { display: false },
			tooltip: {
				callbacks: {
					label: (ctx) => {
						const val = typeof ctx.raw === 'number' ? ctx.raw : 0;
						return ` ${ctx.label}: ${formatSgd(val)}`;
					},
				},
			},
		},
	};
</script>

{#if slices.length === 0}
	<div class="flex flex-col items-center justify-center text-center py-8 gap-2">
		<p class="text-sm font-semibold text-[#0F172A]">No data for this period</p>
		<p class="text-sm text-[#64748B]">Add expenses and they'll appear here.</p>
	</div>
{:else}
	<div style="height: {height}px; position: relative;">
		<Doughnut data={chartData} options={chartOptions} />
	</div>
	<!-- Legend: name + formatSgd(total), 12px -->
	<div class="mt-3 flex flex-col gap-1">
		{#each slices as slice}
			<div class="flex items-center justify-between gap-2 text-[12px]">
				<div class="flex items-center gap-1.5">
					<span
						class="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0"
						style="background-color: {slice.color};"
					></span>
					<span class="text-[#0F172A]">{slice.name}</span>
				</div>
				<span class="tabular-nums text-[#64748B]">{formatSgd(slice.total_sgd_minor)}</span>
			</div>
		{/each}
	</div>
{/if}
