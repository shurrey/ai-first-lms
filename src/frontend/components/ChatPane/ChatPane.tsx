export function ChatPane() {
  return (
    <main className="flex h-full flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-2xl space-y-4">
          <p className="text-center text-sm text-muted-foreground">
            Start a conversation with the AI-First LMS.
          </p>
        </div>
      </div>
      <div className="shrink-0 border-t border-border p-4">
        <div className="mx-auto max-w-2xl">
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Type a message..."
              className="flex-1 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/50"
              disabled
            />
            <button
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
              disabled
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
