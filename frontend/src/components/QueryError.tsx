import { cn } from "@/lib/utils"

interface QueryErrorProps {
  /** User-facing error message, e.g. from getErrorMessage(error). */
  message: string
  /** Calls the query's refetch. Omit to render without a Retry button. */
  onRetry?: () => void
  className?: string
}

/**
 * Shared failure-path fallback for the primary queries on each page. Styled to match the existing
 * "Loading…" / "Select a cluster" thin placeholders, but in the critical (brick) accent color.
 */
export default function QueryError({ message, onRetry, className }: QueryErrorProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center h-full gap-3 text-center px-6", className)}>
      <span className="material-symbols-outlined text-[28px] text-eo-brick">error_outline</span>
      <p className="text-xs font-mono text-eo-brick max-w-md">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-3 py-1.5 text-xs font-mono rounded border border-eo-border text-eo-stone hover:text-eo-cream hover:border-eo-amber transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  )
}
