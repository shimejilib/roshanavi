import type { TourDef, TourId } from '../types';
import { firstInputTour } from './firstInput';
import { functionNodeTour } from './functionNode';
import { overviewTour } from './overview';
import { qosFixTour } from './qosFix';
import { scenarioTour } from './scenario';

/** In the order they are offered (the first is the one the welcome card starts). */
export const TOURS: readonly TourDef[] = [overviewTour, firstInputTour, qosFixTour, functionNodeTour, scenarioTour];

export const tourById = (id: TourId): TourDef => TOURS.find((tour) => tour.id === id) ?? (overviewTour as TourDef);
