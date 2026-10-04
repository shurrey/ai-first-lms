"""ToolGateway: the one guardrail path for agent model and tool calls (spec.md §5.2).

Steps: 1 allow-list, 2 role, 3 identity and scope (including object-level scope for id-keyed
tools), 5 write-gate, 6 budget, 7 execute, 8 PII, 9 injection wrapping, 10 provenance.
Denials reach the model as "not permitted" tool errors.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any, Protocol

from engine.auth.access_log import AccessLog, AccessResource
from engine.auth.directory import ScopeDirectory
from engine.auth.models import AuthContext
from engine.auth.scope import (
    ALL_COURSES,
    SensitiveRead,
    actable_course_ids,
    can_view_student,
    is_course_staff,
    record_access,
    record_sensitive_read,
)
from engine.guardrails.approval import (
    ApprovalGate,
    ApprovalRequest,
    artifact_type_for,
)
from engine.guardrails.budget import ActiveClock, BudgetExceededError, BudgetTracker
from engine.guardrails.grade_commit import (
    COMMIT_TOOL,
    INSTRUCTOR_INPUTS,
    CommitIncompleteError,
    check_commit,
    criterion_keys,
    without_instructor_inputs,
)
from engine.guardrails.injection import source_for_tool, wrap_tool_value, wrap_user_content
from engine.guardrails.object_directory import ObjectDirectory
from engine.guardrails.objects import DraftLedger, identity_paths, parse_object
from engine.guardrails.pii import scan_and_redact, scan_and_redact_result
from engine.guardrails.private_evidence import withhold_private_in_result
from engine.guardrails.registry import get_manifest_registry, get_tool_roles
from engine.guardrails.tool_roles import ToolRoles
from engine.logging_config import get_logger
from engine.manifests import AgentManifest, ManifestRegistry
from engine.provenance import ProvenanceRecorder, ProvenanceTrail, ToolCallFacts, call_key
from engine.turn_repository import ToolCallOutcome, ToolCallRow, TurnRepository

log = get_logger(__name__)

NOT_PERMITTED = "not permitted"
SUMMARY_CHARS = 200
SUBJECT_ARGS = ("person_id", "student_id")
SUBJECT_LIST_ARGS = ("person_ids", "student_ids")
REQUESTER_ARG = "requester_id"
AUTHOR_ARG = "author_id"
ISSUER_ARG = "issuer_id"
GRADER_ARG = "graded_by"
COURSE_ARG = "course_id"
_CROSS_COURSE_ROLES = frozenset({"advisor", "admin"})
APPROVER_ARGS = ("reviewer_id", GRADER_ARG)  # set to the approving person on resume

LEARNER_BACKGROUND_TOOLS = frozenset({"assessments.save_criterion_feedback"})
# Agents that run only in a background flow (spec.md §7.3), never for a chat turn.
BACKGROUND_AGENTS = frozenset({"feedback"})
# Tools a bound feedback run may call only for the submission it reviews.
BOUND_SUBMISSION_TOOLS = frozenset({"assessments.get_submission",
                                    "assessments.save_criterion_feedback"})
GRADING_STATUS_TOOL = "assessments.grading_status"
# Tools keyed by ids the gateway resolves to a course: tool -> (argument, id kind).
COURSE_OBJECT_TOOLS = {
    "content.generate_practice": ("criterion_id", "criterion"),
    "assessments.propose_alignment": ("assignment_node", "node"),
    "graph.subgraph_for_outcomes": ("outcome_ids", "node"),
}
SUBMISSION_TOOLS = frozenset({"assessments.get_submission", "assessments.draft_grade",
                              "assessments.save_criterion_feedback",
                              "assessments.release_feedback"})
# Non-admin staff callers must name the course: the server filters by it and nothing else ties
# the call to a course the caller teaches.
SUBMISSION_LIST_TOOL = "assessments.list_submission_history"
PENDING_TOOLS = frozenset({"assessments.get_credential_evidence",
                           "assessments.approve_credential"})
# Tools whose session_id must be the caller's current session or one they may view;
# roster.save_session is excluded because it creates the row.
SESSION_REQUIRED_TOOLS = frozenset({"roster.get_session_transcript",
                                    "roster.update_session_summary"})
SESSION_EXEMPT_TOOLS = frozenset({"roster.save_session"})
AUDIENCE_TOOL = "communications.draft_message"
BANK_TOOL = "assessments.create_question"
CONCEPT_WRITE_TOOLS = frozenset({"content.save_skill"})
# node_id is optional here; a draft on a node can replace what readers of that node see.
NODE_WRITE_TOOLS = frozenset({"content.save_draft"})
# The analytics server reads a missing scope.course_id or person_id as "no filter".
ANALYTICS_TOOLS = frozenset({"analytics.query", "analytics.trend",
                             "analytics.cohort_compare"})
# A student's evidence-writing calls count toward mastery timing in the current session only.
STUDENT_SESSION_TOOLS = frozenset({"attestations.attest", "roster.save_concept_review"})
# Object ids _check_objects reads only at the top level; no tool contract nests them.
TOP_LEVEL_OBJECT_KEYS = frozenset({"submission_id", "grade_id", "draft_id", "pending_id",
                                   "concept_id", "session_id", "bank_id"})

# Reads that write a data_access_log row for a non-self requester (spec.md §12.3):
# tool -> (resource, argument holding the resource id). roster.get and roster.get_student
# return persons.attributes, which carries the learner profile and analyst insights;
# roster.list_student_sessions returns each session's first message.
SENSITIVE_READS: dict[str, tuple[AccessResource, str | None]] = {
    "roster.get_session_transcript": ("transcript", "session_id"),
    "roster.get_recent_turns": ("transcript", None),
    "roster.list_student_sessions": ("transcript", None),
    "roster.get_learner_profile": ("profile", None),
    "roster.get_goals": ("profile", None),
    "roster.get": ("profile", None),
    "roster.get_student": ("profile", None),
    "assessments.get_submission": ("submission", "submission_id"),
}

UNRESOLVED = "That record could not be found within this account's access."
UNKNOWN_DRAFT = ("That draft was not made in a conversation this service remembers; "
                 "draft it again first.")

REJECTED_REASON = "A person reviewed this action and declined it, so it was not carried out."
APPROVAL_UNAVAILABLE = "This action needs a person's approval, which this request cannot ask for."

_ACTIONS = {
    "assessments.commit_grade": "Commit grade",
    "assessments.approve_credential": "Approve credential",
    "assessments.create_question": "Add question to a live question bank",
    "attestations.override": "Override attestation",
    "communications.send_message": "Send message",
    "content.publish": "Publish content",
    "assessments.release_feedback": "Release feedback",
    "policy.set": "Change policy",
}

Executor = Callable[[str, dict[str, Any]], Awaitable[str]]
EventSink = Callable[[dict[str, Any]], Awaitable[None]]
# (context, tool, arguments) -> arguments to run; may only drop or correct content, never ids.
ArgFilter = Callable[["GatewayContext", str, dict[str, Any]], dict[str, Any]]


class TurnStatusSink(Protocol):
    async def update_status(self, turn_id: str, status: str) -> None: ...


def _collect_actions(ctx: GatewayContext, facts: ToolCallFacts) -> None:
    if ctx.ai_action_ids is not None:
        ctx.ai_action_ids.extend(i for i in facts.recorded if i not in ctx.ai_action_ids)


def approval_timeout_s() -> float:
    return float(os.environ.get("APPROVAL_TIMEOUT_MINUTES", "30")) * 60


# ScopeDenied is the name spec.md §5.2 uses; its siblings follow it.
class ToolDenied(Exception):  # noqa: N818
    kind: ToolCallOutcome = "denied_permission"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason  # user-safe: no names, no raw arguments


class PermissionDenied(ToolDenied):  # noqa: N818
    kind: ToolCallOutcome = "denied_permission"


class ScopeDenied(ToolDenied):  # noqa: N818
    kind: ToolCallOutcome = "denied_scope"


class EditRejected(ToolDenied):  # noqa: N818
    """An approver's edit changes what the action applies to; POST /api/approval maps it
    to 422."""

    kind: ToolCallOutcome = "denied_policy"


@dataclass(frozen=True)
class BackgroundFeedback:
    """The one submission a background feedback run reviews, and its assignment."""

    submission_id: str
    assignment_id: str


@dataclass(frozen=True)
class GatewayContext:
    """Who is asking and where; `auth` None means no signed-in requester (every call is denied)."""

    auth: AuthContext | None
    session_id: str = ""
    turn_id: str = ""
    step_id: str = ""
    budget: BudgetTracker | None = None
    course_id: str = ""  # the session's course, used to scope an approver
    emit: EventSink | None = None  # live event sink; without it gated tools are denied
    agent_clock: ActiveClock | None = None  # paused, like the budget clock, during approvals
    provenance: ProvenanceTrail | None = None  # the agent run's model, prompt hash, sources
    # Shared list receiving the id of every ai_actions row written for this context's calls.
    ai_action_ids: list[str] | None = None
    # Applied after the scope checks, before approval and execution.
    arg_filter: ArgFilter | None = None
    # Set only by the formative flow's background run on a learner's own submission.
    background_feedback: BackgroundFeedback | None = None


@dataclass(frozen=True)
class ToolResult:
    text: str  # what the model receives: redacted and user_content-wrapped
    outcome: ToolCallOutcome
    args: dict[str, Any]  # as executed, or as they stood when denied
    latency_ms: float
    guardrail: dict[str, Any] | None = None  # GuardrailPayload (contracts/events.md) on denial
    summary: str = ""  # redacted, unwrapped, at most SUMMARY_CHARS; for events and logs
    approval: dict[str, Any] | None = None  # {approval_id, decision, approved_by} when gated
    value: Any = None  # parsed, redacted, unwrapped result; None unless the call succeeded

    @property
    def success(self) -> bool:
        return self.outcome == "ok"


def _looks_like_error(text: str) -> bool:
    return "error" in text.lower()[:50]


def _redact_args(value: Any) -> Any:
    if isinstance(value, str):
        return scan_and_redact(value).text
    if isinstance(value, dict):
        return {k: _redact_args(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_args(v) for v in value]
    return value


def _parse_audience(value: Any) -> Any:
    """draft_message accepts the audience as an object or its JSON text."""
    if not isinstance(value, str):
        return value
    parsed = parse_object(value)
    if parsed is None:
        try:
            listed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            listed = None
        if isinstance(listed, list):
            return listed
        raise ScopeDenied("The audience must name a course or people.")
    return parsed


def _course_arg(args: dict[str, Any]) -> str | None:
    course = args.get("course_id")
    return course if isinstance(course, str) and course and course != ALL_COURSES else None


class ToolGateway:
    """Stateless apart from its collaborators; safe to share across turns."""

    def __init__(
        self,
        executor: Executor,
        *,
        directory: ScopeDirectory | None = None,
        objects: ObjectDirectory | None = None,
        access_log: AccessLog | None = None,
        turns: TurnRepository | None = None,
        manifests: ManifestRegistry | None = None,
        tool_roles: dict[str, ToolRoles] | None = None,
        approvals: ApprovalGate | None = None,
        turn_status: TurnStatusSink | None = None,
        approval_timeout: float | None = None,
        provenance: ProvenanceRecorder | None = None,
    ) -> None:
        """`approval_timeout` is in seconds; defaults to APPROVAL_TIMEOUT_MINUTES (30)."""
        self._executor = executor
        self._directory = directory
        self._objects = objects
        self._access_log = access_log
        self._turns = turns
        self._manifests = manifests
        self._tool_roles = tool_roles
        self._approvals = approvals
        self._turn_status = turn_status
        self._approval_timeout = approval_timeout
        self._provenance = provenance
        self.drafts = DraftLedger()

    async def invoke(
        self, ctx: GatewayContext, agent: str, tool: str, args: dict[str, Any],
        *, call_id: str = "",
    ) -> ToolResult:
        """Raises BudgetExceededError (call not executed or recorded) when over a cap, and
        ApprovalTimeoutError when a gated call is not decided in time. `call_id` (the model's
        tool-use id) makes provenance writes idempotent per tool call."""
        start = time.monotonic()
        current = dict(args)
        try:
            manifest = self._check_allow_list(agent, tool)
            auth = self._check_permission(ctx, tool)
            self._check_background(ctx, agent, tool, current)
            purpose = _purpose(agent, tool)
            current = await self._apply_identity(auth, tool, current, purpose)
            current = self._bind_student_session(auth, tool, current, ctx.session_id)
            await self._check_objects(auth, tool, current, ctx.session_id, purpose)
            if tool == COMMIT_TOOL:
                current = without_instructor_inputs(current)
            if ctx.arg_filter is not None:
                current = self._filtered(ctx, tool, current)
        except ToolDenied as denied:
            result = self._denied(ctx, agent, tool, current, denied, start)
            await self._record(ctx, agent, tool, result)
            return result

        approval: dict[str, Any] | None = None
        proposed = current
        if self.requires_approval(tool, current):
            held = await self._hold_for_approval(ctx, manifest, agent, tool, current, start)
            if isinstance(held, ToolResult):
                if held.approval is not None and held.approval.get("decision") == "reject":
                    await self._provenance_rejected(ctx, agent, tool, proposed, held, call_id)
                return held
            current, approval = held
            start = time.monotonic()  # latency_ms is the call's, not the person's wait

        self.charge(ctx, agent, tool_calls=1)

        try:
            raw = await self._executor(tool, current)
        except Exception:
            await self._record(ctx, agent, tool, ToolResult(
                "", "error", current, (time.monotonic() - start) * 1000, approval=approval))
            raise
        outcome: ToolCallOutcome = "error" if _looks_like_error(raw) else "ok"
        if outcome == "ok":
            raw = withhold_private_in_result(tool, current, raw, auth.person_id)
            self.drafts.record_result(tool, auth.person_id, current, raw)
        text, summary, value = self._guard_result(ctx, manifest, tool, raw)
        result = ToolResult(text, outcome, current, (time.monotonic() - start) * 1000,
                            summary=summary, approval=approval,
                            value=value if outcome == "ok" else None)
        await self._record(ctx, agent, tool, result)
        if outcome == "ok":
            await self._provenance_succeeded(ctx, agent, tool, proposed, result, raw, call_id)
        return result

    @staticmethod
    def _filtered(ctx: GatewayContext, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        assert ctx.arg_filter is not None
        out = ctx.arg_filter(ctx, tool, dict(args))
        if identity_paths(out) != identity_paths(args):
            raise ScopeDenied("An argument filter can't change which record this applies to.")
        return out

    # --- provenance write points (spec.md §6.4) ------------------------------------------

    def _facts(self, ctx: GatewayContext, agent: str, tool: str, proposed: dict[str, Any],
               result: ToolResult, parsed: dict[str, Any] | None, call_id: str
               ) -> ToolCallFacts:
        assert ctx.auth is not None
        return ToolCallFacts(
            agent=agent, tool=tool, call_key=call_key(ctx.turn_id, call_id, tool, proposed),
            requester_id=ctx.auth.person_id, args=result.args, proposed=proposed,
            result=parsed, session_id=ctx.session_id, turn_id=ctx.turn_id,
            course_id=ctx.course_id, approval=result.approval, trail=ctx.provenance,
        )

    async def _provenance_succeeded(
        self, ctx: GatewayContext, agent: str, tool: str, proposed: dict[str, Any],
        result: ToolResult, raw: str, call_id: str,
    ) -> None:
        parsed = parse_object(raw)
        if ctx.provenance is not None:
            ctx.provenance.observe(tool, result.args, parsed)
        if self._provenance is None:
            return
        facts = self._facts(ctx, agent, tool, proposed, result, parsed, call_id)
        await self._provenance.tool_succeeded(facts, self._submission_facts)
        _collect_actions(ctx, facts)

    async def _provenance_rejected(
        self, ctx: GatewayContext, agent: str, tool: str, proposed: dict[str, Any],
        result: ToolResult, call_id: str,
    ) -> None:
        if self._provenance is not None:
            facts = self._facts(ctx, agent, tool, proposed, result, None, call_id)
            await self._provenance.tool_rejected(facts)
            _collect_actions(ctx, facts)

    async def _submission_facts(self, submission_id: str) -> tuple[str | None, str | None]:
        """(author, course) of a submission; either is None when it cannot be resolved."""
        submission = await self._read("assessments.get_submission",
                                      {"submission_id": submission_id}) or {}
        owner = submission.get("person_id")
        return (owner if isinstance(owner, str) else None,
                await self._submission_course(submission_id))

    # --- step 5: write-gate ---------------------------------------------------------------

    def requires_approval(self, tool: str, args: dict[str, Any]) -> bool:
        """`Requires approval: true` in contracts/mcp-tools.md.

        `assessments.create_question` is gated only when it publishes to a live bank. Every
        bank it writes is treated as live: practice items are saved by
        `content.generate_practice`, never through this tool, and banks carry no live flag.
        """
        roles = (self._tool_roles or get_tool_roles()).get(tool)
        return roles is not None and roles.requires_approval

    async def _hold_for_approval(
        self,
        ctx: GatewayContext,
        manifest: AgentManifest,
        agent: str,
        tool: str,
        args: dict[str, Any],
        start: float,
    ) -> ToolResult | tuple[dict[str, Any], dict[str, Any]]:
        """Suspend until a person decides. Returns (approved args, approval record), or the
        tool result the model gets when the call is rejected or cannot be gated."""
        if self._approvals is None or ctx.emit is None or ctx.auth is None:
            log.warning("approval_unavailable", agent=agent, tool=tool, turn_id=ctx.turn_id)
            result = self._denied(ctx, agent, tool, args, PermissionDenied(APPROVAL_UNAVAILABLE),
                                  start)
            await self._record(ctx, agent, tool, result)
            return result

        approvals = self._approvals
        request = approvals.create_request(
            step_id=ctx.step_id,
            agent=agent,
            action=_ACTIONS.get(tool, f"Run {tool}"),
            preview=await self._preview(ctx, manifest, tool, args),
            artifact_type=artifact_type_for(tool),
            tool_name=tool,
            tool_arguments=args,
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            course_id=ctx.course_id,
            requester_id=ctx.auth.person_id,
        )
        approval_id = request.approval_id
        await self._record(ctx, agent, tool, ToolResult(
            "", "gated", {**args, "approval_id": approval_id}, (time.monotonic() - start) * 1000))
        log.info("approval_requested", agent=agent, tool=tool, turn_id=ctx.turn_id,
                 approval_id=approval_id)

        await self._set_status(ctx, "awaiting_approval")
        try:
            await ctx.emit({"event": "approval_request",
                            "payload": approvals.to_event_payload(request)})
            with ExitStack() as paused:
                for clock in (ctx.budget.clock if ctx.budget else None, ctx.agent_clock):
                    if clock is not None:
                        paused.enter_context(clock.pause())
                resolution = await approvals.wait(approval_id, self._timeout_s())
        except BaseException:
            approvals.discard(approval_id)
            log.warning("approval_abandoned", agent=agent, tool=tool, turn_id=ctx.turn_id,
                        approval_id=approval_id)
            raise
        finally:
            await self._set_status(ctx, "active")

        decision = resolution.decision.decision
        approver_id = resolution.approver.person_id if resolution.approver else ""
        record = {"approval_id": approval_id, "decision": decision, "approved_by": approver_id}
        log.info("approval_resolved", agent=agent, tool=tool, turn_id=ctx.turn_id,
                 approval_id=approval_id, decision=decision, approved_by=approver_id)
        if decision == "reject" or resolution.approver is None:
            text = json.dumps({"error": "rejected", "reason": REJECTED_REASON})
            rejected = ToolResult(text, "gated", args, (time.monotonic() - start) * 1000,
                                  summary=text[:SUMMARY_CHARS], approval=record)
            await self._record(ctx, agent, tool, rejected)
            return rejected
        # POST /api/approval checks this before resolving; repeated so no caller of
        # ApprovalGate.resolve can skip it.
        try:
            approved = await self.authorize_approver(
                request, resolution.approver, dict(resolution.tool_arguments))
        except ToolDenied as denied:
            result = self._denied(ctx, agent, tool, args, denied, start)
            await self._record(ctx, agent, tool, result)
            return result
        return approved, record

    async def authorize_approver(
        self, request: ApprovalRequest, approver: AuthContext, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Re-check on resume, as if the approver had made the call: allow-list, role,
        identity, object-level scope and the course. Raises EditRejected when `args` change
        an identity key or add an undeclared one, else ToolDenied; returns `args` with
        identity rules applied for the approver (requester and reviewer ids become theirs)."""
        tool = request.tool_name
        self._check_edit(request, args)
        self._check_allow_list(request.agent, tool)
        self._check_role(approver, tool)
        purpose = _purpose(request.agent, tool)
        out = await self._apply_identity(approver, tool, args, purpose)
        for key in APPROVER_ARGS:
            if key in out:
                out[key] = approver.person_id
        await self._check_objects(approver, tool, out, request.session_id, purpose)
        course = await self._approval_course(request, out)
        if not await self._covers_course(approver, course):
            record_access(approver, request.requester_id, course, f"approve:{tool}", False)
            raise ScopeDenied("Only staff of this course can approve this action.")
        if tool == COMMIT_TOOL:
            try:
                out = check_commit(out, await self._commit_criteria(out))
            except CommitIncompleteError as incomplete:
                raise EditRejected(str(incomplete)) from None
        return out

    async def _commit_criteria(self, args: dict[str, Any]) -> list[str]:
        """The criteria a commit of this draft must score; [] when neither the draft nor its
        rubric names any."""
        draft = self.drafts.get("grade", args.get("grade_id"))
        if draft is None:
            return []
        rubric_id = draft.args.get("rubric_id")
        rubric = (await self._read("assessments.get_rubric", {"rubric_id": rubric_id})
                  if isinstance(rubric_id, str) and rubric_id else None)
        return criterion_keys(draft.args.get("scores"), rubric)

    async def _approval_course(
        self, request: ApprovalRequest, args: dict[str, Any]
    ) -> str | None:
        """The course of the object the action changes, else its course_id argument, else
        the session's course."""
        found = await self._object_course(request.tool_name, args)
        return found or _course_arg(args) or _course_arg({"course_id": request.course_id})

    async def _object_course(self, tool: str, args: dict[str, Any]) -> str | None:
        if tool == "assessments.approve_credential":
            pending_id = args.get("pending_id")
            if isinstance(pending_id, str) and self._directory is not None:
                return await self._directory.pending_credential_course(pending_id)
        elif tool == "assessments.commit_grade":
            draft = self.drafts.get("grade", args.get("grade_id"))
            submission_id = draft.args.get("submission_id") if draft else None
            if isinstance(submission_id, str) and submission_id:
                return await self._submission_course(submission_id)
        elif tool == BANK_TOOL:
            return await self._bank_course(args.get("bank_id"))
        return None

    async def _submission_course(self, submission_id: str) -> str | None:
        if self._objects is None:
            log.warning("object_directory_unavailable", object="submission")
            return None
        return await self._objects.submission_course(submission_id)

    async def _check_course_objects(self, auth: AuthContext, tool: str, args: dict[str, Any],
                                    purpose: str) -> None:
        """Every id in COURSE_OBJECT_TOOLS[tool] must resolve to a course the caller may act
        in; an id that resolves to nothing is refused for everyone but admin."""
        if auth.active_role == "admin":
            return
        arg, kind = COURSE_OBJECT_TOOLS[tool]
        value = args.get(arg)
        ids = value if isinstance(value, list) else [value]
        if not ids or not all(isinstance(v, str) and v for v in ids):
            raise ScopeDenied(f"{arg} must name {kind} ids.")
        if self._objects is None:
            log.warning("object_directory_unavailable", object=kind)
            raise ScopeDenied(UNRESOLVED)
        for item in ids:
            course = (await self._objects.criterion_course(item) if kind == "criterion"
                      else await self._objects.node_course(item))
            if course is None:
                raise ScopeDenied(UNRESOLVED)
            await self._check_course(auth, course, purpose)

    async def _bank_course(self, bank_id: Any) -> str | None:
        if not isinstance(bank_id, str) or not bank_id:
            return None
        if self._objects is None:
            log.warning("object_directory_unavailable", object="question_bank")
            return None
        return await self._objects.question_bank_course(bank_id)

    async def _covers_course(self, approver: AuthContext, course: str | None) -> bool:
        """Admin always; otherwise the course must be known and taught (or, for an advisor,
        have one of their advisees enrolled)."""
        if approver.active_role == "admin":
            return True
        if course is None:
            return False
        if approver.active_role == "advisor":
            if self._directory is None:
                return False
            return course in await self._directory.course_ids_with_students(
                approver.advisee_ids)
        return is_course_staff(approver, course)

    def _check_edit(self, request: ApprovalRequest, args: dict[str, Any]) -> None:
        if identity_paths(args) != identity_paths(request.original_arguments):
            raise EditRejected("An edit can't change which record or person this action "
                               "applies to.")
        roles = (self._tool_roles or get_tool_roles()).get(request.tool_name)
        declared = roles.input_keys if roles else frozenset()
        unknown = set(args) - declared - set(request.original_arguments)
        if request.tool_name == COMMIT_TOOL:
            unknown -= INSTRUCTOR_INPUTS
        if declared and unknown:
            raise EditRejected(f"An edit can't add {', '.join(sorted(unknown))}.")

    # --- approval preview: the drafted artifact, guarded like a tool result -------------

    async def _preview(
        self, ctx: GatewayContext, manifest: AgentManifest, tool: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        preview: dict[str, Any] = {"tool": tool, "arguments": args}
        artifact = await self._artifact(tool, args)
        if artifact:
            preview["artifact"] = artifact
        redaction = scan_and_redact_result(
            preview,
            allowed_fields=manifest.requires_pii,
            requester_id=ctx.auth.person_id if ctx.auth else None,
            requester_name=ctx.auth.display_name if ctx.auth else None,
        )
        wrapped = wrap_tool_value(tool, redaction.value)
        return wrapped if isinstance(wrapped, dict) else preview

    async def _artifact(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """What the approver is shown; reads run after the object-level scope check passed.
        A part that cannot be loaded is replaced by a `details_unavailable` note."""
        if tool == "assessments.commit_grade":
            return await self._grade_artifact(args)
        if tool == "communications.send_message":
            return await self._message_artifact(args)
        if tool == "assessments.approve_credential":
            return await self._credential_artifact(args)
        if tool == "assessments.create_question":
            keys = ("bank_id", "type", "stem", "options", "answer_key", "bloom_level",
                    "difficulty", "aligned_nodes")
            return {"question": {k: args[k] for k in keys if k in args}}
        return {}

    async def _grade_artifact(self, args: dict[str, Any]) -> dict[str, Any]:
        draft = self.drafts.get("grade", args.get("grade_id"))
        if draft is None:
            return {"details_unavailable": "The draft grade could not be loaded."}
        keys = ("submission_id", "rubric_id", "scores", "feedback", "holistic_md")
        out: dict[str, Any] = {
            "grade": {"grade_id": draft.object_id,
                      **{k: draft.args[k] for k in keys if k in draft.args}},
            # What the approver's edit must carry (POST /api/approval rejects it otherwise).
            "requires": {"final_scores": await self._commit_criteria(args),
                         "holistic_md": True},
        }
        submission = await self._read("assessments.get_submission",
                                      {"submission_id": draft.args.get("submission_id")})
        if submission is None:
            out["details_unavailable"] = "The submission could not be loaded."
            return out
        out["submission"] = {"id": submission.get("id"),
                             "assignment_node": submission.get("assignment_node"),
                             "submitted_at": submission.get("submitted_at")}
        student_id = submission.get("person_id")
        person = await self._read("roster.get", {"person_id": student_id})
        out["student"] = {"person_id": student_id,
                          "display_name": person.get("display_name") if person else None,
                          "roles": ["student"]}
        return out

    async def _message_artifact(self, args: dict[str, Any]) -> dict[str, Any]:
        draft = self.drafts.get("message", args.get("draft_id"))
        if draft is None:
            return {"details_unavailable": "The draft message could not be loaded."}
        keys = ("channel", "audience", "subject", "body_md", "scheduled_for")
        out: dict[str, Any] = {
            "message": {"draft_id": draft.object_id,
                        **{k: draft.args[k] for k in keys if k in draft.args}},
        }
        count = await self._recipient_count(draft.args.get("audience"))
        out["recipient_count"] = count
        if count is None:
            out["details_unavailable"] = "The number of recipients could not be determined."
        return out

    async def _recipient_count(self, audience: Any) -> int | None:
        if isinstance(audience, list):
            return len(audience)
        if not isinstance(audience, dict):
            return None
        people = audience.get("person_ids")
        if isinstance(people, list) and people:
            return len(people)
        course = _course_arg(audience)
        if course is None:
            return None
        query: dict[str, Any] = {"course_id": course}
        if isinstance(audience.get("role"), str):
            query["role"] = audience["role"]
        listed = await self._read("roster.list_by_course", query)
        persons = listed.get("persons") if listed else None
        return len(persons) if isinstance(persons, list) else None

    async def _credential_artifact(self, args: dict[str, Any]) -> dict[str, Any]:
        evidence = await self._read("assessments.get_credential_evidence",
                                    {"pending_id": args.get("pending_id")})
        if evidence is None:
            return {"details_unavailable": "The pending credential could not be loaded."}
        concepts = evidence.get("concepts")
        concepts = concepts if isinstance(concepts, list) else []
        levels: dict[str, int] = {}
        for concept in concepts:
            level = concept.get("level") if isinstance(concept, dict) else None
            key = level if isinstance(level, str) else "none"
            levels[key] = levels.get(key, 0) + 1
        return {
            "credential": {k: evidence.get(k) for k in
                           ("pending_id", "credential_title", "student_name", "created_at")},
            "evidence": {"session_count": evidence.get("session_count"),
                         "concept_count": len(concepts), "levels": levels,
                         "concepts": concepts},
        }

    async def _read(self, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
        """A read the gateway itself makes; None (logged) when it fails or returns an error."""
        try:
            raw = await self._executor(tool, args)
        except Exception:
            log.warning("gateway_read_failed", tool=tool, exc_info=True)
            return None
        data = parse_object(raw)
        if data is None or "error" in data:
            log.warning("gateway_read_unusable", tool=tool)
            return None
        return data

    def _timeout_s(self) -> float:
        return self._approval_timeout if self._approval_timeout is not None \
            else approval_timeout_s()

    async def _set_status(self, ctx: GatewayContext, status: str) -> None:
        if self._turn_status is not None and ctx.turn_id:
            await self._turn_status.update_status(ctx.turn_id, status)

    # --- step 6: budget ------------------------------------------------------------------

    def charge(
        self,
        ctx: GatewayContext,
        agent: str,
        *,
        tokens: int = 0,
        tool_calls: int = 0,
        agent_invocations: int = 0,
    ) -> None:
        """Charge the turn budget; raises BudgetExceededError once any cap is passed."""
        if ctx.budget is None:
            return
        check = ctx.budget.charge(
            tokens=tokens, tool_calls=tool_calls, agent_invocations=agent_invocations,
        )
        if check.exceeded:
            log.warning("budget_exceeded", agent=agent, turn_id=ctx.turn_id,
                        step_id=ctx.step_id, reason=check.reason, **ctx.budget.summary())
            raise BudgetExceededError(check.reason)

    # --- steps 8 and 9: PII, then injection wrapping --------------------------------------

    def _guard_result(
        self, ctx: GatewayContext, manifest: AgentManifest, tool: str, raw: str
    ) -> tuple[str, str, Any]:
        """(model text, event summary, redacted value). JSON objects and arrays keep their
        shape; other text is wrapped whole; JSON numbers, booleans and null pass through."""
        try:
            parsed: Any = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            parsed = raw
        if not isinstance(parsed, (str, dict, list)):
            return raw, raw[:SUMMARY_CHARS], parsed
        redaction = scan_and_redact_result(
            parsed,
            allowed_fields=manifest.requires_pii,
            requester_id=ctx.auth.person_id if ctx.auth else None,
            requester_name=ctx.auth.display_name if ctx.auth else None,
        )
        if redaction.pseudonymized or redaction.redacted:
            log.info("tool_result_pii_redacted", agent=manifest.name, tool=tool,
                     turn_id=ctx.turn_id, pseudonymized=redaction.pseudonymized,
                     redacted=redaction.redacted)
        value = redaction.value
        if isinstance(value, str):
            return wrap_user_content(value, source_for_tool(tool)), value[:SUMMARY_CHARS], value
        summary = json.dumps(value, ensure_ascii=False, default=str)[:SUMMARY_CHARS]
        wrapped = json.dumps(wrap_tool_value(tool, value), ensure_ascii=False, default=str)
        return wrapped, summary, value

    def redact_context(self, agent: str, text: str) -> str:
        """Outgoing prompt text (the user's message, history): PII patterns only, no names."""
        if not text:
            return text
        return scan_and_redact(text, allowed_fields=self._manifest(agent).requires_pii).text

    # --- step 1: allow-list --------------------------------------------------------------

    def _manifest(self, agent: str) -> AgentManifest:
        """Raises KeyError for an agent with no manifest."""
        return (self._manifests or get_manifest_registry()).get_manifest(agent)

    def _check_allow_list(self, agent: str, tool: str) -> AgentManifest:
        try:
            manifest = self._manifest(agent)
        except KeyError:
            raise PermissionDenied(f"The {agent} assistant has no tool list.") from None
        if manifest.status == "planned" or tool not in manifest.mcp_tools:
            raise PermissionDenied(f"{tool} is not one of this assistant's tools.")
        return manifest

    # --- step 2: role permission ---------------------------------------------------------

    def _check_permission(self, ctx: GatewayContext, tool: str) -> AuthContext:
        if ctx.auth is None:
            raise PermissionDenied("Tools need a signed-in requester.")
        self._check_role(ctx.auth, tool)
        # A chat turn could otherwise overwrite feedback awaiting instructor review.
        if ctx.background_feedback is None and tool in LEARNER_BACKGROUND_TOOLS:
            raise PermissionDenied("Feedback is generated after you submit, not in chat.")
        return ctx.auth

    @staticmethod
    def _check_background(ctx: GatewayContext, agent: str, tool: str,
                          args: dict[str, Any]) -> None:
        """Background agents run only in their flow; a feedback run reads and writes only the
        submission it was started for, and lists only that assignment's versions."""
        bound = ctx.background_feedback
        if bound is None:
            if agent in BACKGROUND_AGENTS:
                raise PermissionDenied("Feedback is generated after you submit, not in chat.")
            return
        if tool in BOUND_SUBMISSION_TOOLS and args.get("submission_id") != bound.submission_id:
            raise ScopeDenied("This feedback run covers one submission only.")
        if tool == SUBMISSION_LIST_TOOL and args.get("assignment_node") != bound.assignment_id:
            raise ScopeDenied("This feedback run covers one assignment only.")

    def _check_role(self, auth: AuthContext, tool: str) -> None:
        roles = (self._tool_roles or get_tool_roles()).get(tool)
        if roles is None or auth.active_role not in roles.allowed_roles:
            raise PermissionDenied(f"{tool} is not available to the {auth.active_role} role.")

    # --- step 3: identity and scope (spec.md §4.5) ---------------------------------------

    async def _apply_identity(
        self, auth: AuthContext, tool: str, args: dict[str, Any], purpose: str
    ) -> dict[str, Any]:
        """Requester, author and grader ids are always the caller (requester_id is added when
        the tool's contract declares it); a student's attestation
        carries no issuer, anyone else's carries the caller. A student's subject id is forced
        to self (a different non-empty value is refused, not rewritten; an omitted one that
        the tool's contract declares is added). Courses and other
        learners are scope-checked; `scope` (analytics.query) is checked the same way."""
        out = dict(args)
        roles = (self._tool_roles or get_tool_roles()).get(tool)
        declared = roles.input_keys if roles else frozenset()
        for key in (REQUESTER_ARG, AUTHOR_ARG, GRADER_ARG):
            if key in out:
                out[key] = auth.person_id
        # Servers mask or refuse by requester_id, so it is sent even when the model omits it.
        if REQUESTER_ARG in declared:
            out[REQUESTER_ARG] = auth.person_id
        if ISSUER_ARG in out:
            if auth.active_role == "student":
                del out[ISSUER_ARG]
            else:
                out[ISSUER_ARG] = auth.person_id
        if auth.active_role == "student":
            # A tool whose contract takes a subject id must not run without one for a
            # student, or a tool that defaults to "everyone" would answer for other learners.
            for key in SUBJECT_ARGS:
                if key in declared and key not in out:
                    out[key] = auth.person_id
        elif tool == SUBMISSION_LIST_TOOL and out.get("person_id") in (None, ""):
            # Staff may list every learner's submissions; _check_objects bounds it by course.
            out.pop("person_id", None)
        if tool == AUDIENCE_TOOL and "audience" in out:
            out["audience"] = _parse_audience(out["audience"])
        tree = await self._scope_tree(auth, out, None, purpose, self._profile_read(tool))
        assert isinstance(tree, dict)
        return tree

    async def _scope_tree(
        self, auth: AuthContext, value: Any, outer_course: str | None, purpose: str,
        read: SensitiveRead | None = None,
    ) -> Any:
        """Scope-check identity keys at every depth; a nested dict inherits the nearest
        enclosing course_id. `read` is logged for the top-level subject only."""
        if isinstance(value, list):
            return [await self._scope_tree(auth, item, outer_course, purpose)
                    for item in value]
        if not isinstance(value, dict):
            return value
        out = await self._scope_subjects(auth, value, outer_course, purpose, read)
        course = _course_arg(out) or outer_course
        for key, item in out.items():
            if key not in SUBJECT_LIST_ARGS and isinstance(item, (dict, list)):
                out[key] = await self._scope_tree(auth, item, course, purpose)
        return out

    async def _scope_subjects(
        self, auth: AuthContext, args: dict[str, Any], outer_course: str | None, purpose: str,
        read: SensitiveRead | None = None,
    ) -> dict[str, Any]:
        out = dict(args)
        course = _course_arg(out) or outer_course
        for key in SUBJECT_ARGS:
            if key not in out:
                continue
            value = out[key]
            if auth.active_role == "student":
                if value not in (None, "", auth.person_id):
                    record_access(auth, str(value), course, purpose, False)
                    raise ScopeDenied("Students can only look up their own records.")
                out[key] = auth.person_id
                continue
            if not isinstance(value, str) or not value:
                raise ScopeDenied(f"{key} must name one learner.")
            if not await self._can_view(auth, value, course, purpose, read):
                raise ScopeDenied("That learner is outside this account's access.")
        for key in SUBJECT_LIST_ARGS:
            if out.get(key) is None:
                continue
            values = out[key]
            if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
                raise ScopeDenied(f"{key} must list learners by id.")
            for value in values:
                if auth.active_role == "student" and value != auth.person_id:
                    record_access(auth, value, course, purpose, False)
                    raise ScopeDenied("Students can only look up their own records.")
                if not await self._can_view(auth, value, course, purpose):
                    raise ScopeDenied("That learner is outside this account's access.")
        if COURSE_ARG in out:
            await self._check_course(auth, out[COURSE_ARG], purpose)
        return out

    async def _check_course(self, auth: AuthContext, value: Any, purpose: str) -> None:
        """Raises ScopeDenied unless the caller may act in this course (spec.md §4.4): the
        courses they could open a session in. An empty value names no course."""
        if value in (None, ""):
            return
        if not isinstance(value, str):
            raise ScopeDenied("course_id must name one course.")
        if value == ALL_COURSES:
            if auth.active_role in _CROSS_COURSE_ROLES:
                return
            log.warning("course_scope_denied", tool_purpose=purpose, course_id=value,
                        active_role=auth.active_role, requester_id=auth.person_id)
            raise ScopeDenied("Only advisors and admins can query across all courses.")
        if auth.active_role == "admin":
            return
        if self._directory is None:
            log.warning("scope_directory_unavailable", tool_purpose=purpose)
            raise ScopeDenied("That course is outside this account's access.")
        allowed = await actable_course_ids(auth, self._directory)
        if allowed is None or value in allowed:
            return
        ref = await self._directory.resolve_course(value)
        if ref is not None and ref.id in allowed:
            return
        log.warning("course_scope_denied", tool_purpose=purpose, course_id=value,
                    active_role=auth.active_role, requester_id=auth.person_id)
        raise ScopeDenied("That course is outside this account's access.")

    # --- step 3, object level: tools keyed by an id other than a person or course ---------

    async def _check_objects(
        self, auth: AuthContext, tool: str, args: dict[str, Any], current_session: str,
        purpose: str,
    ) -> None:
        """Raises ScopeDenied unless the object the call names belongs to someone (or a
        course) the caller may act on. `current_session` is the caller's own session."""
        nested = _nested_object_keys(args)
        if nested:
            raise ScopeDenied(f"{nested[0]} must be a top-level argument.")
        if tool in SUBMISSION_TOOLS:
            await self._check_submission(auth, args.get("submission_id"), purpose,
                                         self._object_read(tool, args))
        elif tool == "assessments.commit_grade":
            draft = self.drafts.get("grade", args.get("grade_id"))
            if draft is None:
                raise ScopeDenied(UNKNOWN_DRAFT)
            await self._check_submission(auth, draft.args.get("submission_id"), purpose)
        elif tool == "communications.send_message":
            draft = self.drafts.get("message", args.get("draft_id"))
            if draft is None:
                raise ScopeDenied(UNKNOWN_DRAFT)
            if draft.author_id != auth.person_id:
                raise ScopeDenied("Only the person who drafted this message can send it.")
        elif tool in PENDING_TOOLS:
            await self._check_pending(auth, tool, args.get("pending_id"), purpose)
        elif tool in CONCEPT_WRITE_TOOLS:
            await self._check_node(auth, args.get("concept_id"), purpose, "concept_id")
        elif tool in NODE_WRITE_TOOLS and args.get("node_id") not in (None, ""):
            await self._check_node(auth, args.get("node_id"), purpose, "node_id")
        elif tool == AUDIENCE_TOOL:
            await self._check_audience(auth, args.get("audience"), purpose)
        elif tool in ANALYTICS_TOOLS:
            await self._check_analytics_scope(auth, tool, args, purpose)
        elif tool == SUBMISSION_LIST_TOOL and not args.get(COURSE_ARG) \
                and auth.active_role not in ("admin", "student"):
            # Without a course the server lists the learner's (or, with no person_id, every
            # learner's) submissions in every course; course_id is what gets scope-checked.
            raise ScopeDenied("Listing submissions needs the course.")
        elif tool == BANK_TOOL:
            course = await self._bank_course(args.get("bank_id"))
            if course is None:
                raise ScopeDenied(UNRESOLVED)
            await self._check_course(auth, course, purpose)
        elif tool == GRADING_STATUS_TOOL and not args.get(COURSE_ARG) \
                and auth.active_role != "admin":
            raise ScopeDenied("Grading status needs the course.")
        elif tool in COURSE_OBJECT_TOOLS:
            await self._check_course_objects(auth, tool, args, purpose)
        if tool not in SESSION_EXEMPT_TOOLS and (
                "session_id" in args or tool in SESSION_REQUIRED_TOOLS):
            await self._check_session(auth, tool, args.get("session_id"), current_session,
                                      purpose, self._object_read(tool, args))

    @staticmethod
    def _bind_student_session(auth: AuthContext, tool: str, args: dict[str, Any],
                              current_session: str) -> dict[str, Any]:
        """A student's attest or concept review always names their current session."""
        if auth.active_role != "student" or tool not in STUDENT_SESSION_TOOLS:
            return args
        if not current_session:
            raise ScopeDenied("This action needs the current session.")
        return {**args, "session_id": current_session}

    async def _check_analytics_scope(self, auth: AuthContext, tool: str,
                                     args: dict[str, Any], purpose: str) -> None:
        """Every scope the server filters by (the top level, or for cohort_compare each cohort
        merged over it) must name a course for faculty and an advisee for advisors. Ids were
        already scope-checked; they are re-checked here against the merged course."""
        if auth.active_role == "admin":
            return
        top = args.get("scope", {})
        if not isinstance(top, dict):
            raise ScopeDenied("scope must be an object naming a course or learner.")
        scopes = [top]
        if tool == "analytics.cohort_compare":
            cohorts = args["cohorts"]
            if not isinstance(cohorts, list) or not cohorts:
                raise ScopeDenied("cohorts must list objects with a scope.")
            scopes = []
            for cohort in cohorts:
                inner = cohort.get("scope", {}) if isinstance(cohort, dict) else None
                if not isinstance(inner, dict):
                    raise ScopeDenied("cohorts must list objects with a scope.")
                scopes.append({**top, **inner})
        for scope in scopes:
            course = _course_arg(scope)
            person = scope.get("person_id")
            if person in (None, ""):
                person = None
            if auth.active_role == "advisor" and person is None:
                raise ScopeDenied("Advisors can query analytics only for a named advisee.")
            if auth.active_role != "advisor" and course is None:
                raise ScopeDenied("Analytics queries must name a course.")
            if course is not None:
                await self._check_course(auth, course, purpose)
            if person is not None and (not isinstance(person, str)
                                       or not await self._can_view(auth, person, course,
                                                                   purpose)):
                raise ScopeDenied("That learner is outside this account's access.")

    def _profile_read(self, tool: str) -> SensitiveRead | None:
        entry = SENSITIVE_READS.get(tool)
        if entry is None or entry[1] is not None:
            return None
        return SensitiveRead(self._access_log, entry[0])

    def _object_read(self, tool: str, args: dict[str, Any]) -> SensitiveRead | None:
        entry = SENSITIVE_READS.get(tool)
        if entry is None or entry[1] is None:
            return None
        object_id = args.get(entry[1])
        return SensitiveRead(self._access_log, entry[0],
                             object_id if isinstance(object_id, str) else None)

    async def _check_submission(self, auth: AuthContext, submission_id: Any,
                                purpose: str, read: SensitiveRead | None = None) -> None:
        """The submission must be the caller's own, or its author viewable through the
        submission's course; an unresolved course is refused for everyone but admins."""
        if not isinstance(submission_id, str) or not submission_id:
            raise ScopeDenied("submission_id must name one submission.")
        submission = await self._read("assessments.get_submission",
                                      {"submission_id": submission_id}) or {}
        owner = submission.get("person_id")
        if not isinstance(owner, str) or not owner:
            raise ScopeDenied(UNRESOLVED)
        if owner == auth.person_id:
            return
        if auth.active_role == "admin":
            record_access(auth, owner, None, purpose, True)
            if read is not None:
                await record_sensitive_read(auth, owner, purpose, read)
            return
        course = await self._submission_course(submission_id)
        if course is None:
            record_access(auth, owner, None, purpose, False)
            raise ScopeDenied(UNRESOLVED)
        if not await self._can_view(auth, owner, course, purpose, read):
            raise ScopeDenied("That submission is outside this account's access.")

    async def _check_pending(self, auth: AuthContext, tool: str, pending_id: Any,
                             purpose: str) -> None:
        """Approving needs faculty of the credential's course or an admin, as on
        /api/approve-credential; reading the evidence needs scope over the learner."""
        if auth.active_role == "admin":
            return
        if not isinstance(pending_id, str) or not pending_id or self._directory is None:
            raise ScopeDenied(UNRESOLVED)
        course = await self._directory.pending_credential_course(pending_id)
        if course is None:
            raise ScopeDenied(UNRESOLVED)
        if tool == "assessments.approve_credential":
            if not is_course_staff(auth, course):
                record_access(auth, "", course, purpose, False)
                raise ScopeDenied("Only faculty of this course or an admin can approve "
                                  "credentials.")
            return
        await self._check_course(auth, course, purpose)
        listed = await self._read("assessments.list_pending_credentials",
                                  {"course_id": course})
        pending = listed.get("pending") if listed else None
        owner = next((p.get("person_id") for p in pending or []
                      if isinstance(p, dict) and p.get("id") == pending_id), None)
        if not isinstance(owner, str) or not await self._can_view(auth, owner, course, purpose):
            raise ScopeDenied(UNRESOLVED)

    async def _check_session(self, auth: AuthContext, tool: str, session_id: Any,
                             current_session: str, purpose: str,
                             read: SensitiveRead | None = None) -> None:
        if session_id in (None, ""):
            if tool in SESSION_REQUIRED_TOOLS:
                raise ScopeDenied("session_id must name one session.")
            return
        if not isinstance(session_id, str):
            raise ScopeDenied("session_id must name one session.")
        if current_session and session_id == current_session:
            return
        if self._directory is None:
            log.warning("scope_directory_unavailable", tool_purpose=purpose)
            raise ScopeDenied(UNRESOLVED)
        owner = await self._directory.session_owner(session_id)
        if owner is None or not await self._can_view(auth, owner.person_id, owner.course_id,
                                                     purpose, read):
            raise ScopeDenied("That session is outside this account's access.")

    async def _check_node(self, auth: AuthContext, node_id: Any, purpose: str,
                          arg: str) -> None:
        """A content write on a graph node needs a course the caller may act in: the node
        itself as a course, or its part_of chain (concept or skill, module, course)."""
        if auth.active_role == "admin":
            return
        if not isinstance(node_id, str) or not node_id:
            raise ScopeDenied(f"{arg} must name one node.")
        courses: set[str] = {node_id}
        courses.update(await self._parents(node_id, "course"))
        for module in await self._parents(node_id, "module"):
            courses.update(await self._parents(module, "course"))
        for course in sorted(courses):
            try:
                await self._check_course(auth, course, purpose)
            except ScopeDenied:
                continue
            return
        raise ScopeDenied("That content is outside this account's access.")

    async def _parents(self, node_id: str, kind: str) -> list[str]:
        found = await self._read("graph.neighbors", {"node_id": node_id, "direction": "out",
                                                     "kinds": ["part_of"]})
        nodes = found.get("nodes") if found else None
        return [n["id"] for n in nodes or []
                if isinstance(n, dict) and n.get("kind") == kind and isinstance(n.get("id"), str)]

    async def _check_audience(self, auth: AuthContext, audience: Any, purpose: str) -> None:
        """Course and person ids inside the audience were scope-checked with the rest of the
        arguments; this refuses audiences that name no one (everyone) unless admin, and any
        audience from an advisor that does not name people (they message advisees only)."""
        if auth.active_role == "admin":
            return
        if isinstance(audience, list):
            if not audience or not all(isinstance(p, str) and p for p in audience):
                raise ScopeDenied("The audience must name a course or people.")
            for person in audience:
                if not await self._can_view(auth, person, None, purpose):
                    raise ScopeDenied("That learner is outside this account's access.")
            return
        if not isinstance(audience, dict):
            raise ScopeDenied("The audience must name a course or people.")
        if audience.get(COURSE_ARG) == ALL_COURSES:
            raise ScopeDenied("Only admins can message every course.")
        # communications resolves person_ids ahead of course_id, so naming them is enough.
        if auth.active_role == "advisor" and not audience.get("person_ids"):
            raise ScopeDenied("Advisors can message only advisees named in person_ids.")
        if _course_arg(audience) is None and not audience.get("person_ids"):
            raise ScopeDenied("Only admins can message everyone; name a course or people.")

    async def _can_view(
        self, auth: AuthContext, student_id: str, course: str | None, purpose: str,
        read: SensitiveRead | None = None,
    ) -> bool:
        if student_id == auth.person_id:
            return True
        if self._directory is None:
            log.warning("scope_directory_unavailable", tool_purpose=purpose)
            record_access(auth, student_id, course, purpose, False)
            return False
        return await can_view_student(
            auth, student_id, course, purpose=purpose, directory=self._directory, read=read
        )

    # --- denial and provenance (step 10) -------------------------------------------------

    def _denied(
        self,
        ctx: GatewayContext,
        agent: str,
        tool: str,
        args: dict[str, Any],
        denied: ToolDenied,
        start: float,
    ) -> ToolResult:
        log.warning(
            "tool_denied",
            kind=denied.kind,
            agent=agent,
            tool=tool,
            active_role=ctx.auth.active_role if ctx.auth else None,
            requester_id=ctx.auth.person_id if ctx.auth else None,
            turn_id=ctx.turn_id,
            reason=denied.reason,
        )
        guardrail = {
            "kind": denied.kind,
            "step_id": ctx.step_id,
            "agent": agent,
            "tool": tool,
            "reason": denied.reason,
        }
        text = json.dumps({"error": NOT_PERMITTED, "reason": denied.reason})
        return ToolResult(text, denied.kind, args, (time.monotonic() - start) * 1000, guardrail,
                          summary=text[:SUMMARY_CHARS])

    async def _record(
        self, ctx: GatewayContext, agent: str, tool: str, result: ToolResult
    ) -> None:
        """Never raises: a provenance failure is logged at ERROR and the turn continues."""
        args = {**result.args, **result.approval} if result.approval else result.args
        row = ToolCallRow(
            turn_id=ctx.turn_id,
            agent=agent,
            tool=tool,
            args=_redact_args(args),
            outcome=result.outcome,
            latency_ms=round(result.latency_ms),
        )
        persisted = False
        if self._turns is not None:
            try:
                persisted = await self._turns.record_tool_call(row)
            except Exception:
                log.error("tool_call_provenance_failed", turn_id=ctx.turn_id, agent=agent,
                          tool=tool, outcome=row.outcome, exc_info=True)
                return
        log.info("tool_call_provenance", turn_id=ctx.turn_id, agent=agent, tool=tool,
                 outcome=row.outcome, latency_ms=row.latency_ms, persisted=persisted)


def _purpose(agent: str, tool: str) -> str:
    return f"gateway:{agent}:{tool}"


def _nested_object_keys(value: Any, depth: int = 0) -> list[str]:
    """TOP_LEVEL_OBJECT_KEYS found below the top level of a tool's arguments."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if depth > 0 and key in TOP_LEVEL_OBJECT_KEYS:
                found.append(key)
            found.extend(_nested_object_keys(item, depth + 1))
    elif isinstance(value, list):
        for item in value:
            found.extend(_nested_object_keys(item, depth + 1))
    return found
