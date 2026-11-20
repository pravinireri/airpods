import CoreMotion
import Foundation
import Network

// stream airpods attitude and user acceleration as
// yaw, pitch, roll, accX, accY, accZ over UDP

final class Streamer: NSObject, CMHeadphoneMotionManagerDelegate {
    private let manager = CMHeadphoneMotionManager()
    private let connection: NWConnection
    private let destination: String
    private var sent: UInt64 = 0
    var onSample: ((Double, Double, Double, Double, Double, Double, Double, Double, Double, Double) -> Void)?

    init(host: String, port: UInt16) {
        destination = "\(host):\(port)"
        connection = NWConnection(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port)!,
            using: .udp
        )
        super.init()
    }

    func start() {
        connection.stateUpdateHandler = { state in
            switch state {
            case .ready:
                fputs("udp \(self.destination) ready\n", stderr)
            case .failed(let error):
                fputs("udp failed: \(error)\n", stderr)
                exit(1)
            case .waiting(let error):
                fputs("udp waiting: \(error)\n", stderr)
            default:
                break
            }
        }
        connection.start(queue: .main)

        guard manager.isDeviceMotionAvailable else {
            fputs("Headphone motion is unavailable.\n", stderr)
            exit(1)
        }

        switch CMHeadphoneMotionManager.authorizationStatus() {
        case .notDetermined:
            fputs("Requesting Motion & Fitness access...\n", stderr)
        case .restricted:
            fputs("Motion access is restricted.\n", stderr)
            exit(1)
        case .denied:
            fputs("Motion access denied.\n", stderr)
            exit(1)
        case .authorized:
            fputs("Motion access authorized.\n", stderr)
        @unknown default:
            break
        }

        manager.delegate = self
        manager.startDeviceMotionUpdates(to: .main) { [weak self] motion, error in
            guard let self else { return }
            if let error {
                fputs("motion error: \(error.localizedDescription)\n", stderr)
                return
            }
            guard let motion else { return }
            let attitude = motion.attitude
            let acceleration = motion.userAcceleration
            let rotation = motion.rotationRate
            let message = """
            \(motion.timestamp),
            \(attitude.yaw),
            \(attitude.pitch),
            \(attitude.roll),
            \(acceleration.x),
            \(acceleration.y),
            \(acceleration.z),
            \(rotation.x),
            \(rotation.y),
            \(rotation.z)
            """
            self.connection.send(content: message.data(using: .utf8), completion: .idempotent)
            self.onSample?(
                motion.timestamp,
                attitude.yaw,
                attitude.pitch,
                attitude.roll,
                acceleration.x,
                acceleration.y,
                acceleration.z,
                rotation.x,
                rotation.y,
                rotation.z
            )
            self.sent += 1
            if self.sent == 1 || self.sent % 100 == 0 {
                fputs("sent \(self.sent) \(message)\n", stderr)
            }
        }

        fputs("streaming headphone motion to udp \(destination)\n", stderr)
    }

    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) {
        fputs("headphones connected\n", stderr)
    }

    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) {
        fputs("headphones disconnected\n", stderr)
    }
}

// connect jaw to main
let jaw = JawClenchDetector()
let streamer = Streamer(host: "127.0.0.1", port: 9999)

streamer.onSample = { t, yaw, pitch, roll, ax, ay, az, rx, ry, rz in
    if jaw.update(
        t: t,
        ax: ax,
        ay: ay,
        az: az,
        rx: rx,
        ry: ry,
        rz: rz
    ) {
        print("jaw clench detected")
    }
}

streamer.start()
RunLoop.main.run()