<script lang="ts">
	import '$lib/chart.js';
	import { Bar } from 'svelte-chartjs';
	import { formatSgd } from '$lib/format.js';
	import type { ChartData, ChartOptions } from 'chart.js';

	interface Props {
		labels: string[];
		data: number[]; // SGD minor units
		title: string;
		height?: number; // px, default 220
	}

	let { labels, data, title, height = 220 }: Props = $props();

	let chartData = $derived<ChartData<'bar', number[], string>>({
		labels,
		datasets: [
			{
				label: title,
				data,
				backgroundColor: '#4F46E5',
				borderRadius: 4,
				borderSkipped: false,
			},
		],
	});

	const chartOptions: ChartOptions<'bar'> = {
		responsive: true,
		maintainAspectRatio: false,
		plugins: {
			legend: { display: false },
			tooltip: {
				callbacks: {
					label: (ctx) => {
						const val = typeof ctx.raw === 'number' ? ctx.raw : 0;
						return ` ${formatSgd(val)}`;
					},
				},
			},
		},
		scales: {
			y: {
				beginAtZero: true,
				ticks: {
					callback: (value) => formatSgd(typeof value === 'number' ? value : 0),
					font: { size: 11 },
					color: '#64748B',
					maxTicksLimit: 5,
				},
				grid: { color: '#E2E8F0' },
			},
			x: {
				ticks: {
					font: { size: 11 },
					color: '#64748B',
				},
				grid: { display: false },
			},
		},
	};
</script>

<div style="height: {height}px; position: relative;">
	<Bar data={chartData} options={chartOptions} />
</div>
