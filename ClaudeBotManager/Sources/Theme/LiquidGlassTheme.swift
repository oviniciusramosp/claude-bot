import SwiftUI

// MARK: - Spacing Scale

enum Spacing {
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 12
    static let lg: CGFloat = 16
    static let xl: CGFloat = 20
    static let xxl: CGFloat = 24
}

// MARK: - Colors

extension Color {
    static let statusGreen = Color(red: 0.20, green: 0.78, blue: 0.35)
    static let statusRed   = Color(red: 0.95, green: 0.23, blue: 0.21)
    static let statusYellow = Color(red: 0.98, green: 0.75, blue: 0.14)
    static let statusBlue   = Color(red: 0.25, green: 0.56, blue: 0.98)

    static var glassBackground: Color { Color.primary.opacity(0.04) }
    static var glassBorder: Color { Color.primary.opacity(0.12) }
}

// MARK: - Glass Card

struct GlassCard<Content: View>: View {
    let content: Content
    var padding: CGFloat = 16

    init(padding: CGFloat = 16, @ViewBuilder content: () -> Content) {
        self.padding = padding
        self.content = content()
    }

    var body: some View {
        content
            .padding(padding)
            .background {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(.ultraThinMaterial)
                    .overlay {
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .strokeBorder(Color.glassBorder, lineWidth: 0.5)
                    }
            }
    }
}

// MARK: - Section Card

struct SectionCard<Content: View>: View {
    var title: String
    var symbol: String
    var content: Content

    init(title: String, symbol: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.symbol = symbol
        self.content = content()
    }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Spacing.md) {
                Label(title, systemImage: symbol)
                    .font(.headline)
                    .foregroundStyle(.primary)
                content
            }
        }
    }
}

// MARK: - Setting Row

struct SettingRow<Control: View>: View {
    var label: String
    var control: Control

    init(_ label: String, @ViewBuilder control: () -> Control) {
        self.label = label
        self.control = control()
    }

    var body: some View {
        HStack {
            Text(label)
                .font(.callout)
                .foregroundStyle(.secondary)
            Spacer()
            control
        }
    }
}

// MARK: - Status Dot

struct StatusDot: View {
    var isRunning: Bool
    var size: CGFloat = 8

    @State private var isPulsing = false

    var body: some View {
        Circle()
            .fill(isRunning ? Color.statusGreen : Color.statusRed)
            .frame(width: size, height: size)
            .shadow(color: (isRunning ? Color.statusGreen : Color.statusRed).opacity(0.6), radius: isPulsing ? 5 : 3)
            .scaleEffect(isPulsing ? 1.15 : 1.0)
            .animation(isRunning ? .easeInOut(duration: 1.2).repeatForever(autoreverses: true) : .default, value: isPulsing)
            .onChange(of: isRunning) { _, running in isPulsing = running }
            .onAppear { isPulsing = isRunning }
    }
}

// MARK: - Usage Bar

struct UsageBar: View {
    var percent: Double  // 0–1
    var label: String
    var sublabel: String

    private var barColor: Color {
        if percent < 0.6 { return .statusGreen }
        if percent < 0.85 { return .statusYellow }
        return .statusRed
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(sublabel)
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.primary)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 3)
                        .fill(Color.primary.opacity(0.08))
                    RoundedRectangle(cornerRadius: 3)
                        .fill(barColor)
                        .frame(width: geo.size.width * min(percent, 1.0))
                        .animation(.easeInOut(duration: 0.4), value: percent)
                }
            }
            .frame(height: 6)
        }
    }
}

// MARK: - Section Header

struct SectionHeader: View {
    var title: String
    var symbol: String

    var body: some View {
        Label(title, systemImage: symbol)
            .font(.headline)
            .foregroundStyle(.primary)
    }
}

// MARK: - Model Badge

struct ModelBadge: View {
    var model: String

    private var color: Color {
        switch model {
        case "opus": return .purple
        case "haiku": return .statusGreen
        default: return .statusBlue
        }
    }

    var body: some View {
        Text(model.capitalized)
            .font(.caption.bold())
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }
}

// MARK: - Tag Chip

struct TagChip: View {
    var tag: String

    var body: some View {
        Text(tag)
            .font(.caption2)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(Color.primary.opacity(0.08))
            .foregroundStyle(.secondary)
            .clipShape(Capsule())
    }
}

// MARK: - Weekly Segment Bar
// 7 separate segments with gaps and a pill-shaped reference marker (Figma spec)

struct WeeklySegmentBar: View {
    var percent: Double             // actual fill 0–1
    var referencePercent: Double    // elapsed fraction of the 7-day window 0–1
    var barColor: Color = .statusBlue

