export type Persona = "student" | "faculty" | "advisor" | "admin";

export interface Course {
  id: string;
  title: string;
  studentCount: number;
  instructor: string;
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
