/**
 * Mock SSE event sequences for each test scenario.
 * Each function returns an array of event envelope objects
 * that the mock server sends as SSE data.
 */

interface MockEvent {
  event: string;
  session_id: string;
  turn_id: string;
  sequence: number;
  timestamp: string;
  payload: Record<string, unknown>;
}

const ts = () => new Date().toISOString();

export function scenario1Events(
  sessionId: string,
  turnId: string
): MockEvent[] {
  return [
    {
      event: "reasoning",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 1,
      timestamp: ts(),
      payload: {
        step: "interpret",
        text: "Student wants to understand recursion.",
      },
    },
    {
      event: "plan",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 2,
      timestamp: ts(),
      payload: {
        strategy: "react",
        steps: [
          {
            step_id: "s1",
            agent: "tutor",
            input_summary: "Explain recursion to student",
            depends_on: [],
          },
        ],
        estimated_cost_usd: 0.01,
        estimated_tokens: 500,
      },
    },
    {
      event: "agent_start",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 3,
      timestamp: ts(),
      payload: { step_id: "s1", agent: "tutor", inputs: {} },
    },
    {
      event: "agent_tool_call",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 4,
      timestamp: ts(),
      payload: {
        step_id: "s1",
        agent: "tutor",
        tool: "content.retrieve",
        arguments: { topic: "recursion" },
        result_summary: "Found 3 relevant content items",
        latency_ms: 45,
        success: true,
      },
    },
    {
      event: "agent_token",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 5,
      timestamp: ts(),
      payload: {
        step_id: "s1",
        agent: "tutor",
        delta: "Recursion is when a function calls itself.",
        channel: "response",
      },
    },
    {
      event: "agent_result",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 6,
      timestamp: ts(),
      payload: {
        step_id: "s1",
        agent: "tutor",
        output: {},
        cost_usd: 0.005,
        tokens: 250,
        success: true,
      },
    },
    {
      event: "final",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 7,
      timestamp: ts(),
      payload: {
        answer_markdown:
          "**Recursion** is when a function calls itself to solve a smaller version of the same problem. Think of it like looking into a mirror that reflects another mirror.",
        artifacts: [],
        cost_usd: 0.01,
        tokens: 500,
        wall_time_ms: 1200,
      },
    },
  ];
}

export function scenario3Events(
  sessionId: string,
  turnId: string
): MockEvent[] {
  return [
    {
      event: "reasoning",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 1,
      timestamp: ts(),
      payload: {
        step: "interpret",
        text: "Faculty wants to grade Essay 3 submissions with a rubric.",
      },
    },
    {
      event: "plan",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 2,
      timestamp: ts(),
      payload: {
        strategy: "react",
        steps: [
          {
            step_id: "s1",
            agent: "grading_assistant",
            input_summary: "Grade Essay 3 with rubric",
            depends_on: [],
          },
        ],
        estimated_cost_usd: 0.05,
        estimated_tokens: 2000,
      },
    },
    {
      event: "agent_start",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 3,
      timestamp: ts(),
      payload: {
        step_id: "s1",
        agent: "grading_assistant",
        inputs: {},
      },
    },
    {
      event: "agent_tool_call",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 4,
      timestamp: ts(),
      payload: {
        step_id: "s1",
        agent: "grading_assistant",
        tool: "assessments.rubrics",
        arguments: {},
        result_summary: "Loaded rubric for Essay 3",
        latency_ms: 30,
        success: true,
      },
    },
    {
      event: "agent_result",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 5,
      timestamp: ts(),
      payload: {
        step_id: "s1",
        agent: "grading_assistant",
        output: {},
        cost_usd: 0.04,
        tokens: 1800,
        success: true,
      },
    },
    {
      event: "approval_request",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 6,
      timestamp: ts(),
      payload: {
        approval_id: "a1",
        step_id: "s1",
        agent: "grading_assistant",
        action: "Commit grades for 23 students",
        preview: {
          criteria: [
            {
              name: "Thesis",
              levels: [
                { label: "Excellent", points: 10, description: "Clear thesis" },
                { label: "Good", points: 7, description: "Mostly clear" },
                { label: "Needs Work", points: 4, description: "Unclear" },
              ],
            },
          ],
        },
        artifact_type: "rubric_grades",
      },
    },
  ];
}

