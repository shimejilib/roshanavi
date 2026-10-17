import { describe, expect, it } from 'vitest';
import { emissionRate, MAX_PARTICLES, MAX_RATE_PER_EDGE, ParticleField, TRAVEL_SEC } from './particles';

describe('emissionRate', () => {
  it('is zero for low-rate topics and capped for fast ones', () => {
    expect(emissionRate(0)).toBe(0);
    expect(emissionRate(1)).toBe(0);
    expect(emissionRate(2)).toBeCloseTo(2);
    expect(emissionRate(10)).toBeGreaterThan(emissionRate(2));
    expect(emissionRate(1000)).toBe(MAX_RATE_PER_EDGE);
  });
});

describe('ParticleField', () => {
  it('emits proportionally and retires particles after the travel time', () => {
    const field = new ParticleField(() => 0);
    field.setEdges([{ id: 'a', hz: 2, flowing: true }, { id: 'b', hz: 50, flowing: false }]);
    for (let i = 0; i < 10; i += 1) field.step(0.1); // 1 s at 2 particles/s
    expect(field.particles().filter((p) => p.edgeId === 'a')).toHaveLength(2);
    expect(field.particles().filter((p) => p.edgeId === 'b')).toHaveLength(0);
    field.setEdges([{ id: 'a', hz: 0, flowing: true }]);
    for (let i = 0; i < Math.ceil(TRAVEL_SEC / 0.1) + 1; i += 1) field.step(0.1);
    expect(field.particles()).toHaveLength(0);
  });

  it('pulses only flowing edges and respects the global cap', () => {
    const field = new ParticleField(() => 0);
    field.setEdges([{ id: 'slow', hz: 0.5, flowing: true }, { id: 'bad', hz: 0.5, flowing: false }]);
    field.pulse('slow');
    field.pulse('bad');
    field.pulse('missing');
    expect(field.particles()).toEqual([{ edgeId: 'slow', progress: 0 }]);
    const many = Array.from({ length: 500 }, (_, i) => ({ id: `e${i}`, hz: 1000, flowing: true }));
    field.setEdges(many);
    for (let i = 0; i < 20; i += 1) field.step(0.1);
    expect(field.particles().length).toBeLessThanOrEqual(MAX_PARTICLES);
  });

  it('drops particles of edges that stop flowing', () => {
    const field = new ParticleField(() => 0);
    field.setEdges([{ id: 'a', hz: 10, flowing: true }]);
    field.step(0.25);
    field.step(0.25);
    expect(field.particles().length).toBeGreaterThan(0);
    field.setEdges([{ id: 'a', hz: 10, flowing: false }]);
    expect(field.particles()).toHaveLength(0);
  });
});
