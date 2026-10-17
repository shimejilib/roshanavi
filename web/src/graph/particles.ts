// Flow-particle simulation (pure: no DOM, time is passed in; unit-tested).
//
// Emission rate per edge is proportional to the topic Hz, capped so a 1 kHz
// topic does not flood the screen. Topics at or below LOW_RATE_HZ do not emit
// continuously; instead they emit one particle per tick in which a message was
// actually received (`pulse`), so slow topics show real arrivals.

export const MAX_RATE_PER_EDGE = 6; // particles / s
export const TRAVEL_SEC = 1.2; // time for a particle to cross an edge
export const MAX_PARTICLES = 1200;
export const LOW_RATE_HZ = 1;

export interface FlowEdge {
  id: string;
  hz: number;
  /** false for stale / not monitored / QoS-incompatible edges. */
  flowing: boolean;
}

export interface Particle {
  edgeId: string;
  progress: number; // 0..1 along source -> target
}

export function emissionRate(hz: number): number {
  if (!(hz > LOW_RATE_HZ)) return 0;
  // sqrt keeps 2 Hz vs 50 Hz visibly different while staying under the cap.
  return Math.min(MAX_RATE_PER_EDGE, 1 + Math.sqrt(hz - LOW_RATE_HZ));
}

export class ParticleField {
  private edges = new Map<string, FlowEdge>();
  private credit = new Map<string, number>();
  private list: Particle[] = [];

  /** `rng` staggers the first particle per edge (injectable for tests). */
  constructor(private readonly rng: () => number = Math.random) {}

  setEdges(edges: readonly FlowEdge[]): void {
    this.edges = new Map(edges.map((e) => [e.id, e]));
    this.list = this.list.filter((p) => this.edges.get(p.edgeId)?.flowing);
    for (const id of [...this.credit.keys()]) if (!this.edges.has(id)) this.credit.delete(id);
  }

  /** One immediate particle (low-rate receipt). */
  pulse(edgeId: string): void {
    if (this.edges.get(edgeId)?.flowing && this.list.length < MAX_PARTICLES) {
      this.list.push({ edgeId, progress: 0 });
    }
  }

  step(dtSec: number): void {
    const dt = Math.max(0, Math.min(dtSec, 0.25)); // tab switch: avoid bursts
    const advanced: Particle[] = [];
    for (const p of this.list) {
      const progress = p.progress + dt / TRAVEL_SEC;
      if (progress < 1) advanced.push({ edgeId: p.edgeId, progress });
    }
    this.list = advanced;
    for (const e of this.edges.values()) {
      const rate = e.flowing ? emissionRate(e.hz) : 0;
      if (rate === 0) continue;
      let credit = (this.credit.get(e.id) ?? this.rng()) + rate * dt;
      while (credit >= 1 && this.list.length < MAX_PARTICLES) {
        credit -= 1;
        this.list.push({ edgeId: e.id, progress: 0 });
      }
      this.credit.set(e.id, Math.min(credit, 1));
    }
  }

  particles(): readonly Particle[] {
    return this.list;
  }

  clear(): void {
    this.list = [];
  }
}
