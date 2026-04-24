import SwiftUI

struct FallbackChainEditor: View {
    @Binding var chain: String
    let zaiKeySet: Bool
    let codexAvailable: Bool

    private let defaultChain = "opus,glm-5.1,sonnet,glm-4.7,haiku"

    private var models: [String] {
        chain.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }

    private var availableToAdd: [String] {
        ModelCatalog.all.map(\.id).filter { !models.contains($0) }
    }

    private func setModels(_ newModels: [String]) {
        chain = newModels.joined(separator: ",")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            ForEach(Array(models.enumerated()), id: \.element) { index, modelId in
                HStack(spacing: Spacing.sm) {
                    // Position badge
                    Text("\(index + 1)")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .frame(width: 16, alignment: .trailing)

                    // Model label
                    Text(ModelCatalog.label(for: modelId))
                        .font(.callout)

                    // Availability warnings by provider
                    let prov = ModelCatalog.provider(for: modelId)
                    if prov == "zai" && !zaiKeySet {
                        Text("sem API key")
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.orange)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 2)
                            .background(Color.orange.opacity(0.12))
                            .clipShape(Capsule())
                    } else if prov == "openai" && !codexAvailable {
                        Text("sem codex")
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.orange)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 2)
                            .background(Color.orange.opacity(0.12))
                            .clipShape(Capsule())
                    }

                    Spacer()

                    // Reorder buttons
                    HStack(spacing: 2) {
                        Button {
                            var m = models
                            m.swapAt(index, index - 1)
                            setModels(m)
                        } label: {
                            Image(systemName: "chevron.up")
                                .font(.caption)
                        }
                        .buttonStyle(.plain)
                        .disabled(index == 0)
                        .foregroundStyle(index == 0 ? Color.secondary.opacity(0.4) : .secondary)

                        Button {
                            var m = models
                            m.swapAt(index, index + 1)
                            setModels(m)
                        } label: {
                            Image(systemName: "chevron.down")
                                .font(.caption)
                        }
                        .buttonStyle(.plain)
                        .disabled(index == models.count - 1)
                        .foregroundStyle(index == models.count - 1 ? Color.secondary.opacity(0.4) : .secondary)
                    }

                    // Remove
                    Button {
                        var m = models
                        m.remove(at: index)
                        setModels(m)
                    } label: {
                        Image(systemName: "xmark")
                            .font(.caption)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                }
                .padding(.vertical, 4)
                .padding(.horizontal, Spacing.sm)
                .background(Color.primary.opacity(0.03))
                .clipShape(RoundedRectangle(cornerRadius: 6))
            }

            // Add model menu + reset
            HStack {
                if !availableToAdd.isEmpty {
                    Menu {
                        ForEach(availableToAdd, id: \.self) { modelId in
                            Button(ModelCatalog.label(for: modelId)) {
                                setModels(models + [modelId])
                            }
                        }
                    } label: {
                        Label("Adicionar modelo", systemImage: "plus")
                            .font(.callout)
                    }
                    .buttonStyle(.bordered)
                }

                Spacer()

                Button("Resetar padrão") {
                    chain = defaultChain
                }
                .buttonStyle(.bordered)
                .font(.callout)
            }
            .padding(.top, Spacing.xs)
        }
    }
}
