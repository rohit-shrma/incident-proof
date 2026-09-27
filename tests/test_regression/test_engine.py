import pytest

from claude_ops.regression.engine import RegressionTestGenerator


def test_generate_creates_verification_test():
    generator = RegressionTestGenerator()

    suite = generator.generate(
        incident="payment timeout",
        verification_command=("python", "verify.py"),
        expected_output=("PASS",),
    )

    assert suite.incident == "payment timeout"
    assert len(suite.tests) == 1
    assert suite.tests[0].name == "regression-payment-timeout"
    assert suite.tests[0].command == ("python", "verify.py")
    assert suite.tests[0].expected_output == ("PASS",)


def test_generate_from_reproduction_creates_two_tests():
    generator = RegressionTestGenerator()

    suite = generator.generate_from_reproduction(
        incident="payment timeout",
        reproduction_command=("python", "reproduce.py"),
        verification_command=("python", "verify.py"),
        expected_output=("PASS",),
    )

    assert len(suite.tests) == 2
    assert suite.tests[0].name == "reproduction-payment-timeout"
    assert suite.tests[1].name == "regression-payment-timeout"


def test_empty_incident_is_rejected():
    generator = RegressionTestGenerator()

    with pytest.raises(ValueError):
        generator.generate(
            incident="",
            verification_command=("python", "verify.py"),
        )


def test_empty_verification_command_is_rejected():
    generator = RegressionTestGenerator()

    with pytest.raises(ValueError):
        generator.generate(
            incident="payment timeout",
            verification_command=(),
        )


def test_empty_reproduction_command_is_rejected():
    generator = RegressionTestGenerator()

    with pytest.raises(ValueError):
        generator.generate_from_reproduction(
            incident="payment timeout",
            reproduction_command=(),
            verification_command=("python", "verify.py"),
        )