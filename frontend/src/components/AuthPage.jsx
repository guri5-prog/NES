import { useState } from "react";

const API_URL = import.meta.env.VITE_API_URL ?? "";

export default function AuthPage({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const response = await fetch(`${API_URL}/api/auth/${mode === "register" ? "register" : "login"}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify(mode === "register" ? { name, email, password } : { email, password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Authentication failed.");
      onAuthenticated(data.user);
    } catch (requestError) { setError(requestError.message || "Could not connect to the server."); }
    finally { setBusy(false); }
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <a className="auth-brand" href="#home"><span className="brand-mark">N</span><span><strong>Northstar</strong><small>LOGISTICS INTELLIGENCE</small></span></a>
        <p className="eyebrow auth-eyebrow">RISK AWARE OPERATIONS</p>
        <h1>{mode === "login" ? "Welcome back" : "Create your account"}</h1>
        <p className="auth-subtitle">{mode === "login" ? "Sign in to continue to your operations dashboard." : "Register to access your operations dashboard."}</p>
        <form className="auth-form" onSubmit={submit}>
          {mode === "register" && <label>Full name<input autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} required maxLength={100} /></label>}
          <label>Email address<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={150} /></label>
          <label>Password<input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} maxLength={128} /></label>
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button className="auth-submit" type="submit" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</button>
        </form>
        <p className="auth-switch">{mode === "login" ? "New to Northstar?" : "Already have an account?"}{" "}<button type="button" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>{mode === "login" ? "Create an account" : "Sign in"}</button></p>
      </section>
      <div className="auth-footer">AI Smart Logistics · Route intelligence for safer operations</div>
    </main>
  );
}
