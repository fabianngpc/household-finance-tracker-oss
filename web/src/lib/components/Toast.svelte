<script lang="ts">
	import { toast } from '$lib/stores/toast.js';
</script>

<!-- Toast container: fixed bottom-right, 3s auto-dismiss, slide-in from right -->
<div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
	{#each $toast as item (item.id)}
		<div
			class="pointer-events-auto bg-[#0F172A] text-white text-sm px-4 py-3 rounded-lg shadow-lg
			       min-w-[220px] max-w-[340px] animate-slide-in-right"
		>
			{item.message}
		</div>
	{/each}
</div>

<style>
	@keyframes slide-in-right {
		from {
			transform: translateX(120%);
			opacity: 0;
		}
		to {
			transform: translateX(0);
			opacity: 1;
		}
	}
	.animate-slide-in-right {
		animation: slide-in-right 0.2s ease-out;
	}
</style>
