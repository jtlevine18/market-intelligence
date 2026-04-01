export function formatRs(n: number): string {
  return '\u20b9' + n.toLocaleString('en-IN')
}

export function directionArrow(dir: string): string {
  if (dir === 'up') return '\u2191'
  if (dir === 'down') return '\u2193'
  return '\u2192'
}

export function directionColor(dir: string): string {
  if (dir === 'up') return '#2a9d8f'
  if (dir === 'down') return '#e63946'
  return '#6b6b6b'
}
