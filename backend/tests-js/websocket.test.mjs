import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../static/js/websocket.js", import.meta.url), "utf8");
const { initWebSocket } = await import(
    "data:text/javascript;base64," + Buffer.from(source).toString("base64")
);

function harness(urlFactory) {
    const timers = [];
    const states = [];
    const sockets = [];
    const original = {
        setTimeout: globalThis.setTimeout,
        clearTimeout: globalThis.clearTimeout,
        random: Math.random,
        WebSocket: globalThis.WebSocket
    };
    class FakeWebSocket {
        static OPEN = 1;
        static CLOSED = 3;
        constructor(url) { this.url = url; this.readyState = 0; sockets.push(this); }
        close(code = 1000) {
            this.readyState = FakeWebSocket.CLOSED;
            this.onclose?.({ code });
        }
        open() { this.readyState = FakeWebSocket.OPEN; this.onopen?.(); }
    }
    globalThis.WebSocket = FakeWebSocket;
    globalThis.setTimeout = (callback, delay) => {
        const timer = { callback, delay, cleared: false, ran: false };
        timers.push(timer);
        return timer;
    };
    globalThis.clearTimeout = timer => { if (timer) timer.cleared = true; };
    Math.random = () => 0.5;
    const client = initWebSocket(urlFactory, () => {}, (...args) => states.push(args));
    return {
        client, timers, states, sockets,
        async flush() { await Promise.resolve(); await Promise.resolve(); },
        runNextTimer() {
            const timer = timers.find(item => !item.cleared && !item.ran);
            assert.ok(timer, "a reconnect timer should be scheduled");
            timer.ran = true;
            timer.callback();
        },
        restore() {
            client.close();
            globalThis.setTimeout = original.setTimeout;
            globalThis.clearTimeout = original.clearTimeout;
            Math.random = original.random;
            if (original.WebSocket === undefined) delete globalThis.WebSocket;
            else globalThis.WebSocket = original.WebSocket;
        }
    };
}

test("retries transient ticket errors with bounded backoff and obtains a fresh ticket", async () => {
    let calls = 0;
    const h = harness(async () => {
        calls += 1;
        if (calls === 1) throw new Error("network unavailable");
        return "wss://example.test/live?ticket=fresh";
    });
    try {
        await h.flush();
        assert.equal(h.timers[0].delay, 1000);
        h.runNextTimer();
        await h.flush();
        assert.equal(calls, 2);
        assert.equal(h.sockets.length, 1);
        assert.match(h.sockets[0].url, /ticket=fresh/);
    } finally { h.restore(); }
});

test("does not retry definitive 401 or 403 ticket failures", async () => {
    for (const status of [401, 403]) {
        const error = Object.assign(new Error("forbidden"), { status });
        const h = harness(async () => { throw error; });
        try {
            await h.flush();
            assert.equal(h.timers.length, 0);
            assert.equal(h.sockets.length, 0);
        } finally { h.restore(); }
    }
});

test("stops retrying after WebSocket policy close 1008", async () => {
    const h = harness(async () => "wss://example.test/live");
    try {
        await h.flush();
        h.sockets[0].close(1008);
        assert.equal(h.timers.length, 0);
    } finally { h.restore(); }
});

test("voluntary close cancels a pending reconnect timer", async () => {
    const h = harness(async () => { throw new Error("temporary network failure"); });
    try {
        await h.flush();
        assert.equal(h.timers.length, 1);
        h.client.close();
        assert.equal(h.timers[0].cleared, true);
        assert.equal(h.sockets.length, 0);
    } finally { h.restore(); }
});

test("resets retry backoff after a successful WebSocket open", async () => {
    const h = harness(async () => { throw new Error("temporary network failure"); });
    try {
        await h.flush();
        assert.equal(h.timers[0].delay, 1000);
        h.runNextTimer();
        await h.flush();
        h.sockets[0].open();
        h.sockets[0].close(1006);
        assert.equal(h.timers[1].delay, 1000);
    } finally { h.restore(); }
});
