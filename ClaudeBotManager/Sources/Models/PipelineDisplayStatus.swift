import Foundation
import SwiftUI

/// Pipeline-level display status (Pipeline v2 spec § 5).
///
/// Mirrors the canonical Python enum `PipelineDisplayStatus` defined in
/// `claude-fallback-bot.py`. The Python side is the single source of truth —
/// every raw value here MUST match its Python counterpart byte-for-byte.
/// The parity test in `PipelineDisplayStatusTests.swift` locks this contract.
///
/// Priority order when multiple states could apply (see spec § 5.1):
///   Running > Failed > Success > Skipped > Scheduled > Idle
///
/// Decoding rule (Phase 2 — v3.58.2): when the routines-state JSON entry
/// carries a precomputed `display_status` field (Python writes this since
/// v3.57.1), use it directly. Otherwise fall back to legacy synthesis from
/// the lower-level execution status so back-compat with older state files
/// keeps working.
enum PipelineDisplayStatus: String, Sendable, CaseIterable {
    case idle      = "Idle"
    case scheduled = "Scheduled"
    case running   = "Running"
    case success   = "Success"
    case failed    = "Failed"
    case skipped   = "Skipped"

    /// SF Symbol name suitable for inline rendering next to a label.
    var symbol: String {
        switch self {
        case .idle:      return "moon.zzz"
        case .scheduled: return "clock"
        case .running:   return "arrow.trianglehead.2.clockwise"
        case .success:   return "checkmark.circle.fill"
        case .failed:    return "xmark.circle.fill"
        case .skipped:   return "forward.fill"
        }
    }

    /// Color coding that matches the existing dashboard design system
    /// (LiquidGlassTheme palette + RGB literals already used in DashboardView).
    var color: Color {
        switch self {
        case .idle:      return Color(red: 0.447, green: 0.447, blue: 0.447) // grey
        case .scheduled: return Color(red: 0.25, green: 0.56, blue: 0.98)    // statusBlue
        case .running:   return .orange
        case .success:   return Color(red: 0.204, green: 0.780, blue: 0.349) // statusGreen
        case .failed:    return Color(red: 1.0, green: 0.220, blue: 0.235)   // statusRed
        case .skipped:   return Color(red: 0.447, green: 0.447, blue: 0.447) // grey
        }
    }

    /// True when the pipeline is actively executing — drives the pulse
    /// animation on `StatusDot` so the dashboard reads as live.
    var isRunning: Bool { self == .running }

    /// Synthesize a display status from a legacy `RoutineExecution.Status`
    /// for entries that pre-date Phase 1 of Pipeline v2 (no `display_status`
    /// in the JSON). Used as the fallback path in `init(rawValueOrLegacy:)`.
    /// Note: `publish_emitted` is also a Phase 1 field; without it we can't
    /// distinguish a soft-success-with-no-publish from a real success, so a
    /// completed legacy run maps to `.success` (the previous UI behaviour).
    static func fromLegacy(_ status: RoutineExecution.Status,
                           hasFutureFireToday: Bool = false) -> PipelineDisplayStatus {
        switch status {
        case .running:   return .running
        case .failed:    return .failed
        case .completed: return .success
        case .skipped:   return .skipped
        case .pending:   return hasFutureFireToday ? .scheduled : .idle
        }
    }

    /// Decode from a JSON entry. Phase 1 entries carry `display_status`
    /// directly — trust it. Older entries (or entries written by a v1-only
    /// pipeline) lack the field and we fall back to synthesis.
    static func from(stateEntry entry: [String: Any],
                     fallback: RoutineExecution.Status,
                     hasFutureFireToday: Bool = false) -> PipelineDisplayStatus {
        if let raw = entry["display_status"] as? String,
           let parsed = PipelineDisplayStatus(rawValue: raw) {
            return parsed
        }
        return fromLegacy(fallback, hasFutureFireToday: hasFutureFireToday)
    }
}
