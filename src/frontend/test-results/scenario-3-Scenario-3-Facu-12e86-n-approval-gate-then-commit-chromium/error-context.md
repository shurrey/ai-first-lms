# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: scenario-3.spec.ts >> Scenario 3: Faculty grades with rubric >> grades wait behind an approval gate, then commit
- Location: tests/e2e/scenario-3.spec.ts:10:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('region', { name: 'Approval needed' }).getByRole('button', { name: 'Approve' }).and(locator(':enabled')).or(locator('main').getByText(/^(Error: |Failed to send message)/).first().or(getByTestId('clarify-prompt').or(locator('div.border-blue-200.bg-blue-50:has(> p.text-sm.font-medium)')).first()))
Expected: visible
Timeout: 150000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 150000ms
  - waiting for getByRole('region', { name: 'Approval needed' }).getByRole('button', { name: 'Approve' }).and(locator(':enabled')).or(locator('main').getByText(/^(Error: |Failed to send message)/).first().or(getByTestId('clarify-prompt').or(locator('div.border-blue-200.bg-blue-50:has(> p.text-sm.font-medium)')).first()))

```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - alert [ref=e2]
  - generic [ref=e3]:
    - banner [ref=e4]:
      - heading "AI-First LMS" [level=1] [ref=e5]
      - generic [ref=e6]: ·
      - generic [ref=e7]: Course
      - combobox "Course" [ref=e8]:
        - option "Select a course..."
        - option "CS 101 — Introduction to Computer Science" [selected]
      - generic [ref=e9]:
        - status [ref=e10]
        - button "Dr. Maria Torres Faculty" [ref=e12]:
          - generic [ref=e13]: Dr. Maria Torres
          - generic [ref=e14]: Faculty
          - generic [ref=e15]: ▾
    - generic [ref=e16]:
      - main [ref=e17]:
        - generic [ref=e19]:
          - generic [ref=e21]:
            - generic [ref=e22]:
              - paragraph [ref=e23]:
                - text: Welcome back! Your course has
                - strong [ref=e24]: 50 students
                - text: enrolled across 12 modules, with active learning data through October 14, 2026.
              - paragraph [ref=e25]:
                - strong [ref=e26]: "Items needing your attention:"
              - list [ref=e27]:
                - listitem [ref=e28]:
                  - strong [ref=e29]: "Submissions to grade:"
                  - text: Multiple
                  - code [ref=e30]: "`artifact_submission`"
                  - text: entries from recent days (including assignments on Functions, Data Structures, and Variables modules) are awaiting faculty review, particularly several with lower confidence scores that may benefit from your manual input.
                - listitem [ref=e31]:
                  - strong [ref=e32]: "At-risk students:"
                  - text: At least 4 students show a pattern of low scores (below 30%) on recent quiz attempts and assignments — notably
                  - strong [ref=e33]: Avery Lewis
                  - text: ","
                  - strong [ref=e34]: Ethan Garcia
                  - text: ","
                  - strong [ref=e35]: Harper Taylor
                  - text: ", and"
                  - strong [ref=e36]: Dylan Rivera
                  - text: — suggesting they may need outreach or support.
              - paragraph [ref=e37]:
                - strong [ref=e38]: "Suggested action right now:"
                - text: Pull up the Gradebook and review pending
                - code [ref=e39]: "`artifact_submission`"
                - text: items flagged with low confidence scores, then send a check-in message to your at-risk students before the next module deadline.
            - button "AI-generated · sources" [ref=e41]:
              - img [ref=e42]
              - text: AI-generated · sources
          - paragraph [ref=e47]: Grade submissions for Essay 3 with my rubric.
          - generic [ref=e49]:
            - paragraph [ref=e51]: I took too long processing your request. Please try a more specific question.
            - button "AI-generated · sources" [ref=e53]:
              - img [ref=e54]
              - text: AI-generated · sources
          - button "What ran 14 tool calls" [ref=e58]:
            - generic [ref=e59]: ▶
            - generic [ref=e60]: What ran
            - generic [ref=e61]: 14 tool calls
          - status
        - generic [ref=e63]:
          - textbox "Type a message... (Shift+Enter for new line)" [ref=e64]
          - button "Send" [disabled]
      - complementary [ref=e65]:
        - generic [ref=e66]:
          - button "Overview" [pressed] [ref=e67]
          - button "Roster" [ref=e68]
        - generic [ref=e69]:
          - button "Open AI Review" [ref=e70]:
            - img [ref=e71]
            - text: Open AI Review
          - generic [ref=e73]:
            - generic [ref=e74]:
              - heading "Class at a Glance" [level=3] [ref=e75]
              - generic [ref=e76]:
                - generic [ref=e77]:
                  - generic [ref=e78]: Students
                  - generic [ref=e79]: "50"
                - generic [ref=e80]:
                  - generic [ref=e81]: Instructors
                  - generic [ref=e82]: "2"
                - generic [ref=e83]:
                  - generic [ref=e84]: Modules
                  - generic [ref=e85]: "12"
                - generic [ref=e86]:
                  - generic [ref=e87]: Class Avg
                  - generic [ref=e88]: 64%
            - generic [ref=e89]:
              - heading "Score Distribution" [level=3] [ref=e90]
              - generic [ref=e91]:
                - generic [ref=e92]:
                  - 'generic "High: 8" [ref=e93]'
                  - 'generic "Medium: 35" [ref=e94]'
                  - 'generic "Low: 6" [ref=e95]'
                  - 'generic "At-risk: 1" [ref=e96]'
                - generic [ref=e97]:
                  - generic [ref=e98]: 8 high
                  - generic [ref=e100]: 35 mid
                  - generic [ref=e102]: 6 low
                  - generic [ref=e104]: 1 risk
            - generic [ref=e106]:
              - heading "Needs Attention" [level=3] [ref=e107]
              - generic [ref=e108]:
                - button "Avery Lewis 25%" [ref=e109]:
                  - generic [ref=e110]: Avery Lewis
                  - generic [ref=e111]: 25%
                - button "Ethan Garcia 34%" [ref=e112]:
                  - generic [ref=e113]: Ethan Garcia
                  - generic [ref=e114]: 34%
                - button "Dylan Rivera 37%" [ref=e115]:
                  - generic [ref=e116]: Dylan Rivera
                  - generic [ref=e117]: 37%
                - button "Mia Hernandez 42%" [ref=e118]:
                  - generic [ref=e119]: Mia Hernandez
                  - generic [ref=e120]: 42%
                - button "Noah Brown 44%" [ref=e121]:
                  - generic [ref=e122]: Noah Brown
                  - generic [ref=e123]: 44%
            - generic [ref=e124]:
              - heading "Quick Actions" [level=3] [ref=e125]
              - generic [ref=e126]:
                - button "📊 Class performance" [ref=e127]
                - button "⚠️ At-risk students" [ref=e128]
                - button "📝 Grade submissions" [ref=e129]
                - button "🎯 Create quiz" [ref=e130]
                - button "📢 Announcement" [ref=e131]
        - paragraph [ref=e132]: 65b1de40
```

