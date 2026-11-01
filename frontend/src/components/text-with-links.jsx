import { textLinks } from "@/utils/textLinks"

/**
 * 文字裡的 https 網址做成連結，在新分頁開啟；其餘照原樣。用在後端給的原因與下一步，例如本機轉錄
 * 缺 Microsoft Visual C++ 可轉散發套件時的下載網址（#304）。放在 Typography.Text 裡面用。
 */
export function TextWithLinks({ text }) {
    return textLinks(text).map((part, index) => part.url
        ? <a key={index} href={part.url} target="_blank" rel="noopener noreferrer">{part.text}</a>
        : <span key={index}>{part.text}</span>)
}
