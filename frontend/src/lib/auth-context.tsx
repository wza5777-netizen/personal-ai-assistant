"use client";

// Lightweight authentication state built on React Context + the backend JWT.
// No Redux / NextAuth / OAuth / refresh-token machinery — the backend issues a
// single user Bearer JWT that we store via auth-storage and restore on load.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { authApi, setUnauthorizedHandler, User } from "./api-client";
import {
  clearUserLocalState,
  getAccessToken,
  setAccessToken,
} from "./auth-storage";

interface AuthState {
  user: User | null;
  /** True only during the initial token -> /auth/me restore check. */
  isLoading: boolean;
  isAuthenticated: boolean;
  /** Persist a freshly issued token + user (used after login / register). */
  setAuth: (token: string, user: User) => void;
  /** Clear all local auth state. */
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Called by the API client whenever any protected request returns 401.
  // We clear everything and drop to unauthenticated; route guards then redirect.
  const handleUnauthorized = useCallback(() => {
    clearUserLocalState();
    setUser(null);
    setIsLoading(false);
  }, []);

  // On mount: if a token exists, try to restore the user via /auth/me.
  // Failure (expired/invalid token) clears the stale token and stays guest.
  useEffect(() => {
    let cancelled = false;
    const token = getAccessToken();
    if (!token) {
      setIsLoading(false);
      return;
    }
    authApi
      .getMe()
      .then((u) => {
        if (cancelled) return;
        setUser(u);
        setIsLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        clearUserLocalState();
        setUser(null);
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const setAuth = useCallback((token: string, u: User) => {
    setAccessToken(token);
    setUser(u);
    setIsLoading(false);
  }, []);

  const logout = useCallback(() => {
    clearUserLocalState();
    setUser(null);
  }, []);

  // Register the 401 handler with the API client exactly once.
  useEffect(() => {
    setUnauthorizedHandler(handleUnauthorized);
    return () => setUnauthorizedHandler(null);
  }, [handleUnauthorized]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      isLoading,
      isAuthenticated: user !== null,
      setAuth,
      logout,
    }),
    [user, isLoading, setAuth, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
