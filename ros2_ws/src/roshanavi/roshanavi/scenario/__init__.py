"""Scenario tests (docs/design/scenarios.md): schema, runner, CLI, JUnit, record mode.

Public API::

    from roshanavi.scenario import run_scenario
    result = run_scenario('scenarios/state_machine.yaml')
    assert result.passed, result.failures()
"""

from .result import Result
from .schema import Scenario, ScenarioSchemaError, load_file, parse_data, parse_text


def run_scenario(path, **kwargs) -> Result:
    """See :func:`roshanavi.scenario.api.run_scenario` (imported lazily: needs rclpy)."""
    from .api import run_scenario as _run
    return _run(path, **kwargs)


__all__ = ['Result', 'Scenario', 'ScenarioSchemaError', 'load_file', 'parse_data', 'parse_text',
           'run_scenario']
