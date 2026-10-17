// Step texts may mark `code` with backticks; everything else is plain text (no HTML anywhere).

export interface TextSegment {
  text: string;
  code: boolean;
}

export function richSegments(text: string): TextSegment[] {
  return text
    .split('`')
    .map((part, index) => ({ text: part, code: index % 2 === 1 }))
    .filter((segment) => segment.text !== '');
}
