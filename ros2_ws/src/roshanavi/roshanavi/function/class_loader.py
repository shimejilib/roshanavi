"""Import a user's class from the workspace (same containment and hot reload as functions)."""

import inspect
from typing import Any, Optional

from .loader import FunctionLoader, _relative


class ClassLoader(FunctionLoader):
    """``FunctionLoader`` for a class: ``function`` / ``function_name`` hold the class."""

    member_label = 'class'

    def _check_member(self, member: Any, module: str) -> None:
        if not inspect.isclass(member):
            raise TypeError(f'{module}.{self.function_name} is not a class')

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._location: Optional[str] = None

    def load(self) -> Any:
        member = super().load()
        self._location = self._find_location()   # now, while the file on disk is the one loaded
        return member

    def location_of_function(self) -> Optional[str]:
        return self._location

    def _find_location(self) -> Optional[str]:
        if self.function is None or self.resolved is None:
            return None
        try:
            line = inspect.getsourcelines(self.function)[1]
            path = inspect.getsourcefile(self.function) or self.resolved.file
        except (OSError, TypeError):
            return _relative(self.resolved.file, self.resolved.package.base_dir)
        return f'{_relative(path, self.resolved.package.base_dir)}:{line}'
