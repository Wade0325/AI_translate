import { describe, expect, it } from 'vitest';
import { textLinks } from './textLinks.js';

const URL = 'https://aka.ms/vc14/vc_redist.x64.exe';

describe('訊息裡的網址做成連結（#304）', () => {
  it('沒有網址時整段是一般文字', () => {
    expect(textLinks('這台電腦沒有可用的 NVIDIA 顯卡')).toEqual([
      { text: '這台電腦沒有可用的 NVIDIA 顯卡', url: null },
    ]);
  });

  it('網址前後有空白：切出網址，接起來還是原文', () => {
    const message = `本機轉錄不能用，從 ${URL} 下載安裝後重新開啟 Mimiji，或改用 Gemini`;
    const parts = textLinks(message);

    expect(parts).toEqual([
      { text: '本機轉錄不能用，從 ', url: null },
      { text: URL, url: URL },
      { text: ' 下載安裝後重新開啟 Mimiji，或改用 Gemini', url: null },
    ]);
    expect(parts.map((part) => part.text).join('')).toBe(message);
  });

  it('網址在全形括號裡：括號不算進網址', () => {
    expect(textLinks(`可轉散發套件（${URL}）後重新開啟`)).toEqual([
      { text: '可轉散發套件（', url: null },
      { text: URL, url: URL },
      { text: '）後重新開啟', url: null },
    ]);
  });

  it.each(['，', '。', '；', '、'])('網址後面直接接全形標點「%s」', (mark) => {
    expect(textLinks(`${URL}${mark}再試`)[0]).toEqual({ text: URL, url: URL });
  });

  it('只認 https，其他寫法照原樣', () => {
    expect(textLinks('http://example.com 與 ftp://example.com')).toEqual([
      { text: 'http://example.com 與 ftp://example.com', url: null },
    ]);
  });

  it('空的訊息沒有任何部分', () => {
    expect(textLinks(null)).toEqual([]);
    expect(textLinks('')).toEqual([]);
  });
});
