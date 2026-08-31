"""Local Streamlit presentation for the frozen BumpShield v1 engine."""

from __future__ import annotations

import html
import json
from pathlib import Path

import streamlit as st

from demo_ui.adapters import (
    LiveBumpShieldAdapter,
    TaskFormValues,
    VerificationView,
    build_task_spec,
    friendly_error,
    list_artifacts,
    load_demo_values,
    load_research_results,
    load_task_values,
    planning_to_view,
    read_artifact_text,
    repair_to_view,
    status_tone,
    task_preview,
)
from demo_ui.state import (
    form_values,
    initialize_state,
    reset_replay_state,
    reset_run_state,
    set_form_values,
)
from demo_ui.replay import (
    DEFAULT_REPLAY_BUNDLE,
    REPLAY_ROOT,
    REPLAY_SCENARIOS,
    REPLAY_STAGES,
    RecordedRunSource,
    ReplayBundleError,
)


PAGES = (
    "Overview",
    "New Migration",
    "Investigation",
    "Migration Plan",
    "Repair & Verification",
    "Evidence & Results",
)
LIVE_MODE = "Live Run"
RECORDED_MODE = "Recorded Verified Run"


st.set_page_config(
    page_title="BumpShield",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)
initialize_state(st.session_state)


def escape(value: object) -> str:
    return html.escape(str(value))


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bs-ink: #172033;
            --bs-muted: #607086;
            --bs-line: #dce3eb;
            --bs-panel: #f7f9fc;
            --bs-blue: #3158d4;
            --bs-green: #177245;
            --bs-green-bg: #eaf7f0;
            --bs-amber: #986900;
            --bs-amber-bg: #fff7dc;
            --bs-red: #ad2f2f;
            --bs-red-bg: #fff0f0;
        }
        .block-container { padding-top: 2.2rem; padding-bottom: 4rem; }
        h1, h2, h3 { color: var(--bs-ink); letter-spacing: -0.02em; }
        .bs-hero { border: 1px solid var(--bs-line); border-radius: 18px;
            padding: 2rem 2.2rem; background: linear-gradient(135deg,#f7f9ff,#fff); }
        .bs-eyebrow { color: var(--bs-blue); font-weight: 750; font-size: .78rem;
            letter-spacing: .11em; text-transform: uppercase; }
        .bs-title { font-size: 3rem; font-weight: 800; color: var(--bs-ink);
            line-height: 1.05; margin: .25rem 0 .4rem; }
        .bs-tagline { font-size: 1.35rem; color: #35435a; font-weight: 650; }
        .bs-subtitle { color: var(--bs-muted); margin-top: .45rem; }
        .bs-card { border: 1px solid var(--bs-line); border-radius: 14px;
            padding: 1.15rem 1.25rem; background: white; min-height: 100%; }
        .bs-card-title { color: var(--bs-muted); font-size: .76rem; font-weight: 750;
            letter-spacing: .08em; text-transform: uppercase; margin-bottom: .55rem; }
        .bs-card-value { color: var(--bs-ink); font-weight: 760; font-size: 1.15rem; }
        .bs-muted { color: var(--bs-muted); font-size: .9rem; }
        .bs-pill { display: inline-block; border: 1px solid var(--bs-line);
            border-radius: 999px; padding: .34rem .67rem; margin: .2rem .18rem;
            background: white; color: #344258; font-size: .8rem; font-weight: 650; }
        .bs-arrow { color: #8c99aa; padding: 0 .08rem; }
        .bs-badge { display: inline-block; border-radius: 999px; padding: .22rem .55rem;
            font-size: .72rem; font-weight: 750; letter-spacing: .04em; }
        .bs-success { color: var(--bs-green); background: var(--bs-green-bg); }
        .bs-review { color: var(--bs-amber); background: var(--bs-amber-bg); }
        .bs-failure { color: var(--bs-red); background: var(--bs-red-bg); }
        .bs-neutral { color: #58677a; background: #edf1f5; }
        .bs-chain { border-left: 3px solid #b8c5e4; margin: .5rem 0 1rem 1rem;
            padding-left: 1.1rem; }
        .bs-chain-step { border: 1px solid var(--bs-line); border-radius: 11px;
            background: white; padding: .7rem .9rem; margin: .5rem 0; }
        .bs-chain-step strong { color: var(--bs-ink); }
        .bs-final { border: 2px solid #58a77d; border-radius: 18px;
            background: var(--bs-green-bg); padding: 1.8rem; text-align: center; }
        .bs-final h2 { color: var(--bs-green); font-size: 2.2rem; margin: 0 0 .5rem; }
        .bs-statement { border-left: 4px solid var(--bs-blue); padding: .8rem 1rem;
            background: #f4f6ff; border-radius: 0 10px 10px 0; margin: 1rem 0; }
        .bs-code-label { color: var(--bs-muted); font-size: .78rem; margin-bottom: .2rem; }
        [data-testid="stSidebar"] { border-right: 1px solid var(--bs-line); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(status: str, label: str | None = None) -> str:
    tone = status_tone(status)
    return (
        f'<span class="bs-badge bs-{tone}">'
        f'{escape(label or status.replace("_", " "))}</span>'
    )


def card(title: str, value: str, detail: str = "", status: str | None = None) -> None:
    status_html = f"<br>{badge(status)}" if status else ""
    st.markdown(
        f"""
        <div class="bs-card">
          <div class="bs-card-title">{escape(title)}</div>
          <div class="bs-card-value">{escape(value)}</div>
          <div class="bs-muted">{escape(detail)}</div>
          {status_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(eyebrow: str, title: str, description: str = "") -> None:
    st.markdown(f'<div class="bs-eyebrow">{escape(eyebrow)}</div>', unsafe_allow_html=True)
    st.header(title)
    if description:
        st.caption(description)


def render_sidebar() -> tuple[str, str]:
    st.sidebar.markdown("## 🛡️ BumpShield")
    st.sidebar.caption("Find what broke. Fix it. Prove it.")
    mode = st.sidebar.radio(
        "Demo Mode",
        (RECORDED_MODE, LIVE_MODE),
        key="demo_mode",
    )
    if mode == RECORDED_MODE:
        st.sidebar.markdown("**RECORDED** · no live execution")
        page = st.sidebar.radio(
            "Navigation",
            ("Replay", "Evidence & Results"),
            key="replay_page",
        )
    else:
        st.sidebar.markdown("**LIVE** · real pipeline execution")
        page = st.sidebar.radio("Navigation", PAGES, key="page")
    st.sidebar.divider()
    task = st.session_state.task if mode == LIVE_MODE else None
    if task is not None:
        st.sidebar.caption("REQUESTED UPGRADE")
        st.sidebar.markdown(f"**{task.target_dependency.artifact_id}**")
        st.sidebar.caption(
            f"{task.target_dependency.old_version} to {task.target_dependency.new_version}"
        )
        st.sidebar.caption(f"Repository: `{task.repository.name}`")
    planning = st.session_state.planning_result if mode == LIVE_MODE else None
    repair = st.session_state.repair_result if mode == LIVE_MODE else None
    if repair is not None:
        st.sidebar.caption(f"Run ID: `{repair.run_id}`")
    elif planning is not None:
        st.sidebar.caption(f"Run ID: `{planning.plan.run_id}`")
    st.sidebar.divider()
    st.sidebar.checkbox("Show technical details", key="show_technical_details")
    st.sidebar.caption("Original repositories are never patched by this GUI.")
    return mode, page


def render_mode_banner(mode: str) -> None:
    """Keep live and replay provenance visible on every main screen."""
    if mode == RECORDED_MODE:
        st.info(
            "RECORDED VERIFIED RUN — REPLAY MODE — NO LIVE EXECUTION\n\n"
            "This view reads integrity-checked artifacts from a previously completed "
            "real Java/Maven/Codex run. It makes zero Codex, Maven, Java, Git-analysis, "
            "or network calls."
        )
    else:
        st.caption(
            "LIVE MODE — actions on this screen may execute the real BumpShield pipeline "
            "only after an explicit button click."
        )


def switch_to_mode(mode: str) -> None:
    """Change presentation mode only after an explicit user action."""
    st.session_state.demo_mode = mode
    if mode == RECORDED_MODE:
        st.session_state.replay_page = "Replay"
    else:
        st.session_state.page = "Overview"


@st.cache_data(show_spinner=False)
def cached_research_results():
    return load_research_results()


@st.cache_resource(show_spinner=False)
def cached_recorded_source(bundle_name: str = DEFAULT_REPLAY_BUNDLE.name) -> RecordedRunSource:
    """Load and validate committed replay evidence without external execution."""
    return RecordedRunSource.load(REPLAY_ROOT / bundle_name)


def selected_recorded_source() -> RecordedRunSource:
    """Return the integrity-checked bundle selected for offline presentation."""
    label = str(st.session_state.replay_scenario)
    bundle = REPLAY_SCENARIOS.get(label, DEFAULT_REPLAY_BUNDLE)
    return cached_recorded_source(bundle.name)


def render_pipeline() -> None:
    labels = (
        "Reproduce",
        "Dependency Diff",
        "Failure Localization",
        "API Evidence",
        "Causal Diagnosis",
        "Migration Plan",
        "AI Repair",
        "Independent Verification",
    )
    content = '<span class="bs-arrow">›</span>'.join(
        f'<span class="bs-pill">{escape(item)}</span>' for item in labels
    )
    st.markdown(content, unsafe_allow_html=True)


def render_overview() -> None:
    st.markdown(
        """
        <div class="bs-hero">
          <div class="bs-eyebrow">Causal Dependency Migration Agent</div>
          <div class="bs-title">BumpShield</div>
          <div class="bs-tagline">Find what broke. Fix it. Prove it.</div>
          <div class="bs-subtitle">When a Java/Maven dependency upgrade breaks a project,
          BumpShield traces the actual causal dependency, proves the API change,
          constrains an AI-generated migration, and independently verifies it.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    columns = st.columns(3)
    with columns[0]:
        card("FIND", "Causal diagnosis", "Dependency graph, failure, and JAR API evidence")
    with columns[1]:
        card("FIX", "Constrained Codex migration", "Bounded source files and explicit guardrails")
    with columns[2]:
        card("PROVE", "Independent verification", "Git, Maven, dependency, test, and scope checks")

    st.subheader("One pipeline. Separate authorities.")
    render_pipeline()

    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("Why causal analysis matters")
        st.markdown(
            """
            <div class="bs-statement">
            You upgraded <strong>core-lib</strong>, but the missing API belongs to
            <strong>parser-lib</strong>, which changed transitively. BumpShield reconstructs
            that chain before asking AI to edit source.
            </div>
            """,
            unsafe_allow_html=True,
        )
        render_chain(
            (
                "Requested: core-lib 1.0 to 2.0",
                "Hidden: parser-lib 1.0 to 2.0",
                "Parser.parseValue(String) REMOVED",
                "TextNormalizer.java:9 still calls it",
                "COMPILATION FAILURE",
            )
        )
    with right:
        st.subheader("Hero example")
        card("REQUESTED UPGRADE", "core-lib", "1.0 to 2.0 · DIRECT")
        st.write("")
        card("ACTUAL CAUSAL DEPENDENCY", "parser-lib", "1.0 to 2.0 · TRANSITIVE")
        st.write("")
        card("FINAL", "VERIFIED_MIGRATION", "Original repository unchanged", "VERIFIED_MIGRATION")

    st.subheader("Why trust the result?")
    trust_columns = st.columns(2)
    with trust_columns[0]:
        st.markdown(
            """
            - AI cannot mark itself verified.
            - Git determines the actual patch.
            - Maven performs compile and tests.
            """
        )
    with trust_columns[1]:
        st.markdown(
            """
            - Dependency resolution is checked again.
            - Tests cannot be silently deleted or disabled.
            - Original repository stays isolated.
            """
        )
    render_research_panel(compact=True)


def render_new_migration() -> None:
    section_header(
        "LIVE WORKFLOW",
        "New Migration",
        "Investigation is deterministic. Codex is not invoked until you explicitly start repair.",
    )

    load_columns = st.columns([1, 2])
    with load_columns[0]:
        if st.button("Load Demo Fixture", width="stretch"):
            try:
                reset_run_state(st.session_state)
                set_form_values(st.session_state, load_demo_values())
                st.session_state.last_error = None
                st.rerun()
            except Exception as error:  # presentation boundary
                st.session_state.last_error = error
    with load_columns[1]:
        st.caption("TRANSITIVE API BREAK DEMO · Application / core-lib / parser-lib")

    st.text_input("Existing task.json path", key="task_json_path", placeholder="/path/to/task.json")
    if st.button("Load task.json"):
        try:
            reset_run_state(st.session_state)
            set_form_values(
                st.session_state,
                load_task_values(st.session_state.task_json_path),
            )
            st.rerun()
        except Exception as error:  # presentation boundary
            st.session_state.last_error = error

    with st.form("migration-form"):
        st.text_input("Repository path", key="form_repository")
        commit_columns = st.columns(2)
        with commit_columns[0]:
            st.text_input("Base commit", key="form_base_commit")
        with commit_columns[1]:
            st.text_input("Updated commit", key="form_updated_commit")
        dependency_columns = st.columns(2)
        with dependency_columns[0]:
            st.text_input("Target dependency group ID", key="form_group_id")
        with dependency_columns[1]:
            st.text_input("Target dependency artifact ID", key="form_artifact_id")
        version_columns = st.columns(2)
        with version_columns[0]:
            st.text_input("Old version", key="form_old_version")
        with version_columns[1]:
            st.text_input("New version", key="form_new_version")
        st.text_input(
            "Optional external state directory",
            key="form_state_directory",
            placeholder="Uses BumpShield default when empty",
        )
        submitted = st.form_submit_button(
            "Investigate Upgrade",
            type="primary",
            disabled=bool(st.session_state.investigation_running),
            width="stretch",
        )

    try:
        preview_task = build_task_spec(form_values(st.session_state))
    except ValueError:
        preview_task = None
    if preview_task is not None:
        with st.expander("Task JSON preview"):
            st.code(task_preview(preview_task), language="json")

    if submitted:
        st.session_state.investigation_running = True
        st.session_state.last_error = None
        st.session_state.repair_result = None
        try:
            task = build_task_spec(form_values(st.session_state))
            st.session_state.task = task
            adapter = LiveBumpShieldAdapter(st.session_state.form_state_directory)
            with st.status("Investigating dependency upgrade…", expanded=True) as status:
                st.write("Running existing deterministic analysis and planning services.")
                live = adapter.investigate(task)
                st.session_state.reproduction_result = live.reproduction
                if live.planning is None:
                    raise RuntimeError(
                        f"Regression gate returned {live.reproduction.status.value}; "
                        "causal planning did not run."
                    )
                result = live.planning
                view = planning_to_view(result, live.reproduction)
                render_completed_stages(view)
                status.update(label="Investigation complete", state="complete")
            st.session_state.planning_result = result
            st.success("Root-cause investigation complete. Open Investigation in sidebar.")
        except Exception as error:  # presentation boundary
            st.session_state.last_error = error
        finally:
            st.session_state.investigation_running = False

    render_last_error()


def render_completed_stages(view) -> None:
    stages = (
        ("Regression reproduced", view.regression_confirmed),
        ("Dependency graphs compared", view.dependency_analysis_complete),
        ("Failure localized", view.failure is not None),
        ("Dependency JAR APIs inspected", view.api_change is not None),
        ("Causal diagnosis constructed", view.diagnosis.status == "SUPPORTED_DIAGNOSIS"),
        ("Migration planned", view.plan.status == "PLAN_READY"),
    )
    for label, complete in stages:
        st.write(f"{'✓' if complete else '—'} {label}")


def require_investigation():
    result = st.session_state.planning_result
    if result is None:
        st.info("No investigation yet. Open New Migration and click Investigate Upgrade.")
        return None, None
    return result, planning_to_view(result, st.session_state.reproduction_result)


def render_investigation() -> None:
    result, view = require_investigation()
    if view is None:
        return
    section_header("WHY IT BROKE", "Causal Investigation", f"Run {view.run_id}")
    render_completed_stages(view)

    requested, causal = st.columns(2)
    with requested:
        card(
            "REQUESTED UPGRADE",
            view.requested.artifact_id,
            f"{view.requested.old_version} to {view.requested.new_version} · {view.requested.relationship}",
        )
    with causal:
        if view.causal:
            card(
                "ACTUAL CAUSAL DEPENDENCY",
                view.causal.artifact_id,
                f"{view.causal.old_version} to {view.causal.new_version} · {view.causal.relationship}",
            )
        else:
            card("ACTUAL CAUSAL DEPENDENCY", "Not established", "Evidence incomplete")

    if view.causal and view.causal.artifact_id != view.requested.artifact_id:
        st.markdown(
            f"""
            <div class="bs-statement"><strong>YOU UPGRADED</strong><br>
            {escape(view.requested.artifact_id)}<br><br>
            <strong>BUT THE BREAKING API BELONGS TO</strong><br>
            {escape(view.causal.artifact_id)} {badge(view.causal.relationship)}</div>
            """,
            unsafe_allow_html=True,
        )

    left, right = st.columns(2)
    with left:
        st.subheader("Dependency chain")
        path = view.dependency_path or (
            f"Application",
            f"{view.requested.artifact_id}:{view.requested.new_version}",
            (
                f"{view.causal.artifact_id}:{view.causal.new_version}"
                if view.causal
                else "Causal dependency unavailable"
            ),
        )
        render_chain(path)
        render_failure(view.failure)
    with right:
        render_api_evidence(view.api_change)

    st.subheader("Causal chain")
    steps = view.diagnosis.causal_steps or (view.diagnosis.summary,)
    render_chain(steps)
    render_diagnosis(view.diagnosis)

    with st.expander("Why did this break?"):
        if view.diagnosis.causal_steps:
            for index, step in enumerate(view.diagnosis.causal_steps, start=1):
                st.markdown(f"**{index}.** {step}")
        else:
            st.write(view.diagnosis.summary)
        if view.diagnosis.explanation:
            st.caption(view.diagnosis.explanation)

    if st.session_state.show_technical_details:
        st.caption(f"Artifacts: `{view.artifact_directory}`")
        st.json({"run_id": view.run_id, "diagnosis_status": view.diagnosis.status})


def render_chain(steps) -> None:
    body = "".join(
        f'<div class="bs-chain-step"><strong>{index}.</strong> {escape(step)}</div>'
        for index, step in enumerate(steps, start=1)
    )
    st.markdown(f'<div class="bs-chain">{body}</div>', unsafe_allow_html=True)


def render_failure(failure) -> None:
    st.subheader("Project failure")
    if failure is None:
        st.warning("Failure was not localized.")
        return
    file_label = failure.file or "Not localized"
    detail = f"{file_label}:{failure.line}" if failure.line else file_label
    card("CATEGORY", failure.category, detail, "FAIL")
    if failure.symbol:
        st.markdown(f"**Symbol:** `{failure.symbol}`")
    st.caption(failure.message)
    if failure.source_excerpt:
        st.code(failure.source_excerpt, language="java")


def render_api_evidence(api) -> None:
    st.subheader("Old vs new API")
    if api is None:
        st.warning("API evidence unavailable.")
        return
    st.markdown(f"**{api.class_name}** · {badge(api.kind)}", unsafe_allow_html=True)
    columns = st.columns(2)
    with columns[0]:
        card(
            "OLD API",
            api.old_version or "Unknown version",
            "Class present" if api.old_class_present else "Class absent or unknown",
            "PASS" if api.old_class_present else "UNKNOWN",
        )
        for declaration in api.old_members[:6]:
            st.code(declaration, language="java")
    with columns[1]:
        removed = api.kind in {
            "REMOVED_MEMBER",
            "REMOVED_CLASS",
            "PACKAGE_REMOVED",
            "DEPENDENCY_REMOVED_WITH_CLASS",
        }
        card(
            "NEW API",
            api.new_version or "Dependency removed",
            "Required API removed" if removed else "API changed",
            "FAIL" if removed else "REVIEW",
        )
        for declaration in api.new_members[:6]:
            st.code(declaration, language="java")
    if api.candidates:
        st.markdown(f"**Observed candidates** {badge('REVIEW', 'UNVERIFIED CANDIDATE')}", unsafe_allow_html=True)
        for candidate in api.candidates:
            st.code(candidate, language="java")
        st.caption("Candidates are evidence for repair reasoning, not verified replacements.")


def render_diagnosis(diagnosis) -> None:
    st.subheader("Causal diagnosis")
    columns = st.columns(3)
    with columns[0]:
        card("STATUS", diagnosis.status, "Deterministic result", diagnosis.status)
    with columns[1]:
        card("EVIDENCE", diagnosis.evidence_strength or "Unavailable", "Ordinal evidence strength")
    with columns[2]:
        score = f"{diagnosis.evidence_score} / 100" if diagnosis.evidence_score is not None else "Unavailable"
        card("EVIDENCE SCORE", score, "Ordinal score, not probability")
    st.write(diagnosis.summary)


def render_plan() -> None:
    _, view = require_investigation()
    if view is None:
        return
    plan = view.plan
    section_header("WHAT MUST CHANGE", "Migration Plan", plan.required_outcome)
    columns = st.columns(3)
    with columns[0]:
        card("STATUS", plan.status, "Planning gate", plan.status)
    with columns[1]:
        card("MIGRATION TYPE", plan.migration_kind, plan.affected_api or "API unavailable")
    with columns[2]:
        card("ESTIMATED SCOPE", plan.scope, f"{len(plan.allowed_files)} initially allowed file(s)")

    if plan.candidates:
        st.subheader("Observed new API candidates")
        st.markdown(badge("REVIEW", "UNVERIFIED CANDIDATE"), unsafe_allow_html=True)
        for candidate in plan.candidates:
            st.code(candidate, language="java")
        st.caption("BumpShield does not assert semantic equivalence before execution.")

    left, right = st.columns(2)
    with left:
        st.subheader("AI edit boundary")
        if plan.allowed_files:
            for file in plan.allowed_files:
                st.code(file)
        else:
            st.warning("No files are automatically allowed.")
        if plan.affected_files:
            with st.expander("All evidence-backed source locations"):
                for file in plan.affected_files:
                    st.write(file)
    with right:
        st.subheader("Repair guardrails")
        for constraint in plan.constraints:
            st.write(f"✓ {constraint.replace('_', ' ').title()}")
        st.info("The model proposes a patch. It does not control verification.")

    with st.expander("Required verification"):
        for requirement in plan.verification_requirements:
            st.write(f"• {requirement.replace('_', ' ').title()}")
    if plan.cautious_repair:
        st.warning("Plan requires cautious repair because evidence is not at the strongest tier.")


def render_repair() -> None:
    if st.session_state.task is None or st.session_state.planning_result is None:
        st.info("Complete Investigation before repair.")
        return
    section_header(
        "WHAT AI CHANGED · HOW BUMPSHIELD PROVED IT",
        "Repair & Independent Verification",
        "Repair occurs in a fresh isolated worktree. Original repository is not patched.",
    )
    st.info(
        "This action invokes the existing RepairEngine. BumpShield independently reruns "
        "dependency resolution, compile, tests, integrity, and patch-scope checks."
    )
    if st.button(
        "Repair in Isolated Workspace",
        type="primary",
        disabled=bool(st.session_state.repair_running),
        width="stretch",
    ):
        st.session_state.repair_running = True
        st.session_state.last_error = None
        try:
            adapter = LiveBumpShieldAdapter(st.session_state.form_state_directory)
            with st.status("Running constrained repair…", expanded=True) as status:
                st.write("Creating isolated updated-revision worktree.")
                st.write("Codex may propose edits. Git and BumpShield remain authority.")
                result = adapter.repair(st.session_state.task)
                st.session_state.repair_result = result
                view = repair_to_view(result)
                st.write(f"Completed {len(view.attempts)} repair attempt(s).")
                state = "complete" if view.verified else "error"
                status.update(label=f"Repair finished: {view.final_status}", state=state)
        except Exception as error:  # presentation boundary
            st.session_state.last_error = error
        finally:
            st.session_state.repair_running = False

    render_last_error()
    result = st.session_state.repair_result
    if result is None:
        st.caption("No repair has run in this session. Streamlit rerenders do not invoke one.")
        return
    render_repair_result(repair_to_view(result))


def render_repair_result(view: VerificationView) -> None:
    st.subheader("Repair attempt timeline")
    for attempt in view.attempts:
        expanded = attempt.number == view.winning_attempt or attempt.number == len(view.attempts)
        with st.expander(f"Attempt {attempt.number} · {attempt.status}", expanded=expanded):
            metrics = st.columns(4)
            metrics[0].metric("Files", attempt.files_changed)
            metrics[1].metric("Added", f"+{attempt.lines_added}")
            metrics[2].metric("Removed", f"-{attempt.lines_removed}")
            metrics[3].metric("Provider", attempt.provider_status or "NOT RUN")
            st.markdown(
                f"Compile {badge(attempt.compile_status or 'NOT_RUN')} &nbsp; "
                f"Tests {badge(attempt.test_status or 'NOT_RUN')} &nbsp; "
                f"Verification {badge(attempt.verification_status or 'NOT_RUN')}",
                unsafe_allow_html=True,
            )
            if attempt.representative_failure:
                st.caption("Representative failure")
                st.code(attempt.representative_failure[:4000])
            if attempt.patch:
                st.caption("Git-ground-truth patch")
                st.code(attempt.patch, language="diff")
            if attempt.provider_status in {"ERROR", "UNAVAILABLE"}:
                title, message = friendly_error(attempt.provider_issue or "Provider unavailable")
                st.error(f"{title}\n\n{message}")
                if title == "CODING PROVIDER UNAVAILABLE":
                    st.button(
                        "View Recorded Verified Run",
                        key=f"attempt-{attempt.number}-open-replay",
                        on_click=switch_to_mode,
                        args=(RECORDED_MODE,),
                    )
                if attempt.provider_issue and st.session_state.show_technical_details:
                    st.code(attempt.provider_issue)

    st.subheader("Independent verification")
    if view.checks:
        for name, status, details in view.checks:
            columns = st.columns([1.2, .5, 2.3])
            columns[0].write(f"**{name.replace('_', ' ').title()}**")
            columns[1].markdown(badge(status), unsafe_allow_html=True)
            columns[2].caption(details)
    else:
        st.warning("Independent verifier did not produce checks for this result.")

    if view.verified:
        winning = next(
            (item for item in view.attempts if item.number == view.winning_attempt),
            None,
        )
        stats = (
            f"{winning.files_changed} file(s) · +{winning.lines_added} / -{winning.lines_removed}"
            if winning
            else "Verified patch"
        )
        st.markdown(
            f"""
            <div class="bs-final">
              <h2>✓ VERIFIED_MIGRATION</h2>
              <div>The repair model proposed the migration. BumpShield independently proved it.</div>
              <div class="bs-muted" style="margin-top:.6rem">{escape(stats)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif view.final_status == "NEEDS_HUMAN_REVIEW":
        st.warning("NEEDS_HUMAN_REVIEW\n\nMigration is not verified. Review findings block automatic acceptance.")
    else:
        st.error("UNRESOLVED\n\nMigration was not independently verified.")
    for reason in view.reasons:
        st.write(f"• {reason}")

    st.subheader("Original repository safety")
    st.markdown(
        """
        - RepairEngine edited only disposable repair worktrees.
        - This GUI did not apply `final.patch` to the original repository.
        - No automatic commit, push, or pull request was performed.
        """
    )
    st.caption(
        "Current result proves engine workflow isolation. This panel does not invent "
        "HEAD/index checks absent from the structured result."
    )


def render_replay() -> None:
    """Render manual, offline walkthrough from validated recorded evidence."""
    selected = st.selectbox(
        "Replay scenario",
        tuple(REPLAY_SCENARIOS),
        key="replay_scenario",
    )
    selected_bundle = REPLAY_SCENARIOS[selected]
    try:
        source = cached_recorded_source(selected_bundle.name)
    except (ReplayBundleError, OSError, json.JSONDecodeError) as error:
        section_header("REPLAY INTEGRITY", "Recorded run unavailable")
        st.error("ARTIFACT INTEGRITY ✗ FAILED")
        st.write(str(error))
        st.warning("VERIFIED_MIGRATION is disabled because recorded evidence did not validate.")
        return

    bundle = source.bundle
    render_replay_integrity(bundle)
    if not st.session_state.replay_started:
        render_replay_start(bundle)
        return

    if st.session_state.replay_fast_view:
        render_replay_fast_view(bundle)
        return

    render_replay_controls(bundle)
    if st.session_state.replay_show_all:
        section_header("FULL RECORDED STORY", "All ten recorded stages")
        for index, stage in enumerate(bundle.stages):
            st.divider()
            st.markdown(f"### Step {index + 1} / {len(bundle.stages)} · {stage}")
            render_replay_stage(bundle, index)
        return

    step = min(max(int(st.session_state.replay_step), 0), len(bundle.stages) - 1)
    st.progress((step + 1) / len(bundle.stages))
    section_header(
        f"STEP {step + 1} / {len(bundle.stages)}",
        bundle.stages[step],
        "Recorded execution evidence — no command is running now.",
    )
    render_replay_stage(bundle, step)


def render_replay_integrity(bundle) -> None:
    columns = st.columns([1, 2])
    with columns[0]:
        st.markdown(badge("PASS", "ARTIFACT INTEGRITY ✓ VERIFIED"), unsafe_allow_html=True)
    with columns[1]:
        st.caption(f"Bundle SHA-256: `{bundle.bundle_hash}`")


def render_replay_start(bundle) -> None:
    view = bundle.investigation
    real_world = bundle.provenance.source_run_type == "REAL_OPEN_SOURCE_PROJECT"
    eyebrow = (
        "RECORDED REAL-WORLD VERIFIED RUN" if real_world else "RECORDED VERIFIED RUN"
    )
    title = bundle.provenance.project or "BumpShield"
    subtitle = (
        f"REAL OPEN-SOURCE PROJECT · {view.requested.artifact_id} "
        f"{view.requested.old_version} → {view.requested.new_version}"
        if real_world
        else "Scenario: transitive dependency API break"
    )
    st.markdown(
        f"""
        <div class="bs-hero">
          <div class="bs-eyebrow">{escape(eyebrow)}</div>
          <div class="bs-title">{escape(title)}</div>
          <div class="bs-tagline">Find what broke. Fix it. Prove it.</div>
          <div class="bs-subtitle">{escape(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    card(
        "REQUESTED UPGRADE",
        view.requested.artifact_id,
        f"{view.requested.old_version} to {view.requested.new_version}",
    )
    st.info(
        "Why Replay Mode? Live AI demos depend on provider availability, network, quota, "
        "and toolchain latency. Replay shows integrity-checked evidence from a previously "
        "verified real run. It does not simulate a new repair."
    )
    controls = st.columns(3)
    if controls[0].button("Start Replay", type="primary", width="stretch"):
        st.session_state.replay_started = True
        st.session_state.replay_step = 0
        st.session_state.replay_show_all = False
        st.session_state.replay_fast_view = False
        st.rerun()
    if controls[1].button("30-Second Fast View", width="stretch"):
        st.session_state.replay_started = True
        st.session_state.replay_fast_view = True
        st.rerun()
    controls[2].button(
        "Switch to Live Mode",
        width="stretch",
        on_click=switch_to_mode,
        args=(LIVE_MODE,),
    )
    render_replay_provenance(bundle)


def render_replay_controls(bundle) -> None:
    controls = st.columns(5)
    if controls[0].button(
        "Previous",
        disabled=st.session_state.replay_step <= 0 or st.session_state.replay_show_all,
        width="stretch",
    ):
        st.session_state.replay_step -= 1
        st.rerun()
    if controls[1].button(
        "Next",
        disabled=(
            st.session_state.replay_step >= len(bundle.stages) - 1
            or st.session_state.replay_show_all
        ),
        type="primary",
        width="stretch",
    ):
        st.session_state.replay_step += 1
        st.rerun()
    if controls[2].button("Restart Replay", width="stretch"):
        reset_replay_state(st.session_state)
        st.rerun()
    show_label = "One Stage" if st.session_state.replay_show_all else "Show All"
    if controls[3].button(show_label, width="stretch"):
        st.session_state.replay_show_all = not st.session_state.replay_show_all
        st.rerun()
    if controls[4].button("Fast View", width="stretch"):
        st.session_state.replay_fast_view = True
        st.rerun()


def render_replay_stage(bundle, step: int) -> None:
    renderers = (
        render_replay_regression,
        render_replay_dependency_diff,
        render_replay_failure,
        render_replay_api,
        render_replay_diagnosis,
        render_replay_plan,
        render_replay_repair,
        render_replay_compile,
        render_replay_tests,
        render_replay_verification,
    )
    renderers[step](bundle)


def render_replay_regression(bundle) -> None:
    evidence = bundle.reproduction
    before, after = st.columns(2)
    with before:
        card(
            "BEFORE UPGRADE",
            "BUILD SUCCESS",
            f"{evidence.base.command} · {evidence.base.tests}/{evidence.base.tests} tests passed",
            evidence.base.status,
        )
    with after:
        card(
            "AFTER UPGRADE",
            "BUILD FAILURE",
            f"{evidence.updated.command} · {evidence.updated_reason}",
            evidence.updated.status,
        )
    st.caption("Recorded Maven execution. Replay did not invoke Maven.")


def render_replay_dependency_diff(bundle) -> None:
    view = bundle.investigation
    direct = view.causal.relationship == "DIRECT"
    requested, causal = st.columns(2)
    with requested:
        card(
            "REQUESTED UPGRADE",
            view.requested.artifact_id,
            f"{view.requested.old_version} to {view.requested.new_version} · DIRECT",
        )
    with causal:
        card(
            "CAUSAL DIRECT CHANGE" if direct else "TRANSITIVE CHANGE DISCOVERED",
            view.causal.artifact_id,
            f"{view.causal.old_version} to {view.causal.new_version} · {view.causal.relationship}",
        )
    if direct:
        st.markdown(
            f"<div class='bs-statement'><strong>{escape(view.requested.artifact_id)}</strong> "
            "owns the removed API directly.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div class='bs-statement'>You upgraded <strong>{escape(view.requested.artifact_id)}</strong>, "
            f"but <strong>{escape(view.causal.artifact_id)}</strong> also changed underneath it.</div>",
            unsafe_allow_html=True,
        )
    render_chain(view.dependency_path)


def render_replay_failure(bundle) -> None:
    render_failure(bundle.investigation.failure)
    st.caption("Recorded bounded source context. No repository was opened during replay.")


def render_replay_api(bundle) -> None:
    api = bundle.investigation.api_change
    render_api_evidence(api)
    if api is not None and api.new_members:
        st.markdown("**Observed new class member in recorded `javap` evidence**")
        for member in api.new_members:
            st.code(member, language="java")
    if api is not None and not api.candidates:
        st.caption(
            "Recorded migration plan exposed no candidate replacement. New class members "
            "remain API evidence only; replay does not promote them to verified replacements."
        )


def render_replay_diagnosis(bundle) -> None:
    diagnosis = bundle.investigation.diagnosis
    render_chain(diagnosis.causal_steps)
    render_diagnosis(diagnosis)
    st.caption("100 / 100 is a deterministic ordinal evidence score, not probability.")


def render_replay_plan(bundle) -> None:
    plan = bundle.investigation.plan
    columns = st.columns(3)
    with columns[0]:
        card("STATUS", plan.status, "Recorded planning gate", plan.status)
    with columns[1]:
        card("MIGRATION", plan.migration_kind, plan.affected_api or "API unavailable")
    with columns[2]:
        card("SCOPE", plan.scope, f"{len(plan.allowed_files)} allowed file(s)")
    st.write(plan.required_outcome)
    left, right = st.columns(2)
    with left:
        st.markdown("**Allowed source boundary**")
        for file in plan.allowed_files:
            st.code(file)
    with right:
        st.markdown("**Guardrails**")
        for constraint in plan.constraints:
            st.write(f"✓ {constraint.replace('_', ' ').title()}")
    if not plan.candidates:
        st.info("No migration candidate was asserted by the recorded plan.")


def render_replay_repair(bundle) -> None:
    attempt = bundle.verification.attempts[0]
    columns = st.columns(4)
    columns[0].metric("Provider", "Codex")
    columns[1].metric("Attempt", attempt.number)
    columns[2].metric("Files", attempt.files_changed)
    columns[3].metric("Lines", f"+{attempt.lines_added} / -{attempt.lines_removed}")
    st.caption("Real Git-ground-truth patch from recorded BumpShield run")
    st.code(bundle.patch, language="diff")


def render_replay_compile(bundle) -> None:
    card(
        "INDEPENDENT EXECUTION",
        bundle.compile.command,
        "Recorded execution",
        bundle.compile.status,
    )
    st.success("PASS")
    st.caption("BumpShield ran this command after provider editing. Replay did not.")


def render_replay_tests(bundle) -> None:
    tests = bundle.tests
    card("INDEPENDENT EXECUTION", tests.command, "Recorded execution", tests.status)
    columns = st.columns(4)
    columns[0].metric("Tests", tests.tests)
    columns[1].metric("Failures", tests.failures)
    columns[2].metric("Errors", tests.errors)
    columns[3].metric("Skipped", tests.skipped)
    st.caption("Counts come from preserved Maven Surefire output; replay did not run tests.")


def render_replay_verification(bundle) -> None:
    view = bundle.verification
    st.subheader("Independent verifier checks")
    for name, status, details in view.checks:
        columns = st.columns([1.2, .5, 2.3])
        columns[0].write(f"**{name.replace('_', ' ').title()}**")
        columns[1].markdown(badge(status), unsafe_allow_html=True)
        columns[2].caption(details)
    if not view.verified:
        st.error("Recorded verifier evidence does not authorize verified presentation.")
        return
    real_world = bundle.provenance.source_run_type == "REAL_OPEN_SOURCE_PROJECT"
    label = (
        "RECORDED REAL-WORLD VERIFIED RUN" if real_world else "RECORDED VERIFIED RUN"
    )
    st.markdown(
        f"""
        <div class="bs-final">
          <div class="bs-eyebrow">{escape(label)}</div>
          <h2>✓ VERIFIED_MIGRATION</h2>
          <div>The model proposed the patch.</div>
          <div><strong>BumpShield independently verified the migration.</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if bundle.provenance.original_repository_unchanged:
        st.success("ORIGINAL REPOSITORY — UNCHANGED")
    st.caption("Final status comes from recorded IndependentVerifier evidence, not manifest text.")
    render_replay_provenance(bundle)


def render_replay_fast_view(bundle) -> None:
    view = bundle.investigation
    attempt = bundle.verification.attempts[0]
    section_header("30-SECOND VIEW", "Recorded verified migration")
    rows = (
        ("Requested", f"{view.requested.artifact_id} {view.requested.old_version} to {view.requested.new_version}"),
        ("Causal", f"{view.causal.artifact_id} {view.causal.old_version} to {view.causal.new_version} · {view.causal.relationship}"),
        ("Break", f"{view.failure.symbol} removed"),
        ("Source", f"{view.failure.file}:{view.failure.line}"),
        ("Patch", f"{attempt.files_changed} file · +{attempt.lines_added} / -{attempt.lines_removed}"),
        ("Verification", "Dependency guards, compile, tests, integrity, and scope PASS"),
    )
    for label, value in rows:
        card(label, value)
        st.write("")
    render_replay_verification(bundle)
    if st.button("Return to Replay Start", width="stretch"):
        reset_replay_state(st.session_state)
        st.rerun()


def render_replay_provenance(bundle) -> None:
    provenance = bundle.provenance
    with st.expander("Run Provenance"):
        st.write(f"**Fixture:** {provenance.fixture}")
        if provenance.project:
            st.write(f"**Project:** {provenance.project}")
        if provenance.showcase_type:
            st.write(f"**Showcase type:** `{provenance.showcase_type}`")
        if provenance.upstream_repository:
            st.write(f"**Upstream:** {provenance.upstream_repository}")
        st.write(f"**Source type:** `{provenance.source_run_type}`")
        st.write(f"**Recorded run:** `{provenance.source_run_id}`")
        st.write(f"**Recorded date:** {provenance.recorded_at or 'Unknown'}")
        st.write(f"**Source report:** `{provenance.source_report}`")
        st.write(f"**Original status:** `{provenance.original_final_status}`")
        st.write(f"**Bundle hash:** `{provenance.bundle_hash}`")
        st.caption(provenance.sanitization_status)
        st.dataframe(
            [{"Tool": key, "Recorded version": value} for key, value in provenance.toolchain],
            hide_index=True,
            width="stretch",
        )


def render_recorded_evidence_results() -> None:
    section_header("READ-ONLY EVIDENCE", "Evidence & Results")
    try:
        bundle = selected_recorded_source().bundle
    except (ReplayBundleError, OSError, json.JSONDecodeError) as error:
        st.error(f"ARTIFACT INTEGRITY ✗ FAILED\n\n{error}")
        return
    render_replay_integrity(bundle)
    render_replay_provenance(bundle)
    with st.expander("Recorded migration report"):
        st.code(bundle.migration_report, language="text")
    st.divider()
    render_research_panel(compact=False)


def render_evidence_results() -> None:
    section_header("AUDIT TRAIL", "Evidence & Results")
    render_research_panel(compact=False)
    st.divider()
    st.subheader("Run artifacts")
    roots = []
    planning = st.session_state.planning_result
    repair = st.session_state.repair_result
    if planning is not None:
        roots.append(("Investigation", planning.plan.artifact_directory))
    if repair is not None:
        roots.append(("Repair", repair.artifact_directory))
    if not roots:
        st.info("No live run artifacts yet.")
        return
    labels = [f"{name}: {path}" for name, path in roots]
    selected_label = st.selectbox("Artifact run", labels)
    root = roots[labels.index(selected_label)][1]
    artifacts = list_artifacts(root)
    if not artifacts:
        st.warning("No readable artifacts found.")
        return
    selected = st.selectbox("Artifact", artifacts, format_func=lambda item: item.as_posix())
    try:
        content = read_artifact_text(root, selected)
        language = "json" if selected.suffix == ".json" else "diff" if selected.suffix == ".diff" or selected.name.endswith(".patch") else "text"
        st.code(content, language=language)
    except ValueError as error:
        st.error(str(error))


def render_research_panel(compact: bool) -> None:
    st.subheader("Frozen research evidence")
    try:
        research = cached_research_results()
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        st.info("Committed BUMP-FINAL-v1 summary is unavailable.")
        return
    st.caption(
        f"{research.suite_id} · {research.total_cases} frozen synthetic cases · "
        f"{research.planned_trials} strategy trials · {research.direct_cases} direct / "
        f"{research.transitive_cases} transitive"
    )
    rows = []
    names = {
        "direct-one-shot": "Direct One-Shot",
        "direct-retry": "Direct Retry",
        "bumpshield": "BumpShield",
    }
    for item in research.strategies:
        rows.append(
            {
                "Strategy": names[item.strategy],
                "Strict verified": f"{item.verified}/{item.attempted}",
                "Strict VRR": f"{item.strict_vrr:.0%}",
                "Provider-available": (
                    f"{item.provider_available}/{item.provider_available} "
                    f"({item.provider_available_vrr:.0%})"
                    if item.provider_available_vrr is not None
                    else "Unavailable"
                ),
            }
        )
    st.dataframe(rows, hide_index=True, width="stretch")
    metrics = st.columns(3)
    metrics[0].metric(
        "Causal dependency localization",
        f"{research.dependency_correct}/{research.dependency_labeled}",
    )
    metrics[1].metric(
        "Transitive localization",
        f"{research.transitive_dependency_correct}/{research.transitive_dependency_labeled}",
    )
    metrics[2].metric("API-change accuracy", f"{research.api_correct}/{research.api_labeled}")
    with st.expander("What did the benchmark show?", expanded=not compact):
        st.write(
            "The synthetic benchmark did not demonstrate a repair-rate advantage from "
            "causal analysis because all provider-available repair strategies succeeded."
        )
        st.write(
            "BumpShield's strongest measured result was causal dependency localization: "
            f"{research.dependency_correct}/{research.dependency_labeled} overall and "
            f"{research.transitive_dependency_correct}/"
            f"{research.transitive_dependency_labeled} on transitive cases. "
            "Two strict-VRR failures were "
            "Codex quota failures. Production-project generality remains future work."
        )
        st.caption("All 20 cases are synthetic. Results are descriptive, not a superiority claim.")
    if not compact:
        st.subheader("Direct Repair Baseline vs BumpShield Pipeline")
        comparison = [
            ("Compiler failure", "Included", "Included"),
            ("Dependency graph comparison", "Not provided", "Included"),
            ("Transitive causal attribution", "Not provided", "Included"),
            ("Old/new JAR API evidence", "Not provided", "Included"),
            ("Explicit causal diagnosis", "Not provided", "Included"),
            ("Migration plan", "Not provided", "Included"),
            ("Independent dependency guard", "Same verifier", "Same verifier"),
            ("Audit artifacts", "Repair evidence", "Full causal and repair evidence"),
        ]
        st.dataframe(
            [
                {"Capability": item[0], "Evaluated direct baseline": item[1], "BumpShield": item[2]}
                for item in comparison
            ],
            hide_index=True,
            width="stretch",
        )
        st.markdown(
            """
            **Trust boundary**

            `Codex` proposes patch  
            `BumpShield` captures Git diff  
            `Dependency Guard + Compile + Tests + Test Integrity + Patch Scope`  
            `IndependentVerifier` decides `VERIFIED_MIGRATION`

            **The model proposes. BumpShield verifies.**
            """
        )


def render_last_error() -> None:
    error = st.session_state.last_error
    if error is None:
        return
    title, message = friendly_error(error)
    st.error(f"{title}\n\n{message}")
    if title == "CODING PROVIDER UNAVAILABLE":
        st.caption(
            "Causal investigation remains available. Recorded mode can show a previously "
            "verified end-to-end run without invoking provider or toolchain."
        )
        st.button(
            "Open Recorded Verified Run",
            key="error-open-replay",
            on_click=switch_to_mode,
            args=(RECORDED_MODE,),
        )
    if st.session_state.show_technical_details:
        with st.expander("Technical details"):
            st.code(str(error))


inject_styles()
mode, page = render_sidebar()
render_mode_banner(mode)

if mode == RECORDED_MODE:
    if page == "Replay":
        render_replay()
    else:
        render_recorded_evidence_results()
elif page == "Overview":
    render_overview()
elif page == "New Migration":
    render_new_migration()
elif page == "Investigation":
    render_investigation()
elif page == "Migration Plan":
    render_plan()
elif page == "Repair & Verification":
    render_repair()
elif page == "Evidence & Results":
    render_evidence_results()
