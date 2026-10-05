export function PlaceholderTab({
  title,
  subtitle,
}: {
  title: string
  subtitle: string
}) {
  return (
    <div className="mx-auto flex max-w-lg flex-col items-center justify-center gap-3 px-6 py-24 text-center">
      <div className="rounded-full border border-zinc-800 bg-zinc-900 px-4 py-1 text-xs text-zinc-500">
        Phase 3+
      </div>
      <h2 className="text-xl font-semibold text-zinc-200">{title}</h2>
      <p className="text-sm leading-relaxed text-zinc-500">{subtitle}</p>
    </div>
  )
}