    private let segmentCount = 7
    private let segmentGap: CGFloat = 2
    private let barHeight: CGFloat = 10

    var body: some View {
        GeometryReader { geo in
            let totalGaps = segmentGap * CGFloat(segmentCount - 1)
            let segW = (geo.size.width - totalGaps) / CGFloat(segmentCount)

            // — Segments —
            HStack(spacing: segmentGap) {
                ForEach(0..<segmentCount, id: \.self) { i in
                    segmentView(index: i, segmentWidth: segW)
                }
            }

            // — Reference marker (white pill) —
            let refX = geo.size.width * min(max(referencePercent, 0), 1)
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.white)
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .strokeBorder(Color(white: 0.75), lineWidth: 1)
                )
                .frame(width: 4, height: 18)
                .shadow(color: .black.opacity(0.25), radius: 2, x: 0, y: 2)
                .offset(x: refX - 2, y: -4)
        }
        .frame(height: barHeight)
    }

    /// Each segment: background (unfilled) + colored fill clipped to the right fraction
    @ViewBuilder
    private func segmentView(index: Int, segmentWidth: CGFloat) -> some View {
        let corners = segmentCorners(index)
        let fillFraction = segmentFillFraction(index)

        ZStack(alignment: .leading) {
            // Background (unfilled)
            UnevenRoundedRectangle(
                topLeadingRadius: corners.leading,
                bottomLeadingRadius: corners.leading,
                bottomTrailingRadius: corners.trailing,
                topTrailingRadius: corners.trailing
            )
            .fill(Color.primary.opacity(0.05))

            // Fill
            if fillFraction > 0 {
                UnevenRoundedRectangle(
                    topLeadingRadius: corners.leading,
                    bottomLeadingRadius: corners.leading,
                    bottomTrailingRadius: fillFraction >= 1 ? corners.trailing : 2,
                    topTrailingRadius: fillFraction >= 1 ? corners.trailing : 2
                )
                .fill(barColor)
                .frame(width: segmentWidth * min(fillFraction, 1))
                .animation(.easeInOut(duration: 0.5), value: percent)
            }
        }
        .frame(width: segmentWidth, height: barHeight)
    }

    /// Corner radii: first segment rounded-left, last rounded-right, middle = 2
    private func segmentCorners(_ index: Int) -> (leading: CGFloat, trailing: CGFloat) {
        let cap: CGFloat = barHeight / 2  // full capsule end
        let flat: CGFloat = 2
        if index == 0                   { return (cap, flat) }
        if index == segmentCount - 1    { return (flat, cap) }
        return (flat, flat)
    }

    /// How much of this segment is filled (0 = empty, 1 = full, 0..<1 = partial)
    private func segmentFillFraction(_ index: Int) -> CGFloat {
        let segStart = CGFloat(index) / CGFloat(segmentCount)
        let segEnd   = CGFloat(index + 1) / CGFloat(segmentCount)
        let pct      = CGFloat(min(max(percent, 0), 1))

        if pct >= segEnd   { return 1 }
        if pct <= segStart { return 0 }
        return (pct - segStart) / (segEnd - segStart)
    }
}

// MARK: - Empty State

struct EmptyStateView: View {
    var symbol: String
    var title: String
    var subtitle: String

    var body: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: symbol)
                .font(.system(size: 48))
                .foregroundStyle(.tertiary)
            Text(title)
                .font(.headline)
                .foregroundStyle(.secondary)
            Text(subtitle)
                .font(.subheadline)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Custom Segmented Control (full-width)

struct CustomSegmentedControl: View {
    @Binding var selection: String
    var options: [(String, String)] // (value, label)

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(options.enumerated()), id: \.element.0) { idx, option in
                let isSelected = selection == option.0
                Button {
                    withAnimation(.easeInOut(duration: 0.15)) {
                        selection = option.0
                    }
                } label: {
                    Text(option.1)
                        .font(.system(size: 13, weight: .medium))
                        .frame(maxWidth: .infinity)
                        .frame(height: 22)
                        .foregroundStyle(isSelected ? .white : .primary)
                        .background(
                            Group {
                                if isSelected {
                                    RoundedRectangle(cornerRadius: 5)
                                        .fill(Color(red: 0.05, green: 0.44, blue: 1.0))
                                }
                            }
                        )
                }
                .buttonStyle(.plain)

                // Separator between non-selected segments
                if idx < options.count - 1 && selection != option.0 && selection != options[idx + 1].0 {
                    Color(white: 0.85).frame(width: 1, height: 14)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: 24)
        .background(Color.black.opacity(0.05))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}
