import XCTest
@testable import IPhoneAgent

/// `video` chunk reassembly (docs/ble-protocol.md).
final class VideoTests: XCTestCase {
    typealias F = VideoAssembler.Flags

    func chunk(_ seq: UInt16, _ flags: F, _ payload: [UInt8], ms: UInt32? = nil) -> Data {
        var d = Data([UInt8(seq & 0xff), UInt8(seq >> 8), flags.rawValue])
        if let ms { d.append(contentsOf: [UInt8(ms & 0xff), UInt8(ms >> 8 & 0xff), UInt8(ms >> 16 & 0xff), UInt8(ms >> 24)]) }
        d.append(contentsOf: payload)
        return d
    }

    let sps: [UInt8] = [0, 0, 0, 1, 0x67, 1, 2]
    let idr: [UInt8] = [0, 0, 0, 1, 0x65, 9, 9]
    let p: [UInt8] = [0, 0, 0, 1, 0x41, 7]

    func testInOrderChunksMakeAccessUnits() {
        var a = VideoAssembler()
        XCTAssertEqual(a.add(chunk(0, [.start, .end, .config], sps, ms: 1000))?.config, true)
        XCTAssertNil(a.add(chunk(1, [.start, .idr], Array(idr[0..<5]), ms: 1001)))
        let unit = a.add(chunk(2, [.end, .idr], Array(idr[5...])))
        XCTAssertEqual(unit, AccessUnit(data: Data(idr), idr: true, config: false, snap: false, boardMs: 1001))
        XCTAssertEqual(a.add(chunk(3, [.start, .end], p, ms: 1200))?.data, Data(p))
        XCTAssertEqual(a.drops, 0)
    }

    func testGapDropsUntilTheNextKeyUnit() {
        var a = VideoAssembler()
        _ = a.add(chunk(10, [.start, .end, .idr], idr, ms: 1))
        XCTAssertNil(a.add(chunk(11, [.start], p, ms: 2)))
        XCTAssertNil(a.add(chunk(13, [.end], p)))           // 12 lost: the half unit is dropped
        XCTAssertEqual(a.drops, 1)
        XCTAssertNil(a.add(chunk(14, [.start, .end], p, ms: 3)))  // a P-frame after a gap is useless
        XCTAssertNotNil(a.add(chunk(15, [.start, .end, .config], sps, ms: 4)))  // recovered on CONFIG
        XCTAssertNotNil(a.add(chunk(16, [.start, .end], p, ms: 5)))
    }

    func testRecoversOnIDRAndWrapsSeq() {
        var a = VideoAssembler()
        _ = a.add(chunk(65534, [.start, .end, .idr], idr, ms: 1))
        XCTAssertNotNil(a.add(chunk(65535, [.start, .end], p, ms: 2)))
        XCTAssertNotNil(a.add(chunk(0, [.start, .end], p, ms: 3)))  // u16 wrap is not a gap
        XCTAssertEqual(a.drops, 0)
        XCTAssertNil(a.add(chunk(5, [.start, .end], p, ms: 4)))
        XCTAssertEqual(a.drops, 4)
        let unit = a.add(chunk(6, [.start, .end, .idr, .snap], idr, ms: 5))
        XCTAssertEqual(unit?.snap, true)
    }

    func testWaitsForAKeyUnitAtStartAndIgnoresBench() {
        var a = VideoAssembler()
        XCTAssertNil(a.add(chunk(0, [.start, .end], p, ms: 1)))
        XCTAssertNil(a.add(chunk(1, [.bench], [UInt8](repeating: 0, count: 100))))
        XCTAssertEqual(a.benchBytes, 103)
        XCTAssertNotNil(a.add(chunk(2, [.start, .end, .idr], idr, ms: 2)))
    }

    func testAnnexBSplitsNALUnits() {
        let units = annexBUnits(Data(sps + [0, 0, 1, 0x68, 5] + idr))
        XCTAssertEqual(units.map { $0.first! & 0x1f }, [7, 8, 5])
        XCTAssertEqual(units[0], Data([0x67, 1, 2]))
    }
}


