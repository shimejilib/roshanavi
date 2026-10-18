"""Read and change parameters of a running node through its parameter services.

Every rclpy / rclcpp node offers ``<node>/list_parameters``, ``describe_parameters``,
``get_parameters`` and ``set_parameters`` (rcl_interfaces). This module calls them
from the server's own node with a timeout on every step, so an unresponsive node
can never hang a request. Value conversion (``value_to_msg`` / ``value_from_msg``)
is pure and checks types strictly before anything is sent.
"""

import logging
import math
import re
from typing import Any, Dict, List, Tuple

from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import (DescribeParameters, GetParameters, ListParameters,
                                SetParameters)
from .api_errors import ApiError
from .ros_runtime import RosRuntime
from .service_call import ServiceCaller, ServiceErrors
from .service_defaults import DEFAULT_SERVICE_TIMEOUT_SEC

LOG = logging.getLogger(__name__)

READ_RETRIES = 1  # reads are repeated once when the node did not answer in time; set is not
MAX_PARAMS = 500
MAX_CACHED_CLIENTS = 24
MAX_STRING = 4096
MAX_ARRAY = 1000
INT64_MIN, INT64_MAX = -2 ** 63, 2 ** 63 - 1

NODE_RE = re.compile(r'^(/[A-Za-z_][A-Za-z0-9_]*)+$')
# rclcpp names contain dots and, for QoS overrides, slashes (qos_overrides./chatter.publisher...).
PARAM_NAME_RE = re.compile(r'^[A-Za-z_/][A-Za-z0-9_./]{0,255}$')

TYPE_NAMES = {
    ParameterType.PARAMETER_NOT_SET: 'not_set',
    ParameterType.PARAMETER_BOOL: 'bool',
    ParameterType.PARAMETER_INTEGER: 'integer',
    ParameterType.PARAMETER_DOUBLE: 'double',
    ParameterType.PARAMETER_STRING: 'string',
    ParameterType.PARAMETER_BYTE_ARRAY: 'byte_array',
    ParameterType.PARAMETER_BOOL_ARRAY: 'bool_array',
    ParameterType.PARAMETER_INTEGER_ARRAY: 'integer_array',
    ParameterType.PARAMETER_DOUBLE_ARRAY: 'double_array',
    ParameterType.PARAMETER_STRING_ARRAY: 'string_array',
}
TYPE_IDS = {name: tid for tid, name in TYPE_NAMES.items()}
FIELDS = {'bool': 'bool_value', 'integer': 'integer_value', 'double': 'double_value',
          'string': 'string_value', 'byte_array': 'byte_array_value',
          'bool_array': 'bool_array_value', 'integer_array': 'integer_array_value',
          'double_array': 'double_array_value', 'string_array': 'string_array_value'}
SETTABLE_TYPES = tuple(FIELDS)
PARAM_ERRORS = ServiceErrors('param_service_unavailable', 'param_timeout', 'param_call_failed',
                             'parameter')


def check_node_name(node: str) -> str:
    if not NODE_RE.match(node) or len(node) > 256:
        raise ApiError('invalid_node_name', f'invalid node name {node!r}')
    return node


def check_param_name(name: str) -> str:
    if not PARAM_NAME_RE.match(name) or '..' in name:
        raise ApiError('invalid_param_name', f'invalid parameter name {name!r}')
    return name


# ---- value conversion (pure) ---------------------------------------------
def _scalar(kind: str, value: Any) -> Any:
    if kind == 'bool':
        if not isinstance(value, bool):
            raise ApiError('invalid_param_value', 'expected true or false')
        return value
    if kind == 'integer':
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError('invalid_param_value', 'expected a whole number')
        if not INT64_MIN <= value <= INT64_MAX:
            raise ApiError('invalid_param_value', 'the number is out of the 64-bit range')
        return value
    if kind == 'double':
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError('invalid_param_value', 'expected a number')
        if not math.isfinite(float(value)):
            raise ApiError('invalid_param_value', 'the number must be finite')
        return float(value)
    if not isinstance(value, str):
        raise ApiError('invalid_param_value', 'expected text')
    if len(value) > MAX_STRING:
        raise ApiError('invalid_param_value', f'text longer than {MAX_STRING} characters')
    return value


def value_to_msg(type_name: str, value: Any) -> ParameterValue:
    """Strictly typed JSON value -> ``ParameterValue`` (ApiError on any mismatch)."""
    if type_name not in FIELDS:
        raise ApiError('invalid_param_type', f'unsupported parameter type {type_name!r}')
    msg = ParameterValue(type=TYPE_IDS[type_name])
    if type_name.endswith('_array'):
        if not isinstance(value, list) or len(value) > MAX_ARRAY:
            raise ApiError('invalid_param_value', f'expected a list of up to {MAX_ARRAY} items')
        if type_name == 'byte_array':
            items = [_scalar('integer', v) for v in value]
            if any(not 0 <= v <= 255 for v in items):
                raise ApiError('invalid_param_value', 'bytes must be 0..255')
            setattr(msg, FIELDS[type_name], [bytes([v]) for v in items])
        else:
            kind = type_name[:-len('_array')]
            setattr(msg, FIELDS[type_name], [_scalar(kind, v) for v in value])
        return msg
    setattr(msg, FIELDS[type_name], _scalar(type_name, value))
    return msg


