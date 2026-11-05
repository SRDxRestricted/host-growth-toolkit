import { Link } from 'react-router-dom';

export default function DashboardFooter() {
  return <footer className="dashboard-footer"><span>© 2026 host It.</span><nav aria-label="Legal"><Link to="/privacy">Privacy</Link><Link to="/terms">Terms</Link><Link to="/cookies">Cookies</Link></nav></footer>;
}
