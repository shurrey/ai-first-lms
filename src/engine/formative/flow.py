"""The formative loop's background steps (spec.md §7.3), run outside any chat turn.

The `feedback` agent scores a draft acting as its learner. Under `auto` release the feedback
is released at once; otherwise it waits for the instructor. Once the learner can see it, the
weakness detector runs and `content_generator` builds practice for each new weakness.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from engine.agents.runner import AgentRunner
from engine.auth.directory import ScopeDirectory
from engine.auth.models import AuthContext, EnrollmentRecord
from engine.formative.locks import KeyedLocks
from engine.formative.policy import release_mode, weakness_window
from engine.formative.spans import check_spans
from engine.formative.store import CriterionRow, FormativeStore, SubmissionRow
from engine.guardrails.budget import BudgetConfig, BudgetTracker
from engine.guardrails.gateway import (
    ArgFilter,
    BackgroundFeedback,
    GatewayContext,
    ToolGateway,
)
from engine.guardrails.injection import wrap_user_content
from engine.logging_config import get_logger
from engine.provenance import ProvenanceTrail, as_uuid, source

log = get_logger(__name__)

FEEDBACK_AGENT = "feedback"
PRACTICE_AGENT = "content_generator"
SAVE_TOOL = "assessments.save_criterion_feedback"
RELEASE_TOOL = "assessments.release_feedback"
WEAKNESS_TOOL = "assessments.weaknesses"
PRACTICE_TOOL = "content.generate_practice"
PRACTICE_COUNT = 4  # spec.md §7.3 asks for 3-5 items

ToolCaller = Callable[[str, dict[str, Any]], Awaitable[Any]]
ReviewAction = Literal["release", "suppress"]


class ToolRefusedError(Exception):
    """A tool returned an error; `code` is the tool's (validation_error, conflict, not_found,
    forbidden) or None, and `message` is user-safe."""

    def __init__(self, code: str | None, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def tool_error(result: Any) -> ToolRefusedError | None:
    if not isinstance(result, dict):
        return ToolRefusedError(None, "The data service returned an unexpected result.")
    if not result.get("error"):
        return None
    code = result.get("code")
    return ToolRefusedError(code if isinstance(code, str) else None, str(result["error"]))


async def _default_call_tool(tool: str, args: dict[str, Any]) -> Any:
    from engine.agents.runner import _call_mcp_json

    return await _call_mcp_json(tool, args)


def _default_runner() -> AgentRunner:
    from engine.graph.dispatch import get_agent_runner

    return get_agent_runner()


class FormativeFlow:
    def __init__(
        self,
        store: FormativeStore,
        *,
        gateway: ToolGateway,
        directory: ScopeDirectory | None,
        locks: KeyedLocks,
        runner: AgentRunner | None = None,
        call_tool: ToolCaller | None = None,
    ) -> None:
        """`locks` is shared across requests: one per learner serializes practice generation.
        `runner` and `call_tool` default to the process's agent runner and MCP client."""
        self._store = store
        self._gateway = gateway
        self._directory = directory
        self._locks = locks
        self._runner = runner
        self._call_tool = call_tool or _default_call_tool

    # --- entry points ---------------------------------------------------------------------

    async def submitted(self, submission_id: str) -> None:
        """Background step after a submission (or a retry): feedback for a draft, nothing
        for a final. A run that saves no feedback leaves a failure marker the learner and
        instructor see as feedback_status `failed`."""
        submission = await self._store.submission(submission_id)
        if submission is None:
            log.error("formative_submission_missing", submission_id=submission_id)
            return
        if submission.status != "draft":
            return
        try:
            failure = await self.generate_feedback(submission)
        except Exception:
            log.error("formative_feedback_failed", submission_id=submission.id, exc_info=True)
            failure = "error"
        if failure is not None:
            await self._store.record_feedback_failure(submission, failure)

    async def generate_feedback(self, submission: SubmissionRow) -> str | None:
        """Scores the draft and, under auto release, releases it; returns why that did not
        happen (no_rubric, agent_error, nothing_saved, release_failed), or None. Feedback an
        earlier run saved is kept, so a retry after a refused release only re-releases."""
        criteria = (await self._store.criteria([submission.id])).get(submission.id, [])
        if not criteria:
            log.warning("formative_no_rubric", submission_id=submission.id,
                        assignment_id=submission.assignment_id)
            return "no_rubric"
        scored = _scored(criteria)
        if not scored:
            failure = await self._score(submission, criteria)
            if failure is not None:
                return failure
            scored = _scored((await self._store.criteria([submission.id])).get(
                submission.id, []))
        mode = await release_mode(self._store, submission.course_id)
        log.info("formative_feedback_saved", submission_id=submission.id,
                 criteria=len(scored), release_mode=mode)
        if mode != "auto" or any(c.released_at is not None for c in scored):
            return None
        refused = tool_error(await self._call_tool(
            RELEASE_TOOL, {"submission_id": submission.id, "decision": "release"}))
        if refused is not None:
            log.error("formative_auto_release_failed", submission_id=submission.id,
                      code=refused.code, error=refused.message)
            return "release_failed"
        await self.feedback_visible(submission.id)
        return None

    async def _score(self, submission: SubmissionRow, criteria: list[CriterionRow]
                     ) -> str | None:
        learner = await self._learner(submission)
        dropped, trails, agent_ok = await self._run_feedback_agent(submission, criteria,
                                                                   learner)
        scored = _scored((await self._store.criteria([submission.id])).get(submission.id, []))
        if not scored:
            log.error("formative_feedback_not_saved", submission_id=submission.id)
            return "nothing_saved" if agent_ok else "agent_error"
        await self._annotate_feedback(submission, scored, dropped,
                                      trails[-1] if trails else None)
        return None

    async def feedback_visible(self, submission_id: str) -> None:
        """Weakness detection and practice once the learner can see feedback."""
        submission = await self._store.submission(submission_id)
        if submission is None or not submission.course_id:
            return
        async with self._locks.hold(submission.person_id):
            await self._practice_for_weaknesses(submission)

    # --- the feedback agent ---------------------------------------------------------------

    async def _run_feedback_agent(
        self, submission: SubmissionRow, criteria: list[CriterionRow], learner: AuthContext
    ) -> tuple[dict[str, list[dict[str, Any]]], list[ProvenanceTrail], bool]:
        """Runs the agent with non-verbatim evidence spans removed from its saves; returns
        the spans dropped per criterion, the run's provenance trail and whether the agent
        reported success."""
        body = submission.body_md or ""
        dropped: dict[str, list[dict[str, Any]]] = {}
        trails: list[ProvenanceTrail] = []

        def verbatim_spans(ctx: GatewayContext, tool: str, args: dict[str, Any]
                           ) -> dict[str, Any]:
            if tool != SAVE_TOOL or args.get("submission_id") != submission.id:
                return args
            if ctx.provenance is not None:
                trails.append(ctx.provenance)
            items = []
            for item in args.get("criteria") or []:
                if not isinstance(item, dict):
                    items.append(item)
                    continue
                check = check_spans(body, item.get("ai_evidence_spans"))
                cid = item.get("criterion_id")
                if check.dropped and isinstance(cid, str):
                    dropped[cid] = check.dropped
                    log.warning("evidence_spans_dropped", submission_id=submission.id,
                                criterion_id=cid, dropped=len(check.dropped))
                items.append({**item, "ai_evidence_spans": check.kept})
            return {**args, "criteria": items}

        result = await self._run_agent(
            FEEDBACK_AGENT, submission, learner, _feedback_request(submission, criteria),
            arg_filter=verbatim_spans,
            bound=BackgroundFeedback(submission.id, submission.assignment_id))
        ok = bool(result.get("success", True))
        if not ok:
            log.error("formative_feedback_agent_failed", submission_id=submission.id)
        return dropped, trails, ok

    async def _annotate_feedback(
        self, submission: SubmissionRow, scored: list[CriterionRow],
        dropped: dict[str, list[dict[str, Any]]], trail: ProvenanceTrail | None,
    ) -> None:
        """Adds the model, prompt hash, earlier versions read and dropped spans to the
        criterion_feedback rows the server wrote."""
        actions = sorted({c.ai_action_id for c in scored if c.ai_action_id})
        if not actions:
            log.error("formative_feedback_action_missing", submission_id=submission.id)
            return
        earlier = [v for v in await self._store.versions(submission.person_id,
                                                         submission.assignment_id)
                   if v.id != submission.id and v.submitted_at <= submission.submitted_at]
        own = [s for s in [source("submission", submission.id, submission.version),
                           source("rubric", submission.rubric_id),
                           *(source("submission", v.id, v.version) for v in earlier)]
               if s is not None]
        sources = trail.sources(own, submission.person_id) if trail else own
        output = {"dropped_spans": dropped} if dropped else {}
        for action_id in actions:
            try:
                found = await self._store.annotate_action(
                    action_id, model=trail.model if trail else None,
                    prompt_sha256=trail.prompt_sha256 if trail else None, sources=sources,
                    output=output)
            except Exception:
                log.error("provenance_write_failed", action_type="criterion_feedback",
                          ai_action_id=action_id, exc_info=True)
                continue
            if not found:
                log.error("formative_feedback_action_missing", ai_action_id=action_id)

    # --- instructor review ----------------------------------------------------------------

    async def review(self, submission: SubmissionRow, *, pending: list[CriterionRow],
                     reviewer_id: str, action: ReviewAction,
                     edits: dict[str, dict[str, Any]], suppress: frozenset[str],
                     reason: str | None) -> None:
        """Release (with edits) or suppress the `pending` criteria. The server records one
        human decision per criterion for `reviewer_id`. `edits` maps criterion id -> the
        changed ai_score / ai_rationale / next_step. Raises ToolRefusedError."""
        held = [c.criterion_id for c in pending
                if action == "suppress" or c.criterion_id in suppress]
        released = [c.criterion_id for c in pending if c.criterion_id not in held]
        common: dict[str, Any] = {"submission_id": submission.id, "reviewer_id": reviewer_id}
        if reason:
            common["reason"] = reason
        if released:
            tool_edits = [{"criterion_id": cid, **edits[cid]} for cid in released
                          if edits.get(cid)]
            await self._release_call({**common, "decision": "release",
                                      "criterion_ids": released,
                                      **({"edits": tool_edits} if tool_edits else {})})
        if held:
            await self._release_call({**common, "decision": "suppress", "criterion_ids": held})
        log.info("formative_feedback_reviewed", submission_id=submission.id,
                 released=len(released), suppressed=len(held), reviewer_id=reviewer_id)

    async def _release_call(self, args: dict[str, Any]) -> None:
        refused = tool_error(await self._call_tool(RELEASE_TOOL, args))
        if refused is not None:
            log.warning("formative_release_refused", submission_id=args["submission_id"],
                        decision=args["decision"], code=refused.code, error=refused.message)
            raise refused

    # --- weaknesses and practice ----------------------------------------------------------

    async def _practice_for_weaknesses(self, submission: SubmissionRow) -> None:
        assert submission.course_id is not None
        window = await weakness_window(self._store, submission.course_id)
        result = await self._call_tool(WEAKNESS_TOOL, {
            "student_id": submission.person_id, "course_id": submission.course_id,
            "window": window})
        refused = tool_error(result)
        if refused is not None:
            log.error("formative_weakness_check_failed", submission_id=submission.id,
                      code=refused.code, error=refused.message)
            return
        found = [w for w in result.get("weaknesses") or []
                 if isinstance(w, dict) and as_uuid(w.get("criterion_id"))]
        if not found:
            return
        existing = await self._store.practice_sets(
            submission.person_id, [w["criterion_id"] for w in found])
        learner = await self._learner(submission)
        for weakness in found:
            if as_uuid(weakness["criterion_id"]) not in existing:
                await self._generate_practice(submission, learner, weakness)

    async def _generate_practice(self, submission: SubmissionRow, learner: AuthContext,
                                 weakness: dict[str, Any]) -> None:
        criterion = as_uuid(weakness["criterion_id"])
        assert criterion is not None
        trails: list[ProvenanceTrail] = []

        def capture_trail(ctx: GatewayContext, tool: str, args: dict[str, Any]
                          ) -> dict[str, Any]:
            if tool == PRACTICE_TOOL and ctx.provenance is not None:
                trails.append(ctx.provenance)
            return args

        result = await self._run_agent(PRACTICE_AGENT, submission, learner,
                                       _practice_request(submission, weakness),
                                       arg_filter=capture_trail)
        action_id = (await self._store.practice_sets(submission.person_id,
                                                     [criterion])).get(criterion)
        if action_id is None:
            log.error("formative_practice_not_saved", submission_id=submission.id,
                      criterion_id=criterion, agent_success=result.get("success", True))
            return
        trail = trails[-1] if trails else None
        if trail is not None:
            try:
                await self._store.annotate_action(
                    action_id, model=trail.model, prompt_sha256=trail.prompt_sha256,
                    sources=trail.sources(None, submission.person_id), output={})
            except Exception:
                log.error("provenance_write_failed", action_type="practice_item",
                          ai_action_id=action_id, exc_info=True)
        log.info("formative_practice_generated", submission_id=submission.id,
                 criterion_id=criterion, ai_action_id=action_id)

    # --- shared ---------------------------------------------------------------------------

    async def _run_agent(self, agent: str, submission: SubmissionRow, learner: AuthContext,
                         message: str, *, arg_filter: ArgFilter,
                         bound: BackgroundFeedback | None = None) -> dict[str, Any]:
        runner = self._runner or _default_runner()
        ctx = GatewayContext(auth=learner, course_id=submission.course_id or "",
                             budget=BudgetTracker(BudgetConfig.from_env()),
                             arg_filter=arg_filter, background_feedback=bound)
        try:
            return await runner.run(agent, {
                "message": message, "persona": "student", "person_id": learner.person_id,
                "course_id": submission.course_id or "", "conversation": [],
                "session_id": "", "_gateway": self._gateway, "_tool_context": ctx,
            })
        except Exception:
            log.error("formative_agent_failed", agent=agent, submission_id=submission.id,
                      exc_info=True)
            return {"success": False}

    async def _learner(self, submission: SubmissionRow) -> AuthContext:
        """The learner as a requester, enrolled as a student in the submission's course only,
        so the agent's tool calls are scoped to their own work."""
        names = await self._store.display_names([submission.person_id])
        enrollments: tuple[EnrollmentRecord, ...] = ()
        if submission.course_id:
            ref = (await self._directory.resolve_course(submission.course_id)
                   if self._directory is not None else None)
            enrollments = (EnrollmentRecord(
                submission.course_id, ref.slug if ref else submission.course_id,
                ref.title if ref else "", "student"),)
        return AuthContext(
            person_id=submission.person_id,
            display_name=names.get(submission.person_id, ""), email=None,
            roles=("student",), active_role="student", enrollments=enrollments,
            advisee_ids=frozenset(), session_id="")


