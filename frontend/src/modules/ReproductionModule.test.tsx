import { describe, expect, it } from 'vitest';

import { formatReproductionField } from './ReproductionModule';


describe('formatReproductionField', () => {
  it('explains unknown fields without presenting them as empty output', () => {
    expect(formatReproductionField('unknown')).toBe('论文上下文未提供');
    expect(formatReproductionField('unknown: 缺少明确指标')).toBe('论文上下文未提供：缺少明确指标');
  });

  it('keeps grounded report values unchanged', () => {
    expect(formatReproductionField('Visual Genome')).toBe('Visual Genome');
  });
});
