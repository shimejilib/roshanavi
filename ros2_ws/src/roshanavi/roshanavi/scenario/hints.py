"""Likely causes of a failed step, from the ROS graph (pure; reuses diagnostics / qos_compat).

``hints(raw, inputs, outputs)`` looks only at the topics the failed step uses:
no publisher on a checked topic (with similar published names), nobody
subscribing to a sent topic, QoS pairs that DDS will not connect, and topics
advertised with several types.
"""

from typing import Any, Dict, Iterable, List, Sequence

from ..diagnostics import names_similar
from ..graph import RawGraph
from ..qos_compat import incompatible_pairs
from ..ros_runtime import is_self_node

POLICY_TEXT = {'reliability': '信頼性 (reliability)', 'durability': '保存 (durability)',
               'deadline': '期限 (deadline)', 'liveliness': '生存確認 (liveliness)',
               'liveliness_lease': '生存確認の期間 (lease)'}


def _hint(code: str, topic: str, message: str) -> Dict[str, Any]:
    return {'code': code, 'topic': topic, 'message': message}


def _others(endpoints: Iterable[Any]) -> List[str]:
    return sorted({e.node for e in endpoints if not is_self_node(e.node)})


def _similar(topic: str, candidates: Iterable[str]) -> List[str]:
    return sorted(c for c in candidates if names_similar(topic, c))


def _edges(raw: RawGraph, topics: Sequence[str]) -> List[Dict[str, Any]]:
    edges = []
    for topic in topics:
        for direction, table in (('pub', raw.publishers), ('sub', raw.subscribers)):
            for ep in table.get(topic, []):
                edges.append({'node': ep.node, 'topic': topic, 'dir': direction, 'qos': ep.qos})
    return edges


def _node_label(node: str) -> str:
    return 'roshanavi (シナリオ)' if is_self_node(node) else node


def hints(raw: RawGraph, inputs: Sequence[str] = (), outputs: Sequence[str] = ()
          ) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    published = [t for t, eps in raw.publishers.items() if _others(eps)]
    subscribed = [t for t, eps in raw.subscribers.items() if _others(eps)]
    for topic in outputs:
        if _others(raw.publishers.get(topic, [])):
            continue
        text = (f'{topic} に送信しているノードがいません (ノードが起動していない・落ちた、トピックの名前の'
                '打ち間違い、リマップ忘れなど)。')
        similar = _similar(topic, published)
        if similar:
            text += f'似た名前で送信されているトピック: {", ".join(similar)}。'
        result.append(_hint('no_publisher', topic, text))
    for topic in inputs:
        if _others(raw.subscribers.get(topic, [])):
            continue
        text = f'{topic} を受信しているノードがいません (送っても誰も受け取りません)。'
        similar = _similar(topic, subscribed)
        if similar:
            text += f'似た名前で受信されているトピック: {", ".join(similar)}。'
        result.append(_hint('no_subscriber', topic, text))
    topics = list(dict.fromkeys([*inputs, *outputs]))
    for pair in incompatible_pairs(_edges(raw, topics)):
        reasons = '、'.join(f'{POLICY_TEXT.get(r["policy"], r["policy"])}: 送信側 {r["pub"]} / '
                           f'受信側 {r["sub"]}' for r in pair['reasons'])
        result.append(_hint('qos_incompatible', pair['topic'],
                            f'{pair["topic"]}: {_node_label(pair["publisher"])} → '
                            f'{_node_label(pair["subscriber"])} は QoS が合わないためつながりません '
                            f'({reasons})。'))
    for topic in topics:
        types = sorted(set(raw.topics.get(topic, [])))
        if len(types) > 1:
            result.append(_hint('type_mismatch', topic, f'{topic} は複数の型 ({", ".join(types)}) で'
                                '使われています。送る側と受ける側で型をそろえてください。'))
    return result
