import { describe, expect, it } from 'vitest';
import { formatLang, isUnverifiedLanguage, languages } from './languages';

const values = (options) => options.map((o) => o.value);
const group = (label) => languages.find((o) => o.label === label);

describe('語言選單（ADR-0002、#14 Q2、#13 Q5）', () => {
  it('最上面是 Auto Detect，下面是官方支援與未驗證兩組', () => {
    expect(languages.map((o) => o.label)).toEqual(['Auto Detect', '官方支援', '未驗證']);
    expect(languages[0].value).toBe('auto');
  });

  it('官方支援只有日文與中文（繁體）', () => {
    expect(values(group('官方支援').options)).toEqual(['ja', 'zh-TW']);
  });

  it('選單沒有 zh-CN：中文一律輸出繁體', () => {
    const all = [languages[0], ...group('官方支援').options, ...group('未驗證').options];
    expect(values(all)).not.toContain('zh-CN');
  });

  it('每個語言只出現一次', () => {
    const all = values([languages[0], ...group('官方支援').options, ...group('未驗證').options]);
    expect(new Set(all).size).toBe(all.length);
  });
});

describe('formatLang', () => {
  it('官方支援語言與 Auto Detect 只寫名稱', () => {
    expect(formatLang('ja')).toBe('Japanese');
    expect(formatLang('zh-TW')).toBe('Chinese (Traditional)');
    expect(formatLang('auto')).toBe('Auto Detect');
  });

  it('未驗證語言加上「（未驗證）」', () => {
    expect(formatLang('fr')).toBe('French（未驗證）');
    expect(formatLang('en')).toBe('English（未驗證）');
  });

  it('選單裡沒有的值（舊紀錄的 zh-CN）回傳原值', () => {
    expect(formatLang('zh-CN')).toBe('zh-CN');
  });
});

describe('isUnverifiedLanguage', () => {
  it('只有未驗證那一組算', () => {
    expect(isUnverifiedLanguage('ko')).toBe(true);
    expect(isUnverifiedLanguage('ja')).toBe(false);
    expect(isUnverifiedLanguage('zh-TW')).toBe(false);
    expect(isUnverifiedLanguage('auto')).toBe(false);
    expect(isUnverifiedLanguage('zh-CN')).toBe(false);
  });
});
