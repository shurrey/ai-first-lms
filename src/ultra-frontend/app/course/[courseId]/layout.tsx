import { CourseNav } from "@/components/CourseNav";
import { CourseTabs } from "@/components/CourseTabs";
import { CourseBanner } from "@/components/CourseBanner";

const COURSE_TITLES: Record<string, string> = {
  "bdd640fb-0667-4ad1-9c80-317fa3b1799d": "CS 101 — Introduction to Computer Science",
  "23b8c1e9-3924-46de-beb1-3b9046685257": "MATH 201 — Linear Algebra",
  "bd9c66b3-ad3c-4d6d-9a3d-1fa7bc8960a9": "ENG 102 — Academic Writing",
  "972a8469-1641-4f82-8b9d-2434e465e150": "BIO 150 — General Biology",
};

export default async function CourseLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  const title = COURSE_TITLES[courseId] ?? "Course";

  return (
    <div className="flex h-full flex-col">
      <CourseNav courseTitle={title} />
      <CourseTabs courseId={courseId} />
      <CourseBanner courseId={courseId} title={title} />
      <div className="flex-1 overflow-auto">{children}</div>
    </div>
  );
}
