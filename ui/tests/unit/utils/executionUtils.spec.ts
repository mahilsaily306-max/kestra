import {afterEach, beforeEach, describe, expect, it, vi} from "vitest"
import {waitFor} from "../../../src/utils/executionUtils"

type Client = Parameters<typeof waitFor>[0]

const clientReturning = (get: ReturnType<typeof vi.fn>) => ({get} as unknown as Client)

describe("waitFor", () => {
    beforeEach(() => {
        vi.useFakeTimers()
    })

    afterEach(() => {
        vi.useRealTimers()
    })

    it("resolves with the execution once the predicate accepts it", async () => {
        const get = vi.fn()
            .mockResolvedValueOnce({data: {id: "e", state: "RUNNING"}})
            .mockResolvedValueOnce({data: {id: "e", state: "SUCCESS"}})
        const result = waitFor(clientReturning(get), {id: "e"}, (data) => data.state === "SUCCESS")

        await vi.advanceTimersByTimeAsync(600)

        await expect(result).resolves.toEqual({id: "e", state: "SUCCESS"})
        expect(get).toHaveBeenCalledTimes(2)
    })

    it("stops polling and resolves with the last state seen when the predicate never accepts", async () => {
        const get = vi.fn().mockResolvedValue({data: {id: "e", state: "RUNNING"}})
        const result = waitFor(clientReturning(get), {id: "e"}, () => false)

        await vi.advanceTimersByTimeAsync(300 * 100)
        await expect(result).resolves.toEqual({id: "e", state: "RUNNING"})

        await vi.advanceTimersByTimeAsync(300 * 10)
        expect(get).toHaveBeenCalledTimes(100)
    })

    it("rejects instead of hanging when a poll request fails", async () => {
        const get = vi.fn().mockRejectedValue(new Error("offline"))
        const result = waitFor(clientReturning(get), {id: "e"}, () => true)
        const rejection = expect(result).rejects.toThrow("offline")

        await vi.advanceTimersByTimeAsync(300)

        await rejection
    })
})
