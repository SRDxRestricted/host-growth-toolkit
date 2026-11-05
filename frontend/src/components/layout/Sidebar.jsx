import { NavLink, useNavigate } from 'react-router-dom'
import { LayoutDashboard, TrendingUp, Home, Calendar as CalendarIcon, CalendarDays, LogOut, Map, Repeat2, User } from 'lucide-react'

function Sidebar() {
  const navigate = useNavigate();
  const user = JSON.parse(localStorage.getItem('wayzyy_user') || '{}');
  const displayName = user.first_name
    ? `${user.first_name} ${user.last_name ? user.last_name.charAt(0) + '.' : ''}`
    : 'Host';

  const clearSession = () => localStorage.removeItem('wayzyy_user');
  const handleLogout = () => { clearSession(); navigate('/login', { replace: true }); };
  const handleSwitchAccount = () => { clearSession(); navigate('/login?switch=true', { replace: true }); };

  return (
    <aside className="sidebar">
      <NavLink to="/dashboard" end className="sidebar-brand" aria-label="host It overview">
        host It<span className="brand-dot">.</span>
      </NavLink>
      
      <nav className="sidebar-nav">
        <NavLink to="/dashboard" end className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}>
          <LayoutDashboard size={20} />
          <span>Overview</span>
        </NavLink>
        <NavLink to="/dashboard/pricing" className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}>
          <TrendingUp size={20} />
          <span>Pricing</span>
        </NavLink>
        <NavLink to="/dashboard/portfolio-map" className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}>
          <Map size={20} />
          <span>View map</span>
        </NavLink>
        <NavLink to="/dashboard/listings" className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}>
          <Home size={20} />
          <span>Listings</span>
        </NavLink>
        <NavLink to="/dashboard/calendar" className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}>
          <CalendarDays size={20} />
          <span>Calendar</span>
        </NavLink>
        <NavLink to="/dashboard/bookings" className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}>
          <CalendarIcon size={20} />
          <span>Bookings</span>
        </NavLink>
      </nav>

      <div className="sidebar-footer">
        <div className="host-profile">
          <div className="avatar">
            <User size={16} />
          </div>
          <span className="host-name">{displayName}</span>
        </div>
        <div className="account-actions">
          <button type="button" onClick={handleSwitchAccount}><Repeat2 size={14} />Switch account</button>
          <button type="button" onClick={handleLogout}><LogOut size={14} />Log out</button>
        </div>
      </div>
    </aside>
  )
}

export default Sidebar

