"""Subprocess entry: ``python3 -m roshanavi.launch_import.child`` (docs/design/launcher.md).

Reads ``{"path", "args"}`` as JSON on stdin, loads the launch file (Python /
XML / YAML) and walks it with :mod:`.walker`, then writes one JSON object to
the *original* stdout. Anything the launch file itself prints goes to stderr,
so it can never corrupt the result. Started by :mod:`.runner` with a timeout
in its own session; this module must never run inside the server process.
"""

import json
import os
import sys
from typing import Any, Dict, List

from launch import LaunchContext
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.utilities import perform_substitutions

from .walker import WalkResult, walk

NO_DESCRIPTION = 'no description given'  # launch's placeholder text


def _text(context: Any, substitutions: Any) -> Any:
    if substitutions is None:
        return None
    try:
        return perform_substitutions(context, substitutions)
    except Exception:  # depends on something not known yet: show the expression instead
        return ''.join(s.describe() for s in substitutions)


def describe_arguments(description: Any, context: Any) -> List[Dict[str, Any]]:
    result, seen = [], set()
    for arg in description.get_launch_arguments():
        if arg.name in seen:
            continue
        seen.add(arg.name)
        result.append({'name': arg.name, 'default': _text(context, arg.default_value),
                       'description': '' if arg.description == NO_DESCRIPTION
                       else arg.description or '',
                       'choices': list(arg.choices) if arg.choices else None,
                       'conditional': bool(getattr(arg, '_conditionally_included', False))})
    return result


def evaluate(path: str, args: Dict[str, str]) -> Dict[str, Any]:
    context = LaunchContext()
    description = AnyLaunchDescriptionSource(path).get_launch_description(context)
    for name, value in args.items():
        context.launch_configurations[name] = value
    context.extend_locals({'current_launch_file_path': path,
                           'current_launch_file_directory': os.path.dirname(path)})
    arguments = describe_arguments(description, context)
    missing = [a['name'] for a in arguments
               if a['default'] is None and not a['conditional'] and a['name'] not in args]
    base = {'ok': True, 'file': path, 'arguments': arguments, 'missing_args': missing}
    if missing:
        return {**base, **WalkResult().to_dict()}
    result = WalkResult()
    walk(description, context, result)
    return {**base, **result.to_dict()}


def main() -> int:
    result_fd = os.dup(1)
    os.dup2(2, 1)  # the launch file's own prints go to stderr
    try:
        request = json.load(sys.stdin)
        payload = evaluate(str(request['path']), dict(request.get('args') or {}))
    except Exception as exc:  # report everything (syntax errors, missing packages ...)
        payload = {'ok': False, 'error': {'code': 'launch_eval_failed',
                                          'message': f'{type(exc).__name__}: {exc}'[:2000]}}
    with os.fdopen(result_fd, 'w', encoding='utf-8') as out:
        json.dump(payload, out, default=str)
    return 0


if __name__ == '__main__':
    sys.exit(main())
