// Simple toast notification store.
// Toasts appear bottom-right, auto-dismiss after `duration` ms (default 3000).

import { writable } from 'svelte/store';

export interface ToastItem {
	id: number;
	message: string;
}

let nextId = 0;

function createToastStore() {
	const { subscribe, update } = writable<ToastItem[]>([]);

	function show(message: string, duration = 3000) {
		const id = ++nextId;
		update((toasts) => [...toasts, { id, message }]);
		setTimeout(() => {
			update((toasts) => toasts.filter((t) => t.id !== id));
		}, duration);
	}

	return { subscribe, show };
}

export const toast = createToastStore();
