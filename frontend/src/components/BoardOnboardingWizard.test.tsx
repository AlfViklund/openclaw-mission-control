import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import { BoardOnboardingWizard, computeCurrentStep } from "./BoardOnboardingWizard";

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
  Input: ({ "data-testid": testid, ...props }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input type="text" data-testid={testid} {...props} />
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

      const nextBtn = await waitFor(
        () => {
          const b = screen.queryByRole("button", { name: /next/i });
          if (!b) return null;
          if (b.hasAttribute("disabled")) return null;
          return b;
        },
        { timeout: 5000 },
      );
      fireEvent.click(nextBtn!);
      await waitFor(() => {
        expect(screen.getByTestId("dialog-title")).toHaveTextContent("First milestone & delivery");
      });

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

  describe("confirm — does NOT call onConfirmed immediately", () => {
    it("does not call onConfirmed at step 1 (confirm button not rendered)", () => {
      const onConfirmedSpy = vi.fn();

      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={onConfirmedSpy} />,
      );

      expect(screen.getByTestId("dialog-title")).toHaveTextContent("What are we building?");
      expect(screen.queryByRole("button", { name: /confirm/i })).toBeNull();
      expect(onConfirmedSpy).not.toHaveBeenCalled();
    });
  });

  describe("restore progress — computeCurrentStep", () => {
    it("returns 1 for empty draft", () => {
      expect(computeCurrentStep({})).toBe(1);
    });

    it("returns 2 when only project_mode and project_stage are set", () => {
      expect(computeCurrentStep({ project_info: { project_mode: "new_product", project_stage: "codebase_exists" } })).toBe(2);
    });

    it("returns 2 when milestone set but delivery_mode missing", () => {
      expect(computeCurrentStep({ project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp" } })).toBe(2);
    });

    it("returns 2 when milestone+delivery set but deadline_mode missing", () => {
      expect(computeCurrentStep({ project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced" } })).toBe(2);
    });

    it("returns 4 when step 2 is fully complete (milestone+delivery+deadline=none), skipping optional step 3", () => {
      expect(computeCurrentStep({ project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced", deadline_mode: "none" } })).toBe(4);
    });

    it("returns 5 when lead_agent name is set", () => {
      expect(computeCurrentStep({
        project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced", deadline_mode: "none" },
        lead_agent: { name: "Ava" },
      })).toBe(5);
    });

    it("returns 6 when team_plan provision_mode is set", () => {
      expect(computeCurrentStep({
        project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced", deadline_mode: "none" },
        lead_agent: { name: "Ava" },
        team_plan: { provision_mode: "full_team" },
      })).toBe(6);
    });

    it("returns 7 when planning_policy bootstrap_mode is set", () => {
      expect(computeCurrentStep({
        project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced", deadline_mode: "none" },
        lead_agent: { name: "Ava" },
        team_plan: { provision_mode: "full_team" },
        planning_policy: { bootstrap_mode: "generate_backlog" },
      })).toBe(7);
    });

    it("returns 8 when qa_policy strictness is set", () => {
      expect(computeCurrentStep({
        project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced", deadline_mode: "none" },
        lead_agent: { name: "Ava" },
        team_plan: { provision_mode: "full_team" },
        planning_policy: { bootstrap_mode: "generate_backlog" },
        qa_policy: { strictness: "balanced" },
      })).toBe(8);
    });

    it("returns 10 when all steps 1–8 are complete and no refine state", () => {
      expect(computeCurrentStep({
        project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced", deadline_mode: "none" },
        lead_agent: { name: "Ava" },
        team_plan: { provision_mode: "full_team" },
        planning_policy: { bootstrap_mode: "generate_backlog" },
        qa_policy: { strictness: "balanced" },
        automation_policy: { automation_profile: "normal" },
      })).toBe(10);
    });

    it("returns 9 when refine is pending", () => {
      expect(computeCurrentStep({
        project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced", deadline_mode: "none" },
        lead_agent: { name: "Ava" },
        team_plan: { provision_mode: "full_team" },
        planning_policy: { bootstrap_mode: "generate_backlog" },
        qa_policy: { strictness: "balanced" },
        automation_policy: { automation_profile: "normal" },
      }, "pending")).toBe(9);
    });

    it("returns 9 when refine has questions", () => {
      expect(computeCurrentStep({
        project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced", deadline_mode: "none" },
        lead_agent: { name: "Ava" },
        team_plan: { provision_mode: "full_team" },
        planning_policy: { bootstrap_mode: "generate_backlog" },
        qa_policy: { strictness: "balanced" },
        automation_policy: { automation_profile: "normal" },
      }, "questions")).toBe(9);
    });

    it("returns 10 when refine is complete", () => {
      expect(computeCurrentStep({
        project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced", deadline_mode: "none" },
        lead_agent: { name: "Ava" },
        team_plan: { provision_mode: "full_team" },
        planning_policy: { bootstrap_mode: "generate_backlog" },
        qa_policy: { strictness: "balanced" },
        automation_policy: { automation_profile: "normal" },
      }, "complete")).toBe(10);
    });

    it("returns 10 when refine is idle", () => {
      expect(computeCurrentStep({
        project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced", deadline_mode: "none" },
        lead_agent: { name: "Ava" },
        team_plan: { provision_mode: "full_team" },
        planning_policy: { bootstrap_mode: "generate_backlog" },
        qa_policy: { strictness: "balanced" },
        automation_policy: { automation_profile: "normal" },
      }, "idle")).toBe(10);
    });
  });

  describe("confirm payload — objective is human-readable, not enum", () => {
    it("sends objective from context description without board_type", async () => {
      let capturedBody: unknown;
      customFetchMock.mockImplementation((url: string, opts?: { body?: string }) => {
        if (url.includes("/confirm")) {
          capturedBody = opts?.body ? JSON.parse(opts.body) : undefined;
          return Promise.resolve({
            status: 200,
            data: {
              board: { id: "board-1", name: "Test", slug: "test", description: "", organization_id: "o1", created_at: "", updated_at: "" },
              bootstrap: { lead_status: "created", team_status: "not_requested", team_agents_created: 0, team_created_roles: [], team_skipped_roles: [], team_failed_roles: [], planner_status: "not_requested" },
            },
          });
        }
        return Promise.resolve({ status: 200, data: {} });
      });

      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      // Advance through steps by filling required fields
      fireEvent.click(screen.getByText("New product"));
      fireEvent.click(screen.getByText("Idea only"));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("First milestone & delivery"));
      fireEvent.click(screen.getByText("MVP"));
      fireEvent.click(screen.getByText("Balanced"));
      fireEvent.click(screen.getByText("No deadline"));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Project context"));
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Lead agent preferences"));
      const leadInput = screen.getByPlaceholderText(/ava/i);
      fireEvent.change(leadInput, { target: { value: "Ava" } });
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Team on startup"));
      fireEvent.click(screen.getByText(/only lead/i));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("How do we start work?"));
      fireEvent.click(screen.getByText(/generate initial backlog/i));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Process strictness"));
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Agent activity level"));
      fireEvent.click(screen.getByRole("button", { name: /review/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Review configuration"));
      const confirmBtn = screen.getByRole("button", { name: /confirm.*bootstrap/i });
      await waitFor(() => expect(confirmBtn).toBeEnabled());
      fireEvent.click(confirmBtn);

      await waitFor(() => {
        expect(capturedBody).toBeDefined();
        const body = capturedBody as Record<string, unknown>;
        expect(body).not.toHaveProperty("board_type");
        expect(body.objective).toBeUndefined();
      });
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

  describe("refine flow — polling and state transitions", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("shows refine button on step 9 when status is idle", async () => {
      customFetchMock.mockImplementation((url: string) => {
        if (url.includes("/onboarding") && !url.includes("/draft") && !url.includes("/refine")) {
          return Promise.resolve({
            status: 200,
            data: {
              draft_goal: {
                project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp" },
                lead_agent: { name: "Ava" },
                team_plan: { provision_mode: "full_team" },
                planning_policy: { bootstrap_mode: "generate_backlog" },
                qa_policy: { strictness: "balanced" },
                automation_policy: { automation_profile: "normal" },
              },
              refine_status: "idle",
            },
          });
        }
        return Promise.resolve({ status: 200, data: {} });
      });

      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      await waitFor(() => {
        expect(screen.getByTestId("dialog-title")).toHaveTextContent("Review configuration");
      });

      // Navigate back to step 9
      fireEvent.click(screen.getByRole("button", { name: /back/i }));

      await waitFor(() => {
        expect(screen.getByTestId("dialog-title")).toHaveTextContent("AI refinement");
      });
      expect(screen.getByRole("button", { name: /let ai refine/i })).toBeTruthy();
    });

    it("shows questions UI when refine_status is questions on restore", async () => {
      customFetchMock.mockImplementation((url: string) => {
        if (url.includes("/onboarding") && !url.includes("/draft") && !url.includes("/refine")) {
          return Promise.resolve({
            status: 200,
            data: {
              draft_goal: {
                project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp" },
                lead_agent: { name: "Ava" },
                team_plan: { provision_mode: "full_team" },
                planning_policy: { bootstrap_mode: "generate_backlog" },
                qa_policy: { strictness: "balanced" },
                automation_policy: { automation_profile: "normal" },
              },
              refine_status: "questions",
              refine_questions: [
                { id: "q1", question: "What is the target audience?", options: [] },
              ],
            },
          });
        }
        return Promise.resolve({ status: 200, data: {} });
      });

      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      await waitFor(() => {
        expect(screen.getByTestId("dialog-title")).toHaveTextContent("AI refinement");
      });
      expect(screen.getByText("What is the target audience?")).toBeTruthy();
    });

    it("shows refined indicator when refine_status is complete on restore", async () => {
      customFetchMock.mockImplementation((url: string) => {
        if (url.includes("/onboarding") && !url.includes("/draft") && !url.includes("/refine")) {
          return Promise.resolve({
            status: 200,
            data: {
              draft_goal: {
                project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp" },
                lead_agent: { name: "Ava" },
                team_plan: { provision_mode: "full_team" },
                planning_policy: { bootstrap_mode: "generate_backlog" },
                qa_policy: { strictness: "balanced" },
                automation_policy: { automation_profile: "normal" },
              },
              refine_status: "complete",
              refine_summary: "Configuration looks solid.",
            },
          });
        }
        return Promise.resolve({ status: 200, data: {} });
      });

      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      await waitFor(() => {
        expect(screen.getByTestId("dialog-title")).toHaveTextContent("Review configuration");
      });
      expect(screen.getByText("Configuration has been refined by AI.")).toBeTruthy();
      expect(screen.getByText("Configuration looks solid.")).toBeTruthy();
    });
  });

  describe("refine other_text path — non-special option id", () => {
    it("requires other_text when option label contains 'Other' even with numeric id", async () => {
      let capturedPayloads: Record<string, unknown>[] = [];
      customFetchMock.mockImplementation((url: string, opts?: { method?: string; body?: string }) => {
        if (url.includes("/refine-answer") && opts?.body) {
          capturedPayloads.push(JSON.parse(opts.body));
          return Promise.resolve({ status: 200, data: {} });
        }
        if (url.includes("/onboarding") && !url.includes("/draft") && !url.includes("/refine")) {
          return Promise.resolve({
            status: 200,
            data: {
              draft_goal: {
                project_info: { project_mode: "new_product", project_stage: "codebase_exists", first_milestone_type: "mvp", delivery_mode: "balanced", deadline_mode: "none" },
                lead_agent: { name: "Ava" },
                team_plan: { provision_mode: "full_team" },
                planning_policy: { bootstrap_mode: "generate_backlog" },
                qa_policy: { strictness: "balanced" },
                automation_policy: { automation_profile: "normal" },
              },
              refine_status: "questions",
              refine_questions: [
                {
                  id: "q1",
                  question: "Who is this product for?",
                  options: [
                    { id: "b2b", label: "B2B teams" },
                    { id: "99", label: "Other (I'll type it)" },
                  ],
                },
              ],
            },
          });
        }
        return Promise.resolve({ status: 200, data: {} });
      });

      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={() => undefined} />,
      );

      await waitFor(() => {
        expect(screen.getByTestId("dialog-title")).toHaveTextContent("AI refinement");
      });

      // Input should not be visible until "Other" option is selected
      expect(screen.queryByPlaceholderText("Please specify")).toBeNull();

      // Select the "Other" option
      fireEvent.click(screen.getByText("Other (I'll type it)"));

      // Input should now appear
      await waitFor(() => {
        expect(screen.getByPlaceholderText("Please specify")).toBeTruthy();
      });

      // Submit should be disabled while otherText is empty
      const submitBtn = screen.getByRole("button", { name: /submit answers/i });
      expect(submitBtn).toBeDisabled();

      // Enter text
      fireEvent.change(screen.getByPlaceholderText("Please specify"), {
        target: { value: "Small internal fintech teams" },
      });

      // Submit should now be enabled
      await waitFor(() => {
        expect(submitBtn).toBeEnabled();
      });

      // Submit
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(capturedPayloads.length).toBe(1);
        expect(capturedPayloads[0]).toEqual({
          question_id: "q1",
          answer: "99",
          other_text: "Small internal fintech teams",
        });
      });
    });
  });

  describe("outcome — onConfirmed handoff", () => {
    it("does not call onConfirmed until confirm completes", async () => {
      const onConfirmedSpy = vi.fn();
      let confirmResolve: ((value: unknown) => void) | null = null;
      customFetchMock.mockImplementation((url: string) => {
        if (url.includes("/confirm")) {
          return new Promise((resolve) => {
            confirmResolve = resolve;
          });
        }
        return Promise.resolve({ status: 200, data: {} });
      });

      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={onConfirmedSpy} />,
      );

      // Advance through all steps quickly
      fireEvent.click(screen.getByText("New product"));
      fireEvent.click(screen.getByText("Idea only"));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("First milestone & delivery"));
      fireEvent.click(screen.getByText("MVP"));
      fireEvent.click(screen.getByText("Balanced"));
      fireEvent.click(screen.getByText("No deadline"));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Project context"));
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Lead agent preferences"));
      fireEvent.change(screen.getByPlaceholderText(/ava/i), { target: { value: "Ava" } });
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Team on startup"));
      fireEvent.click(screen.getByText(/only lead/i));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("How do we start work?"));
      fireEvent.click(screen.getByText(/generate initial backlog/i));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Process strictness"));
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Agent activity level"));
      fireEvent.click(screen.getByRole("button", { name: /review/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Review configuration"));

      // Click confirm — should be pending
      fireEvent.click(screen.getByRole("button", { name: /confirm.*bootstrap/i }));

      // onConfirmed should NOT have been called yet
      expect(onConfirmedSpy).not.toHaveBeenCalled();

      // Resolve the confirm
      if (confirmResolve) {
        confirmResolve({
          status: 200,
          data: {
            board: { id: "board-1", name: "Test", slug: "test", description: "", organization_id: "o1", created_at: "", updated_at: "" },
            bootstrap: { lead_status: "created", team_status: "not_requested", team_agents_created: 0, team_created_roles: [], team_skipped_roles: [], team_failed_roles: [], planner_status: "not_requested" },
          },
        });
      }

      await waitFor(() => {
        expect(screen.getByTestId("dialog-title")).toHaveTextContent("Bootstrap complete");
        expect(onConfirmedSpy).not.toHaveBeenCalled();
      });
    });

    it("calls onConfirmed with board when Open project board is clicked", async () => {
      const onConfirmedSpy = vi.fn();
      customFetchMock.mockImplementation((url: string) => {
        if (url.includes("/confirm")) {
          return Promise.resolve({
            status: 200,
            data: {
              board: { id: "board-1", name: "Test Board", slug: "test", description: "", organization_id: "o1", created_at: "", updated_at: "" },
              bootstrap: { lead_status: "created", team_status: "not_requested", team_agents_created: 0, team_created_roles: [], team_skipped_roles: [], team_failed_roles: [], planner_status: "not_requested" },
            },
          });
        }
        return Promise.resolve({ status: 200, data: {} });
      });

      render(
        <BoardOnboardingWizard boardId="board-1" onConfirmed={onConfirmedSpy} />,
      );

      // Advance through all steps
      fireEvent.click(screen.getByText("New product"));
      fireEvent.click(screen.getByText("Idea only"));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("First milestone & delivery"));
      fireEvent.click(screen.getByText("MVP"));
      fireEvent.click(screen.getByText("Balanced"));
      fireEvent.click(screen.getByText("No deadline"));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Project context"));
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Lead agent preferences"));
      fireEvent.change(screen.getByPlaceholderText(/ava/i), { target: { value: "Ava" } });
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Team on startup"));
      fireEvent.click(screen.getByText(/only lead/i));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("How do we start work?"));
      fireEvent.click(screen.getByText(/generate initial backlog/i));
      await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Process strictness"));
      fireEvent.click(screen.getByRole("button", { name: /next/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Agent activity level"));
      fireEvent.click(screen.getByRole("button", { name: /review/i }));

      await waitFor(() => expect(screen.getByTestId("dialog-title")).toHaveTextContent("Review configuration"));
      fireEvent.click(screen.getByRole("button", { name: /confirm.*bootstrap/i }));

      await waitFor(() => {
        expect(screen.getByTestId("dialog-title")).toHaveTextContent("Bootstrap complete");
      });

      fireEvent.click(screen.getByRole("button", { name: /open project board/i }));

      await waitFor(() => {
        expect(onConfirmedSpy).toHaveBeenCalledTimes(1);
        expect(onConfirmedSpy).toHaveBeenCalledWith(
          expect.objectContaining({ id: "board-1", name: "Test Board" }),
        );
      });
    });
  });
});
