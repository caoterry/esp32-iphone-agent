import SwiftUI

/// The Provider row of the model form: the current provider's logo and name; tapping opens the list.
struct ProviderPicker: View {
    @ObservedObject var settings: Settings
    @State private var showing = false

    var body: some View {
        Button { showing = true } label: {
            LabeledContent("Provider") {
                HStack(spacing: Space.s) {
                    ProviderLogoView(provider: settings.provider, size: 20)
                    Text(verbatim: settings.provider.title).lineLimit(1)
                    Image(systemName: "chevron.right").font(.footnote).accessibilityHidden(true)
                }
                .foregroundStyle(.secondary)
            }
            .frame(minHeight: 44)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .sheet(isPresented: $showing) { ProviderSelectionView(settings: settings) }
    }
}

/// All providers with their logos: recommended first, a custom endpoint last.
struct ProviderSelectionView: View {
    @ObservedObject var settings: Settings
    @Environment(\.dismiss) private var dismiss

    private var listed: [ModelProvider] {
        let presets = ModelProvider.allCases.filter { $0 != .others }
        return presets.filter(\.recommended) + presets.filter { !$0.recommended }
    }

    var body: some View {
        NavigationStack {
            List {
                Section { ForEach(listed) { row($0) } }
                Section("Custom") { row(.others) }
            }
            .navigationTitle("Choose Provider")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
    }

    private func row(_ provider: ModelProvider) -> some View {
        Button {
            settings.selectedProvider = provider
            dismiss()
        } label: {
            HStack(spacing: Space.m) {
                ProviderLogoView(provider: provider, size: 28)
                VStack(alignment: .leading, spacing: 2) {
                    Text(verbatim: provider.title).foregroundStyle(.primary)
                    Text(provider == .others ? String(localized: "Any OpenAI-compatible endpoint") : provider.host)
                        .font(.footnote).foregroundStyle(.secondary)
                        .lineLimit(1).truncationMode(.middle)
                }
                Spacer()
                if provider.recommended { RecommendedBadge().fixedSize() }
                if settings.provider == provider {
                    Image(systemName: "checkmark").accessibilityLabel("Selected")
                }
            }
            .frame(minHeight: 44)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(settings.provider == provider ? .isSelected : [])
    }
}

/// A provider's monochrome mark in a rounded square (follows light / dark mode).
struct ProviderLogoView: View {
    let provider: ModelProvider
    let size: CGFloat

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.25, style: .continuous)
            .fill(Color(.secondarySystemFill))
            .frame(width: size, height: size)
            .overlay { mark.foregroundStyle(.primary) }
            .accessibilityHidden(true)
    }

    @ViewBuilder private var mark: some View {
        switch provider.logo {
        case .asset(let name):
            Image(name).resizable().scaledToFit().padding(size * 0.2)
        case .letter(let letter):
            Text(verbatim: letter).font(.system(size: size * 0.5, weight: .semibold, design: .rounded))
        case .symbol(let name):
            Image(systemName: name).font(.system(size: size * 0.45))
        }
    }
}

/// Small "Recommended" capsule, shared by the provider and model lists.
struct RecommendedBadge: View {
    var body: some View {
        Text("Recommended")
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, Space.s).padding(.vertical, 2)
            .overlay(Capsule().strokeBorder(.secondary.opacity(0.6)))
            .foregroundStyle(.secondary)
    }
}
