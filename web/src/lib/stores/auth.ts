import { writable } from 'svelte/store';
import { api, type User } from '$lib/api';

interface AuthState {
	user: User | null;
	loading: boolean;
}

function createAuthStore() {
	const { subscribe, set, update } = writable<AuthState>({
		user: null,
		loading: false,
	});

	return {
		subscribe,

		/** Log in with username and password. Sets the user on success, throws on failure. */
		async login(username: string, password: string): Promise<User> {
			const result = await api.auth.login(username, password);
			set({ user: result.user, loading: false });
			return result.user;
		},

		/** Log out and clear the user state. */
		async logout(): Promise<void> {
			try {
				await api.auth.logout();
			} finally {
				set({ user: null, loading: false });
			}
		},

		/** Fetch the current user from the server (used on app load). */
		async loadMe(): Promise<User | null> {
			update((s) => ({ ...s, loading: true }));
			try {
				const user = await api.auth.me();
				set({ user, loading: false });
				return user;
			} catch {
				set({ user: null, loading: false });
				return null;
			}
		},

		/** Imperatively set the user (e.g. for testing). */
		setUser(user: User | null): void {
			update((s) => ({ ...s, user }));
		},
	};
}

export const auth = createAuthStore();
