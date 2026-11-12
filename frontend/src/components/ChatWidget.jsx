import { useEffect, useRef, useState } from "react";
import { sendChat } from "../api";

const SUGGESTIONS = [
  "สรุปพอร์ตวันนี้",
  "หุ้นตัวไหนกำไร/ขาดทุนมากสุด",
  "ข่าวสำคัญของหุ้นในพอร์ต",
  "ปฏิทินเศรษฐกิจสัปดาห์นี้",
];

/** Floating command chat. Stays mounted while closed, so the conversation
 *  survives toggling and switching views. */
export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState([]); // [{role: "user"|"assistant"|"error", text}]
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const listRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    listRef.current?.scrollTo(0, listRef.current.scrollHeight);
  }, [msgs, busy]);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  async function send(text) {
    text = text.trim();
    if (!text || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      const r = await sendChat(text, sessionId);
      setSessionId(r.session_id ?? sessionId);
      setMsgs((m) => [...m, { role: "assistant", text: r.reply }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "error", text: e.message }]);
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(e) {
    // Enter sends, Shift+Enter is a newline. Skip while an IME (Thai) is composing.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(input);
    }
  }

  return (
    <>
      {open && (
        <div className="chat-panel" role="dialog" aria-label="QuantPa assistant">
          <div className="chat-head">
            <span>Assistant</span>
            <div>
              {msgs.length > 0 && (
                <button
                  className="chat-icon-btn"
                  onClick={() => { setMsgs([]); setSessionId(null); }}
                  title="เริ่มแชทใหม่"
                >
                  ↺
                </button>
              )}
              <button className="chat-icon-btn" onClick={() => setOpen(false)} aria-label="ปิด">
                ✕
              </button>
            </div>
          </div>

          <div className="chat-list" ref={listRef}>
            {msgs.length === 0 && (
              <div className="chat-empty">
                <p className="muted-text">สั่งงานหรือถามเรื่องพอร์ตได้เลย</p>
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chat-chip" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`chat-msg ${m.role}`}>{m.text}</div>
            ))}
            {busy && <div className="chat-msg assistant typing">กำลังคิด…</div>}
          </div>

          <div className="chat-input">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              placeholder="พิมพ์คำสั่ง…"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
            />
            <button onClick={() => send(input)} disabled={busy || !input.trim()}>
              ส่ง
            </button>
          </div>
        </div>
      )}

      <button
        className="chat-fab"
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? "ปิดแชท" : "เปิดแชท"}
        aria-expanded={open}
      >
        {open ? "✕" : (
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        )}
      </button>
    </>
  );
}
