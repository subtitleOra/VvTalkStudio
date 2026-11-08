import SwiftUI

@main
struct VvTalkStudioApp: App {
    @StateObject private var model = StudioModel()

    var body: some Scene {
        Window("VvTalk Studio", id: "studio") {
            StudioView(model: model)
        }
        .defaultSize(width: 1260, height: 800)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("新建文稿") { model.newProject() }
                    .keyboardShortcut("n")
                    .disabled(model.busy)
                Button("打开工程或文本…") { Task { await model.open() } }
                    .keyboardShortcut("o")
                    .disabled(model.busy)
                Button("导入参考素材…") { model.beginReference() }
                    .keyboardShortcut("i")
                    .disabled(model.busy)
                Divider()
                Button("保存") { Task { await model.save() } }
                    .keyboardShortcut("s")
                    .disabled(!model.canSave)
                Button("另存为…") { Task { await model.save(asNew: true) } }
                    .keyboardShortcut("s", modifiers: [.command, .shift])
                    .disabled(!model.canSave)
                Button("导出 \(model.target.ext.uppercased())…") { Task { await model.export() } }
                    .keyboardShortcut("e")
                    .disabled(!model.canSave)
            }
            CommandMenu("语调") {
                Button("生成语调") { Task { await model.generate() } }
                    .keyboardShortcut(.return, modifiers: .command)
                    .disabled(!model.canGenerate)
                Button("ACE 试听") { Task { await model.renderPreview() } }
                    .disabled(!model.canSave || model.previewing)
            }
        }
    }
}
