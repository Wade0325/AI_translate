/** 產生前端用的唯一識別碼（file uid / session / batch id，非加密用途）。 */
export function randomId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}
