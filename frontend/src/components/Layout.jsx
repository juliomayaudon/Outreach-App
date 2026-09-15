import { NavLink } from "react-router-dom";
import { useAuth } from "../App";

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-inner">
          <div className="brand">
            Outreach
            <span>LinkedIn connection requests</span>
          </div>
          <NavLink to="/" className="nav-link" end>
            Dashboard
          </NavLink>
          <NavLink to="/campaigns" className="nav-link">
            Campaigns
          </NavLink>
          <NavLink to="/accounts" className="nav-link">
            LinkedIn accounts
          </NavLink>
          {user.role === "admin" && (
            <NavLink to="/team" className="nav-link">
              Team
            </NavLink>
          )}
          <div className="sidebar-footer">
            <div className="sidebar-user">
              {user.name || user.email}
              <br />
              {user.role === "admin" ? "Admin" : "Member"}
            </div>
            <button className="btn-small" onClick={logout}>
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
