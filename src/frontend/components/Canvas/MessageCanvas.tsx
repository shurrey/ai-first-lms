"use client";

import { CanvasShell, type ArtifactStatus } from "./CanvasShell";

interface MessageData {
  subject?: string;
  body: string;
  recipients?: string[];
  sender?: string;
}

interface MessageCanvasProps {
  data: MessageData;
  status: ArtifactStatus;
}

export function MessageCanvas({ data, status }: MessageCanvasProps) {
  return (
    <CanvasShell title="Draft Message" status={status}>
      <div className="space-y-3 text-sm">
        {data.subject && (
          <div>
            <span className="text-xs text-muted-foreground">Subject: </span>
            <span className="font-medium">{data.subject}</span>
          </div>
        )}
        <div>
          <span className="text-xs text-muted-foreground">To: </span>
          <span>{(data.recipients ?? []).join(", ")}</span>
        </div>
        {data.sender && (
          <div>
            <span className="text-xs text-muted-foreground">From: </span>
            <span>{data.sender}</span>
          </div>
        )}
        <div className="rounded border border-border bg-muted/30 p-3 text-sm whitespace-pre-wrap">
          {data.body}
        </div>
      </div>
    </CanvasShell>
  );
}
