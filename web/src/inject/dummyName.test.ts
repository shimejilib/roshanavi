import { describe, expect, it } from 'vitest';
import { suggestDummyName } from './dummyName';

describe('suggestDummyName', () => {
  it('derives a valid ROS node name from the topic', () => {
    expect(suggestDummyName('/camera/image_raw')).toBe('dummy_image_raw');
    expect(suggestDummyName('/scan-2')).toBe('dummy_scan_2');
    expect(suggestDummyName('/3d')).toBe('dummy__3d');
    expect(suggestDummyName(null)).toBe('dummy_input');
  });
});
