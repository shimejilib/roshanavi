// Shapes of the node parameter and interface-definition API (docs/design/launcher.md).

export type ParamType =
  | 'not_set'
  | 'bool'
  | 'integer'
  | 'double'
  | 'string'
  | 'byte_array'
  | 'bool_array'
  | 'integer_array'
  | 'double_array'
  | 'string_array';

export type ParamJsonValue = boolean | number | string | boolean[] | number[] | string[] | null;

export interface ParamInfo {
  name: string;
  type: ParamType;
  value: ParamJsonValue;
  description: string;
  read_only: boolean;
  dynamic_typing: boolean;
  declared_type: ParamType;
  additional_constraints: string;
  range: { min: number; max: number; step: number } | null;
}

export interface ParamsResponse {
  node: string;
  role: string;
  external: boolean;
  parameters: ParamInfo[];
}

export interface ParamSetRequest {
  name: string;
  type: Exclude<ParamType, 'not_set'>;
  value: ParamJsonValue;
  allow_external?: boolean;
}

export interface InterfaceInfo {
  type: string;
  text: string;
  expanded: string;
  truncated: boolean;
}
