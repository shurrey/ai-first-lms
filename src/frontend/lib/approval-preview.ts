/**
 * Canvas data for an approval_request preview. The engine sends `{tool, arguments, artifact}`
 * (src/engine/guardrails/gateway.py `_preview`), with free text wrapped in <user_content> tags;
 * the canvases expect the artifact's own shape (contracts/events.md FinalPayload).
 */

type Data = Record<string, unknown>;

const WRAPPER = /<user_content\b[^>]*>|<\/user_content>/g;

function text(value: unknown): string | undefined {
  return typeof value === "string" ? value.replace(WRAPPER, "") : undefined;
}

function asObject(value: unknown): Data | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Data) : undefined;
}

export function approvalCanvasData(artifactType: string, preview: Data): Data {
  const artifact = asObject(preview.artifact);
  const message = asObject(artifact?.message);
  if (artifactType === "message" && message) {
    const count = artifact?.recipient_count;
    return {
      subject: text(message.subject),
      body: text(message.body_md) ?? "",
      recipients: typeof count === "number" ? [`${count} recipient${count === 1 ? "" : "s"}`] : [],
    };
  }
  const question = asObject(artifact?.question);
  if (artifactType === "quiz" && question) {
    const options = Array.isArray(question.options) ? question.options.map((o) => text(o) ?? String(o)) : undefined;
    return {
      title: "Question to save",
      questions: [{ question: text(question.stem) ?? "", type: text(question.type) ?? "short_answer", options }],
    };
  }
  return preview;
}