def value_from_msg(msg: ParameterValue) -> Tuple[str, Any]:
    """``ParameterValue`` -> (type name, JSON-friendly value)."""
    type_name = TYPE_NAMES.get(msg.type, 'not_set')
    if type_name == 'not_set':
        return type_name, None
    value = getattr(msg, FIELDS[type_name])
    if type_name == 'byte_array':
        return type_name, [b[0] if isinstance(b, bytes) else int(b) for b in value]
    if type_name.endswith('_array'):
        return type_name, list(value)
    return type_name, value


def descriptor_dict(desc: Any) -> Dict[str, Any]:
    ranges = list(desc.integer_range) + list(desc.floating_point_range)
    rng = ranges[0] if ranges else None
    return {'description': desc.description,
            'read_only': bool(desc.read_only),
            'dynamic_typing': bool(getattr(desc, 'dynamic_typing', False)),
            'declared_type': TYPE_NAMES.get(desc.type, 'not_set'),
            'additional_constraints': desc.additional_constraints,
            'range': ({'min': rng.from_value, 'max': rng.to_value, 'step': rng.step}
                      if rng is not None else None)}


# ---- service calls ---------------------------------------------------------
class ParamService:
    """Calls a node's parameter services from the roshanavi node (thread-safe)."""

    def __init__(self, runtime: RosRuntime, timeout_sec: float = DEFAULT_SERVICE_TIMEOUT_SEC):
        self._caller = ServiceCaller(runtime, PARAM_ERRORS, timeout_sec, MAX_CACHED_CLIENTS)

    def _call(self, node: str, suffix: str, srv_type: type, request: Any,
              retries: int = READ_RETRIES) -> Any:
        return self._caller.call(node, suffix, srv_type, request, retries=retries)

    def list(self, node: str) -> List[Dict[str, Any]]:
        """All parameters with type, value and descriptor, sorted by name."""
        check_node_name(node)
        names = list(self._call(node, 'list_parameters', ListParameters,
                                ListParameters.Request(prefixes=[], depth=0)).result.names)
        names = sorted(names)[:MAX_PARAMS]
        if not names:
            return []
        descs = self._call(node, 'describe_parameters', DescribeParameters,
                           DescribeParameters.Request(names=names)).descriptors
        values = self._call(node, 'get_parameters', GetParameters,
                            GetParameters.Request(names=names)).values
        result = []
        for name, desc, value in zip(names, descs, values):
            type_name, py_value = value_from_msg(value)
            result.append({'name': name, 'type': type_name, 'value': py_value,
                           **descriptor_dict(desc)})
        return result

    def describe(self, node: str, name: str) -> Dict[str, Any]:
        descs = self._call(node, 'describe_parameters', DescribeParameters,
                           DescribeParameters.Request(names=[name])).descriptors
        if not descs:
            raise ApiError('param_not_found', f'{node} has no parameter {name!r}', 404)
        return descriptor_dict(descs[0])

    def get(self, node: str, name: str) -> Dict[str, Any]:
        values = self._call(node, 'get_parameters', GetParameters,
                            GetParameters.Request(names=[name])).values
        type_name, value = value_from_msg(values[0]) if values else ('not_set', None)
        return {'name': name, 'type': type_name, 'value': value}

    def set(self, node: str, name: str, type_name: str, value: Any) -> Dict[str, Any]:
        """Check the descriptor (read-only, type), set, and return the new value."""
        check_node_name(node)
        check_param_name(name)
        msg = value_to_msg(type_name, value)
        desc = self.describe(node, name)
        if desc['read_only']:
            raise ApiError('param_read_only', f'{name} is read-only on {node}')
        declared = desc['declared_type']
        if declared not in ('not_set', type_name) and not desc['dynamic_typing']:
            raise ApiError('param_type_mismatch', f'{name} is a {declared} parameter, '
                           f'not {type_name}')
        results = self._call(node, 'set_parameters', SetParameters, SetParameters.Request(
            parameters=[Parameter(name=name, value=msg)]), retries=0).results
        if not results or not results[0].successful:
            reason = results[0].reason if results else 'no result'
            raise ApiError('param_rejected', f'{node} rejected {name}: {reason}')
        LOG.info('parameter %s on %s set (%s)', name, node, type_name)
        return {**self.get(node, name), **desc}

    def close(self) -> None:
        self._caller.close()
