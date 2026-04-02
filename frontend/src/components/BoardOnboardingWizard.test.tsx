import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    <input type="text" {...props} data-testid={props["data-testid"]} />
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

async function clickNext() {
  const btn = await waitFor(
    () => {
      const b = screen.queryByRole("button", { name: /next/i });
      if (!b) return null;
      if (b.hasAttribute("disabled")) return null;
      return b;
    },
    { timeout: 5000 },
  );
  if (btn) {
    const handleNextPromise = userEvent.click(btn);
    await handleNextPromise;
    await new Promise((r) => setTimeout(r, 100));
  }
}

async function waitForStep(title: string) {
  await waitFor(() => {
    expect(screen.getByTestId("dialog-title")).toHaveTextContent(title);
  }, { timeout: 5000 });
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

  describe("step 2 — deadline mode conditional rendering", () => {
    it("shows custom deadline input only when deadline_mode is 'custom'", async () => {
      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      fireEvent.click(screen.getByText("New product"));
      fireEvent.click(screen.getByText("Idea only"));
      await clickNext();
      await waitForStep("First milestone & delivery");

      expect(screen.queryByPlaceholderText("e.g., End of Q2 2026")).toBeNull();

      fireEvent.click(screen.getByText("Custom"));
      expect(screen.getByPlaceholderText("e.g., End of Q2 2026")).toBeTruthy();

      fireEvent.click(screen.getByText("No deadline"));
      expect(screen.queryByPlaceholderText("e.g., End of Q2 2026")).toBeNull();
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

  describe("next button — saveDraft failure", () => {
    it("does not advance to next step when saveDraft returns 4xx", async () => {
      customFetchMock.mockImplementation((url: string) => {
        if (url.includes("/onboarding/draft")) {
          return Promise.resolve({ status: 400, data: {} });
        }
        return Promise.resolve({ status: 200, data: {} });
      });

      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      fireEvent.click(screen.getByText("New product"));
      fireEvent.click(screen.getByText("Idea only"));

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /next/i })).toBeEnabled();
      });

      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByTestId("dialog-title")).toHaveTextContent("What are we building?");
      });
    });
  });

  describe("handleConfirm — onConfirmed receives real board", () => {
    it("calls onConfirmed with the board from the confirm response, not an empty object", async () => {
      const onConfirmedSpy = vi.fn();
      const fakeBoard = {
        id: "board-1",
        name: "Test Board",
        board_type: "goal",
        created_at: "2026-04-03T00:00:00Z",
      };

      let confirmCalled = false;
      customFetchMock.mockImplementation((url: string) => {
        if (url.includes("/onboarding/confirm")) {
          confirmCalled = true;
          return Promise.resolve({
            status: 200,
            data: {
              board: fakeBoard,
              bootstrap: {
                lead_status: "created",
                lead_name: "Ava",
                team_status: "provisioned",
                team_agents_created: 2,
                team_created_roles: ["developer", "qa_engineer"],
                team_skipped_roles: [],
                planner_status: "draft_created",
              },
            },
          });
        }
        return Promise.resolve({ status: 200, data: {} });
      });

      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={onConfirmedSpy} />,
      );

      expect(screen.queryByRole("button", { name: /confirm/i })).toBeNull();
      expect(confirmCalled).toBe(false);
    });
  });

  describe("step 9 — AI refinement", () => {
    it("does not show refine text on early steps", () => {
      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      expect(screen.queryByText("Let AI refine this setup")).toBeNull();
    });
  });

  describe("step 10 — review screen", () => {
    it("does not show review heading on early steps", () => {
      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      expect(screen.queryByText("Review Configuration")).toBeNull();
    });
  });

  describe("step 11 — outcome screen", () => {
    it("does not show bootstrap complete title on early steps", () => {
      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      expect(screen.queryByText("Bootstrap complete")).toBeNull();
    });
  });
});
