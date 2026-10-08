interface Insight {
  title: string
  description: string
  emoji: string
}

interface InsightCardComponentProps {
  insight: Insight
  type: "bull" | "bear" |"info"
}

export function InsightCardComponent({ insight, type }: InsightCardComponentProps) {
  const getTypeStyles = () => {
    switch (type) {
      case "bull":
        return "border-l-4 border-l-[#00d237] bg-[var(--brand-accent)]/10"
      case "bear":
        return "border-l-4 border-l-red-500 bg-red-50"
      default:
        return "border-l-4 border-l-[var(--border-base)]"
    }
  }

  return (
    <div className={`bg-[var(--bg-surface)] border border-[var(--border-base)] rounded-xl p-3 ${getTypeStyles()}`}>
      <div className="flex items-start gap-2">
        <span className="text-lg">{insight.emoji}</span>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] font-['Roobert'] mb-1">{insight.title}</h3>
          <p className="text-xs text-[var(--text-secondary)] font-['Plus_Jakarta_Sans'] leading-relaxed">{insight.description}</p>
        </div>
      </div>
    </div>
  )
}
