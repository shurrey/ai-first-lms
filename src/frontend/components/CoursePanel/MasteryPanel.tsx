"use client";

function sendPrompt(prompt: string) {
  const input = document.querySelector<HTMLInputElement>('form input[type="text"]');
  const form = input?.closest("form");
  if (input && form) {
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    nativeSetter?.call(input, prompt);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    requestAnimationFrame(() => requestAnimationFrame(() => form.requestSubmit()));
  }
}

interface MasteryData {
  summary: {
    total_concepts: number;
    mastery: number;
    proficient: number;
    emerging: number;
    not_started: number;
    microcredentials_earned: number;
    microcredentials_total: number;
  };
  microcredentials: Array<{
    title: string;
    earned: boolean;
    total_concepts: number;
    progress: { mastery: number; proficient: number; emerging: number; not_started: number };
  }>;
}

export function MasteryPanel({ data }: { data: MasteryData | null }) {
  if (!data || !data.summary) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading mastery data...</p>;
  }

  const { summary, microcredentials } = data;

  return (
    <div className="space-y-4">
      <section>
        <SectionLabel>Mastery Progress</SectionLabel>
        <div className="rounded-lg border border-border bg-card p-3 space-y-2">
          <div className="text-center">
            <div className="text-2xl font-bold">{summary.mastery}/{summary.total_concepts}</div>
            <div className="text-[10px] text-muted-foreground">concepts mastered</div>
          </div>
          <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted">
            {summary.mastery > 0 && <div className="bg-green-500" style={{ width: `${(summary.mastery / summary.total_concepts) * 100}%` }} />}
            {summary.proficient > 0 && <div className="bg-blue-400" style={{ width: `${(summary.proficient / summary.total_concepts) * 100}%` }} />}
            {summary.emerging > 0 && <div className="bg-amber-400" style={{ width: `${(summary.emerging / summary.total_concepts) * 100}%` }} />}
          </div>
          <div className="flex justify-between text-[9px] text-muted-foreground">
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-green-500" />{summary.mastery} mastered</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-blue-400" />{summary.proficient} proficient</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-amber-400" />{summary.emerging} emerging</span>
          </div>
        </div>
      </section>

      <section>
        <SectionLabel>Microcredentials ({summary.microcredentials_earned}/{summary.microcredentials_total})</SectionLabel>
        <div className="space-y-2">
          {microcredentials.map((mc, i) => {
            const pct = mc.total_concepts > 0 ? Math.round((mc.progress.mastery / mc.total_concepts) * 100) : 0;
            return (
              <button
                key={i}
                onClick={() => sendPrompt(`Tell me about my progress on the ${mc.title} microcredential`)}
                className="w-full rounded-lg border border-border bg-card p-3 text-left hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium flex items-center gap-1">
                    {mc.earned ? "🏅" : "🔒"} {mc.title}
                  </span>
                  <span className="text-[10px] text-muted-foreground">{pct}%</span>
                </div>
                <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  {mc.progress.mastery > 0 && <div className="bg-green-500" style={{ width: `${(mc.progress.mastery / mc.total_concepts) * 100}%` }} />}
                  {mc.progress.proficient > 0 && <div className="bg-blue-400" style={{ width: `${(mc.progress.proficient / mc.total_concepts) * 100}%` }} />}
                  {mc.progress.emerging > 0 && <div className="bg-amber-400" style={{ width: `${(mc.progress.emerging / mc.total_concepts) * 100}%` }} />}
                </div>
                <div className="mt-1 text-[9px] text-muted-foreground">{mc.progress.mastery}/{mc.total_concepts} mastered</div>
              </button>
            );
          })}
        </div>
      </section>

      <section>
        <SectionLabel>Quick Actions</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          <Pill onClick={() => sendPrompt("What should I work on next to earn my next microcredential?")}>🎯 What's next?</Pill>
          <Pill onClick={() => sendPrompt("Show me my full mastery map")}>📊 Mastery map</Pill>
          <Pill onClick={() => sendPrompt("Quiz me on a concept I'm working on")}>📝 Quiz me</Pill>
          <Pill onClick={() => sendPrompt("What microcredentials have I earned?")}>🏅 My credentials</Pill>
        </div>
      </section>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>;
}

function Pill({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-muted transition-colors">
      {children}
    </button>
  );
}
