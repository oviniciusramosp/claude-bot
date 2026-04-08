import SwiftUI

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
                    .fill(.regularMaterial)
                    .overlay {
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .strokeBorder(Color.glassBorder, lineWidth: 0.5)
                    }
            }
    }
}

// MARK: - Status Dot

struct StatusDot: View {
    var isRunning: Bool
    var size: CGFloat = 8

    var body: some View {
        Circle()
            .fill(isRunning ? Color.statusGreen : Color.statusRed)
            .frame(width: size, height: size)
            .shadow(color: (isRunning ? Color.statusGreen : Color.statusRed).opacity(0.6), radius: 3)
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
            .font(.caption2.bold())
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
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

// MARK: - Empty State

struct EmptyStateView: View {
    var symbol: String
    var title: String
    var subtitle: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 40))
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
