"use client";

import { AuthMode } from "@/auth/mode";

let localToken: string | null = null;
const STORAGE_KEY = "mc_local_auth_token";
const LEGACY_STORAGE_KEY = "mc_auth_token";

export function isLocalAuthMode(): boolean {
  return process.env.NEXT_PUBLIC_AUTH_MODE === AuthMode.Local;
}

export function setLocalAuthToken(token: string): void {
  localToken = token;
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, token);
    window.localStorage.setItem(LEGACY_STORAGE_KEY, token);
  } catch {
    // Ignore storage failures (private mode / policy).
  }
}

export function getLocalAuthToken(): string | null {
  if (localToken) return localToken;
  if (typeof window === "undefined") return null;
  try {
    const stored = window.sessionStorage.getItem(STORAGE_KEY);
    if (stored) {
      localToken = stored;
      return stored;
    }
    const legacyStored = window.localStorage.getItem(LEGACY_STORAGE_KEY);
    if (legacyStored) {
      localToken = legacyStored;
      try {
        window.sessionStorage.setItem(STORAGE_KEY, legacyStored);
      } catch {
        // Ignore storage failures (private mode / policy).
      }
      return legacyStored;
    }
  } catch {
    // Ignore storage failures (private mode / policy).
  }
  return null;
}

export function clearLocalAuthToken(): void {
  localToken = null;
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    // Ignore storage failures (private mode / policy).
  }
}
