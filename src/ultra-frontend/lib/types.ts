/** PersonRole in contracts/api.openapi.yaml. */
export type Role = "student" | "faculty" | "program_lead" | "advisor" | "admin";

export interface Enrollment {
  course_id: string;
  slug: string;
  title: string;
  role: "student" | "faculty" | "ta" | "observer";
}

export interface CapabilityGrant {
  scope: "self" | "own" | "program" | "assigned" | "all";
  access: "full" | "read" | "summary" | "aggregate";
}

/** A missing key means not permitted. */
export type Capabilities = Partial<Record<
  | "course_list" | "tutor_chat" | "content_generation" | "submit_work" | "feedback_release"
  | "grade_commit" | "improvement_view" | "mastery_matrix" | "attestation_override"
  | "badge_approve" | "badge_revoke" | "roster" | "transcripts_of_others"
  | "learner_profile_of_others" | "early_alert_flags" | "degree_audit" | "ai_review"
  | "ai_actions_log" | "policy_edit" | "policy_precedence" | "compliance_report"
  | "program_outcome_report" | "my_data" | "deletion_request_approval" | "system_settings"
  | "notifications",
  CapabilityGrant
>>;

/** The /api/auth/me payload. */
export interface Me {
  person: { id: string; display_name: string; email: string | null };
  roles: Role[];
  active_role: Role;
  enrollments: Enrollment[];
  advisees_count: number;
  home_route: string;
  capabilities: Capabilities;
  effective_ui_policy: Record<string, unknown>;
  must_change_password: boolean;
}


export interface Module {
  id: string;
  title: string;
  order: number;
  items: ContentItem[];
}

export interface ContentItem {
  id: string;
  title: string;
  kind: string;
}

export interface StudentGrade {
  id: string;
  name: string;
  email: string;
  overall: number | null;
  grades: Record<string, number | null>;
}

export interface RosterPerson {
  id: string;
  name: string;
  email: string;
  role: string;
  overall: number | null;
  attributes: Record<string, unknown>;
}

export interface AnalyticsStudent {
  id: string;
  name: string;
  overallGrade: number | null;
  missedDueDates: number;
  hoursInCourse: number;
  daysSinceAccess: number;
}

export interface PageData<T = unknown> {
  page: string;
  data: T;
}

// ---- provenance and measurement (contracts/api.openapi.yaml) ----

export type AiActionType =
  | "generation" | "grade_draft" | "criterion_feedback" | "practice_item" | "recommendation"
  | "attestation" | "profile_update" | "nudge" | "alert";

export type HumanDecisionValue = "accepted" | "edited" | "rejected" | "overridden" | "dismissed" | "disputed" | "snoozed";

export interface ProvenanceSource {
  type: "content_item" | "node" | "submission" | "rubric" | "policy";
  id: string;
  version?: number | string | null;
  title?: string | null;
}

export interface AppliedPolicy {
  key: string;
  value: unknown;
  scope_type: string;
  scope_id?: string | null;
  version?: number | null;
}

export interface HumanDecision {
  id: string;
  ai_action_id: string;
  decided_by: string;
  decided_by_name?: string | null;
  decision: HumanDecisionValue;
  diff?: Record<string, unknown> | null;
  reason?: string | null;
  decided_at: string;
}

export interface OutcomeLink {
  ai_action_id: string;
  evidence_id?: string | null;
  attestation_id?: string | null;
  delta?: Record<string, unknown> | null;
  observed_at: string;
}

export interface AiAction {
  id: string;
  session_id?: string | null;
  turn_id?: string | null;
  agent: string;
  action_type: AiActionType;
  subject_person_id?: string | null;
  course_id?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  sources: ProvenanceSource[];
  policies: AppliedPolicy[];
  model?: string | null;
  prompt_sha256?: string | null;
  output: Record<string, unknown>;
  created_at: string;
  decisions: HumanDecision[];
  outcome_links?: OutcomeLink[];
}

/** Rates are over decided items, 0–1, and null when nothing is decided. */
export interface DecisionRates {
  agent?: string | null;
  action_type?: AiActionType | null;
  total: number;
  accepted: number;
  edited: number;
  rejected: number;
  other?: number;
  undecided: number;
  acceptance_rate?: number | null;
  edit_rate?: number | null;
  reject_rate?: number | null;
}

export interface DeltaStat {
  n: number;
  mean_delta?: number | null;
}

export interface MeasurementSummary {
  scope: { type: "course" | "program" | "institution"; id?: string | null; title?: string | null };
  from: string | null;
  to: string;
  rates: DecisionRates[];
  criterion_score_changes: { criterion_id: string; criterion_key: string; n: number; mean_delta: number }[];
  learning_delta_by_decision: { accepted: DeltaStat; edited: DeltaStat; rejected: DeltaStat };
  most_edited_criteria: { criterion_id: string; criterion_key: string; edit_count: number; edit_rate: number }[];
  offloading?: { hint_dependency_ratio?: number | null; solution_check_trips?: number };
}

export interface CourseRef {
  course_id: string;
  slug?: string | null;
  title: string;
}

export interface MeasurementRollup extends MeasurementSummary {
  per_course: { course: CourseRef; totals: DecisionRates }[];
  compliance: { mismatches_count: number };
}
