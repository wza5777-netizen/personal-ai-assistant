// Centralized token + user-scoped client state storage.
//
// SECURITY NOTE: This stage stores the Bearer JWT in localStorage as an
// engineering compromise for the current SPA architecture. All token access
// MUST go through this module so that, in a production custom-domain / BFF
// deployment, we can swap to a Secure HttpOnly Cookie without touching the
// rest of the app — only this file (and the API client) would need to change.
//
// Never call `localStorage.getItem("access_token")` directly from a component.

const ACCESS_TOKEN_KEY = "access_token";

/**
 * localStorage is only available in the browser. These guards keep the module
 * safe during Next.js server-side rendering (no `window`/`localStorage`).
 */
function hasWindow(): boolean {
  return typeof window !== "undefined";
}

export function getAccessToken(): string | null {
  if (!hasWindow()) return null;
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  if (!hasWindow()) return;
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  if (!hasWindow()) return;
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
}

/**
 * User-scoped conversation key. Each authenticated user gets an isolated
 * "current conversation" pointer so that User B never restores User A's chat
 * after a logout/login cycle.
 *
 * Note: the legacy shared `"conversation_id"` key is intentionally NOT used
 * here. `clearUserLocalState` removes it during logout to clean up old data.
 */
export function conversationKeyFor(userId: string): string {
  return `conversation_id:${userId}`;
}

const LEGACY_CONVERSATION_KEY = "conversation_id";

/**
 * Remove all user-specific client state: the access token plus any cached
 * conversation id / messages. Called on logout and on invalid-token (401).
 *
 * Centralizing this guarantees a clean slate between accounts.
 */
export function clearUserLocalState(userId?: string | null): void {
  if (!hasWindow()) return;
  clearAccessToken();
  // Legacy shared conversation key (pre user-scoping).
  window.localStorage.removeItem(LEGACY_CONVERSATION_KEY);
  // User-scoped conversation key.
  if (userId) {
    window.localStorage.removeItem(conversationKeyFor(userId));
  }
  // Defensive sweep: drop any remaining user-scoped conversation keys.
  for (let i = window.localStorage.length - 1; i >= 0; i--) {
    const k = window.localStorage.key(i);
    if (k && k.startsWith("conversation_id:")) {
      window.localStorage.removeItem(k);
    }
  }
}
