// Chart.js global registration — import this once before using any chart component.
// Registers all required controllers, elements, scales, and plugins for Doughnut + Bar charts.

import {
	Chart,
	ArcElement,
	Tooltip,
	Legend,
	BarElement,
	CategoryScale,
	LinearScale,
	type ChartOptions,
} from 'chart.js';

Chart.register(ArcElement, Tooltip, Legend, BarElement, CategoryScale, LinearScale);

/** Default tooltip options shared by all charts */
export const defaultTooltipOptions: ChartOptions['plugins'] = {
	tooltip: {
		backgroundColor: '#0F172A',
		titleColor: '#F8FAFC',
		bodyColor: '#F8FAFC',
		padding: 8,
		cornerRadius: 6,
	},
};
