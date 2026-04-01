"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "clawdev_active_board_id";
const EVENT_NAME = "clawdev-active-board-change";

export function getActiveBoardId(): string {
  if (typeof window === "undefined") {
    return "";
  }
  return localStorage.getItem(STORAGE_KEY) || "";
}

export function setActiveBoardId(boardId: string): void {
  if (typeof window === "undefined") {
    return;
  }
  if (boardId) {
    localStorage.setItem(STORAGE_KEY, boardId);
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
  window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: boardId }));
}

export function useActiveBoard(): [string, (boardId: string) => void] {
  const [activeBoardId, setActiveBoardState] = useState("");

  useEffect(() => {
    setActiveBoardState(getActiveBoardId());

    const onStorage = () => setActiveBoardState(getActiveBoardId());
    const onCustom = (event: Event) => {
      const customEvent = event as CustomEvent<string>;
      setActiveBoardState(customEvent.detail || getActiveBoardId());
    };

    window.addEventListener("storage", onStorage);
    window.addEventListener(EVENT_NAME, onCustom as EventListener);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(EVENT_NAME, onCustom as EventListener);
    };
  }, []);

  return [activeBoardId, setActiveBoardId];
}
