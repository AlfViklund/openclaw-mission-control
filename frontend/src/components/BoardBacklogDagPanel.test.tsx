import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const invalidateQueries = vi.fn();
const refetch = vi.fn();
const draftMutateAsync = vi.fn();
const applyMutateAsync = vi.fn();
const boardRefresh = vi.fn();
const onTaskSelect = vi.fn();

const artifacts = [
  {
    id: "spec-1",
    board_id: "board-1",
    title: "Launch dashboard",
    body: "# Launch dashboard\n## Backend\n- Add planner API\n- Add tests",
    source: "markdown",
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
] as const;

const tasks = [
  {
    id: "task-1",
    title: "Root task",
    status: "inbox",
    priority: "medium",
    description: "Prepare the initial launch plan.",
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:05:00Z",
    depends_on_task_ids: [],
    blocked_by_task_ids: [],
    is_blocked: false,
  },
  {
    id: "task-2",
    title: "Child task",
    status: "in_progress",
    priority: "high",
    description: "Implement the backend planner API.",
    created_at: "2026-04-01T00:10:00Z",
    updated_at: "2026-04-01T00:20:00Z",
    depends_on_task_ids: ["task-1"],
    blocked_by_task_ids: ["task-1"],
    is_blocked: true,
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
    data: { status: 200, data: artifacts },
    error: null,
    isLoading: false,
    refetch,
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

import { BoardBacklogDagPanel } from "./BoardBacklogDagPanel";

describe("BoardBacklogDagPanel", () => {
  beforeEach(() => {
    invalidateQueries.mockReset();
    refetch.mockReset();
    draftMutateAsync.mockReset();
    applyMutateAsync.mockReset();
    boardRefresh.mockReset();
    onTaskSelect.mockReset();

    draftMutateAsync.mockResolvedValue({
      status: 200,
      data: {
        spec_artifact_id: "spec-1",
        spec_title: "Launch dashboard",
        node_count: 3,
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
          {
            key: "node-3",
            title: "Add planner API",
            depth: 30,
            source_line: 3,
            parent_key: "node-2",
            depends_on_keys: ["node-2"],
          },
        ],
      },
    });
    applyMutateAsync.mockResolvedValue({
      status: 200,
      data: [
        {
          id: "task-3",
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

  it("renders a task tree and spec detail workspace", async () => {
    render(
      <BoardBacklogDagPanel
        boardId="board-1"
        tasks={tasks as unknown as React.ComponentProps<typeof BoardBacklogDagPanel>["tasks"]}
        canWrite
        onTaskSelect={onTaskSelect}
        onBoardRefresh={boardRefresh}
      />,
    );

    expect(screen.getByText("Task tree")).toBeInTheDocument();
    expect(screen.getByText("Root task")).toBeInTheDocument();
    expect(screen.getByText("Child task")).toBeInTheDocument();
    expect(screen.getByText("Spec detail")).toBeInTheDocument();
    expect(screen.getAllByText("Launch dashboard").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Child task" }));
    expect(onTaskSelect).toHaveBeenCalledWith({ id: "task-2" });

    fireEvent.click(screen.getByRole("button", { name: /draft/i }));
    await waitFor(() => {
      expect(screen.getByText(/3 nodes drafted from the spec/i)).toBeInTheDocument();
    });
    expect(screen.getAllByText("Add planner API").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /apply/i }));
    await waitFor(() => {
      expect(applyMutateAsync).toHaveBeenCalledWith({
        boardId: "board-1",
        specArtifactId: "spec-1",
      });
    });
    await waitFor(() => {
      expect(boardRefresh).toHaveBeenCalled();
    });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["/api/v1/boards/board-1/spec-artifacts/"],
    });
  });
});
