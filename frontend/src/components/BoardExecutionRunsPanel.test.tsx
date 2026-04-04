import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const invalidateQueries = vi.fn();
const runsRefetch = vi.fn();
const artifactsRefetch = vi.fn();
const mutateAsync = vi.fn();
const fetchMock = vi.fn();

const runs = [
  {
    id: "run-1",
    board_id: "board-1",
    task_id: "task-1",
    agent_id: "agent-1",
    scope: "task",
    runtime_kind: "opencode",
    runtime_session_key: "session-abc",
    status: "running",
    current_phase: "build",
    plan_summary: "Map the migration path.",
    build_summary: "Wire the dashboard panel.",
    test_summary: null,
    last_error: null,
    retry_count: 1,
    last_heartbeat_at: "2026-03-31T00:20:00Z",
    heartbeat_age_seconds: 1200,
    is_stale: true,
    can_resume: true,
    can_heartbeat: false,
    started_at: "2026-03-31T00:00:00Z",
    completed_at: null,
    execution_state: null,
    recovery_state: null,
    created_at: "2026-03-31T00:00:00Z",
    updated_at: "2026-03-31T00:20:00Z",
  },
  {
    id: "run-2",
    board_id: "board-1",
    task_id: null,
    agent_id: null,
    scope: "board",
    runtime_kind: "claude-code",
    runtime_session_key: null,
    status: "done",
    current_phase: "review",
    plan_summary: null,
    build_summary: null,
    test_summary: "Validated the dashboard integration.",
    last_error: null,
    retry_count: 0,
    last_heartbeat_at: null,
    heartbeat_age_seconds: null,
    is_stale: false,
    can_resume: false,
    can_heartbeat: false,
    started_at: "2026-04-01T01:00:00Z",
    completed_at: "2026-04-01T01:15:00Z",
    execution_state: null,
    recovery_state: null,
    created_at: "2026-04-01T01:00:00Z",
    updated_at: "2026-04-01T01:15:00Z",
  },
  {
    id: "run-3",
    board_id: "board-1",
    task_id: "task-1",
    agent_id: "agent-2",
    scope: "task",
    runtime_kind: "opencode",
    runtime_session_key: "session-live",
    status: "running",
    current_phase: "test",
    plan_summary: "Prepare the run.",
    build_summary: "Keep the session alive.",
    test_summary: null,
    last_error: null,
    retry_count: 0,
    last_heartbeat_at: "2026-03-31T23:56:00Z",
    heartbeat_age_seconds: 240,
    is_stale: false,
    can_resume: false,
    can_heartbeat: true,
    started_at: "2026-03-31T23:40:00Z",
    completed_at: null,
    execution_state: null,
    recovery_state: null,
    created_at: "2026-03-31T23:40:00Z",
    updated_at: "2026-03-31T23:56:00Z",
  },
] as const;

