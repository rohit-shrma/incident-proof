from __future__ import annotations

import sys

import pytest

from claude_ops.reproduction.engine import (
    ReproductionEngine,
    ReproductionScenario,
)


def test_reproduces_expected_failure():
    scenario = ReproductionScenario(
        name="intentional failure",
        command=(
            sys.executable,
            "-c",
            "print('OOMKilled: container exceeded memory limit'); raise SystemExit(1)",
        ),
        expected_failure_tokens=("OOMKilled", "memory limit"),
    )

    result = ReproductionEngine().run(scenario)

    assert result.reproduced is True
    assert result.command_result is not None
    assert result.command_result.exit_code == 1
    assert "OOMKilled" in result.command_result.stdout
    assert "Failure tokens matched" in result.evidence[1]


def test_successful_command_is_not_reproduced():
    scenario = ReproductionScenario(
        name="healthy command",
        command=(sys.executable, "-c", "print('service healthy')"),
        expected_failure_tokens=("OOMKilled",),
    )

    result = ReproductionEngine().run(scenario)

    assert result.reproduced is False
    assert result.command_result is not None
    assert result.command_result.exit_code == 0


def test_failure_without_expected_tokens_is_not_reproduced():
    scenario = ReproductionScenario(
        name="different failure",
        command=(
            sys.executable,
            "-c",
            "print('connection refused'); raise SystemExit(1)",
        ),
        expected_failure_tokens=("OOMKilled",),
    )

    result = ReproductionEngine().run(scenario)

    assert result.reproduced is False
    assert result.command_result is not None
    assert result.command_result.exit_code == 1


def test_timeout_is_captured():
    scenario = ReproductionScenario(
        name="timeout scenario",
        command=(
            sys.executable,
            "-c",
            "import time; time.sleep(2)",
        ),
        timeout_seconds=1,
    )

    result = ReproductionEngine().run(scenario)

    assert result.reproduced is False
    assert result.command_result is not None
    assert result.command_result.timed_out is True


def test_invalid_scenario_is_rejected():
    engine = ReproductionEngine()

    with pytest.raises(ValueError):
        engine.run(
            ReproductionScenario(
                name="",
                command=(sys.executable, "-c", "print('x')"),
            )
        )

    with pytest.raises(ValueError):
        engine.run(
            ReproductionScenario(
                name="missing command",
                command=(),
            )
        )

    with pytest.raises(ValueError):
        engine.run(
            ReproductionScenario(
                name="bad timeout",
                command=(sys.executable, "-c", "print('x')"),
                timeout_seconds=0,
            )
        )