export function scenario10Events(
  sessionId: string,
  turnId: string
): MockEvent[] {
  return [
    {
      event: "reasoning",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 1,
      timestamp: ts(),
      payload: {
        step: "interpret",
        text: "Faculty wants tailored study guides for struggling Ch 5 students.",
      },
    },
    {
      event: "plan",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 2,
      timestamp: ts(),
      payload: {
        strategy: "plan_then_execute",
        steps: [
          {
            step_id: "s1",
            agent: "early_alert",
            input_summary: "Identify struggling students",
            depends_on: [],
          },
          {
            step_id: "s2",
            agent: "content_generator",
            input_summary: "Generate study guide",
            depends_on: ["s1"],
          },
          {
            step_id: "s3",
            agent: "communication",
            input_summary: "Send study guide",
            depends_on: ["s2"],
          },
        ],
        estimated_cost_usd: 0.15,
        estimated_tokens: 5000,
      },
    },
    {
      event: "agent_start",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 3,
      timestamp: ts(),
      payload: { step_id: "s1", agent: "early_alert", inputs: {} },
    },
    {
      event: "agent_tool_call",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 4,
      timestamp: ts(),
      payload: {
        step_id: "s1",
        agent: "early_alert",
        tool: "analytics.query",
        arguments: {},
        result_summary: "Found 5 students below threshold",
        latency_ms: 60,
        success: true,
      },
    },
    {
      event: "agent_result",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 5,
      timestamp: ts(),
      payload: {
        step_id: "s1",
        agent: "early_alert",
        output: {},
        cost_usd: 0.03,
        tokens: 800,
        success: true,
      },
    },
    {
      event: "agent_start",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 6,
      timestamp: ts(),
      payload: {
        step_id: "s2",
        agent: "content_generator",
        inputs: {},
      },
    },
    {
      event: "agent_result",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 7,
      timestamp: ts(),
      payload: {
        step_id: "s2",
        agent: "content_generator",
        output: {},
        cost_usd: 0.05,
        tokens: 2000,
        success: true,
      },
    },
    {
      event: "approval_request",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 8,
      timestamp: ts(),
      payload: {
        approval_id: "a1",
        step_id: "s3",
        agent: "communication",
        action: "Send study guide to 5 students",
        preview: {
          subject: "Ch 5 Study Guide",
          body: "Here is a personalized study guide...",
          recipients: ["student1", "student2", "student3", "student4", "student5"],
        },
        artifact_type: "message",
      },
    },
  ];
}

export function scenario11Events(
  sessionId: string,
  turnId: string
): MockEvent[] {
  return [
    {
      event: "reasoning",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 1,
      timestamp: ts(),
      payload: {
        step: "interpret",
        text: "Student wants to improve writing skills and build a learning path.",
      },
    },
    {
      event: "plan",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 2,
      timestamp: ts(),
      payload: {
        strategy: "plan_then_execute",
        steps: [
          {
            step_id: "s1",
            agent: "advising",
            input_summary: "Analyze writing skills and suggest path",
            depends_on: [],
          },
          {
            step_id: "s2",
            agent: "tutor",
            input_summary: "Create learning exercises",
            depends_on: ["s1"],
          },
        ],
        estimated_cost_usd: 0.08,
        estimated_tokens: 3000,
      },
    },
    {
      event: "agent_start",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 3,
      timestamp: ts(),
      payload: { step_id: "s1", agent: "advising", inputs: {} },
    },
    {
      event: "agent_result",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 4,
      timestamp: ts(),
      payload: {
        step_id: "s1",
        agent: "advising",
        output: {},
        cost_usd: 0.04,
        tokens: 1500,
        success: true,
      },
    },
    {
      event: "agent_start",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 5,
      timestamp: ts(),
      payload: { step_id: "s2", agent: "tutor", inputs: {} },
    },
    {
      event: "agent_result",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 6,
      timestamp: ts(),
      payload: {
        step_id: "s2",
        agent: "tutor",
        output: {},
        cost_usd: 0.03,
        tokens: 1200,
        success: true,
      },
    },
    {
      event: "final",
      session_id: sessionId,
      turn_id: turnId,
      sequence: 7,
      timestamp: ts(),
      payload: {
        answer_markdown:
          "Here's your personalized writing improvement path. I've identified key areas and created exercises for each.",
        artifacts: [
          {
            artifact_id: "lp1",
            type: "learning_path",
            data: {
              title: "Writing Improvement Path",
              nodes: [
                {
                  id: "n1",
                  label: "Grammar Fundamentals",
                  mastery: 0.7,
                  type: "concept",
                },
                {
                  id: "n2",
                  label: "Essay Structure",
                  mastery: 0.4,
                  type: "skill",
                },
                {
                  id: "n3",
                  label: "Argumentation",
                  mastery: 0.2,
                  type: "concept",
                },
                {
                  id: "n4",
                  label: "Research Integration",
                  mastery: 0.1,
                  type: "skill",
                },
              ],
              edges: [
                { from: "n1", to: "n2" },
                { from: "n2", to: "n3" },
                { from: "n3", to: "n4" },
              ],
              recommended_next: ["n2", "n3"],
            },
          },
        ],
        cost_usd: 0.08,
        tokens: 3000,
        wall_time_ms: 2500,
      },
    },
  ];
}
