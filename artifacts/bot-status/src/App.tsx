export default function App() {
  return (
    <div style={{
      minHeight: "100vh",
      background: "#0f172a",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "system-ui, sans-serif",
      color: "#f1f5f9"
    }}>
      <div style={{ textAlign: "center", maxWidth: 480, padding: "2rem" }}>
        <div style={{ fontSize: 64, marginBottom: 16 }}>🤖</div>
        <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 8 }}>
          Telegram LinkedIn Bot
        </h1>
        <div style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          background: "#022c22",
          color: "#4ade80",
          border: "1px solid #166534",
          borderRadius: 999,
          padding: "6px 16px",
          fontSize: 14,
          fontWeight: 600,
          marginBottom: 24
        }}>
          <span style={{
            width: 8, height: 8,
            borderRadius: "50%",
            background: "#4ade80",
            display: "inline-block",
            animation: "pulse 2s infinite"
          }} />
          Online & Running 24/7
        </div>
        <p style={{ color: "#94a3b8", lineHeight: 1.6, marginBottom: 32 }}>
          Your AI-powered LinkedIn automation bot is active.<br />
          Open Telegram and send <code style={{ background: "#1e293b", padding: "2px 8px", borderRadius: 4 }}>/post</code> to generate content.
        </p>
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
          textAlign: "left"
        }}>
          {[
            ["✍️", "/post", "Generate a LinkedIn post"],
            ["🐦", "/post → Both", "Post to LinkedIn + Twitter"],
            ["📅", "/queue add", "Plan posts in advance"],
            ["📊", "/stats", "View posting analytics"],
            ["🖼️", "/imagepost", "Post with AI image"],
            ["💬", "/help", "See all commands"],
          ].map(([icon, cmd, desc]) => (
            <div key={cmd} style={{
              background: "#1e293b",
              border: "1px solid #334155",
              borderRadius: 10,
              padding: "12px 14px"
            }}>
              <div style={{ fontSize: 18, marginBottom: 4 }}>{icon}</div>
              <code style={{ fontSize: 12, color: "#38bdf8", display: "block", marginBottom: 2 }}>{cmd}</code>
              <span style={{ fontSize: 12, color: "#64748b" }}>{desc}</span>
            </div>
          ))}
        </div>
        <style>{`
          @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
          }
        `}</style>
      </div>
    </div>
  );
}