def _scored(criteria: list[CriterionRow]) -> list[CriterionRow]:
    return [c for c in criteria if c.ai_score is not None]


def _feedback_request(submission: SubmissionRow, criteria: list[CriterionRow]) -> str:
    listed = "\n".join(
        f"- criterion_id {c.criterion_id}: {wrap_user_content(c.key, 'rubric')}"
        for c in criteria)
    return (
        f"Give formative feedback on draft submission {submission.id} "
        f"(version {submission.version}) in course {submission.course_id or 'unknown'}.\n"
        f"Rubric {submission.rubric_id or 'of the assignment'} has these criteria:\n{listed}\n"
        "Read the submission with assessments.get_submission, the rubric with "
        "assessments.get_rubric, and earlier versions with "
        "assessments.list_submission_history (assignment_node "
        f"{submission.assignment_id}, course_id {submission.course_id or ''}). Then call "
        "assessments.save_criterion_feedback once for this submission_id with every "
        "criterion: ai_score (a rubric level score, not a grade), ai_rationale, "
        "ai_evidence_spans whose quote is copied verbatim from the submission, and exactly "
        "one next_step. Do not assign a grade."
    )


def _practice_request(submission: SubmissionRow, weakness: dict[str, Any]) -> str:
    key = weakness.get("key")
    scores = weakness.get("last_scores")
    return (
        f"Generate a private practice set for learner {submission.person_id} in course "
        f"{submission.course_id}. Recent drafts were below target on rubric criterion "
        f"{wrap_user_content(str(key or ''), 'rubric')} (criterion_id "
        f"{weakness['criterion_id']}; last scores {scores if isinstance(scores, list) else []}"
        "). Call content.generate_practice once with criterion_id "
        f"{weakness['criterion_id']}, student_id {submission.person_id}, count "
        f"{PRACTICE_COUNT} and exactly {PRACTICE_COUNT} items (type, stem, answer_key, "
        "bloom_level) that practise this criterion. Do not mention other learners."
    )
