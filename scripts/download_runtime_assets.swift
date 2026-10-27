// Development recovery only: request local copies of this project's existing
// iCloud assets through Apple's documented FileManager API. No files are moved.
import Foundation

let project = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
let folders = CommandLine.arguments.count > 1 ? Array(CommandLine.arguments.dropFirst()) : ["models", ".venv/lib/python3.12/site-packages", "app", "ui", "tests"]
var requested = 0
var failures = 0
for folder in folders {
    let root = project.appendingPathComponent(folder)
    guard let items = FileManager.default.enumerator(at: root,
        includingPropertiesForKeys: [.isRegularFileKey, .ubiquitousItemDownloadingStatusKey]) else { continue }
    for case let file as URL in items {
        if file.pathComponents.contains("__pycache__") { continue }
        do {
            let values = try file.resourceValues(forKeys: [.isRegularFileKey, .ubiquitousItemDownloadingStatusKey])
            if values.isRegularFile == true && values.ubiquitousItemDownloadingStatus != .current {
                try FileManager.default.startDownloadingUbiquitousItem(at: file)
                requested += 1
            }
        } catch {
            failures += 1
            if failures == 1 { print("First download request error: \(error.localizedDescription)") }
        }
    }
    print("\(folder): \(requested) local-copy requests; \(failures) errors")
}