const artifacts = [
  {
    id: "artifact-1",
    execution_run_id: "run-1",
    kind: "checkpoint",
    title: "Dispatched Build instruction",
    body: "Mission Control OpenCode instruction for execution run run-1.",
    artifact_state: {
      phase: "build",
      runtime_kind: "opencode",
      runtime_session_key: "session-abc",
    },
    created_at: "2026-03-31T00:10:00Z",
    updated_at: "2026-03-31T00:10:00Z",
  },
  {
    id: "artifact-2",
    execution_run_id: "run-1",
    kind: "build",
    title: "Build evidence",
    body: "Wire the dashboard panel.",
    artifact_state: {
      files: ["BoardExecutionRunsPanel.tsx"],
    },
    created_at: "2026-03-31T00:18:00Z",
    updated_at: "2026-03-31T00:18:00Z",
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

vi.mock("@/api/generated/executions/executions", () => ({
  getListExecutionRunsApiV1BoardsBoardIdExecutionRunsGetQueryKey: vi.fn(
    (boardId: string) => [`/api/v1/boards/${boardId}/execution-runs/`],
  ),
  getListExecutionArtifactsApiV1BoardsBoardIdExecutionRunsRunIdArtifactsGetQueryKey: vi.fn(
    (boardId: string, runId: string) => [
      `/api/v1/boards/${boardId}/execution-runs/${runId}/artifacts`,
    ],
  ),
  useListExecutionRunsApiV1BoardsBoardIdExecutionRunsGet: vi.fn(() => ({
    data: { status: 200, data: runs },
    error: null,
    isLoading: false,
    isFetching: false,
    refetch: runsRefetch,
  })),
  useListExecutionArtifactsApiV1BoardsBoardIdExecutionRunsRunIdArtifactsGet: vi.fn(
    (_boardId: string, runId: string) => ({
      data: { status: 200, data: runId === "run-1" ? artifacts : [] },
      error: null,
      isLoading: false,
      refetch: artifactsRefetch,
    }),
  ),
  useCreateExecutionRunApiV1BoardsBoardIdExecutionRunsPost: vi.fn(() => ({
    mutateAsync,
    isPending: false,
  })),
}));

import { BoardExecutionRunsPanel } from "./BoardExecutionRunsPanel";

describe("BoardExecutionRunsPanel", () => {
  beforeEach(() => {
    invalidateQueries.mockReset();
    runsRefetch.mockReset();
    artifactsRefetch.mockReset();
    mutateAsync.mockReset();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    mutateAsync.mockResolvedValue({ status: 201, data: runs[0] });
    fetchMock.mockResolvedValue({ ok: true, json: async () => runs[0] });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders execution run summaries and an evidence timeline", () => {
    render(
      <BoardExecutionRunsPanel
        boardId="board-1"
        taskId="task-1"
        taskTitle="Launch dashboard evidence"
        canWrite
      />,
    );

    expect(screen.getByText("Execution runs")).toBeInTheDocument();
    expect(screen.getAllByText("Total 3").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Healthy 2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Stale 1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Resumable 1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Heartbeatable 1").length).toBeGreaterThan(0);
    expect(screen.getByText("Runtime sessions")).toBeInTheDocument();
    expect(screen.getByText("2 sessions")).toBeInTheDocument();
    expect(screen.getAllByText("session-abc").length).toBeGreaterThan(0);
    expect(screen.getAllByText("session-live").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Running").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Build").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Stale").length).toBeGreaterThan(0);
    expect(screen.getByText(/Stale for 20m ago/i)).toBeInTheDocument();
    expect(screen.getByText("Recovery")).toBeInTheDocument();
    expect(screen.getByText("Stale run")).toBeInTheDocument();
    expect(screen.getAllByText("Resume eligible").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Heartbeat eligible").length).toBeGreaterThan(0);
    expect(screen.getByText("Last dispatch")).toBeInTheDocument();
    expect(screen.getByText("Last heartbeat source")).toBeInTheDocument();
    expect(screen.getByText("Evidence timeline")).toBeInTheDocument();
    expect(screen.getAllByText("Dispatched Build instruction").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Build evidence").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Wire the dashboard panel.").length).toBeGreaterThan(0);
    expect(screen.getByText("opencode · session-abc")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /resume/i })).toBeInTheDocument();
  });

  it("filters runs by recovery posture from the overview strip", () => {
    render(
      <BoardExecutionRunsPanel
        boardId="board-1"
        taskId="task-1"
        taskTitle="Launch dashboard evidence"
        canWrite
      />,
    );

    const staleButtons = screen.getAllByRole("button", { name: /stale \(1\)/i });
    fireEvent.click(staleButtons[0]);

    expect(screen.getAllByText("Total 3").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Stale 1").length).toBeGreaterThan(0);
    expect(screen.getByText("Stale run")).toBeInTheDocument();
    expect(screen.queryByText("claude-code")).not.toBeInTheDocument();
    expect(screen.getByText("Runtime sessions")).toBeInTheDocument();
  });

  it("filters runtime sessions by session posture", () => {
    render(
      <BoardExecutionRunsPanel
        boardId="board-1"
        taskId="task-1"
        taskTitle="Launch dashboard evidence"
        canWrite
      />,
    );

    const staleButtons = screen.getAllByRole("button", { name: /stale \(1\)/i });
    fireEvent.click(staleButtons[1]);

    expect(screen.getByText("Runtime sessions")).toBeInTheDocument();
    expect(screen.getByText("1 sessions")).toBeInTheDocument();
    expect(screen.getByText("session-abc")).toBeInTheDocument();
    expect(screen.queryByText("session-live")).not.toBeInTheDocument();
  });

  it("switches selected run and refreshes evidence artifacts", async () => {
    render(
      <BoardExecutionRunsPanel
        boardId="board-1"
        taskId="task-1"
        taskTitle="Launch dashboard evidence"
        canWrite
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => {
      expect(runsRefetch).toHaveBeenCalled();
      expect(artifactsRefetch).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByRole("button", { name: /claude-code/i }));
    expect(screen.getByText("Evidence timeline")).toBeInTheDocument();
    expect(screen.getByText("No evidence artifacts yet for this run.")).toBeInTheDocument();
  });

  it("starts a new task run and refreshes the query cache", async () => {
    render(
      <BoardExecutionRunsPanel
        boardId="board-1"
        taskId="task-1"
        taskTitle="Launch dashboard evidence"
        canWrite
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /start run/i }));

    expect(mutateAsync).toHaveBeenCalledWith({
      boardId: "board-1",
      data: {
        task_id: "task-1",
        scope: "task",
        runtime_kind: "opencode",
        status: "pending",
        current_phase: "plan",
        plan_summary: "Plan for Launch dashboard evidence",
      },
    });
    await waitFor(() => {
      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: ["/api/v1/boards/board-1/execution-runs/"],
      });
    });
  });

  it("resumes a stale run from the evidence panel", async () => {
    render(
      <BoardExecutionRunsPanel
        boardId="board-1"
        taskId="task-1"
        taskTitle="Launch dashboard evidence"
        canWrite
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /resume/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/boards/board-1/execution-runs/run-1/resume",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(runsRefetch).toHaveBeenCalled();
    expect(artifactsRefetch).toHaveBeenCalled();
  });

  it("records a heartbeat for a live run from the evidence panel", async () => {
    render(
      <BoardExecutionRunsPanel
        boardId="board-1"
        taskId="task-1"
        taskTitle="Launch dashboard evidence"
        canWrite
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /inspect latest/i }));
    expect(screen.getByText("No evidence artifacts yet for this run.")).toBeInTheDocument();
    const heartbeatButtons = screen.getAllByRole("button", { name: /heartbeat/i });
    expect(heartbeatButtons.length).toBeGreaterThan(0);
    expect(screen.getByText("Healthy run")).toBeInTheDocument();
    expect(screen.getByText("Execution state")).toBeInTheDocument();

    fireEvent.click(heartbeatButtons[heartbeatButtons.length - 1]);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/boards/board-1/execution-runs/run-3/heartbeat",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(runsRefetch).toHaveBeenCalled();
    expect(artifactsRefetch).toHaveBeenCalled();
  });
});
