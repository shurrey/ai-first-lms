import { ApiError, apiFetch, apiJson } from "./api";

/** Mirrors contracts/api.openapi.yaml components.schemas (Me, PersonRole, Capabilities). */
export type PersonRole = "student" | "faculty" | "program_lead" | "advisor" | "admin";

export interface CapabilityGrant {
  scope: "self" | "own" | "program" | "assigned" | "all";
  access: "full" | "read" | "summary" | "aggregate";
}

export type CapabilityKey =
  | "course_list"
  | "tutor_chat"
  | "content_generation"
  | "submit_work"
  | "feedback_release"
  | "grade_commit"
  | "improvement_view"
  | "mastery_matrix"
  | "attestation_override"
  | "badge_approve"
  | "badge_revoke"
  | "roster"
  | "transcripts_of_others"
  | "learner_profile_of_others"
  | "early_alert_flags"
  | "degree_audit"
  | "ai_review"
  | "ai_actions_log"
  | "policy_edit"
  | "policy_precedence"
  | "compliance_report"
  | "program_outcome_report"
  | "my_data"
  | "deletion_request_approval"
  | "system_settings"
  | "notifications";

/** A missing key means not permitted. */
export type Capabilities = Partial<Record<CapabilityKey, CapabilityGrant>>;

export interface Enrollment {
  course_id: string;
  slug: string;
  title: string;
  role: "student" | "faculty" | "ta" | "observer";
}

export interface Me {
  person: { id: string; display_name: string; email: string | null };
  roles: PersonRole[];
  active_role: PersonRole;
  enrollments: Enrollment[];
  advisees_count: number;
  home_route: string;
  capabilities: Capabilities;
  effective_ui_policy: Record<string, unknown>;
  must_change_password: boolean;
}

export const ROLE_LABELS: Record<PersonRole, string> = {
  student: "Student",
  faculty: "Faculty",
  program_lead: "Program Lead",
  advisor: "Advisor",
  admin: "Admin",
};

export const LOGIN_FAILED_MESSAGE = "Invalid username or password.";

export function getMe(): Promise<Me> {
  return apiJson<Me>("/api/auth/me");
}

/**
 * Returns the /me payload on success. Every 401 is reported with the generic
 * contract message so the form never reveals whether the account exists or is locked.
 */
export async function login(username: string, password: string): Promise<Me> {
  const res = await apiFetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    allowUnauthorized: true,
  });
  if (res.status === 401) throw new ApiError(401, LOGIN_FAILED_MESSAGE);
  if (!res.ok) throw new ApiError(res.status, `Sign-in failed: ${res.status}`);
  return res.json() as Promise<Me>;
}

export async function logout(): Promise<void> {
  await apiJson<void>("/api/auth/logout", { method: "POST", allowUnauthorized: true });
}

export function switchRole(role: PersonRole): Promise<Me> {
  return apiJson<Me>("/api/auth/role", { method: "POST", json: { role } });
}

export const PASSWORD_MIN_LENGTH = 12;

export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<void> {
  await apiJson<void>("/api/auth/password", {
    method: "POST",
    json: { current_password: currentPassword, new_password: newPassword },
  });
}
