from pathlib import Path

from bumpshield.agent.provider import (
    MAX_FEEDBACK_EXCERPT_CHARS,
    CodexRepairProvider,
    build_repair_request,
)
from bumpshield.agent.repairer import MigrationPlanner, RepairContextBuilder
from bumpshield.config import BumpShieldConfig
from bumpshield.models import (
    CommandResult,
    RepairAttemptStatus,
    RepairFeedback,
    RepairProviderStatus,
    WorkspaceKind,
)
from bumpshield.repo.workspace import RepositoryWorkspace
from test_planner import _location, _planning_inputs
from test_investigator import member


def _context():
    bundle, diagnosis = _planning_inputs(
        new_class_members=(member("parse", ("java.lang.String", "org.example.Options")),),
    )
    plan = MigrationPlanner().plan(bundle, diagnosis, (_location(),))
    return RepairContextBuilder().build(None, bundle, diagnosis, plan)


def test_repair_request_is_bounded_and_marks_candidates_as_unverified() -> None:
    context = _context()
    feedback = RepairFeedback(
        1,
        RepairAttemptStatus.COMPILE_FAILED,
        (Path("src/main/java/com/example/Foo.java"),),
        "compile failed",
        bounded_excerpt="x" * (MAX_FEEDBACK_EXCERPT_CHARS * 2),
    )

    request = build_repair_request(context, 2, feedback)

    assert "Target dependency must remain upgraded" in request.instruction
    assert "Do not delete, disable, weaken, or skip tests" in request.instruction
    assert "BumpShield independently verifies" in request.instruction
    assert "Observed new API candidates (not verified replacements)" in request.instruction
    assert len(request.instruction) <= 40_000
    assert "x" * (MAX_FEEDBACK_EXCERPT_CHARS + 1) not in request.instruction


class RecordingRunner:
    def __init__(self, *, timed_out: bool = False) -> None:
        self.command = ()
        self.cwd = None
        self.timeout = None
        self.timed_out = timed_out

    def run(self, command, *, cwd=None, timeout=None):
        self.command = tuple(command)
        self.cwd = cwd
        self.timeout = timeout
        return CommandResult(
            self.command,
            Path(cwd),
            None if self.timed_out else 0,
            "provider output",
            "",
            1.25,
            self.timed_out,
        )


def test_codex_provider_uses_observed_noninteractive_contract(
    tmp_path: Path, monkeypatch
) -> None:
    runner = RecordingRunner()
    config = BumpShieldConfig(
        state_root=tmp_path / "state",
        repair_provider_timeout_seconds=123,
    )
    monkeypatch.setattr("bumpshield.agent.provider.shutil.which", lambda _: "/usr/bin/codex")
    workspace = RepositoryWorkspace(tmp_path, "abc", WorkspaceKind.REPAIR)
    request = build_repair_request(_context(), 1, None)

    result = CodexRepairProvider(runner=runner, config=config).repair(
        workspace, request
    )

    assert result.status is RepairProviderStatus.SUCCESS
    assert runner.command[:3] == ("codex", "--sandbox", "workspace-write")
    assert "exec" in runner.command
    assert "--ephemeral" in runner.command
    assert "never" in runner.command
    assert runner.command[-1] == request.instruction
    assert runner.cwd == tmp_path
    assert runner.timeout == 123


def test_codex_provider_ignores_host_customization_and_disables_skill_search(
    tmp_path: Path, monkeypatch
) -> None:
    """Repair runs must not import host skills, rules, or user configuration."""
    runner = RecordingRunner()
    monkeypatch.setattr("bumpshield.agent.provider.shutil.which", lambda _: "/usr/bin/codex")
    workspace = RepositoryWorkspace(tmp_path, "abc", WorkspaceKind.REPAIR)

    CodexRepairProvider(
        runner=runner,
        config=BumpShieldConfig(state_root=tmp_path / "state"),
    ).repair(workspace, build_repair_request(_context(), 1, None))

    assert "--ignore-user-config" in runner.command
    assert "--ignore-rules" in runner.command
    assert runner.command.index("exec") < runner.command.index("--ignore-user-config")
    assert runner.command.index("exec") < runner.command.index("--ignore-rules")
    assert runner.command.index("exec") < runner.command.index("--disable")
    assert (
        "--disable",
        "skill_search",
    ) == runner.command[
        runner.command.index("--disable") : runner.command.index("--disable") + 2
    ]
    assert runner.command[:3] == ("codex", "--sandbox", "workspace-write")


def test_codex_provider_reports_missing_executable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("bumpshield.agent.provider.shutil.which", lambda _: None)
    config = BumpShieldConfig(
        state_root=tmp_path / "state",
        repair_provider_executable="missing-codex",
    )
    workspace = RepositoryWorkspace(tmp_path, "abc", WorkspaceKind.REPAIR)

    result = CodexRepairProvider(config=config).repair(
        workspace, build_repair_request(_context(), 1, None)
    )

    assert result.status is RepairProviderStatus.UNAVAILABLE
    assert "missing-codex executable not found" in result.summary


def test_codex_provider_timeout_is_structured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("bumpshield.agent.provider.shutil.which", lambda _: "/usr/bin/codex")
    runner = RecordingRunner(timed_out=True)
    workspace = RepositoryWorkspace(tmp_path, "abc", WorkspaceKind.REPAIR)

    result = CodexRepairProvider(
        runner=runner, config=BumpShieldConfig(state_root=tmp_path / "state")
    ).repair(workspace, build_repair_request(_context(), 1, None))

    assert result.status is RepairProviderStatus.TIMEOUT