/// A snap acknowledgement cannot stand in for a newly decoded image.
@MainActor final class VideoFeedTests: XCTestCase {
    func testSnapRejectsAcknowledgementWithoutANewDecodedImage() async throws {
        let device = FrameDevice(), feed = VideoFeed()
        feed.device = device
        feed.show(Data([1]), width: 10, height: 20)
        do {
            _ = try await feed.snap(decodeWait: 0.02)
            XCTFail("An acknowledged snap with only the old frame must fail")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("no new screen image"))
        }
        XCTAssertEqual(feed.frame, Data([1]))
        XCTAssertTrue(feed.broken)
    }

    func testSnapWaitsForDecodedImageAfterAcknowledgement() async throws {
        let device = FrameDevice(), feed = VideoFeed()
        feed.device = device
        device.onSend = { _ in
            Task { @MainActor in
                try? await Task.sleep(for: .milliseconds(25))
                feed.show(Data([2]), width: 10, height: 20)
            }
        }
        _ = try await feed.snap(decodeWait: 0.5)
        XCTAssertEqual(feed.frame, Data([2]))
        XCTAssertFalse(feed.broken)
    }

    func testSnapWaitsForTheDecoderToWorkThroughTheGOP() async throws {
        let decoder = H264Decoder(), feed = VideoFeed(decoder: decoder)
        let device = FrameDevice()
        feed.device = device
        device.onSend = { _ in
            decoder.queue.async { Thread.sleep(forTimeInterval: 0.3) }  // a long GOP still decoding after the ack
            decoder.queue.async { DispatchQueue.main.async { feed.show(Data([3]), width: 10, height: 20) } }
        }
        _ = try await feed.snap(decodeWait: 0.05)
        XCTAssertEqual(feed.frame, Data([3]))
    }

    func testLateDecodedImageFromDisconnectedLinkCannotReplaceTheScreen() async throws {
        let decoder = H264Decoder(), feed = VideoFeed(decoder: decoder)
        feed.show(Data([1]), width: 10, height: 20)
        let previous = feed.updated
        feed.linkLost()
        let old = H264Decoder.Frame(jpeg: Data([9]), width: 10, height: 20, decodeMs: 1,
                                    unit: AccessUnit(data: Data(), idr: true, config: false, snap: false, boardMs: 0))
        decoder.onFrame?(old)
        try await Task.sleep(for: .milliseconds(25))
        XCTAssertEqual(feed.frame, Data([1]))
        XCTAssertEqual(feed.updated, previous)
        XCTAssertTrue(feed.broken)
        feed.show(Data([2]), width: 10, height: 20)
        XCTAssertEqual(feed.frame, Data([2]))
        XCTAssertFalse(feed.broken)
    }

    func testSnapRejectsNewImageWhenSubsequentVideoChunksWereLost() async {
        let device = FrameDevice(), feed = VideoFeed()
        feed.device = device
        device.onSend = { _ in
            feed.show(Data([2]), width: 10, height: 20)
            feed.receive(Data([0, 0, 0]))
            feed.receive(Data([2, 0, 0]))  // a sequence gap invalidates that image
        }
        do {
            _ = try await feed.snap(decodeWait: 0.02)
            XCTFail("A newer image followed by a video gap must not pass as a healthy snap")
        } catch {
            XCTAssertTrue(feed.broken)
        }
    }

    func testStoppingSnapDoesNotWaitForABlockedDecoderQueue() async {
        let decoder = H264Decoder()
        decoder.queue.suspend()
        defer { decoder.queue.resume() }
        let device = FrameDevice(), feed = VideoFeed(decoder: decoder)
        feed.device = device
        let waiting = Task { try await feed.snap(decodeWait: 10) }
        await Task.yield()
        waiting.cancel()
        let stopped = expectation(description: "Cancelled while the decoder queue is still blocked")
        Task {
            do {
                _ = try await waiting.value
                XCTFail("Cancellation must leave the frame wait")
            } catch {
                XCTAssertTrue(error is CancellationError)
            }
            stopped.fulfill()
        }
        await fulfillment(of: [stopped], timeout: 1)
    }
}

@MainActor private final class FrameDevice: HIDDevice {
    var links = 1
    var connected = true
    var onSend: ((String) -> Void)?
    func send(_ command: String) async throws -> String { onSend?(command); return "ok" }
    func waitConnected(_ timeout: TimeInterval) async -> Bool { connected }
}
