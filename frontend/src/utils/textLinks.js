/**
 * 後端的訊息裡有下載網址時（例如本機轉錄缺 Microsoft Visual C++ 可轉散發套件，#304），切出網址，
 * 畫面上才能做成可以點的連結，使用者不必自己選取複製。
 *
 * 只認 https://：後端寫的網址都是 https。網址在空白或全形標點（，。；、：「」（））前結束，
 * 中文句子裡的網址後面不必空一格。
 */
const URL_PATTERN = /https:\/\/[^\s，。；、：「」（）]+/g;

/** [{ text, url }]：url 是網址或 null（一般文字）；照原文的順序，接起來就是原文。 */
export function textLinks(text) {
  if (!text) return [];
  const parts = [];
  let last = 0;
  for (const match of text.matchAll(URL_PATTERN)) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index), url: null });
    parts.push({ text: match[0], url: match[0] });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), url: null });
  return parts;
}
