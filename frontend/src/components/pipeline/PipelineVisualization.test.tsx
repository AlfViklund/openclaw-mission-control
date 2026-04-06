import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, beforeEach, vi } from "vitest";

import { PipelineVisualization } from "./PipelineVisualization";

const fetchMock = vi.hoisted(() => vi.fn());

vi.mock("@/auth/localAuth", () => ({
  getLocalAuthToken: () => "token",
}));

describe("PipelineVisualization", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("renders and executes the manual review action", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            task_id: "task-1",
            task_status: "in_progress",
            can_start_work: false,
            use_start_work: false,
            recommended_runtime: "opencode_cli",
            next_required_stage: "plan",
            requires_approval: false,
            ready_for_review: false,
            runtime_ready: true,
            execution_mode: "pipeline",
            degraded_allowed: false,
            recommended_action: "request_manual_review",
            stages: [],
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "review_requested",
            review_mode: "manual_evidence",
            task_summary: { task_status: "review" },
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            task_id: "task-1",
            task_status: "review",
            can_start_work: false,
            use_start_work: false,
            recommended_runtime: "opencode_cli",
            requires_approval: false,
            ready_for_review: false,
            runtime_ready: true,
            execution_mode: "pipeline",
            degraded_allowed: false,
            recommended_action: "await_lead_review",
            stages: [],
          }),
          { status: 200 },
        ),
      );

    render(<PipelineVisualization taskId="task-1" boardId="board-1" canWrite />);

    const button = await screen.findByRole("button", { name: /Request review from evidence/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/pipeline/tasks/task-1/request-review"),
        expect.objectContaining({ method: "POST" }),
      );
    });
  });
});
