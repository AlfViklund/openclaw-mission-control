/// <reference types="cypress" />

describe("BoardOnboardingWizard E2E", () => {
  const apiBase = "**/api/v1";
  const boardId = "b-onboarding-1";

  const originalDefaultCommandTimeout = Cypress.config("defaultCommandTimeout");

  beforeEach(() => {
    Cypress.config("defaultCommandTimeout", 30_000);

    cy.intercept("GET", "**/healthz", { statusCode: 200, body: { ok: true } }).as("healthz");
    cy.intercept("GET", `${apiBase}/users/me*`, {
      statusCode: 200,
      body: {
        id: "u1",
        clerk_user_id: "clerk_u1",
        email: "test@example.com",
        name: "Test User",
        preferred_name: "Test",
        timezone: "UTC",
      },
    }).as("usersMe");
    cy.intercept("GET", `${apiBase}/organizations/me/list*`, {
      statusCode: 200,
      body: [{ id: "o1", name: "Testing Org", is_active: true, role: "owner" }],
    }).as("organizations");
    cy.intercept("GET", `${apiBase}/organizations/me/member*`, {
      statusCode: 200,
      body: {
        id: "m1",
        organization_id: "o1",
        user_id: "u1",
        role: "owner",
        all_boards_read: true,
        all_boards_write: true,
        board_access: [{ board_id: boardId, can_read: true, can_write: true }],
      },
    }).as("membership");
    cy.intercept("GET", `${apiBase}/organizations/me/custom-fields*`, {
      statusCode: 200,
      body: [],
    }).as("customFields");
    cy.intercept("GET", `${apiBase}/tags*`, {
      statusCode: 200,
      body: { items: [], total: 0, limit: 200, offset: 0 },
    }).as("tags");
  });

  afterEach(() => {
    Cypress.config("defaultCommandTimeout", originalDefaultCommandTimeout);
  });

  function openOnboardingWizard() {
    cy.visit(`/boards/${boardId}/edit?onboarding=1`);
    cy.get('[aria-label="Board onboarding"]', { timeout: 15_000 }).should("be.visible");
  }

  function stubEmptySse() {
    const emptySse = { statusCode: 200, headers: { "content-type": "text/event-stream" }, body: "" };
    cy.intercept("GET", `${apiBase}/boards/*/tasks/stream*`, emptySse).as("tasksStream");
    cy.intercept("GET", `${apiBase}/boards/*/approvals/stream*`, emptySse).as("approvalsStream");
    cy.intercept("GET", `${apiBase}/boards/*/memory/stream*`, emptySse).as("memoryStream");
    cy.intercept("GET", `${apiBase}/agents/stream*`, emptySse).as("agentsStream");
  }

  function stubBoard() {
    cy.intercept("GET", `${apiBase}/boards/${boardId}/snapshot*`, {
      statusCode: 200,
      body: {
        board: {
          id: boardId,
          name: "Onboarding Test Board",
          slug: "onboarding-test",
          description: "",
          gateway_id: "g1",
          board_group_id: null,
          board_type: "general",
          objective: null,
          success_metrics: null,
          target_date: null,
          goal_confirmed: false,
          goal_source: "test",
          organization_id: "o1",
          created_at: "2026-02-11T00:00:00Z",
          updated_at: "2026-02-11T00:00:00Z",
        },
        tasks: [],
        agents: [],
        approvals: [],
        chat_messages: [],
        pending_approvals_count: 0,
      },
    }).as("snapshot");
    cy.intercept("GET", `${apiBase}/boards/${boardId}/group-snapshot*`, {
      statusCode: 200,
      body: { group: null, boards: [] },
    }).as("groupSnapshot");
    cy.intercept("GET", `${apiBase}/boards/${boardId}$`, {
      statusCode: 200,
      body: {
        id: boardId,
        name: "Onboarding Test Board",
        slug: "onboarding-test",
        description: "",
        gateway_id: "g1",
        board_group_id: null,
        board_type: "general",
        objective: null,
        success_metrics: null,
        target_date: null,
        goal_confirmed: false,
        goal_source: "test",
        organization_id: "o1",
        created_at: "2026-02-11T00:00:00Z",
        updated_at: "2026-02-11T00:00:00Z",
      },
    }).as("boardGet");
  }

  function interceptDraft() {
    cy.intercept("PATCH", `${apiBase}/boards/${boardId}/onboarding/draft`, (req) => {
      expect(req.body).to.be.an("object");
      req.reply({ statusCode: 200, body: { data: {} } });
    }).as("draftPatch");
  }

  function interceptRefine() {
    cy.intercept("POST", `${apiBase}/boards/${boardId}/onboarding/refine`, (req) => {
      req.reply({ statusCode: 200, body: { data: {} } });
    }).as("refinePost");
  }

  function interceptConfirmWithBootstrap(overrides: Record<string, unknown> = {}) {
    cy.intercept("POST", `${apiBase}/boards/${boardId}/onboarding/confirm`, (req) => {
      req.reply({
        statusCode: 200,
        body: {
          data: {
            board: {
              id: boardId,
              name: "Onboarding Test Board",
              slug: "onboarding-test",
              description: "",
              gateway_id: "g1",
              board_group_id: null,
              board_type: "goal",
              objective: "Build a new SaaS product",
              success_metrics: null,
              target_date: null,
              goal_confirmed: true,
              goal_source: "onboarding_wizard",
              organization_id: "o1",
              created_at: "2026-02-11T00:00:00Z",
              updated_at: "2026-02-11T00:00:00Z",
            },
            bootstrap: {
              lead_status: "created",
              lead_name: "Ava",
              team_status: "provisioned",
              team_agents_created: 3,
              team_created_roles: ["developer", "qa_engineer", "technical_writer"],
              team_skipped_roles: [],
              planner_status: "draft_created",
              automation_sync: { status: "success", agents_updated: 4 },
              ...overrides,
            },
          },
        },
      });
    }).as("confirmPost");
  }

  function clickNext() {
    cy.contains("button", /^next$/i, { timeout: 10_000 }).should("not.be.disabled").click();
    cy.wait("@draftPatch", { timeout: 10_000 });
  }

  function clickReview() {
    cy.contains("button", /^review$/i, { timeout: 10_000 }).should("not.be.disabled").click();
    cy.wait("@draftPatch", { timeout: 10_000 });
  }

  function clickConfirmAndBootstrap() {
    cy.contains("button", /confirm.*bootstrap/i, { timeout: 10_000 }).should("not.be.disabled").click();
    cy.wait("@confirmPost", { timeout: 10_000 });
  }

  describe("new product → full team → planner → confirm → outcome", () => {
    it("completes full wizard flow and shows outcome screen", () => {
      stubBoard();
      stubEmptySse();
      interceptDraft();
      interceptRefine();
      interceptConfirmWithBootstrap();

      openOnboardingWizard();

      // Step 1 — project mode & stage
      cy.contains("h2", /what are we building/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /new product/i).click();
      cy.contains("button", /codebase exists/i).click();
      clickNext();

      // Step 2 — milestone & delivery
      cy.contains("h2", /first milestone.*delivery/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /mvp/i).click();
      cy.contains("button", /balanced/i).click();
      cy.contains("button", /no deadline/i).click();
      clickNext();

      // Step 3 — project context
      cy.contains("h2", /project context/i, { timeout: 10_000 }).should("be.visible");
      cy.get("textarea").first().type("Build a new SaaS product for teams");
      clickNext();

      // Step 4 — lead agent
      cy.contains("h2", /lead agent preferences/i, { timeout: 10_000 }).should("be.visible");
      cy.get('input[placeholder*="ava"]').type("Ava");
      cy.contains("button", /autonomous/i).click();
      cy.contains("button", /concise/i).click();
      cy.contains("button", /bullets/i).click();
      cy.contains("button", /daily/i).click();
      clickNext();

      // Step 5 — team provisioning
      cy.contains("h2", /team on startup/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /full standard team/i).click();
      clickNext();

      // Step 6 — planning
      cy.contains("h2", /how do we start/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /generate initial backlog/i).click();
      clickNext();

      // Step 7 — QA
      cy.contains("h2", /process strictness/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /balanced/i).click();
      clickNext();

      // Step 8 — automation
      cy.contains("h2", /agent activity level/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /active/i).click();
      clickNext();

      // Step 9 — AI refinement
      cy.contains("h2", /ai refinement/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /let ai refine/i).click();
      cy.wait("@refinePost", { timeout: 10_000 });
      cy.contains(/configuration looks good/i, { timeout: 10_000 }).should("be.visible");
      clickReview();

      // Step 10 — review
      cy.contains("h2", /review configuration/i, { timeout: 10_000 }).should("be.visible");
      clickConfirmAndBootstrap();

      // Step 11 — outcome
      cy.contains("h2", /bootstrap complete/i, { timeout: 15_000 }).should("be.visible");
      cy.contains(/created/i).should("be.visible");
      cy.contains(/provisioned/i).should("be.visible");
      cy.contains(/draft_created/i).should("be.visible");
    });
  });

  describe("existing product → lead+dev+qa → no deadline → confirm", () => {
    it("skips deadline fields and proceeds to confirm", () => {
      stubBoard();
      stubEmptySse();
      interceptDraft();
      interceptRefine();
      interceptConfirmWithBootstrap();

      openOnboardingWizard();

      // Step 1 — existing product evolution
      cy.contains("h2", /what are we building/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /existing product evolution/i).click();
      cy.contains("button", /active development/i).click();
      clickNext();

      // Step 2 — milestone, no deadline
      cy.contains("h2", /first milestone.*delivery/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /key feature/i).click();
      cy.contains("button", /no deadline/i).should("be.visible");
      clickNext();

      // Step 3
      cy.contains("h2", /project context/i, { timeout: 10_000 }).should("be.visible");
      clickNext();

      // Step 4 — lead agent
      cy.contains("h2", /lead agent preferences/i, { timeout: 10_000 }).should("be.visible");
      cy.get('input[placeholder*="ava"]').type("LeadBot");
      cy.contains("button", /balanced/i).click();
      cy.contains("button", /mixed/i).click();
      cy.contains("button", /hourly/i).click();
      clickNext();

      // Step 5 — selected roles (lead + dev + qa)
      cy.contains("h2", /team on startup/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /lead.*selected roles/i).click();
      cy.contains("button", /developer/i).click();
      cy.contains("button", /qa engineer/i).click();
      clickNext();

      // Step 6
      cy.contains("h2", /how do we start/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /architecture first/i).click();
      clickNext();

      // Step 7
      cy.contains("h2", /process strictness/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /strict/i).click();
      clickNext();

      // Step 8
      cy.contains("h2", /agent activity level/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /normal/i).click();
      clickNext();

      // Step 9
      cy.contains("h2", /ai refinement/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /let ai refine/i).click();
      cy.wait("@refinePost", { timeout: 10_000 });
      clickReview();

      // Step 10
      cy.contains("h2", /review configuration/i, { timeout: 10_000 }).should("be.visible");
      clickConfirmAndBootstrap();

      // Step 11
      cy.contains("h2", /bootstrap complete/i, { timeout: 15_000 }).should("be.visible");
    });
  });

  describe("legacy payload still confirms", () => {
    it("confirm endpoint accepts minimal legacy payload", () => {
      stubBoard();
      stubEmptySse();
      interceptDraft();
      interceptRefine();
      cy.intercept("POST", `${apiBase}/boards/${boardId}/onboarding/confirm`, (req) => {
        req.reply({
          statusCode: 200,
          body: {
            data: {
              board: {
                id: boardId,
                name: "Legacy Board",
                slug: "legacy",
                description: "",
                gateway_id: "g1",
                board_group_id: null,
                board_type: "general",
                objective: null,
                success_metrics: null,
                target_date: null,
                goal_confirmed: true,
                goal_source: "onboarding_wizard",
                organization_id: "o1",
                created_at: "2026-02-11T00:00:00Z",
                updated_at: "2026-02-11T00:00:00Z",
              },
              bootstrap: {
                lead_status: "unchanged",
                team_status: "already_provisioned",
                team_agents_created: 0,
                team_created_roles: [],
                team_skipped_roles: [],
                planner_status: "not_requested",
              },
            },
          },
        });
      }).as("confirmPost");

      openOnboardingWizard();

      // Minimal: just select product mode and stage, skip everything else
      cy.contains("h2", /what are we building/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /research.*prototype/i).click();
      cy.contains("button", /idea only/i).click();
      clickNext();

      // Step 2 — skip all optional fields
      cy.contains("h2", /first milestone.*delivery/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /mvp/i).click();
      cy.contains("button", /balanced/i).click();
      cy.contains("button", /no deadline/i).click();
      clickNext();

      // Step 3 — skip
      cy.contains("h2", /project context/i, { timeout: 10_000 }).should("be.visible");
      clickNext();

      // Step 4 — skip lead agent name
      cy.contains("h2", /lead agent preferences/i, { timeout: 10_000 }).should("be.visible");
      // lead name is required — fill it
      cy.get('input[placeholder*="ava"]').type("R");
      clickNext();

      // Step 5 — lead only
      cy.contains("h2", /team on startup/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /only lead/i).click();
      clickNext();

      // Step 6
      cy.contains("h2", /how do we start/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /lead only/i).click();
      clickNext();

      // Step 7
      cy.contains("h2", /process strictness/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /flexible/i).click();
      clickNext();

      // Step 8
      cy.contains("h2", /agent activity level/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /economy/i).click();
      clickNext();

      // Step 9
      cy.contains("h2", /ai refinement/i, { timeout: 10_000 }).should("be.visible");
      clickReview();

      // Step 10
      cy.contains("h2", /review configuration/i, { timeout: 10_000 }).should("be.visible");
      clickConfirmAndBootstrap();

      // Step 11 — outcome
      cy.contains("h2", /bootstrap complete/i, { timeout: 15_000 }).should("be.visible");
    });
  });

  describe("save draft → reload → wizard restores progress", () => {
    it("restores wizard state from saved draft on reload", () => {
      stubBoard();
      stubEmptySse();
      cy.intercept("GET", `${apiBase}/boards/${boardId}/onboarding*`, {
        statusCode: 200,
        body: {
          data: {
            id: "sess-1",
            board_id: boardId,
            status: "in_progress",
            draft_goal: {
              project_info: {
                project_mode: "new_product",
                project_stage: "codebase_exists",
                first_milestone_type: "mvp",
                delivery_mode: "balanced",
                deadline_mode: "none",
              },
            },
          },
        },
      }).as("onboardingGet");
      interceptDraft();
      interceptRefine();
      interceptConfirmWithBootstrap();

      openOnboardingWizard();
      cy.wait("@onboardingGet", { timeout: 10_000 });

      // Should be on step 2 since step 1 fields are pre-filled
      cy.contains("h2", /first milestone.*delivery/i, { timeout: 10_000 }).should("be.visible");
      // Project mode and stage should be pre-selected from draft
      cy.contains("button", /new product/i).should("have.attr", "aria-pressed", "true");
      cy.contains("button", /codebase exists/i).should("have.attr", "aria-pressed", "true");
      // MVP should be pre-selected
      cy.contains("button", /mvp/i).should("have.attr", "aria-pressed", "true");
    });
  });

  describe("team already provisioned → onboarding later → outcome shows already_provisioned", () => {
    it("shows already_provisioned status in outcome when team was pre-existing", () => {
      stubBoard();
      stubEmptySse();
      interceptDraft();
      interceptRefine();
      cy.intercept("POST", `${apiBase}/boards/${boardId}/onboarding/confirm`, (req) => {
        req.reply({
          statusCode: 200,
          body: {
            data: {
              board: {
                id: boardId,
                name: "Test Board",
                slug: "test",
                description: "",
                gateway_id: "g1",
                board_group_id: null,
                board_type: "goal",
                objective: "Maintain existing product",
                success_metrics: null,
                target_date: null,
                goal_confirmed: true,
                goal_source: "onboarding_wizard",
                organization_id: "o1",
                created_at: "2026-02-11T00:00:00Z",
                updated_at: "2026-02-11T00:00:00Z",
              },
              bootstrap: {
                lead_status: "updated",
                lead_name: "Nova",
                team_status: "already_provisioned",
                team_agents_created: 0,
                team_created_roles: [],
                team_skipped_roles: ["developer", "qa_engineer"],
                planner_status: "not_requested",
                automation_sync: { status: "success", agents_updated: 1 },
              },
            },
          },
        });
      }).as("confirmPost");

      openOnboardingWizard();

      // Quick path: select new product and stage
      cy.contains("h2", /what are we building/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /new product/i).click();
      cy.contains("button", /idea only/i).click();
      clickNext();

      // Step 2
      cy.contains("h2", /first milestone.*delivery/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /mvp/i).click();
      cy.contains("button", /balanced/i).click();
      cy.contains("button", /no deadline/i).click();
      clickNext();

      // Step 3 — skip
      cy.contains("h2", /project context/i, { timeout: 10_000 }).should("be.visible");
      clickNext();

      // Step 4 — fill lead name
      cy.contains("h2", /lead agent preferences/i, { timeout: 10_000 }).should("be.visible");
      cy.get('input[placeholder*="ava"]').type("Nova");
      clickNext();

      // Step 5 — lead only
      cy.contains("h2", /team on startup/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /only lead/i).click();
      clickNext();

      // Step 6
      cy.contains("h2", /how do we start/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /empty board/i).click();
      clickNext();

      // Step 7
      cy.contains("h2", /process strictness/i, { timeout: 10_000 }).should("be.visible");
      clickNext();

      // Step 8
      cy.contains("h2", /agent activity level/i, { timeout: 10_000 }).should("be.visible");
      clickNext();

      // Step 9 — skip refine
      cy.contains("h2", /ai refinement/i, { timeout: 10_000 }).should("be.visible");
      clickReview();

      // Step 10
      cy.contains("h2", /review configuration/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /confirm.*bootstrap/i).should("not.be.disabled").click();
      cy.wait("@confirmPost", { timeout: 10_000 });

      // Step 11 — outcome
      cy.contains("h2", /bootstrap complete/i, { timeout: 15_000 }).should("be.visible");
      // Should show already_provisioned team status
      cy.contains(/already_provisioned/i).should("be.visible");
      // Should show lead status
      cy.contains(/updated.*nova/i).should("be.visible");
    });
  });

  describe("refine updates review → outcome shows refined bootstrap result", () => {
    it("refine flow completes and shows refined outcome", () => {
      stubBoard();
      stubEmptySse();
      interceptDraft();
      interceptRefine();
      interceptConfirmWithBootstrap();

      openOnboardingWizard();

      // Step 1
      cy.contains("h2", /what are we building/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /new product/i).click();
      cy.contains("button", /codebase exists/i).click();
      clickNext();

      // Step 2
      cy.contains("h2", /first milestone.*delivery/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /mvp/i).click();
      cy.contains("button", /balanced/i).click();
      cy.contains("button", /no deadline/i).click();
      clickNext();

      // Step 3
      cy.contains("h2", /project context/i, { timeout: 10_000 }).should("be.visible");
      cy.get("textarea").first().type("Build a collaborative tool");
      clickNext();

      // Step 4
      cy.contains("h2", /lead agent preferences/i, { timeout: 10_000 }).should("be.visible");
      cy.get('input[placeholder*="ava"]').type("Ava");
      clickNext();

      // Step 5
      cy.contains("h2", /team on startup/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /full standard team/i).click();
      clickNext();

      // Step 6
      cy.contains("h2", /how do we start/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /generate initial backlog/i).click();
      clickNext();

      // Step 7
      cy.contains("h2", /process strictness/i, { timeout: 10_000 }).should("be.visible");
      clickNext();

      // Step 8
      cy.contains("h2", /agent activity level/i, { timeout: 10_000 }).should("be.visible");
      clickNext();

      // Step 9 — refine
      cy.contains("h2", /ai refinement/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /let ai refine/i).click();
      cy.wait("@refinePost", { timeout: 10_000 });
      cy.contains(/configuration looks good/i, { timeout: 10_000 }).should("be.visible");
      clickReview();

      // Step 10 — review
      cy.contains("h2", /review configuration/i, { timeout: 10_000 }).should("be.visible");
      clickConfirmAndBootstrap();

      // Step 11 — outcome shows bootstrap result from confirm
      cy.contains("h2", /bootstrap complete/i, { timeout: 15_000 }).should("be.visible");
      cy.contains(/created/i).should("be.visible");
      cy.contains(/provisioned/i).should("be.visible");
      cy.contains(/draft_created/i).should("be.visible");
      cy.contains(/success/i).should("be.visible");
      // Open project board button should be present
      cy.contains("button", /open project board/i).should("be.visible");
    });
  });

  describe("confirm payload contract", () => {
    it("does not send board_type or enum in objective", () => {
      stubBoard();
      stubEmptySse();
      interceptDraft();
      let confirmBody: Record<string, unknown> = {};
      cy.intercept("POST", `${apiBase}/boards/${boardId}/onboarding/confirm`, (req) => {
        confirmBody = req.body;
        req.reply({
          statusCode: 200,
          body: {
            data: {
              board: {
                id: boardId,
                name: "Test",
                slug: "test",
                description: "",
                gateway_id: "g1",
                board_group_id: null,
                board_type: "general",
                objective: "A collaborative tool for teams",
                success_metrics: null,
                target_date: null,
                goal_confirmed: true,
                goal_source: "lead_agent_onboarding",
                organization_id: "o1",
                created_at: "2026-02-11T00:00:00Z",
                updated_at: "2026-02-11T00:00:00Z",
              },
              bootstrap: {
                lead_status: "created",
                lead_name: "Ava",
                team_status: "provisioned",
                team_agents_created: 3,
                team_created_roles: ["developer", "qa_engineer"],
                team_skipped_roles: [],
                planner_status: "draft_created",
                automation_sync: { status: "success", agents_updated: 1 },
              },
            },
          },
        });
      }).as("confirmPost");

      openOnboardingWizard();

      // Quick path through wizard
      cy.contains("h2", /what are we building/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /new product/i).click();
      cy.contains("button", /idea only/i).click();
      clickNext();

      cy.contains("h2", /first milestone.*delivery/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /mvp/i).click();
      cy.contains("button", /balanced/i).click();
      cy.contains("button", /no deadline/i).click();
      clickNext();

      cy.contains("h2", /project context/i, { timeout: 10_000 }).should("be.visible");
      cy.get("textarea").first().type("A collaborative tool for teams");
      clickNext();

      cy.contains("h2", /lead agent preferences/i, { timeout: 10_000 }).should("be.visible");
      cy.get('input[placeholder*="ava"]').type("Ava");
      clickNext();

      cy.contains("h2", /team on startup/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /only lead/i).click();
      clickNext();

      cy.contains("h2", /how do we start/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /empty board/i).click();
      clickNext();

      cy.contains("h2", /process strictness/i, { timeout: 10_000 }).should("be.visible");
      clickNext();

      cy.contains("h2", /agent activity level/i, { timeout: 10_000 }).should("be.visible");
      clickNext();

      cy.contains("h2", /ai refinement/i, { timeout: 10_000 }).should("be.visible");
      clickReview();

      cy.contains("h2", /review configuration/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /confirm.*bootstrap/i).should("not.be.disabled").click();
      cy.wait("@confirmPost", { timeout: 10_000 });

      cy.then(() => {
        expect(confirmBody).to.be.an("object");
        expect(confirmBody).to.not.have.property("board_type");
        expect(confirmBody.objective).to.eq("A collaborative tool for teams");
      });

      cy.contains("h2", /bootstrap complete/i, { timeout: 15_000 }).should("be.visible");
    });
  });

  describe("refine complete updates review", () => {
    it("shows refined summary in review after refine completes", () => {
      stubBoard();
      stubEmptySse();
      interceptDraft();

      cy.intercept("POST", `${apiBase}/boards/${boardId}/onboarding/refine`, {
        statusCode: 200,
        body: { data: {} },
      }).as("refinePost");

      let pollCount = 0;
      cy.intercept("GET", `${apiBase}/boards/${boardId}/onboarding*`, (req) => {
        if (pollCount === 0) {
          pollCount++;
          req.reply({
            statusCode: 200,
            body: {
              data: {
                id: "sess-1",
                board_id: boardId,
                status: "active",
                draft_goal: {
                  project_info: {
                    project_mode: "new_product",
                    project_stage: "codebase_exists",
                    first_milestone_type: "mvp",
                    delivery_mode: "balanced",
                    deadline_mode: "none",
                  },
                  lead_agent: { name: "Ava" },
                  team_plan: { provision_mode: "full_team" },
                  planning_policy: { bootstrap_mode: "generate_backlog" },
                  qa_policy: { strictness: "balanced" },
                  automation_policy: { automation_profile: "normal" },
                },
                refine_status: "idle",
              },
            },
          });
        } else {
          req.reply({
            statusCode: 200,
            body: {
              data: {
                id: "sess-1",
                board_id: boardId,
                status: "completed",
                draft_goal: {
                  project_info: {
                    project_mode: "new_product",
                    project_stage: "codebase_exists",
                    first_milestone_type: "mvp",
                    delivery_mode: "balanced",
                    deadline_mode: "none",
                  },
                  lead_agent: { name: "Ava" },
                  team_plan: { provision_mode: "full_team" },
                  planning_policy: { bootstrap_mode: "generate_backlog" },
                  qa_policy: { strictness: "balanced" },
                  automation_policy: { automation_profile: "normal" },
                },
                refine_status: "complete",
                refine_summary: "Configuration looks solid.",
              },
            },
          });
        }
      }).as("onboardingGet");

      interceptConfirmWithBootstrap();

      openOnboardingWizard();
      cy.wait("@onboardingGet", { timeout: 10_000 });

      cy.contains("h2", /review configuration/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /^back$/i).click();
      cy.contains("h2", /ai refinement/i, { timeout: 10_000 }).should("be.visible");

      cy.contains("button", /let ai refine/i).click();
      cy.wait("@refinePost", { timeout: 10_000 });

      cy.contains(/configuration refined/i, { timeout: 15_000 }).should("be.visible");

      cy.contains("button", /^review$/i).click();
      cy.contains("h2", /review configuration/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("Configuration has been refined by AI.").should("be.visible");
      cy.contains("Configuration looks solid.").should("be.visible");
    });
  });

  describe("refine questions path", () => {
    it("shows questions, submits answers, and validates request", () => {
      stubBoard();
      stubEmptySse();
      interceptDraft();

      cy.intercept("POST", `${apiBase}/boards/${boardId}/onboarding/refine`, {
        statusCode: 200,
        body: { data: {} },
      }).as("refinePost");

      let refineAnswerBody: Record<string, unknown> = {};
      cy.intercept("POST", `${apiBase}/boards/${boardId}/onboarding/refine-answer`, (req) => {
        refineAnswerBody = req.body;
        req.reply({
          statusCode: 200,
          body: {
            data: {
              id: "sess-1",
              board_id: boardId,
              status: "refining",
              draft_goal: {},
              refine_status: "pending",
              refine_questions: [],
            },
          },
        });
      }).as("refineAnswerPost");

      let pollCount = 0;
      cy.intercept("GET", `${apiBase}/boards/${boardId}/onboarding*`, (req) => {
        if (pollCount === 0) {
          pollCount++;
          req.reply({
            statusCode: 200,
            body: {
              data: {
                id: "sess-1",
                board_id: boardId,
                status: "active",
                draft_goal: {
                  project_info: {
                    project_mode: "new_product",
                    project_stage: "codebase_exists",
                    first_milestone_type: "mvp",
                  },
                  lead_agent: { name: "Ava" },
                  team_plan: { provision_mode: "full_team" },
                  planning_policy: { bootstrap_mode: "generate_backlog" },
                  qa_policy: { strictness: "balanced" },
                  automation_policy: { automation_profile: "normal" },
                },
                refine_status: "idle",
              },
            },
          });
        } else {
          req.reply({
            statusCode: 200,
            body: {
              data: {
                id: "sess-1",
                board_id: boardId,
                status: "active",
                draft_goal: {},
                refine_status: "questions",
                refine_questions: [
                  { id: "q1", question: "What is the primary platform?", options: [{ id: "web", label: "Web" }, { id: "mobile", label: "Mobile" }] },
                ],
                refine_summary: "Need clarification.",
              },
            },
          });
        }
      }).as("onboardingGet");

      interceptConfirmWithBootstrap();

      openOnboardingWizard();
      cy.wait("@onboardingGet", { timeout: 10_000 });

      cy.contains("h2", /review configuration/i, { timeout: 10_000 }).should("be.visible");
      cy.contains("button", /^back$/i).click();
      cy.contains("h2", /ai refinement/i, { timeout: 10_000 }).should("be.visible");

      cy.contains("button", /let ai refine/i).click();
      cy.wait("@refinePost", { timeout: 10_000 });

      cy.contains("What is the primary platform?", { timeout: 15_000 }).should("be.visible");
      cy.contains("button", /web/i).click();

      cy.contains("button", /submit answers/i).click();
      cy.wait("@refineAnswerPost", { timeout: 10_000 });

      cy.then(() => {
        expect(refineAnswerBody).to.have.property("question_id", "q1");
        expect(refineAnswerBody).to.have.property("answer", "web");
      });
    });
  });
});
