import { describe, expect, it } from 'vitest';
import { isUploadResultUncertain, UploadSubmitError } from '../../lib/uploadSubmit';

describe('uploadSubmit errors', () => {
  it('does not describe an explicit HTTP failure as an uncertain result', () => {
    const error = new UploadSubmitError('系统繁忙，请稍后再试', false);

    expect(isUploadResultUncertain(error)).toBe(false);
  });

  it('keeps network failures uncertain after the request was sent', () => {
    const error = new UploadSubmitError('网络异常', true);

    expect(isUploadResultUncertain(error)).toBe(true);
  });
});
