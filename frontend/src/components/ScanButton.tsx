export function ScanButton({
  scanning,
  onClick,
  disabled,
}: {
  scanning: boolean
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <div className="flex justify-center px-4 py-5">
      <button
        type="button"
        disabled={disabled || scanning}
        onClick={onClick}
        className={
          scanning
            ? 'min-w-[280px] rounded-xl bg-blue-700/80 px-8 py-3.5 text-base font-semibold text-white shadow-lg shadow-blue-900/40'
            : 'min-w-[280px] rounded-xl bg-blue-600 px-8 py-3.5 text-base font-semibold text-white shadow-lg shadow-blue-900/40 transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50'
        }
      >
        {scanning ? (
          <span className="inline-flex items-center gap-2">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            Scan en cours...
          </span>
        ) : (
          'Scanner les OrderBlocks'
        )}
      </button>
    </div>
  )
}
