import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, beforeEach, vi } from "vitest";

import NewBoardPage from "./page";

const pushMock = vi.fn();
const createBoardMutateMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
  }),
}));

vi.mock("@/auth/clerk", () => ({
  useAuth: () => ({ isSignedIn: true }),
}));

vi.mock("@/lib/use-organization-membership", () => ({
  useOrganizationMembership: () => ({ isAdmin: true }),
}));

vi.mock("@/api/generated/boards/boards", () => ({
  useCreateBoardApiV1BoardsPost: () => ({
    mutate: createBoardMutateMock,
    isPending: false,
  }),
}));

vi.mock("@/api/generated/gateways/gateways", () => ({
  useListGatewaysApiV1GatewaysGet: () => ({
    isLoading: false,
    error: null,
    data: {
      status: 200,
      data: {
        items: [{ id: "gateway-1", name: "Primary Gateway" }],
      },
    },
  }),
}));

vi.mock("@/api/generated/board-groups/board-groups", () => ({
  useListBoardGroupsApiV1BoardGroupsGet: () => ({
    isLoading: false,
    error: null,
    data: {
      status: 200,
      data: {
        items: [],
      },
    },
  }),
}));

vi.mock("@/components/templates/DashboardPageLayout", () => ({
  DashboardPageLayout: ({
    children,
    title,
    description,
  }: {
    children: React.ReactNode;
    title: string;
    description: string;
  }) => (
    <div>
      <h1>{title}</h1>
      <p>{description}</p>
      {children}
    </div>
  ),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    type = "button",
    onClick,
    disabled,
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type={type} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
}));

vi.mock("@/components/ui/input", () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input {...props} />
  ),
}));

vi.mock("@/components/ui/textarea", () => ({
  Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
    <textarea {...props} />
  ),
}));

vi.mock("@/components/ui/searchable-select", () => ({
  default: ({
    ariaLabel,
    value,
    onValueChange,
    options,
    disabled,
  }: {
    ariaLabel: string;
    value: string;
    onValueChange: (value: string) => void;
    options: Array<{ value: string; label: string }>;
    disabled?: boolean;
  }) => (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onValueChange(event.target.value)}
      disabled={disabled}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

describe("/boards/new", () => {
  beforeEach(() => {
    pushMock.mockReset();
    createBoardMutateMock.mockReset();
  });

  it("creates onboarding boards as general boards by default", () => {
    render(<NewBoardPage />);

    fireEvent.change(screen.getByPlaceholderText(/release operations/i), {
      target: { value: "CardFlow" },
    });
    fireEvent.change(
      screen.getByPlaceholderText(
        /what context should the lead agent know before onboarding/i,
      ),
      {
        target: { value: "Customer onboarding automation" },
      },
    );

    fireEvent.click(screen.getByRole("button", { name: /create board/i }));

    expect(createBoardMutateMock).toHaveBeenCalledWith({
      data: {
        name: "CardFlow",
        slug: "cardflow",
        description: "Customer onboarding automation",
        board_type: "general",
        gateway_id: "gateway-1",
        board_group_id: null,
      },
    });
  });
});
