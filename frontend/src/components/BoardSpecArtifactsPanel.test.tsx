import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const invalidateQueries = vi.fn();
const createMutateAsync = vi.fn();
const draftMutateAsync = vi.fn();
const applyMutateAsync = vi.fn();

const specArtifacts = [
  {
    id: "spec-1",
    board_id: "board-1",
    title: "Launch dashboard",
    body: "# Launch dashboard\n## Backend\n- Add planner API",
    source: "markdown",
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
] as const;

vi.mock("@tanstack/react-query", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-query")>(
    "@tanstack/react-query",
  );
  return {
    ...actual,
    useQueryClient: () => ({ invalidateQueries }),
  };
});

vi.mock("@/api/generated/planner/planner", () => ({
  getListSpecArtifactsApiV1BoardsBoardIdSpecArtifactsGetQueryKey: vi.fn(
    (boardId: string) => [`/api/v1/boards/${boardId}/spec-artifacts/`],
  ),
  useListSpecArtifactsApiV1BoardsBoardIdSpecArtifactsGet: vi.fn(() => ({
    data: { status: 200, data: specArtifacts },
    error: null,
    isLoading: false,
  })),
  useCreateSpecArtifactApiV1BoardsBoardIdSpecArtifactsPost: vi.fn(() => ({
    mutateAsync: createMutateAsync,
    isPending: false,
  })),
  useDraftSpecArtifactApiV1BoardsBoardIdSpecArtifactsSpecArtifactIdDraftPost: vi.fn(
    () => ({
      mutateAsync: draftMutateAsync,
      isPending: false,
    }),
  ),
  useApplySpecArtifactApiV1BoardsBoardIdSpecArtifactsSpecArtifactIdApplyPost: vi.fn(
    () => ({
      mutateAsync: applyMutateAsync,
      isPending: false,
    }),
  ),
}));

import { BoardSpecArtifactsPanel } from "./BoardSpecArtifactsPanel";

describe("BoardSpecArtifactsPanel", () => {
  beforeEach(() => {
    invalidateQueries.mockReset();
    createMutateAsync.mockReset();
    draftMutateAsync.mockReset();
    applyMutateAsync.mockReset();

    createMutateAsync.mockResolvedValue({ status: 201, data: specArtifacts[0] });
    draftMutateAsync.mockResolvedValue({
      status: 200,
      data: {
        spec_artifact_id: "spec-1",
        spec_title: "Launch dashboard",
        node_count: 2,
        nodes: [
          {
            key: "node-1",
            title: "Launch dashboard",
            depth: 10,
            source_line: 1,
            parent_key: null,
            depends_on_keys: [],
          },
          {
            key: "node-2",
            title: "Backend",
            depth: 20,
            source_line: 2,
            parent_key: "node-1",
            depends_on_keys: ["node-1"],
          },
        ],
      },
    });
    applyMutateAsync.mockResolvedValue({
      status: 200,
      data: [
        {
          id: "task-1",
          board_id: "board-1",
          title: "Launch dashboard",
          description: null,
          status: "inbox",
          priority: "medium",
          due_at: null,
          assigned_agent_id: null,
          depends_on_task_ids: [],
          tag_ids: [],
          created_by_user_id: null,
          in_progress_at: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
          blocked_by_task_ids: [],
          is_blocked: false,
          tags: [],
          custom_field_values: null,
        },
      ],
    });
  });

  it("renders spec artifacts and drafts/apply summaries", async () => {
    render(<BoardSpecArtifactsPanel boardId="board-1" canWrite />);

    expect(screen.getByText("Launch dashboard")).toBeInTheDocument();
    expect(screen.getByText(/Add planner API/)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Spec title"), {
      target: { value: "Release checklist" },
    });
    fireEvent.change(
      screen.getByPlaceholderText(
        "Write a markdown spec with headings and bullet points.",
      ),
      {
        target: { value: "# Release checklist\n- Ship it" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /save spec/i }));

    await waitFor(() => {
      expect(createMutateAsync).toHaveBeenCalledWith({
        boardId: "board-1",
        data: {
          title: "Release checklist",
          body: "# Release checklist\n- Ship it",
          source: "markdown",
        },
      });
    });

    fireEvent.click(screen.getByRole("button", { name: /draft/i }));
    await waitFor(() => {
      expect(screen.getByText(/draft: 2 tasks/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /apply/i }));
    await waitFor(() => {
      expect(screen.getByText(/applied 1 tasks to the board/i)).toBeInTheDocument();
    });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["/api/v1/boards/board-1/spec-artifacts/"],
    });
  });
});
