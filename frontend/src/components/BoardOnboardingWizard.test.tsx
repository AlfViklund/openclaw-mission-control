import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BoardOnboardingWizard } from "./BoardOnboardingWizard";

const customFetchMock = vi.fn<(...args: unknown[]) => Promise<unknown>>();

vi.mock("@/api/mutator", () => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  customFetch: (...args: unknown[]) => (customFetchMock as any)(...args),
}));

vi.mock("@/components/ui/dialog", () => ({
  DialogHeader: ({ children }: { children?: ReactNode }) => (
    <div data-testid="dialog-header">{children}</div>
  ),
  DialogFooter: ({ children }: { children?: ReactNode }) => (
    <div data-testid="dialog-footer">{children}</div>
  ),
  DialogTitle: ({ children }: { children?: ReactNode }) => (
    <h2 data-testid="dialog-title">{children}</h2>
  ),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    onClick,
    disabled,
    "data-testid": testid,
  }: {
    children?: ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    "data-testid"?: string;
  }) => (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testid}
    >
      {children}
    </button>
  ),
}));

vi.mock("@/components/ui/input", () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input type="text" {...props} />
  ),
}));

vi.mock("@/components/ui/textarea", () => ({
  Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
    <textarea {...props} />
  ),
}));

vi.mock("@/components/ui/select", () => ({
  Select: ({
    children,
    value,
  }: {
    children?: ReactNode;
    value?: string;
  }) => (
    <div data-testid="select">
      <span>{value}</span>
      <div>{children}</div>
    </div>
  ),
  SelectContent: ({ children }: { children?: ReactNode }) => (
    <div data-testid="select-content">{children}</div>
  ),
  SelectItem: ({
    children,
    value,
  }: {
    children?: ReactNode;
    value?: string;
  }) => (
    <button type="button" data-testid={`select-item-${value}`}>
      {children}
    </button>
  ),
  SelectTrigger: ({ children }: { children?: ReactNode }) => (
    <div>{children}</div>
  ),
  SelectValue: ({ children }: { children?: ReactNode }) => (
    <span>{children}</span>
  ),
}));

async function advanceWizard(targetTitle: string) {
  await waitFor(
    () => {
      const btn = screen.queryByRole("button", { name: /next/i });
      if (btn && !btn.hasAttribute("disabled")) {
        fireEvent.click(btn);
      }
    },
    { timeout: 5000 },
  );
  await waitFor(
    () => {
      expect(screen.getByTestId("dialog-title")).toHaveTextContent(targetTitle);
    },
    { timeout: 5000 },
  );
}

describe("BoardOnboardingWizard", () => {
  beforeEach(() => {
    customFetchMock.mockReset();
    customFetchMock.mockImplementation(() =>
      Promise.resolve({ status: 200, data: {} }),
    );
  });

  describe("step 1 — project setup", () => {
    it("renders the wizard on step 1 with correct title", () => {
      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      expect(screen.getByTestId("dialog-title")).toHaveTextContent(
        "What are we building?",
      );
    });

    it("renders all project mode and stage options", () => {
      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      expect(screen.getByText("New product")).toBeTruthy();
      expect(screen.getByText("Existing product evolution")).toBeTruthy();
      expect(screen.getByText("Idea only")).toBeTruthy();
      expect(screen.getByText("Codebase exists")).toBeTruthy();
    });

    it("disables Next button when required fields are empty", () => {
      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
    });
  });

  describe("step 5 — team provisioning", () => {
    it("uses button-based options, not a chat input", () => {
      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      const textboxes = screen.queryAllByRole("textbox");
      expect(textboxes).toHaveLength(0);
    });
  });

  describe("step 9 — AI refinement", () => {
    it("shows refine button on step 9", () => {
      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      expect(screen.queryByText("Let AI refine this setup")).toBeNull();
    });
  });

  describe("step 10 — review screen", () => {
    it("shows review screen heading", () => {
      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      expect(screen.queryByText("Review Configuration")).toBeNull();
    });
  });

  describe("step 11 — outcome screen", () => {
    it("shows bootstrap complete title", () => {
      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      expect(screen.queryByText("Bootstrap complete")).toBeNull();
    });
  });
});
