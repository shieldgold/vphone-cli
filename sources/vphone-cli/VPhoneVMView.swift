import AppKit
import Dynamic
import Foundation
import Virtualization

/// On macOS 16+ (Tahoe), VZVirtualMachineView natively translates mouse events
/// to touch input. We only override right-click to send Home (Cmd+H).
class VPhoneVMView: VZVirtualMachineView {
    var keyHelper: VPhoneKeyHelper?

    override func rightMouseDown(with _: NSEvent) {
        guard let keyHelper else {
            print("[keys] keyHelper was not set, no way home!")
            return
        }
        keyHelper.sendHome()
    }
}