# Test source

```ts
  71  |   return new RegExp(`^${match[1].toUpperCase()} ${match[2]}\\b`);
  72  | }
  73  | 
  74  | export async function expectActiveRole(page: Page, role: string | null) {
  75  |   if (!role) return;
  76  |   await expect(page.getByTestId("account-menu-button")).toContainText(ROLE_LABELS[role] ?? role);
  77  | }
  78  | 
  79  | /** Picks the course in the header and waits for the orchestrator to create the session. */
  80  | export async function startCourseSession(page: Page, slug: string) {
  81  |   const select = page.locator("#course-select");
  82  |   await expect(select).toBeVisible();
  83  |   const pattern = courseTitlePattern(slug);
  84  |   const options = select.locator("option");
  85  |   const labels = await options.allTextContents();
  86  |   const index = labels.findIndex((l) => pattern.test(l));
  87  |   if (index < 0) throw new Error(`No course matching ${pattern} in [${labels.join(", ")}]`);
  88  |   const value = await options.nth(index).getAttribute("value");
  89  |   if (!value) throw new Error(`Course option ${labels[index]} has no value`);
  90  |   const created = page.waitForResponse(
  91  |     (r) => new URL(r.url()).pathname === "/api/session" && r.request().method() === "POST"
  92  |   );
  93  |   await select.selectOption(value);
  94  |   expect((await created).ok()).toBe(true);
  95  |   await expect(page.getByPlaceholder(/Type a message/)).toBeEnabled();
  96  |   // Every new session streams a generated brief first; the input stays busy until it lands.
  97  |   await expect(answerLabels(page).first().or(turnError(page))).toBeVisible({ timeout: TURN_TIMEOUT_MS });
  98  |   await expect(page.getByRole("button", { name: "Send" })).toBeVisible({ timeout: TURN_TIMEOUT_MS });
  99  | }
  100 | 
  101 | export function approvalGate(page: Page): Locator {
  102 |   return page.getByRole("region", { name: "Approval needed" });
  103 | }
  104 | 
  105 | /** Provenance labels in the message list; the approval preview's label sits outside it. */
  106 | function answerLabels(page: Page): Locator {
  107 |   return page.locator("main > div").first().getByTestId("ai-generated-label");
  108 | }
  109 | 
  110 | function turnError(page: Page): Locator {
  111 |   return page.locator("main").getByText(/^(Error: |Failed to send message)/).first();
  112 | }
  113 | 
  114 | /** ChatPane's ClarifyPrompt: the blue box holding the orchestrator's question. */
  115 | function clarifyPrompt(page: Page): Locator {
  116 |   return page
  117 |     .getByTestId("clarify-prompt")
  118 |     .or(page.locator("div.border-blue-200.bg-blue-50:has(> p.text-sm.font-medium)"))
  119 |     .first();
  120 | }
  121 | 
  122 | /** Something that ends the wait for the next gate or the answer without either arriving. */
  123 | function turnStopped(page: Page): Locator {
  124 |   return turnError(page).or(clarifyPrompt(page));
  125 | }
  126 | 
  127 | async function expectTurnNotStopped(page: Page, when: string) {
  128 |   await expect(clarifyPrompt(page), `turn asked a clarifying question ${when}`).toHaveCount(0);
  129 |   await expect(turnError(page), `turn failed ${when}`).toHaveCount(0);
  130 | }
  131 | 
  132 | export interface TurnObservations {
  133 |   /** The action text of each approval gate, in the order they were approved. */
  134 |   approvedActions: string[];
  135 |   /** Send to answer minus the time each gate waited for its decision, as `scripts/demo` counts. */
  136 |   activeMs: number;
  137 | }
  138 | 
  139 | /**
  140 |  * Sends the scenario's message, approves its scripted gates as they appear, and waits for the
  141 |  * final answer. Fails on an error, a clarifying question, a gate count that differs from the
  142 |  * script (fewer than scripted, with `approveRest`), or an answer slower than the scenario's
  143 |  * `max_wall_time_ms`.
  144 |  */
  145 | export async function runTurn(page: Page, scenario: LiveScenario): Promise<TurnObservations> {
  146 |   const { message, approvals, approveRest } = scenario;
  147 |   const labelsBefore = await answerLabels(page).count();
  148 |   await page.getByPlaceholder(/Type a message/).fill(message);
  149 |   const sentAt = Date.now();
  150 |   await page.getByRole("button", { name: "Send" }).click();
  151 |   await expect(page.getByText(message, { exact: true }).first()).toBeVisible();
  152 | 
  153 |   const gate = approvalGate(page);
  154 |   // The previous gate stays rendered, disabled, until its decision lands; an enabled
  155 |   // button therefore belongs to the next gate.
  156 |   const nextApprove = gate.getByRole("button", { name: "Approve" }).and(page.locator(":enabled"));
  157 |   const approvedActions: string[] = [];
  158 |   let approvalWaitMs = 0;
  159 |   const approveNext = async () => {
  160 |     const shownAt = Date.now();
  161 |     await expect(gate.getByText("Awaiting Approval")).toBeVisible();
  162 |     approvedActions.push((await gate.locator("p.text-sm.font-medium").last().textContent()) ?? "");
  163 |     const decided = page.waitForResponse(
  164 |       (r) => new URL(r.url()).pathname === "/api/approval" && r.request().method() === "POST"
  165 |     );
  166 |     await nextApprove.click();
  167 |     expect((await decided).ok()).toBe(true);
  168 |     approvalWaitMs += Date.now() - shownAt;
  169 |   };
  170 |   for (let i = 0; i < approvals; i++) {
> 171 |     await expect(nextApprove.or(turnStopped(page))).toBeVisible({ timeout: TURN_TIMEOUT_MS });
      |                                                     ^ Error: expect(locator).toBeVisible() failed
  172 |     await expectTurnNotStopped(page, `before approval ${i + 1}`);
  173 |     await approveNext();
  174 |   }
  175 | 
  176 |   const answer = answerLabels(page).nth(labelsBefore);
  177 |   await expect(answer.or(turnStopped(page)).or(nextApprove)).toBeVisible({ timeout: TURN_TIMEOUT_MS });
  178 |   while (approveRest && (await nextApprove.isVisible()) && !(await answer.isVisible())) {
  179 |     await approveNext();
  180 |     await expect(answer.or(turnStopped(page)).or(nextApprove)).toBeVisible({ timeout: TURN_TIMEOUT_MS });
  181 |   }
  182 |   const activeMs = Date.now() - sentAt - approvalWaitMs;
  183 |   await expect(nextApprove, `unscripted approval gate after ${approvals} approvals`).toHaveCount(0);
  184 |   await expectTurnNotStopped(page, "instead of answering");
  185 |   await expect(approvalGate(page)).toHaveCount(0);
  186 |   expect(activeMs, "send to answer, approval gates excluded").toBeLessThanOrEqual(scenario.maxWallTimeMs);
  187 |   return { approvedActions, activeMs };
  188 | }
  189 | 
  190 | /** The collapsed "What ran" drawer lists every tool call the turn made. */
  191 | export async function toolCallsRun(page: Page): Promise<string[]> {
  192 |   const drawer = page.getByRole("button", { name: /What ran/ }).last();
  193 |   await expect(drawer).toBeVisible();
  194 |   if ((await drawer.getAttribute("aria-expanded")) !== "true") await drawer.click();
  195 |   const tools = drawer.locator("xpath=..").locator("div:has(> span[role=img]) > span:nth-child(2)");
  196 |   return (await tools.allTextContents()).map((t) => t.trim());
  197 | }
  198 | 
```