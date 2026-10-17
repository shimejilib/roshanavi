// データの種類 (data kinds): beginner-facing kinds instead of ROS type names (pure; docs/design/nodes.md).
// The kind <-> type table lives in the backend (roshanavi/data_kinds.py, GET /api/data-kinds);
// this module only labels, looks up and filters what the server sent.

import { t, type MessageKey } from '../i18n';

export type KindId = 'string' | 'float' | 'int' | 'bool' | 'numbers' | 'json' | 'image' | 'audio' | 'bytes';
/** `message` = 専用の型 / 詳細設定モード: any ROS type, edited as a template. */
export type PortKind = KindId | 'message';

export interface KindInfo {
  id: KindId;
  type: string;
  available: boolean;
  python: string;
}

export interface KindCatalog {
  kinds: KindInfo[];
  type_kinds: Record<string, KindId>;
  common_types: string[];
}

export interface TypeGroup {
  id: 'common' | 'workspace' | 'package';
  package?: string;
  types: string[];
}

/** The ROS side of an input / output: a kind and the type it resolved to. */
export interface PortValue {
  kind: PortKind | '';
  type: string;
}

export const EMPTY_CATALOG: KindCatalog = { kinds: [], type_kinds: {}, common_types: [] };

/** `std_msgs/String` -> `std_msgs/msg/String` (both spellings are accepted everywhere). */
export function normalizeType(type: string): string {
  const parts = type.trim().split('/');
  return parts.length >= 2 ? `${parts[0]}/msg/${parts[parts.length - 1]}` : type.trim();
}

/** `std_msgs/msg/String` -> `std_msgs/String` (the shorter spelling for labels). */
export function shortType(type: string): string {
  const parts = type.trim().split('/');
  return parts.length >= 2 ? `${parts[0]}/${parts[parts.length - 1]}` : type.trim();
}

export function kindLabel(kind: PortKind): string {
  return t(`kind.${kind}` as MessageKey);
}

/** The kind an existing topic's type is shown as; null = 専用の型. */
export function kindOfType(type: string, catalog: KindCatalog): KindId | null {
  return catalog.type_kinds[normalizeType(type)] ?? null;
}

/** 「文字列 (std_msgs/String)」 or 「専用の型: geometry_msgs/Twist」. */
export function describeType(type: string, catalog: KindCatalog): string {
  const kind = kindOfType(type, catalog);
  if (!kind) return t('kind.special', { type: shortType(type) });
  return t('kind.withType', { kind: kindLabel(kind), type: shortType(type) });
}

export function typeForKind(kind: PortKind | '', catalog: KindCatalog): string | null {
  return catalog.kinds.find((k) => k.id === kind)?.type ?? null;
}

export function portFromKind(kind: PortKind | '', catalog: KindCatalog, currentType = ''): PortValue {
  if (kind === 'message' || kind === '') return { kind, type: kind === 'message' ? currentType : '' };
  return { kind, type: typeForKind(kind, catalog) ?? '' };
}

/** An existing type (topic on the graph, or 詳細設定 choice) as a port. */
export function portFromType(type: string, catalog: KindCatalog): PortValue {
  const normalized = normalizeType(type);
  return { kind: kindOfType(normalized, catalog) ?? 'message', type: normalized };
}

/** The type of an existing port, kept with its own spelling for compatible types (Float32 ...). */
export function portOfSpec(kind: string | undefined, type: string | undefined, catalog: KindCatalog): PortValue {
  if (kind && kind !== 'message') return { kind: kind as KindId, type: type ? normalizeType(type) : typeForKind(kind as KindId, catalog) ?? '' };
  if (type) return kind === 'message' ? { kind: 'message', type: normalizeType(type) } : portFromType(type, catalog);
  return { kind: '', type: '' };
}

export function groupLabel(group: TypeGroup): string {
  if (group.id === 'package') return t('kind.group.package', { package: group.package ?? '' });
  return t(`kind.group.${group.id}` as MessageKey);
}

/** Groups narrowed by a search (type or package name); empty groups are dropped, order kept. */
export function filterGroups(groups: readonly TypeGroup[], query: string): TypeGroup[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return groups
    .map((g) => ({ ...g, types: g.types.filter((type) => words.every((w) => type.toLowerCase().includes(w))) }))
    .filter((g) => g.types.length > 0);
}
