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
