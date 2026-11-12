// Left nav. Items map to top-level views in App. Purely presentational —
// active view + change handler come from parent.
// Minimal line icons (no emoji). Collapsed to icons; hovering the sidebar
// expands it and slides the labels in (pure CSS, see .sidebar:hover in styles.css).
const ICONS = {
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
    </>
  ),
  trading: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v10M15 9.3c0-1.3-1.3-2.3-3-2.3s-3 .9-3 2.1c0 2.8 6 1.3 6 4.1 0 1.3-1.3 2.3-3 2.3s-3-1-3-2.3" />
    </>
  ),
  markets: (
    <>
      <path d="M3 17l6-6 4 4 8-8" />
      <path d="M15 7h6v6" />
    </>
  ),
  news: (
    <>
      <path d="M6 3h9l5 5v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
      <path d="M14 3v5h5M8 13h8M8 17h8" />
    </>
  ),
  backtest: <path d="M9 3h6M10 3v5l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M7.5 15h9" />,
  quant: (
    <>
      <rect x="4" y="7" width="16" height="12" rx="2" />
      <path d="M9 3v4M15 3v4M2 11h2M2 15h2M20 11h2M20 15h2" />
      <circle cx="9" cy="13" r="1" />
      <circle cx="15" cy="13" r="1" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </>
  ),
};

const ITEMS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "trading", label: "Trading" },
  { id: "markets", label: "Markets" },
  { id: "news", label: "News" },
  { id: "backtest", label: "Backtest Lab" },
  { id: "quant", label: "Quant Team" },
  { id: "settings", label: "Settings" },
];

export default function Sidebar({ view, onSelect }) {
  return (
    <aside className="sidebar">
      <div className="brand" title="QuantPa">
        <img className="brand-mark" src="/icon-192.png?v=3" alt="" width="22" height="22" />
        <span className="brand-rest">QuantPa</span>
      </div>
      <nav>
        {ITEMS.map((it) => (
          <button
            key={it.id}
            title={it.label}
            className={`nav-item ${view === it.id ? "active" : ""}`}
            onClick={() => onSelect(it.id)}
          >
            <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              {ICONS[it.id]}
            </svg>
            <span className="nav-label">{it.label}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
