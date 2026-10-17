"""Plain Python classes for roshanavi's class nodes (クラスノード) - no ROS inside.

A class node keeps ONE instance of a class alive: the ``__init__`` arguments become ROS
parameters, methods are bound to topics (or called by a button / a topic / a scenario step), and
the instance remembers things between calls. Nothing here imports rclpy: the classes are normal
Python, easy to test with pytest, and roshanavi does the ROS part.

    MovingAverage(window)   数値 -> 数値      average of the last ``window`` values; reset() forgets
    Counter()               文字列 -> 整数    how many messages arrived so far; reset() sets it to 0
    RunningStats()          数値 -> 平均・件数・最大 (1 つの dict を 3 つのトピックへ送り分け)

Try it: roshanavi -> 「＋ 関数・クラスノードを作る」 -> クラス -> module roshanavi_examples.stateful,
class MovingAverage, method process: input /number, output /average. Change the ``window``
parameter (the node is created again with the new value) and press 「reset を呼ぶ」.

Rules a class follows (docs/design/nodes.md):
- The methods are never called at the same time: no locks needed.
- ``__init__`` arguments with a type hint become parameters; changing one creates a new instance
  (state starts over) unless the class has ``on_param_change(name, value)``.
- After you save this file the instance is created again. To keep the state across a save, add
  ``get_state()`` / ``set_state(state)`` (see ``MovingAverage``).
- ``close()`` is called when the node stops.
"""

from typing import Dict, List, Optional


class MovingAverage:
    """The average of the last ``window`` numbers."""

    def __init__(self, window: int = 5):
        if window < 1:
            raise ValueError(f'window must be 1 or more (got {window})')
        self.window = window
        self.values: List[float] = []

    def process(self, x: float) -> float:
        """Remember ``x`` and return the average of the last ``window`` values."""
        self.values = (self.values + [x])[-self.window:]
        return sum(self.values) / len(self.values)

    def reset(self) -> None:
        """Forget every value (the next average starts from the next number)."""
        self.values = []

    def on_param_change(self, name: str, value: object) -> None:
        """Change ``window`` without losing the values that are still inside the new window."""
        if name == 'window':
            if not isinstance(value, int) or value < 1:
                raise ValueError(f'window must be 1 or more (got {value})')
            self.window = value
            self.values = self.values[-value:]

    def get_state(self) -> Dict[str, List[float]]:
        """Kept when this file is saved (hot reload): the numbers seen so far."""
        return {'values': list(self.values)}

    def set_state(self, state: Dict[str, List[float]]) -> None:
        self.values = list(state.get('values', []))[-self.window:]


class Counter:
    """Counts the messages it has received."""

    def __init__(self, start: int = 0):
        self.start = start
        self.count = start

    def process(self, text: str) -> int:
        """Return how many messages have arrived (including this one)."""
        self.count += 1
        return self.count

    def reset(self) -> None:
        """Go back to the start value."""
        self.count = self.start

    def close(self) -> None:
        """Called when the node stops (clean-up goes here: close files, sockets ...)."""
        print(f'Counter stopped at {self.count}')


class RunningStats:
    """Mean, count and maximum of every number so far. Returns one dict: each key is sent to its
    own topic (mean -> /stats/mean, count -> /stats/count, max -> /stats/max)."""

    def __init__(self):
        self.total = 0.0
        self.count = 0
        self.maximum: Optional[float] = None

    def process(self, x: float) -> Dict[str, float]:
        self.total += x
        self.count += 1
        self.maximum = x if self.maximum is None else max(self.maximum, x)
        return {'mean': self.total / self.count, 'count': self.count, 'max': self.maximum}

    def reset(self) -> None:
        self.__init__()
