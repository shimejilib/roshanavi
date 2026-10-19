"""ROS terms in the messages the server shows in the UI: the official term, no plain-word swap.

web/src/i18n/glossary.ts is the glossary (docs/design/wiring.md); this is its server-side half:
scenario hints, diagnostics text, class parameter errors and the scaffold README must say
トピック / パラメータ / launch ファイル / QoS / メッセージ型 / リマップ, not the words the
#47 wording audit used instead (チャンネル, 設定値, 起動セット, 届け方の設定, データの形, 名前の付け替え).
"""

import pathlib
import re

import roshanavi

SOURCE = pathlib.Path(roshanavi.__file__).parent
OLD_WORDS = re.compile(r'チャンネル(?!数|変換)|設定値|起動セット|届け方の設定|データの形(?!式)|名前の付け替え')


def test_server_messages_use_the_official_ros_terms():
    bad = []
    for path in sorted(SOURCE.rglob('*.py')):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if OLD_WORDS.search(line):
                bad.append(f'{path.relative_to(SOURCE)}:{number}: {line.strip()[:80]}')
    assert bad == []


def test_scaffold_readme_uses_the_official_terms():
    from roshanavi.function import scaffold
    text = ' '.join(str(v) for v in vars(scaffold).values() if isinstance(v, str))
    assert OLD_WORDS.search(text) is None
