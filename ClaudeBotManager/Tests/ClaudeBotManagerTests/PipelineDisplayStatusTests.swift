import XCTest
@testable import ClaudeBotManager

/// Parity tests for `PipelineDisplayStatus` (Pipeline v2 spec § 5).
///
/// The Python enum `PipelineDisplayStatus` in `claude-fallback-bot.py` is the
/// SINGLE SOURCE OF TRUTH for the six display states. Swift mirrors those
/// raw values; if they ever drift, the dashboard renders garbage. These tests
/// hardcode the expected list so the parity contract is locked here even if
/// somebody refactors only one side.
final class PipelineDisplayStatusTests: XCTestCase {

    /// Hardcoded expected raw values, in the same declaration order as the
    /// Python enum (Idle, Scheduled, Running, Success, Failed, Skipped).
    /// Pipeline v2 spec § 5.3 — when this drifts from the Python definition
    /// the build is supposed to break.
    private static let expectedRawValues: [String] = [
        "Idle", "Scheduled", "Running", "Success", "Failed", "Skipped"
    ]

    // MARK: - Parity with Python enum

    func test_rawValuesMatchPythonEnumExactly() {
        let swiftRaw = PipelineDisplayStatus.allCases.map { $0.rawValue }
        XCTAssertEqual(
            swiftRaw,
            Self.expectedRawValues,
            "Swift PipelineDisplayStatus raw values drifted from the Python enum. " +
            "Update both sides together (claude-fallback-bot.py + this file)."
        )
    }

    func test_caseCountMatchesPython() {
        XCTAssertEqual(
            PipelineDisplayStatus.allCases.count,
            Self.expectedRawValues.count,
            "Swift PipelineDisplayStatus has a different number of cases than Python."
        )
    }

    func test_eachExpectedValueRoundTripsToCase() {
        for raw in Self.expectedRawValues {
            XCTAssertNotNil(
                PipelineDisplayStatus(rawValue: raw),
                "Missing Swift case for Python value \"\(raw)\""
            )
        }
    }

    func test_individualCaseRawValues() {
        XCTAssertEqual(PipelineDisplayStatus.idle.rawValue,      "Idle")
        XCTAssertEqual(PipelineDisplayStatus.scheduled.rawValue, "Scheduled")
        XCTAssertEqual(PipelineDisplayStatus.running.rawValue,   "Running")
        XCTAssertEqual(PipelineDisplayStatus.success.rawValue,   "Success")
        XCTAssertEqual(PipelineDisplayStatus.failed.rawValue,    "Failed")
        XCTAssertEqual(PipelineDisplayStatus.skipped.rawValue,   "Skipped")
    }

    // MARK: - JSON decoding from routines-state entries

    func test_decodesPrecomputedDisplayStatusFromEntry() {
        let entry: [String: Any] = [
            "status": "completed",
            "display_status": "Success",
            "publish_emitted": true,
        ]
        let result = PipelineDisplayStatus.from(
            stateEntry: entry,
            fallback: .completed
        )
        XCTAssertEqual(result, .success)
    }

    func test_decodesSkippedWhenPublishDidNotEmit() {
        // Phase 1 writes display_status="Skipped" when a completed run never
        // emitted to a sink. We trust the precomputed value verbatim.
        let entry: [String: Any] = [
            "status": "completed",
            "display_status": "Skipped",
            "publish_emitted": false,
        ]
        let result = PipelineDisplayStatus.from(
            stateEntry: entry,
            fallback: .completed
        )
        XCTAssertEqual(result, .skipped)
    }

    func test_legacyFallbackWhenDisplayStatusAbsent() {
        // Pre-v3.57.1 entries don't have display_status. Synthesize from
        // the lower-level execution status so the dashboard keeps working.
        let entry: [String: Any] = ["status": "completed"]
        let result = PipelineDisplayStatus.from(
            stateEntry: entry,
            fallback: .completed
        )
        XCTAssertEqual(result, .success)
    }

    func test_legacyFallbackForFailed() {
        let entry: [String: Any] = ["status": "failed"]
        let result = PipelineDisplayStatus.from(
            stateEntry: entry,
            fallback: .failed
        )
        XCTAssertEqual(result, .failed)
    }

    func test_legacyFallbackForRunning() {
        let entry: [String: Any] = ["status": "running"]
        let result = PipelineDisplayStatus.from(
            stateEntry: entry,
            fallback: .running
        )
        XCTAssertEqual(result, .running)
    }

    func test_legacyFallbackForSkippedExecutionStatus() {
        let entry: [String: Any] = ["status": "skipped"]
        let result = PipelineDisplayStatus.from(
            stateEntry: entry,
            fallback: .skipped
        )
        XCTAssertEqual(result, .skipped)
    }

    func test_legacyFallbackForPendingHonoursFutureFireFlag() {
        // No execution today + future fire scheduled → Scheduled
        let entryFuture: [String: Any] = ["status": "pending"]
        XCTAssertEqual(
            PipelineDisplayStatus.from(
                stateEntry: entryFuture,
                fallback: .pending,
                hasFutureFireToday: true
            ),
            .scheduled
        )
        // No execution today + nothing scheduled left → Idle
        XCTAssertEqual(
            PipelineDisplayStatus.from(
                stateEntry: entryFuture,
                fallback: .pending,
                hasFutureFireToday: false
            ),
            .idle
        )
    }

    func test_unknownDisplayStatusFallsBackToLegacy() {
        // If Python ever ships a string we don't yet recognise (e.g. a future
        // 7th case before the Swift mirror catches up), don't crash — fall
        // back to legacy synthesis so the dashboard keeps rendering something.
        let entry: [String: Any] = [
            "status": "completed",
            "display_status": "AwaitingApproval", // not a known value
        ]
        let result = PipelineDisplayStatus.from(
            stateEntry: entry,
            fallback: .completed
        )
        XCTAssertEqual(result, .success)
    }
}
