import type { Page } from '@playwright/test';

type Cy = { getElementById: (i: string) => { renderedPosition: () => { x: number; y: number } } };

/** Click a cytoscape element at its rendered position (cytoscape keeps its instance on the container). */
export async function clickElement(page: Page, elementId: string, button: 'left' | 'right' = 'left') {
  const canvas = page.getByTestId('graph-canvas');
  const pos = await canvas.evaluate((el, id) => (el as unknown as { _cyreg: { cy: Cy } })._cyreg.cy.getElementById(id).renderedPosition(), elementId);
  const box = await canvas.boundingBox();
  if (!box) throw new Error('graph canvas not visible');
  await page.mouse.click(box.x + pos.x, box.y + pos.y, { button });
}

export const rightClickNode = (page: Page, elementId: string) => clickElement(page, elementId, 'right');

/** Right-click the empty top-right corner of the map (the legend sits bottom-left). */
export async function rightClickBlank(page: Page) {
  const box = await page.getByTestId('graph-canvas').boundingBox();
  if (!box) throw new Error('graph canvas not visible');
  await page.mouse.click(box.x + box.width - 16, box.y + 16, { button: "right" });
}
