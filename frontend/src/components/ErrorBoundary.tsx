import { Component, type ErrorInfo, type ReactNode } from "react"

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

/** Top-level fallback for uncaught render errors anywhere in the routed app. */
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Unhandled UI error", error, errorInfo)
  }

  handleReload = () => {
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-eo-bg flex items-center justify-center p-6">
          <div className="w-full max-w-sm bg-eo-surface border border-eo-border rounded-lg p-6 text-center">
            <span className="material-symbols-outlined text-[32px] text-eo-brick mb-3 inline-block">
              error_outline
            </span>
            <h2 className="text-lg font-semibold text-eo-cream mb-1">Something went wrong</h2>
            <p className="text-xs text-eo-stone mb-6">
              {this.state.error?.message ?? "An unexpected error occurred."}
            </p>
            <button
              onClick={this.handleReload}
              className="w-full py-2 bg-eo-amber text-eo-bg rounded font-semibold text-sm hover:bg-eo-light-amber transition-colors"
            >
              Reload
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
