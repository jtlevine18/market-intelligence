interface Props {
  status: string
  className?: string
}

const STATUS_MAP: Record<string, { className: string; label?: string }> = {
  critical: { className: 'badge-red' },
  high: { className: 'badge-dark-orange' },
  moderate: { className: 'badge-orange' },
  low: { className: 'badge-green' },
  none: { className: 'badge-slate' },
  good: { className: 'badge-green' },
  poor: { className: 'badge-red' },
  ok: { className: 'badge-green' },
  success: { className: 'badge-green' },
  active: { className: 'badge-green' },
  partial: { className: 'badge-amber' },
  failed: { className: 'badge-red' },
  running: { className: 'badge-blue' },
  pending: { className: 'badge-slate' },
}

export default function StatusBadge({ status, className = '' }: Props) {
  const config = STATUS_MAP[status] ?? { className: 'badge-slate' }
  const label = config.label ?? status

  return (
    <span className={`${config.className} ${className}`}>
      {label}
    </span>
  )
}
