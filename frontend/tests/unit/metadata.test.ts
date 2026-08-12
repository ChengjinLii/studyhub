import { describe, expect, it } from 'vitest';
import {
  SUPPORTED_COLLEGES,
  SUPPORTED_MAJORS,
  UESTC_COLLEGES,
  getCollegeOptions,
  getMajorOptionsForCollege,
} from '../../constants/metadata';

describe('UESTC profile metadata', () => {
  it('provides the current college catalog and newly added majors', () => {
    expect(UESTC_COLLEGES).toHaveLength(20);
    expect(UESTC_COLLEGES.slice(0, 2)).toEqual(['格院', '信通']);
    expect(UESTC_COLLEGES).toContain('计算机科学与工程学院（网络空间安全学院）');
    expect(UESTC_COLLEGES).toEqual(expect.arrayContaining(['信通', '格院']));
    expect(UESTC_COLLEGES).not.toEqual(expect.arrayContaining(['信息与通信工程学院', '格拉斯哥学院', '格拉斯哥海南学院']));
    expect(SUPPORTED_MAJORS).toEqual(expect.arrayContaining(['量子信息科学', '低空技术与工程', '大数据管理与应用', '供应链管理']));
    expect(SUPPORTED_MAJORS).toEqual(expect.arrayContaining(['通信', '电工']));
    expect(SUPPORTED_MAJORS).not.toEqual(expect.arrayContaining(['通信工程', '电子信息工程']));
  });

  it('limits major choices to the selected college', () => {
    expect(getMajorOptionsForCollege('信通')).toEqual(['通信', '电工', '信息对抗技术', '网络工程', '物联网工程']);
    expect(getMajorOptionsForCollege('航空航天学院')).toContain('低空技术与工程');
    expect(getMajorOptionsForCollege('航空航天学院')).not.toContain('金融学');
  });

  it('uses the established StudyHub labels for communications and Glasgow programs', () => {
    expect(SUPPORTED_COLLEGES).toEqual(expect.arrayContaining(['格院', '信通']));
    expect(SUPPORTED_MAJORS).toEqual(expect.arrayContaining(['通信', '微电子', '电工']));
    expect(getMajorOptionsForCollege('信息与通信工程学院')).toEqual(expect.arrayContaining(['通信', '电工', '信息对抗技术']));
    expect(getCollegeOptions()).not.toEqual(expect.arrayContaining(['信息与通信工程学院', '格拉斯哥学院', '格拉斯哥海南学院']));
  });
});
