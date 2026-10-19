"""Files roshanavi creates in the workspace belong to the folder's owner (docs/design/user-code.md).

In the Docker trial the server runs as root while ``/ws/src`` is a folder of the host user; what the
server creates there (「ひな形を作る」, 「ROS ノードのコードとして書き出す」, the launch export)
would be root-owned and the user could not edit it in an editor. So, only when the server runs as
root, every file / directory *this call just created* is handed to the owner of the directory it
was created in.

Rules (docs/design/security.md): only paths that did not exist before the call; ``os.lchown`` (a
symlink is never followed); nothing already there is touched; a failure is logged, never fatal;
nothing happens when not root or when the folder is root's own.
"""

import logging
import os
from typing import Iterable, List, Optional, Tuple

LOG = logging.getLogger(__name__)

Owner = Tuple[int, int]


def owner_for(directory: str) -> Optional[Owner]:
    """``(uid, gid)`` to give new files made in ``directory`` (it may not exist yet: the nearest
    existing parent counts), or None when nothing has to change (not root; owner is root)."""
    if os.geteuid() != 0:
        return None
    current = os.path.abspath(directory)
    while not os.path.isdir(current):
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    try:
        info = os.stat(current)
    except OSError as exc:
        LOG.warning('cannot read the owner of %s: %s', current, exc)
        return None
    owner = (info.st_uid, info.st_gid)
    return None if owner == (0, 0) else owner


def missing_dirs(directory: str) -> List[str]:
    """The directories ``os.makedirs(directory)`` would create, outermost first."""
    missing: List[str] = []
    current = os.path.abspath(directory)
    while not os.path.lexists(current):
        missing.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return missing[::-1]


def give_to(paths: Iterable[str], owner: Optional[Owner]) -> None:
    """``lchown`` each path (created by the caller just now) to ``owner``; no-op without one."""
    if owner is None:
        return
    uid, gid = owner
    for path in paths:
        try:
            os.lchown(path, uid, gid)
        except OSError as exc:
            LOG.warning('cannot give %s to uid %d: %s (the file stays root-owned)', path, uid, exc)


def makedirs_owned(directory: str) -> Optional[Owner]:
    """``os.makedirs(directory, exist_ok=True)``; the directories it creates get the owner of the
    nearest existing parent. Returns that owner (for the files written next)."""
    owner = owner_for(directory)
    created = missing_dirs(directory) if owner else []
    os.makedirs(directory, exist_ok=True)
    give_to([path for path in created if os.path.isdir(path)], owner)
    return owner
