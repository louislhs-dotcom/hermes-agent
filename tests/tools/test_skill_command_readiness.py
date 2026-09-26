"""Readiness command-check must be computed, not hardcoded.

Regression guard: ``_skill_readiness`` used to emit ``required_commands: []`` and
``missing_required_commands: []`` unconditionally, so a skill declaring an absent
binary still reported ``readiness_status: available`` and the command half of the
check could never fire.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.skills_tool import _check_required_commands, _resolve_command  # noqa: E402
from tools.skills_tool_setup import SkillReadinessStatus  # noqa: E402


def test_absent_command_is_reported_missing():
    declared, missing = _check_required_commands(
        {"required_commands": ["definitely-not-a-real-binary-xyz"]})
    assert declared == ["definitely-not-a-real-binary-xyz"]
    assert missing == ["definitely-not-a-real-binary-xyz"]


def test_present_command_is_not_missing():
    declared, missing = _check_required_commands({"required_commands": ["python3"]})
    assert declared == ["python3"]
    assert missing == []


def test_self_provisioned_command_is_never_missing():
    """A skill that installs its own tooling (e.g. into a private venv) must not be
    reported missing by a PATH probe — that produced false 'needs X' markers."""
    declared, missing = _check_required_commands(
        {"required_commands": [{"name": "definitely-not-a-real-binary-xyz",
                                "self_provisioned": True}]})
    assert declared == ["definitely-not-a-real-binary-xyz"]
    assert missing == []


def test_optional_command_is_never_missing():
    declared, missing = _check_required_commands(
        {"required_commands": [{"name": "definitely-not-a-real-binary-xyz", "optional": True}]})
    assert declared == ["definitely-not-a-real-binary-xyz"]
    assert missing == []


def test_undeclared_commands_are_empty():
    assert _check_required_commands({}) == ([], [])


def test_malformed_declaration_does_not_raise():
    assert _check_required_commands({"required_commands": "not-a-list"}) == ([], [])
    assert _check_required_commands({"required_commands": [None, {"noname": 1}, ""]}) == ([], [])


def test_resolver_finds_common_bin_dirs_outside_minimal_path():
    """Gateway/service processes run with a minimal PATH; the resolver must still
    find binaries in the usual user bin directories."""
    assert _resolve_command("python3") is not None
    assert _resolve_command("definitely-not-a-real-binary-xyz") is None


def test_untested_status_exists_and_is_distinct_from_setup_needed():
    assert SkillReadinessStatus.UNTESTED.value == "untested"
    assert SkillReadinessStatus.UNTESTED != SkillReadinessStatus.SETUP_NEEDED


def test_skill_view_reports_untested_for_absent_declared_command(tmp_path, monkeypatch):
    """End-to-end through the real skill_view payload."""
    skills_dir = tmp_path / "skills"
    probe = skills_dir / "probe-skill"
    probe.mkdir(parents=True)
    (probe / "SKILL.md").write_text(
        "---\nname: probe-skill\ndescription: \"probe\"\nversion: 1.0.0\n"
        "required_commands: [python3, definitely-not-a-real-binary-xyz]\n---\n# probe\n",
        encoding="utf-8")
    import tools.skills_tool as st
    monkeypatch.setattr(st, "_skills_dir", lambda: skills_dir)
    out = json.loads(st.skill_view("probe-skill"))
    assert out.get("required_commands") == ["python3", "definitely-not-a-real-binary-xyz"]
    assert out.get("missing_required_commands") == ["definitely-not-a-real-binary-xyz"]
    assert out.get("readiness_status") == "untested"
    # warn-but-allow: a missing binary must NOT block the way a missing credential does
    assert out.get("setup_needed") is False
